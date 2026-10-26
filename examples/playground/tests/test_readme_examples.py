"""The README's "BigInt" and "Decimal" examples answer exactly what it quotes.

The README says which query returns "9007199254740993" and which returns
"1200.50". A reader copies those documents, so the test runs the very text the
README contains against a freshly seeded database and compares the values.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.core.management import call_command
from graphql import ArgumentNode, NameNode, StringValueNode, parse, print_ast
from graphql.language.ast import FieldNode, SelectionSetNode

from tests._documented_operations import GUIDE, README, operation_under_heading

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

_README = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
_BIGINT = '{ postsFlat(ordering: "-viewCount", limit: 1) { id viewCount } }'
_DECIMAL = "{ attachments { results { target { ... on AccountType { balance } } } } }"


def _run(client: Client, query: str) -> dict[str, Any]:
    """POST a document and return its "data", failing on any error.

    Args:
        client: The Django test client issuing the request.
        query: The GraphQL document to execute.

    Returns:
        data: The "data" member of the response body.
    """
    response = client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    body = response.json()
    assert not body.get("errors"), body
    return body["data"]


def test_the_bigint_and_decimal_examples_return_the_quoted_values(
    client: Client, django_user_model: Any
) -> None:
    """Assert both README queries are published verbatim and return their values.

    Args:
        client: The Django test client issuing the requests.
        django_user_model: The user model, to log in as the seeded "demo" user
            (the BigInt post is a draft, which anonymous callers never see).
    """
    call_command("seed", authors=1, posts=1, comments=0, notes=0, verbosity=0)
    client.force_login(django_user_model.objects.get(username="demo"))

    for query, quoted in ((_BIGINT, '"9007199254740993"'), (_DECIMAL, '"1200.50"')):
        assert query in _README
        assert quoted in _README

    big = _run(client, _BIGINT)["postsFlat"]
    assert big[0]["viewCount"] == "9007199254740993"

    balances = [
        row["target"]["balance"]
        for row in _run(client, _DECIMAL)["attachments"]["results"]
        if "balance" in row["target"]
    ]
    assert "1200.50" in balances


@pytest.mark.parametrize(
    ("posts", "expected"), [(1, "fits one page"), (12, "spans multiple pages")]
)
def test_the_seed_summary_describes_the_data_it_created(
    posts: int, expected: str
) -> None:
    """Assert the pagination remark in the seed summary follows the real count.

    Args:
        posts: The posts per author to seed.
        expected: The phrase the summary must contain for that count.
    """
    from io import StringIO

    out = StringIO()
    call_command("seed", authors=1, posts=posts, comments=0, notes=0, stdout=out)

    assert expected in out.getvalue()


def _continue_at(
    selection: SelectionSetNode, path: tuple[str, ...], cursor: str
) -> SelectionSetNode:
    """Add a cursor to results and pageInfo without changing other selections.

    Args:
        selection: The parsed selection set to transform.
        path: Field names leading to the cursor-paginated list.
        cursor: The end cursor from the preceding response.

    Returns:
        A new selection set preserving the original document's other fields.
    """
    fields = []
    for field in selection.selections:
        if not isinstance(field, FieldNode) or field.name.value != path[0]:
            fields.append(field)
            continue
        assert field.selection_set is not None
        if len(path) > 1:
            fields.append(
                replace(
                    field,
                    selection_set=_continue_at(field.selection_set, path[1:], cursor),
                )
            )
            continue
        children = []
        for child in field.selection_set.selections:
            if isinstance(child, FieldNode) and child.name.value in {
                "results",
                "pageInfo",
            }:
                assert not any(
                    arg.name.value == "cursor" for arg in child.arguments or ()
                )
                child = replace(
                    child,
                    arguments=(
                        *(child.arguments or ()),
                        ArgumentNode(
                            name=NameNode(value="cursor"),
                            value=StringValueNode(value=cursor),
                        ),
                    ),
                )
            children.append(child)
        fields.append(
            replace(
                field,
                selection_set=replace(field.selection_set, selections=tuple(children)),
            )
        )
    return replace(selection, selections=tuple(fields))


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        (README, "### 1. Nested lists with all three paginators"),
        (GUIDE, "## Starter queries"),
    ],
    ids=["readme", "guide"],
)
def test_documented_cursor_pages_do_not_skip_rows(
    client: Client, path: Path, heading: str
) -> None:
    """Execute both copied queries and follow their root and nested cursors.

    Args:
        client: The anonymous HTTP client.
        path: The published document containing the literal operation.
        heading: The existing heading that locates the operation.
    """
    from blog.models import Author, Comment, Post

    from django_graphex.paginations import CursorGraphqlPagination

    author = Author.objects.create(name="Walkthrough Author")
    for index in range(4):
        Post.objects.create(
            title=f"Post {index}", author=author, status=Post.Status.PUBLISHED
        )
    post = Post.objects.create(
        title="Post 4", author=author, status=Post.Status.PUBLISHED
    )
    comments = [
        Comment.objects.create(post=post, author_name="Reader", text=f"row-{i:02}")
        for i in range(12)
    ]
    expected = [row.text for row in reversed(comments)]
    expected_ids = {row.text: row.pk for row in comments}
    query = operation_under_heading(path, heading)
    original = parse(query)
    first = _run(client, query)
    assert first["comments"]["totalCount"] == 12
    assert len(first["posts"]["results"]) == 5
    assert first["authors"]["totalCount"] == 1

    for cursor_path, get_list, size in (
        (("comments",), lambda data: data["comments"], 3),
        (
            ("posts", "results", "comments"),
            lambda data: data["posts"]["results"][0]["comments"],
            2,
        ),
    ):
        page = get_list(first)
        seen = []
        while True:
            rows = page["results"]
            info = page["pageInfo"]
            assert [row["text"] for row in rows] == expected[
                len(seen) : len(seen) + size
            ]
            assert info["endCursor"]
            _, cursor_pk = CursorGraphqlPagination.decode_cursor_parts(
                info["endCursor"]
            )
            assert cursor_pk == str(expected_ids[rows[-1]["text"]])
            seen.extend(row["text"] for row in rows)
            if not info["hasNextPage"]:
                break
            selection = _continue_at(
                original.definitions[0].selection_set,
                cursor_path,
                info["endCursor"],
            )
            continued = replace(
                original,
                definitions=(
                    replace(original.definitions[0], selection_set=selection),
                ),
            )
            page = get_list(_run(client, print_ast(continued)))
        assert seen == expected
