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
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.core.management import call_command

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
