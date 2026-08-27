"""The projection boundary, demonstrated end to end on "AuthorType".

"blog/schema.py" projects "Author.bio" away with "Meta.exclude_fields". The
library treats that as a SECURITY boundary rather than an output shape, so this
module pins all three axes the boundary closes on the very schema "make run"
serves:

1. Output — "bio" is absent from "AuthorType" in the SDL, so no client can
   select it.
2. "ordering" — "results(ordering: \\"bio\\")" is refused at query time, because
   ranking rows by a hidden column recovers it one comparison at a time.
3. "filter" — "bio" is absent from "AuthorFilterInput", so there is no lookup
   to send. Naming it in "Meta.filter_fields" would fail the schema build
   instead of being dropped in silence.

Run them from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.test import Client


def _author_type() -> object:
    """Return the compiled "AuthorType" from the playground schema.

    Returns:
        type: The compiled "GraphQLObjectType" the playground serves authors as.
    """
    from blog.schema import schema

    return schema.graphql_schema.type_map["AuthorType"]


def test_the_projected_column_is_not_readable() -> None:
    """Assert the SDL publishes no "bio" field on "AuthorType".

    The control matters as much as the assertion: "name" is still there, so a
    passing test means the projection removed one column rather than the type.
    """
    fields = _author_type().fields

    assert "bio" not in fields
    assert "name" in fields


def test_the_projected_column_is_not_orderable(db: object) -> None:
    """Assert ordering the author list by the hidden column is refused.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    from django.test import Client

    client: Client = Client()
    response = client.post(
        "/graphql/",
        data=json.dumps(
            {"query": '{ authors { results(ordering: "bio") { id name } } }'}
        ),
        content_type="application/json",
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    payload = json.loads(response.content)

    assert "Invalid ordering field: 'bio'" in json.dumps(payload["errors"])


def test_a_published_column_is_still_orderable(db: object) -> None:
    """Assert the boundary costs nothing on a column the type does publish.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    from django.test import Client

    client: Client = Client()
    response = client.post(
        "/graphql/",
        data=json.dumps(
            {"query": '{ authors { results(ordering: "name") { id name } } }'}
        ),
        content_type="application/json",
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    payload = json.loads(response.content)

    assert "errors" not in payload, payload


def test_the_projected_column_is_not_filterable() -> None:
    """Assert the generated filter input carries no lookup for the hidden column.

    "AuthorType.Meta.filter_fields" names "id" and "name" only. Adding "bio"
    would raise "ImproperlyConfigured" while the schema builds rather than
    quietly dropping the entry, so absence here is the whole client-visible
    surface.
    """
    from blog.schema import schema

    fields = schema.graphql_schema.type_map["AuthorFilterInput"].fields

    assert "bio" not in fields
    assert "name" in fields
