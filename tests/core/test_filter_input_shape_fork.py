""" "<Model>FilterInput" shape fork: two contexts, one canonical instance.

Filtering a relation by a column the RELATED type does not itself declare
(e.g. "author__email" on the post type, while the author type only declares
"name") forked the "<Model>FilterInput" shape: the root context built from the
author's own declaration, the nested context built from the (root union
requested) merge, and the two landed under DIFFERENT cache keys. Two distinct
"GraphQLInputObjectType" instances then shared the single name
"FilterForkAuthorFilterInput" and graphql-core refused to assemble the schema:

    TypeError: Schema must contain uniquely named types but contains multiple
    types named 'FilterForkAuthorFilterInput'.

The app did not start at all. The fix makes the UNION authoritative and shared:
the filter-input cache is keyed by "(model, custom-filter identity)" only, so
every context for a model resolves to the SAME cached instance, widened in
place when a later context asks for paths the current shape does not cover.
Convergence must therefore hold in BOTH declaration orders, since a model can
be built for the nested context BEFORE its root is registered.
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import graphql_sync, print_type

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from .._schema_isolation import isolated_pair
from ..models import FilterForkAuthor, FilterForkPost, NestedTreeNode


def _fork_types(shared_registry: Registry) -> tuple[Any, Any]:
    """Build the author/post type pair that forks the author filter-input shape.

    The author type declares only "name"; the post type reaches through the
    relation with "author__email" — a column the author's own root declaration
    does not expose. That divergence is what forked the shape.

    Args:
        shared_registry: The isolated registry both types register on.

    Returns:
        A "(author_type, post_type)" pair of "DjangoObjectType" subclasses.
    """

    class _ForkAuthorType(DjangoObjectType):
        """Root author type declaring only the "name" filter path."""

        class Meta:
            """Bind to "FilterForkAuthor" with the narrow root declaration."""

            model = FilterForkAuthor
            registry = shared_registry
            filter_fields = {"name": ("exact",)}

    class _ForkPostType(DjangoObjectType):
        """Post type filtering the author by "email" through the relation."""

        class Meta:
            """Bind to "FilterForkPost" with a reach-through author path."""

            model = FilterForkPost
            registry = shared_registry
            filter_fields = {"title": ("exact",), "author__email": ("exact",)}

    return _ForkAuthorType, _ForkPostType


@pytest.mark.django_db
def test_filter_input_shape_fork_root_first_builds() -> None:
    """Ships broken if a schema whose ROOT author field is compiled BEFORE the
    nested "author__email" context raises the duplicate-name "TypeError".
    """
    registry = Registry()
    author_type, post_type = _fork_types(registry)

    class _RootFirstQuery(ObjectType):
        """Query compiling the author ROOT context first."""

        authors = DjangoFilterListField(author_type)
        posts = DjangoFilterListField(post_type)

    schema = DjangoGraphQLSchema(
        query=_RootFirstQuery, registries=isolated_pair(registry)
    )
    type_map = schema.graphql_schema.type_map

    assert "FilterForkAuthorFilterInput" in type_map, (
        "the canonical author filter input must be in the type map; got "
        f"{sorted(n for n in type_map if 'Filter' in n)!r}"
    )
    fields = type_map["FilterForkAuthorFilterInput"].fields
    assert {"name", "email"} <= set(fields), (
        "the single canonical FilterForkAuthorFilterInput must be the UNION of "
        f"both contexts (name + email); got {sorted(fields)!r}"
    )


@pytest.mark.django_db
def test_filter_input_shape_fork_nested_first_builds() -> None:
    """Ships broken if a schema whose NESTED "author__email" context is compiled
    BEFORE the author ROOT field raises the duplicate-name "TypeError".

    This is the ordering hazard: the author model is built for the nested
    context first, so the convergence cannot rely on the root being seen first.
    """
    registry = Registry()
    author_type, post_type = _fork_types(registry)

    class _NestedFirstQuery(ObjectType):
        """Query compiling the nested relation context first."""

        posts = DjangoFilterListField(post_type)
        authors = DjangoFilterListField(author_type)

    schema = DjangoGraphQLSchema(
        query=_NestedFirstQuery, registries=isolated_pair(registry)
    )
    type_map = schema.graphql_schema.type_map

    fields = type_map["FilterForkAuthorFilterInput"].fields
    assert {"name", "email"} <= set(fields), (
        "nested-first build must converge on the SAME union shape as "
        f"root-first; got {sorted(fields)!r}"
    )


@pytest.mark.django_db
def test_filter_input_union_serves_both_contexts_end_to_end() -> None:
    """Ships broken if the shared union input stops serving BOTH contexts: the
    root author query filtering by "name" and the post query filtering by
    "author__email" must each execute and return the correct rows.
    """
    registry = Registry()
    author_type, post_type = _fork_types(registry)

    class _BothQuery(ObjectType):
        """Query exposing both the root author list and the post list."""

        authors = DjangoFilterListField(author_type)
        posts = DjangoFilterListField(post_type)

    schema = DjangoGraphQLSchema(query=_BothQuery, registries=isolated_pair(registry))

    ada = FilterForkAuthor.objects.create(name="Ada", email="ada@example.com")
    bob = FilterForkAuthor.objects.create(name="Bob", email="bob@example.com")
    FilterForkPost.objects.create(title="Analytical Engine", author=ada)
    FilterForkPost.objects.create(title="Bridge Design", author=bob)

    root = graphql_sync(
        schema.graphql_schema,
        '{ authors(filter: { name: { exact: "Ada" } }) { name email } }',
    )
    assert root.errors is None, f"root name filter raised: {root.errors!r}"
    assert [row["name"] for row in root.data["authors"]] == ["Ada"], (
        f"root name filter returned the wrong rows: {root.data['authors']!r}"
    )

    nested = graphql_sync(
        schema.graphql_schema,
        "{ posts(filter: { author: { email: { exact: "
        '"bob@example.com" } } }) { title } }',
    )
    assert nested.errors is None, (
        f"nested author__email filter raised: {nested.errors!r}"
    )
    assert [row["title"] for row in nested.data["posts"]] == ["Bridge Design"], (
        f"nested author__email filter returned the wrong rows: {nested.data['posts']!r}"
    )


@pytest.mark.django_db
def test_filter_input_without_fork_keeps_exact_sdl() -> None:
    """Ships broken if a model with no shape fork stops rendering the exact SDL
    it renders today (the union fix must not widen or rename the common case).
    """
    solo_registry = Registry()

    class _SoloAuthorType(DjangoObjectType):
        """Author type filtered from a single context only."""

        class Meta:
            """Bind to "FilterForkAuthor" with a single-context declaration."""

            model = FilterForkAuthor
            registry = solo_registry
            filter_fields = {"name": ("exact", "icontains")}

    class _SoloQuery(ObjectType):
        """Query exposing the single-context author list."""

        authors = DjangoFilterListField(_SoloAuthorType)

    schema = DjangoGraphQLSchema(
        query=_SoloQuery, registries=isolated_pair(solo_registry)
    )
    type_map = schema.graphql_schema.type_map

    assert print_type(type_map["FilterForkAuthorFilterInput"]) == (
        "input FilterForkAuthorFilterInput {\n"
        "  name: FilterForkAuthorNameLookups\n"
        "  and: [FilterForkAuthorFilterInput]\n"
        "  or: [FilterForkAuthorFilterInput]\n"
        "  not: FilterForkAuthorFilterInput\n"
        "}"
    )
    assert print_type(type_map["FilterForkAuthorNameLookups"]) == (
        "input FilterForkAuthorNameLookups {\n  exact: String\n  icontains: String\n}"
    )


@pytest.mark.django_db
def test_filter_input_widening_survives_self_referential_relation() -> None:
    """Ships broken if widening a SELF-referential filter input (the type whose
    field thunk builds itself through its own relation) recurses forever or
    drops fields.

    Widening evicts the memoized ".fields" and recompiles the thunk, which for a
    self-relation re-enters the builder for the very type being recompiled. The
    accumulated declaration is updated BEFORE the recompile, so the re-entrant
    lookup is a plain cache hit and the recursion terminates.
    """
    tree_registry = Registry()

    class _TreeNodeType(DjangoObjectType):
        """Self-referential node type whose root declares only "label"."""

        class Meta:
            """Bind to "NestedTreeNode" with a leaf-only root declaration."""

            model = NestedTreeNode
            registry = tree_registry
            filter_fields = {"label": ("exact",)}

    class _TreeQuery(ObjectType):
        """Query building the leaf shape first, then widening it."""

        nodes = DjangoFilterListField(_TreeNodeType)
        # Explicit per-field override reaching through the SELF relation: a path
        # the root declaration does not expose, so it widens the cached type.
        parented_nodes = DjangoFilterListField(
            _TreeNodeType, fields={"parent__label": ("exact",)}
        )

    schema = DjangoGraphQLSchema(
        query=_TreeQuery, registries=isolated_pair(tree_registry)
    )
    fields = schema.graphql_schema.type_map["NestedTreeNodeFilterInput"].fields

    assert {"label", "parent"} <= set(fields), (
        "widening a self-referential filter input must keep the original leaf "
        f"AND add the relation; got {sorted(fields)!r}"
    )
    assert (
        fields["parent"].type
        is schema.graphql_schema.type_map["NestedTreeNodeFilterInput"]
    ), "the self relation must point back at the SAME canonical instance"
