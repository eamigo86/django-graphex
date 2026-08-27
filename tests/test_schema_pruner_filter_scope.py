# -*- coding: utf-8 -*-
"""One pruned schema must give the two projection axes ONE answer.

Under "PERMISSION_SCOPED_SCHEMA" the served schema is a CLONE that publishes
less than the full one. The ordering axis already knows that: the paginating
results resolver is rebuilt around an allowlist re-derived from the pruned node
type, so a caller who lost the "author" relation loses "ordering: -authorId"
with it.

The filter axis did not. The "filter" argument and its whole nested
"<Model>FilterInput" rode through the prune verbatim, so the same caller, on
the same schema, could still name the relation the SDL denies exists -- and
"author: {name: {icontains: ...}}" is a prefix oracle over a model the clone
does not mount at all.

Same schema, same projection boundary, one predicate: a relation the pruned
node type does not publish is not traversable by the filter either.
"""

from __future__ import annotations

from django_graphex.core import ObjectType
from django_graphex.core.perm_labels import implicit_perms_for_type
from django_graphex.core.schema_pruner import prune_schema
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

_RSCOPE = Registry()


class ScopedAuthorType(DjangoObjectType):
    """Author node reachable only through the post node's relation.

    A caller without this model's read permission loses the relation field and
    the type falls out of the pruned schema entirely.
    """

    class Meta:
        """Configuration for "ScopedAuthorType".

        Declares no projection: what this node loses, it loses to the prune.
        """

        model = Author
        registry = _RSCOPE


class ScopedPostType(DjangoObjectType):
    """Post node publishing the relation the pruner may remove.

    The relation is what the filter argument traverses in the full schema.
    """

    class Meta:
        """Configuration for "ScopedPostType".

        Names the relation so the full schema traverses it and the pruned one
        must not.
        """

        model = Post
        registry = _RSCOPE
        only_fields = ("id", "title", "author")


class ScopedPostListType(DjangoListObjectType):
    """Paginated container filtering across the prunable relation.

    Carries both filter shapes the prune has to reach: the relation declared
    with a tail, and the relation declared on its own.
    """

    class Meta:
        """Configuration for "ScopedPostListType".

        Declares the filter surface whose fate under the prune is the subject.
        """

        model = Post
        registry = _RSCOPE
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)
        filter_fields = {
            "title": ("exact",),
            "author": ("exact",),
            "author__name": ("exact",),
        }


class ScopeQuery(ObjectType):
    """Root query exposing the filtered post list.

    Feeds both the full-schema and pruned-schema answers.
    """

    posts = DjangoListObjectField(ScopedPostListType)


scope_source = DjangoGraphQLSchema(query=ScopeQuery, registries=isolated_pair(_RSCOPE))


def _post_only_grant() -> frozenset[str]:
    """Return the permissions that keep "Post" and drop "Author".

    Returns:
        The read permissions the post node implies, with nothing else.
    """
    perms = implicit_perms_for_type(
        ScopedPostType._meta.graphql_output_type, scope_source.graphql_schema
    )
    return frozenset(perms or ())


def _full_grant() -> frozenset[str]:
    """Return the permissions that keep both nodes in the pruned clone.

    Returns:
        The union of the post and author read permissions.
    """
    author = implicit_perms_for_type(
        ScopedAuthorType._meta.graphql_output_type, scope_source.graphql_schema
    )
    return _post_only_grant() | frozenset(author or ())


class TestTheFilterArgumentIsScopedWithTheSchema:
    """The clone's filter input must describe the clone, not the full schema.

    The prune drops a relation field; the filter input that traverses that very
    relation has to lose it too, or one schema answers two ways about the same
    boundary.
    """

    def test_the_full_schema_traverses_the_relation(self) -> None:
        """The contrast case: nothing is pruned, so everything is filterable.

        Guards the assertions below against a fixture that never had the
        relation in the first place.
        """
        filter_input = scope_source.graphql_schema.type_map["PostFilterInput"]
        assert "author" in filter_input.fields

    def test_the_prune_really_drops_the_relation(self) -> None:
        """The fixture only means something if the clone loses "author".

        Pins the premise the next assertion rests on.
        """
        pruned = prune_schema(scope_source.graphql_schema, _post_only_grant())
        assert "author" not in pruned.type_map["ScopedPostType"].fields
        assert "ScopedAuthorType" not in pruned.type_map

    def test_the_pruned_filter_input_drops_the_relation_too(self) -> None:
        """The relation the clone denies must not be filterable through it.

        If this breaks, "filter: {author: {name: {icontains: ...}}}" walks the
        name of a model the pruned SDL does not mount.
        """
        pruned = prune_schema(scope_source.graphql_schema, _post_only_grant())
        filter_input = pruned.type_map["PostFilterInput"]
        assert "author" not in filter_input.fields
        assert "title" in filter_input.fields

    def test_the_pruned_clone_keeps_no_nested_author_input(self) -> None:
        """The nested input over the dropped model must fall out with it.

        A filter input over a model the schema cannot name is a substring
        oracle over rows nothing can select.
        """
        pruned = prune_schema(scope_source.graphql_schema, _post_only_grant())
        assert "AuthorFilterInput" not in pruned.type_map

    def test_a_full_grant_keeps_the_relation_filterable(self) -> None:
        """The fix must cost nothing to a caller who lost nothing.

        If this breaks, the prune over-narrows and every permitted caller loses
        a legitimate filter.
        """
        pruned = prune_schema(scope_source.graphql_schema, _full_grant())
        filter_input = pruned.type_map["PostFilterInput"]
        assert "author" in filter_input.fields
        assert "title" in filter_input.fields
