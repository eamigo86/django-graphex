# -*- coding: utf-8 -*-
"""Tests for the ordering allowlist walking a cyclic type graph without looping.

Deriving the allowlist means asking the shared predicate about every concrete
column, and for a forward relation the predicate follows the compiled relation
field into the TARGET type's field map. That second read is what closes the
foreign-key blocker -- and the list container takes it from inside its own fields
thunk, which is a lazy callback graphql-core has not finished running.

The walk terminates because it only ever forces a relation TARGET's field map and
then asks that type about a plain key column: building a type's fields
constructs the container FIELDS underneath it but not their maps, so no container
thunk re-enters. That is a property of the walk, not of any schema, and it is
worth a test because the type graph itself is genuinely cyclic -- a post type
publishing its author, an author type publishing a nested list of that same post
container -- and nothing in the derivation carries a visited set.

The schema is built inside the test rather than at module scope so a cached field
map cannot stand in for a successful walk.
"""

from __future__ import annotations

from django.test import SimpleTestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoNestedListObjectField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import Author, Post


def _gtype(name: str, bases: tuple, ns: dict) -> type:
    """Build a native type dynamically with a pydantic-safe namespace.

    The native bases are pydantic models, and pydantic's metaclass needs
    "__module__" in the namespace and a nested "Meta" whose "__qualname__" reads
    like a real class body's would. Supplying both makes the dynamic form behave
    exactly like the equivalent "class" statement.

    Args:
        name: The class name to build.
        bases: The base classes.
        ns: The class namespace.

    Returns:
        The freshly built class.
    """
    ns = dict(ns)
    ns.setdefault("__module__", __name__)
    ns["__qualname__"] = name
    for attr_name, attr_val in list(ns.items()):
        if isinstance(attr_val, type):
            attr_val.__qualname__ = "{}.{}".format(name, attr_name)
    return type(name, bases, ns)


def _build_cyclic_schema() -> DjangoGraphQLSchema:
    """Build a schema whose post and author types reference each other.

    Built inside a function rather than at module scope so the cycle is walked
    fresh on every call: a compiled field map is cached on the type, so a
    module-level schema would hide a re-entrant derivation behind the cache the
    first successful build leaves behind.

    Returns:
        The compiled schema over the cyclic pair.
    """
    registry = Registry()
    paginator = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)

    _gtype(
        "CyclePostType",
        (DjangoObjectType,),
        {
            "__doc__": "Post node publishing the forward relation to its author.",
            "Meta": type(
                "Meta",
                (),
                {
                    "__doc__": 'Configuration for "CyclePostType".',
                    "model": Post,
                    "registry": registry,
                    "only_fields": ("id", "title", "author"),
                },
            ),
        },
    )
    post_list_type = _gtype(
        "CyclePostListType",
        (DjangoListObjectType,),
        {
            "__doc__": "Paginated container whose stamp starts the walk.",
            "Meta": type(
                "Meta",
                (),
                {
                    "__doc__": 'Configuration for "CyclePostListType".',
                    "model": Post,
                    "registry": registry,
                    "pagination": paginator,
                },
            ),
        },
    )
    _gtype(
        "CycleAuthorType",
        (DjangoObjectType,),
        {
            "__doc__": "Author node closing the cycle with a nested post list.",
            "posts": DjangoNestedListObjectField(post_list_type, accessor="posts"),
            "Meta": type(
                "Meta",
                (),
                {
                    "__doc__": 'Configuration for "CycleAuthorType".',
                    "model": Author,
                    "registry": registry,
                    "only_fields": ("id", "name"),
                },
            ),
        },
    )
    author_list_type = _gtype(
        "CycleAuthorListType",
        (DjangoListObjectType,),
        {
            "__doc__": "Paginated container over the author node.",
            "Meta": type(
                "Meta",
                (),
                {
                    "__doc__": 'Configuration for "CycleAuthorListType".',
                    "model": Author,
                    "registry": registry,
                    "pagination": paginator,
                },
            ),
        },
    )
    query = _gtype(
        "CycleQuery",
        (ObjectType,),
        {
            "__doc__": "Root query mounting both sides of the cycle.",
            "authors": DjangoListObjectField(author_list_type),
            "posts": DjangoListObjectField(post_list_type),
        },
    )
    return DjangoGraphQLSchema(query=query, registries=isolated_pair(registry))


class TestTheAllowlistDoesNotReenterAThunk(SimpleTestCase):
    """A cyclic type graph must still compile and still enforce the allowlist.

    Both halves matter: a walk that loops takes the schema down, and a walk that
    bails out early leaves the guard open while the schema builds fine.
    """

    def test_the_cyclic_schema_compiles(self) -> None:
        """Assert the schema builds without exhausting the stack.

        A derivation that forces the relation target's field map from inside the
        container thunk walks back into that same thunk and dies with a
        "fields cannot be resolved" chain -- taking the whole schema offline,
        not just the ordering guard.
        """
        schema = _build_cyclic_schema()
        assert "CyclePostType" in schema.graphql_schema.type_map

    def test_the_allowlist_is_still_enforced_on_the_cycle(self) -> None:
        """Assert the walk still produced a real allowlist on the cycle.

        A build that survived by handing back the empty or the model-wide set
        would pass the compile test above and leave the guard broken, so the
        cycle is exercised end to end: the author type hides "bio", and the term
        naming it has to come back refused.
        """
        schema = _build_cyclic_schema()
        result = graphql_sync(
            schema.graphql_schema,
            '{ authors { results(ordering: "bio") { name } } }',
        )
        messages = [str(err.message) for err in (result.errors or [])]
        assert messages, "the hidden column was accepted on a cyclic schema"
        assert "Invalid ordering field: 'bio'." in messages[0]
