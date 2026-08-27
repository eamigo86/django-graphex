# -*- coding: utf-8 -*-
"""Plain-pk native filtering (the replacement for the old plain-ID filter).

"id: { exact }" / "id: { in }" filter a model by its own primary key, and a
relation declared directly (e.g. "author: { exact }") filters by the related
pk -- for both integer and UUID primary keys.
"""

from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post, UUIDItem, UUIDThing

R = Registry()


class AuthorType(DjangoObjectType):
    """Node type for Author, registered so the "author" relation is filterable.

    A relation the output compiler DROPS (its target model has no registered
    type) is refused as a filter path: the nested input would otherwise probe a
    model the schema cannot name. Registering the target is what publishes the
    relation, and publishing it is what makes "author: { exact }" legal.
    """

    class Meta:
        """Bind the node type to "Author" with no projection.

        See the enclosing type's docstring for why it has to exist.
        """

        model = Author
        registry = R


class PostListType(DjangoListObjectType):
    """List type for Post, filterable by its own id and by related author id.

    Exercises both own-pk and related-fk native filtering.
    """

    class Meta:
        """Configures the model, registry, and native filter fields.

        See the enclosing type's docstring for the filtering contract.
        """

        model = Post
        registry = R
        filter_fields = {"id": ("exact", "in"), "author": ("exact", "in")}


class UUIDThingListType(DjangoListObjectType):
    """List type for UUIDThing, filterable by its own UUID primary key.

    Exercises own-pk native filtering with a UUID-typed primary key.
    """

    class Meta:
        """Configures the model, registry, and native filter fields.

        See the enclosing type's docstring for the filtering contract.
        """

        model = UUIDThing
        registry = R
        filter_fields = {"id": ("exact", "in")}


class UUIDItemListType(DjangoListObjectType):
    """List type for UUIDItem, filterable by the related UUIDThing id.

    Exercises related-fk native filtering with a UUID-typed foreign key.
    """

    class Meta:
        """Configures the model, registry, and native filter fields.

        See the enclosing type's docstring for the filtering contract.
        """

        model = UUIDItem
        registry = R
        filter_fields = {"thing": ("exact", "in")}


class Query(ObjectType):
    """Root query exposing posts, things, and items as filterable list fields.

    Backs the module-level schema used by every test below.
    """

    posts = DjangoListObjectField(PostListType)
    things = DjangoListObjectField(UUIDThingListType)
    items = DjangoListObjectField(UUIDItemListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


def _exec(query: str) -> dict[str, object] | None:
    """Execute a GraphQL query against the module schema and return its data.

    Args:
        query: The GraphQL query document text to execute.

    Returns:
        data: The "data" payload of the executed query.

    Raises:
        AssertionError: If the query result carries any GraphQL errors.
    """
    result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


# -- the generated `filter` argument exposes an input type, not a flat `id` --- #
def test_filter_argument_shape() -> None:
    """The "posts" field must expose a single "filter" input, not flat args.

    If this breaks, the schema would regress to per-field flat filter
    arguments instead of the native "filter" input object.
    """
    args = schema.graphql_schema.query_type.fields["posts"].args
    assert "filter" in args
    # No flat per-field arguments anymore.
    assert "id" not in args
    assert "author" not in args


# -- filter by own integer id via exact / in --------------------------------- #
def test_filter_by_id_exact(db: None) -> None:
    """Filtering posts by "id: { exact }" must return only the matching post.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    a = Author.objects.create(name="A")
    p1 = Post.objects.create(title="p1", author=a)
    Post.objects.create(title="p2", author=a)

    data = _exec(
        "{ posts(filter: { id: { exact: %d } }) { results { title } } }" % p1.pk
    )
    titles = [r["title"] for r in data["posts"]["results"]]
    assert titles == ["p1"]


def test_filter_by_id_in(db: None) -> None:
    """Filtering posts by "id: { in }" must return only the listed posts.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    a = Author.objects.create(name="A")
    p1 = Post.objects.create(title="p1", author=a)
    p2 = Post.objects.create(title="p2", author=a)
    Post.objects.create(title="p3", author=a)

    data = _exec(
        "{ posts(filter: { id: { in: [%d, %d] } }) { results { title } } }"
        % (p1.pk, p2.pk)
    )
    titles = sorted(r["title"] for r in data["posts"]["results"])
    assert titles == ["p1", "p2"]


# -- filter by a related (integer) author id --------------------------------- #
def test_filter_by_related_integer_id(db: None) -> None:
    """Filtering posts by a directly-declared related "author" id must scope results.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    a1 = Author.objects.create(name="A1")
    a2 = Author.objects.create(name="A2")
    Post.objects.create(title="p1", author=a1)
    Post.objects.create(title="p2", author=a2)

    data = _exec(
        "{ posts(filter: { author: { exact: %d } }) { results { title } } }" % a1.pk
    )
    titles = [r["title"] for r in data["posts"]["results"]]
    assert titles == ["p1"]


# -- filter a UUID-pk model by its own id ------------------------------------ #
def test_filter_by_uuid_primary_key(db: None) -> None:
    """Filtering things by "id: { exact }" must work for a UUID primary key.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    t1 = UUIDThing.objects.create(name="t1")
    UUIDThing.objects.create(name="t2")

    data = _exec(
        '{ things(filter: { id: { exact: "%s" } }) { results { name } } }' % t1.id
    )
    names = [r["name"] for r in data["things"]["results"]]
    assert names == ["t1"]


# -- filter by a related UUID id --------------------------------------------- #
def test_filter_by_related_uuid_id(db: None) -> None:
    """Filtering items by a related "thing" UUID id must scope results.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    t1 = UUIDThing.objects.create(name="t1")
    t2 = UUIDThing.objects.create(name="t2")
    UUIDItem.objects.create(label="i1", thing=t1)
    UUIDItem.objects.create(label="i2", thing=t2)

    data = _exec(
        '{ items(filter: { thing: { exact: "%s" } }) { results { label } } }' % t1.id
    )
    labels = [r["label"] for r in data["items"]["results"]]
    assert labels == ["i1"]


# -- an empty filter is a no-op ---------------------------------------------- #
def test_empty_filter_returns_full_queryset(db: None) -> None:
    """An empty "filter: {}" must be a no-op, returning the full queryset.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
    a = Author.objects.create(name="A")
    Post.objects.create(title="p1", author=a)
    Post.objects.create(title="p2", author=a)

    data = _exec("{ posts(filter: {}) { results { title } totalCount } }")
    assert data["posts"]["totalCount"] == 2
