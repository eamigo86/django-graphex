"""The relation-scope hatch, both arms, and the two axes each arm costs.

"PostType.get_queryset" hides DRAFT posts from anonymous callers — but it is a
FIELD-level scope, so an AUTO-EXPANDED relation reads the parent's prefetch
cache and never calls it. "blog/schema.py" mounts the documented escape hatch
for both directions and leaves the unmounted shape standing beside it, so the
boundary is visible rather than merely written down:

- to-MANY: "CategoryType.posts = DjangoFilterListField(PostType)" runs the hook;
  the auto-expanded "AuthorType.posts" container does not, and shows drafts.
- to-ONE: "AuthorType.user = Field(UserType)" plus "resolve_user" hides the
  linked user from anonymous callers.

Declaring either arm makes the relation a MASK — what the client reads is what
the resolver returns, not what the row holds — so the key behind it leaves the
other two axes. Both refusals are pinned here, because a demo whose refusals
quietly come back is a demo teaching the opposite of what it says:

- ordering: "authors { results(ordering: \\"userId\\") }" is refused at query
  time, since ranking rows by the raw foreign key reads a key no type serves.
- filter: a "posts__" / "user__" entry in "Meta.filter_fields" would STOP THE
  SCHEMA BUILDING, so the guarantee is the ABSENCE of those paths from the
  compiled filter inputs.

Run them from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from django.test import Client


def _graphql(client: Client, query: str) -> dict[str, Any]:
    """POST a document to the public endpoint and return the decoded body.

    Args:
        client: The Django test client issuing the request.
        query: The GraphQL document to execute.

    Returns:
        body: The decoded JSON response body.
    """
    response = client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    return json.loads(response.content)


@pytest.fixture
def one_of_each(db: object) -> Any:
    """Create one author with a linked user and both a draft and a published post.

    Args:
        db: The pytest-django database fixture that enables DB access.

    Returns:
        author: The saved "Author" the two posts hang off.
    """
    from blog.models import Author, Category, Post
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="linked", password="pw1234567")
    author = Author.objects.create(name="Hatch Author", bio="hidden", user=user)
    category = Category.objects.create(name="Hatch Category")
    Post.objects.create(
        title="Published one",
        author=author,
        category=category,
        status=Post.Status.PUBLISHED,
    )
    Post.objects.create(
        title="Draft one", author=author, category=category, status=Post.Status.DRAFT
    )
    return author


def test_the_to_many_hatch_scopes_the_relation_for_an_anonymous_caller(
    client: Client, one_of_each: Any
) -> None:
    """Assert the declared "categories.posts" field runs "PostType.get_queryset".

    Args:
        client: The Django test client issuing the unauthenticated POST.
        one_of_each: The author fixture carrying one draft and one published post.
    """
    body = _graphql(client, "{ categories { name posts { title status } } }")

    assert not body.get("errors"), body
    statuses = [
        post["status"] for cat in body["data"]["categories"] for post in cat["posts"]
    ]
    assert statuses == ["PUBLISHED"], body


def test_the_auto_expanded_relation_beside_it_is_not_scoped(
    client: Client, one_of_each: Any
) -> None:
    """Assert the unmounted shape still shows drafts, which is why the hatch exists.

    This is the documented boundary, not a bug: rebuilding the prefetch
    queryset inside the resolver would cost window pagination and the ".only()"
    plan. Pinning it means the day the library closes it, this test says so
    instead of the README quietly becoming wrong.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        one_of_each: The author fixture carrying one draft and one published post.
    """
    body = _graphql(client, "{ authors { results { posts { results { status } } } } }")

    assert not body.get("errors"), body
    statuses = {
        post["status"]
        for author in body["data"]["authors"]["results"]
        for post in author["posts"]["results"]
    }
    assert statuses == {"PUBLISHED", "DRAFT"}, body


def test_the_to_one_hatch_hides_the_linked_user_from_an_anonymous_caller(
    client: Client, one_of_each: Any
) -> None:
    """Assert "resolve_user" runs, which only the declaration above it makes true.

    A bare "resolve_user" with no declared field does nothing at all: an
    auto-expanded forward FK is a plain attribute read off the select_related
    row and nothing consults the parent class.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        one_of_each: The author fixture whose author carries a linked user.
    """
    body = _graphql(client, "{ authors { results { name user { username } } } }")

    assert not body.get("errors"), body
    assert [row["user"] for row in body["data"]["authors"]["results"]] == [None]


def test_the_to_one_hatch_serves_the_user_to_an_authenticated_caller(
    client: Client, one_of_each: Any
) -> None:
    """Assert the demo is not bought by breaking the relation for everyone.

    Args:
        client: The Django test client used to log in and issue the query.
        one_of_each: The author fixture whose author carries a linked user.
    """
    assert client.login(username="linked", password="pw1234567")

    body = _graphql(client, "{ authors { results { name user { username } } } }")

    assert not body.get("errors"), body
    assert body["data"]["authors"]["results"][0]["user"]["username"] == "linked"


def test_the_masked_relations_key_leaves_the_ordering_axis(
    client: Client, one_of_each: Any
) -> None:
    """Assert ranking authors by the raw foreign key behind "user" is refused.

    The term is normalized to the column before it is judged, so the refusal
    names "user_id" whichever spelling the client sends. Both are pinned
    because a reader will try the camelCase one the SDL taught them.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        one_of_each: The author fixture the ordering would rank.
    """
    for term in ("userId", "user_id"):
        body = _graphql(
            client, f'{{ authors {{ results(ordering: "{term}") {{ name }} }} }}'
        )
        messages = " ".join(error["message"] for error in body["errors"])
        assert "Invalid ordering field: 'user_id'." in messages, body


def test_a_published_relation_key_is_still_orderable(
    client: Client, one_of_each: Any
) -> None:
    """Assert the ordering refusal is the MASK talking, not relations in general.

    "PostType" declares no resolver over "author", so that relation serves the
    row's own value and keeps its key. Without this control the test above
    would pass just as well against a guard that refused every foreign key.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        one_of_each: The author fixture whose posts the ordering ranks.
    """
    body = _graphql(client, '{ posts { results(ordering: "authorId") { title } } }')

    assert not body.get("errors"), body


def test_the_masked_relations_paths_are_absent_from_the_filter_inputs() -> None:
    """Assert neither hatch left a filter path that joins around its resolver.

    A "posts__title" or "user__username" entry would compile to an ORM join
    reaching exactly the rows the resolver hides, so the library refuses such
    an entry while the schema BUILDS. That refusal cannot be asserted from a
    schema that built; what can be asserted is its consequence — the inputs
    those types serve publish no path through the masked relation.
    """
    from blog.schema import schema

    type_map = schema.graphql_schema.type_map
    category_filter = set(type_map["CategoryFilterInput"].fields)
    author_filter = set(type_map["AuthorFilterInput"].fields)

    assert not [name for name in category_filter if name.startswith("posts")]
    assert not [name for name in author_filter if name.startswith("user")]
    # The control: both inputs still filter on what they publish.
    assert "name" in category_filter
    assert "name" in author_filter
