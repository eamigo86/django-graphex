# -*- coding: utf-8 -*-
"""The ONE predicate both projection axes ask: is this column's VALUE published?

"Meta.only_fields" / "Meta.exclude_fields" are a SECURITY BOUNDARY: a column a
type projects away must not be readable, orderable OR filterable through that
type. Two axes grew that guard independently and invented two different notions
of "hidden", which now contradict each other -- the ordering axis reads the
COMPILED field map and pins a re-published column as legitimate, while the
filter axis re-reads "Meta" through a registry lookup and refuses the identical
declaration. This module pins the single predicate that settles it, before
either axis consumes it.

The question is deliberately about the VALUE, not the NAME: a declared attribute
whose resolver masks the column publishes the name and hides the value, and a
forward foreign key publishes a column whose value belongs to ANOTHER type.

Ten facts: seven a blocker found in the two-implementation state, and three
clauses that survived a mutation of the predicate itself -- the last of which,
deleted, takes the schema build down rather than merely changing an answer:

  1. A declared field whose resolver masks the column does not publish it.
  2. A declared field that re-publishes the column verbatim -- no resolver, or
     the documented same-name source shortcut -- does publish it. The shortcut
     is the over-refusal that had to die: every declared field carrying a
     resolver was stamped masked, so a type projecting NOTHING silently lost
     ordering and, through the pk, cursor pagination.
  3. Publishing a forward RELATION does not publish the target key's VALUE. The
     foreign key column holds the target's key, so it is published only when the
     target's own type publishes that key.
  4. A relation whose target model has no registered type is dropped from the
     SDL by the output compiler, so nothing about it is published.
  5. A multi-table-inheritance child's own primary key is the parent link, which
     the compiler drops as plumbing -- but the child publishes the PARENT's key
     as "id", and both hold the same value on every row, so the key's value IS
     published.
  6. The predicate answers about the type it is HANDED. A registry lookup would
     answer about a last-wins index a type can leave with "Meta.skip_registry",
     which turned the filter axis' guard into a no-op.
  7. Under "PERMISSION_SCOPED_SCHEMA" the pruned schema publishes less, and the
     pruned clone answers for itself: the predicate reads the compiled type it
     is given, and follows relations through the compiled field map, so the
     clone's smaller SDL yields the clone's smaller answer.
  8. A field owning NO column on the declaring model publishes nothing here.
     Every rule above is written for a field that owns one, so without the
     predicate's first clause a reverse one-to-one answers whatever the TARGET
     says about the key it points at -- True, for any node publishing an "id".
  9. A relation declared over a type bound to ANOTHER model, and carrying no
     resolver, still publishes the target's key -- and it has to, because the
     type is a rendering choice while the VALUE stays the real target row's.
     The guide once promised a refusal here; the refusal would have withdrawn
     an ordering term over a key the same schema demonstrably hands out, which
     is the drift this predicate exists to prevent.
 10. A concrete field whose "target_field" is the field ITSELF stops the walk
     where it stands. A one-to-one relation to "self" declared as the primary
     key is that shape, Django accepts it, and without the clause the predicate
     recurses into its own type forever and the schema build dies with an
     unhandled "RecursionError".
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import CharField, Field, IDField, ObjectType
from django_graphex.core.output_compiler import publishes_column_value
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
from .models import (
    Author,
    AuthorProfile,
    Category,
    MtiRestaurant,
    Post,
    SelfKeyedNode,
)

# ---------------------------------------------------------------------------
# 1 + 2: a declared attribute over a column the projection removed
# ---------------------------------------------------------------------------

_RMASK = Registry()


class MaskedBioAuthorType(DjangoObjectType):
    """Author node that hides "bio" and re-publishes the NAME over a redaction.

    The declared attribute wins over the model-derived field, so the SDL
    advertises "bio" while every response carries a constant.
    """

    bio = CharField()

    class Meta:
        """Configuration for "MaskedBioAuthorType".

        Keeps "id" and "name" so the declared attribute is the only publisher
        of the "bio" name.
        """

        model = Author
        registry = _RMASK
        only_fields = ("id", "name")

    def resolve_bio(self, info: Any) -> str:
        """Return a constant in place of the author's biography.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The redaction marker that stands in for the hidden column.
        """
        return "[redacted]"


_RPASS = Registry()


class PassthroughBioAuthorType(DjangoObjectType):
    """Author node that re-publishes "bio" with graphql-core's default resolver.

    The contrast case for the masking type above: no resolver is declared, so
    the compiled field reads the attribute and serves the real column.
    """

    bio = CharField()

    class Meta:
        """Configuration for "PassthroughBioAuthorType".

        The same projection as the masking type; the ONLY difference is the
        absent resolver.
        """

        model = Author
        registry = _RPASS
        only_fields = ("id", "name")


_RSOURCE = Registry()


class SourcedBioAuthorType(DjangoObjectType):
    """Author node that re-publishes "bio" through the same-name source shortcut.

    The documented no-logic shortcut: the compiled resolver reads the named
    attribute off the row, and the name it reads is the column itself, so the
    value published is the column's value.
    """

    bio = CharField(source="bio")
    id = IDField(source="id")

    class Meta:
        """Configuration for "SourcedBioAuthorType".

        Declares NO projection, which is the sharp end of the over-refusal: a
        type that hides nothing lost the column anyway -- and, with the key
        declared the same way, lost the tiebreak every cursor page needs.
        """

        model = Author
        registry = _RSOURCE


_RSOURCE_OTHER = Registry()


class SourcedElsewhereAuthorType(DjangoObjectType):
    """Author node whose "bio" reads a DIFFERENT attribute off the row.

    A source naming another attribute is a mask like any other: the name is
    published, the column's value is not.
    """

    bio = CharField(source="name")

    class Meta:
        """Configuration for "SourcedElsewhereAuthorType".

        Hides the real "bio" column, so only the redirected declaration
        publishes that name.
        """

        model = Author
        registry = _RSOURCE_OTHER
        only_fields = ("id", "name")


# ---------------------------------------------------------------------------
# 3 + 4: a forward foreign key, and a relation whose target is unregistered
# ---------------------------------------------------------------------------

_RKEYLESS = Registry()


class KeylessAuthorType(DjangoObjectType):
    """Author node that projects its own primary key away.

    Nothing in this schema exposes an author's key, so "Post.author_id" ranks
    rows by a value no type publishes.
    """

    class Meta:
        """Configuration for "KeylessAuthorType".

        Keeps "name" only: no "id", and therefore no readable key.
        """

        model = Author
        registry = _RKEYLESS
        only_fields = ("name",)


class KeylessPostType(DjangoObjectType):
    """Post node publishing the relation to the keyless author node.

    Names "category" too, whose target model has no registered type, which is
    what the output compiler drops from the SDL.
    """

    class Meta:
        """Configuration for "KeylessPostType".

        Names both relations explicitly so neither absence can be blamed on the
        projection.
        """

        model = Post
        registry = _RKEYLESS
        only_fields = ("id", "title", "author", "category")


class KeylessPostListType(DjangoListObjectType):
    """Paginated container over "KeylessPostType".

    Present so the node type reaches a built schema and its relation fields are
    resolved against the registry.
    """

    class Meta:
        """Configuration for "KeylessPostListType".

        Carries a paginator only because the container requires one.
        """

        model = Post
        registry = _RKEYLESS
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class KeylessQuery(ObjectType):
    """Root query exposing the post list whose author node hides its key.

    Feeds the foreign-key and unregistered-target assertions below.
    """

    posts = DjangoListObjectField(KeylessPostListType)


keyless_schema = DjangoGraphQLSchema(
    query=KeylessQuery, registries=isolated_pair(_RKEYLESS)
)


_RKEYED = Registry()


class KeyedAuthorType(DjangoObjectType):
    """Author node publishing its primary key.

    The contrast case: the foreign key's value is readable through
    "author { id }", so the column stays published.
    """

    class Meta:
        """Configuration for "KeyedAuthorType".

        Declares no projection, so the key is published.
        """

        model = Author
        registry = _RKEYED


class KeyedPostType(DjangoObjectType):
    """Post node publishing the relation to the keyed author node.

    Same shape as the keyless post node; only the target type differs.
    """

    class Meta:
        """Configuration for "KeyedPostType".

        Names the relation explicitly so the comparison with the keyless case
        is exact.
        """

        model = Post
        registry = _RKEYED
        only_fields = ("id", "title", "author")


class KeyedPostListType(DjangoListObjectType):
    """Paginated container over "KeyedPostType".

    Present so the node type reaches a built schema.
    """

    class Meta:
        """Configuration for "KeyedPostListType".

        Carries a paginator only because the container requires one.
        """

        model = Post
        registry = _RKEYED
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class KeyedQuery(ObjectType):
    """Root query exposing the post list whose author node publishes its key.

    Feeds the positive half of the foreign-key assertions.
    """

    posts = DjangoListObjectField(KeyedPostListType)


keyed_schema = DjangoGraphQLSchema(query=KeyedQuery, registries=isolated_pair(_RKEYED))


_RREVERSE = Registry()


class ReverseProfileType(DjangoObjectType):
    """Profile node standing on the OTHER side of a reverse one-to-one.

    Publishes its key, which is what makes the reverse relation on the author
    node look -- to every rule below the predicate's first clause -- like a
    published column.
    """

    class Meta:
        """Configuration for "ReverseProfileType".

        Declares no projection, so the key is published.
        """

        model = AuthorProfile
        registry = _RREVERSE


class ReverseAuthorType(DjangoObjectType):
    """Author node publishing the reverse one-to-one as the profile NODE.

    A reverse one-to-one is the sharp shape for the "concrete" clause: unlike a
    to-many, it is published as the target node itself rather than as a
    paginated container, so the recursion lands directly in a field map that
    holds the key it is looking for.
    """

    class Meta:
        """Configuration for "ReverseAuthorType".

        Names the reverse relation so the compiler injects it.
        """

        model = Author
        registry = _RREVERSE
        only_fields = ("id", "name", "author_profile")


_RMASKEDREL = Registry()


class MaskedRelationAuthorType(DjangoObjectType):
    """Author node published behind a masked relation on the post node.

    Publishes its key, so the only reason its key's value stays unpublished
    through the relation is the relation's own mask.
    """

    class Meta:
        """Configuration for "MaskedRelationAuthorType".

        Declares no projection.
        """

        model = Author
        registry = _RMASKEDREL


class MaskedRelationPostType(DjangoObjectType):
    """Post node whose "author" field is the documented to-one scoping hatch.

    "docs/usage/types.md" tells readers to write exactly this -- a declared
    relation field plus its "resolve_" method -- because an auto-expanded FK
    read skips the target type's "get_queryset". What the resolver hands back
    here is an UNSAVED stand-in, so the key behind the relation is readable
    through no type at all; the declaration is a mask like any other.
    """

    author = Field(MaskedRelationAuthorType)

    class Meta:
        """Configuration for "MaskedRelationPostType".

        Names the relation, which the declared attribute above then overrides.
        """

        model = Post
        registry = _RMASKEDREL
        only_fields = ("id", "title", "author")

    def resolve_author(self, info: Any) -> Any:
        """Return a stand-in author instead of the row's related object.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The unsaved stand-in row this field publishes.
        """
        return Author(name="[redacted]")


_RSCALARREL = Registry()


class ScalarRelationPostType(DjangoObjectType):
    """Post node publishing the relation's NAME over a plain string.

    The other half of the discriminator: a declared attribute standing where a
    relation would be, but compiling to a LEAF, publishes no relation at all --
    nothing can be traversed through it and no target type can answer for the
    key. That is a mask, and it is stamped like any other.
    """

    author = CharField()

    class Meta:
        """Configuration for "ScalarRelationPostType".

        Names the relation so the declared attribute overrides the auto-derived
        relation field rather than adding a sibling.
        """

        model = Post
        registry = _RSCALARREL
        only_fields = ("id", "title", "author")

    def resolve_author(self, info: Any) -> str:
        """Return the author's display label instead of the related row.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            A constant standing in for the related object.
        """
        return "[redacted]"


_RWRONGREL = Registry()


class WrongTargetCategoryType(DjangoObjectType):
    """Category node standing where the post's AUTHOR relation is declared.

    It publishes "id" like every other node, and "id" is also the name of the
    key behind "Post.author" -- which is the whole leak: a same-named field on
    an unrelated type answered for a key it knows nothing about.
    """

    class Meta:
        """Configuration for "WrongTargetCategoryType".

        Declares no projection, so its own key is published.
        """

        model = Category
        registry = _RWRONGREL


class WrongTargetAuthorType(DjangoObjectType):
    """Author node that projects its primary key away.

    Nothing in this schema publishes an author's key, so the truthful answer
    for "Post.author_id" is False however the relation field is declared.
    """

    class Meta:
        """Configuration for "WrongTargetAuthorType".

        Keeps "name" only: no readable key.
        """

        model = Author
        registry = _RWRONGREL
        only_fields = ("name",)


class WrongTargetPostType(DjangoObjectType):
    """Post node whose "author" is declared as a type bound to another model.

    Pins the second reason this answers False, so the assertion still means
    something once the mask stamp is lifted: the declaration publishes the
    relation's name over a type serving a DIFFERENT model, so no target answers
    for the key and the walk lands in an unrelated field map -- where "id" is
    published by every node and would have said yes.
    """

    author = Field(WrongTargetCategoryType)

    class Meta:
        """Configuration for "WrongTargetPostType".

        Names the relation so the declared attribute overrides the auto-derived
        field rather than adding a sibling.
        """

        model = Post
        registry = _RWRONGREL
        only_fields = ("id", "title", "author")

    def resolve_author(self, info: Any) -> Any:
        """Return a category in place of the row's author.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The unsaved stand-in row this field publishes.
        """
        return Category(title="[redacted]")


# ---------------------------------------------------------------------------
# 5: multi-table inheritance -- the pk FIELD is the parent link
# ---------------------------------------------------------------------------

_RMTI = Registry()


class MtiRestaurantType(DjangoObjectType):
    """Node over a multi-table-inheritance child.

    Its own primary key is the implicit parent link, which the output compiler
    drops as join plumbing; the parent's key is published as "id" instead.
    """

    class Meta:
        """Configuration for "MtiRestaurantType".

        Declares no projection, so everything the compiler publishes is
        published.
        """

        model = MtiRestaurant
        registry = _RMTI


_RMTIHIDDEN = Registry()


class KeylessMtiRestaurantType(DjangoObjectType):
    """The same child node with the inherited key projected away.

    The contrast case: with "id" gone there is no readable key on either table,
    so the parent link's value is not published either.
    """

    class Meta:
        """Configuration for "KeylessMtiRestaurantType".

        Keeps the child's own scalar only.
        """

        model = MtiRestaurant
        registry = _RMTIHIDDEN
        only_fields = ("serves_pizza",)


# ---------------------------------------------------------------------------
# 6: the type is handed over, never looked up
# ---------------------------------------------------------------------------

_RSKIP = Registry()


class RegisteredAuthorType(DjangoObjectType):
    """The author node that OWNS the registry slot for its model.

    A guard resolving the projection through the registry reads this type's
    declaration -- which hides nothing -- no matter which type is serving.
    """

    class Meta:
        """Configuration for "RegisteredAuthorType".

        Declares no projection, so a registry-resolved guard sees a fully
        published model.
        """

        model = Author
        registry = _RSKIP


class OptedOutAuthorType(DjangoObjectType):
    """The author node that opts OUT of the registry and hides "bio".

    Its projection is the one that governs its own SDL, and it is invisible to
    any registry lookup.
    """

    class Meta:
        """Configuration for "OptedOutAuthorType".

        Opts out of the registry and keeps "name" only.
        """

        model = Author
        registry = _RSKIP
        skip_registry = True
        only_fields = ("name",)


# ---------------------------------------------------------------------------
# 7: the permission-pruned clone answers for itself
# ---------------------------------------------------------------------------

_RPRUNE = Registry()


class PrunedAuthorType(DjangoObjectType):
    """Author node reachable only through the post node's relation.

    A caller without this model's read permission loses the relation field and
    the type falls out of the pruned schema entirely.
    """

    class Meta:
        """Configuration for "PrunedAuthorType".

        Declares no projection: what this node loses, it loses to the prune.
        """

        model = Author
        registry = _RPRUNE


class PrunedPostType(DjangoObjectType):
    """Post node publishing the relation the pruner may remove.

    The relation is what publishes the foreign key's value in the full schema.
    """

    class Meta:
        """Configuration for "PrunedPostType".

        Names the relation so the full schema publishes the key and the pruned
        one does not.
        """

        model = Post
        registry = _RPRUNE
        only_fields = ("id", "title", "author")


class PrunedPostListType(DjangoListObjectType):
    """Paginated container over "PrunedPostType".

    Present so the node type reaches a built schema the pruner can clone.
    """

    class Meta:
        """Configuration for "PrunedPostListType".

        Carries a paginator only because the container requires one.
        """

        model = Post
        registry = _RPRUNE
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class PruneQuery(ObjectType):
    """Root query exposing the post list used by the pruning assertions.

    Feeds both the full-schema and pruned-schema answers.
    """

    posts = DjangoListObjectField(PrunedPostListType)


prune_schema_source = DjangoGraphQLSchema(
    query=PruneQuery, registries=isolated_pair(_RPRUNE)
)


# ---------------------------------------------------------------------------
# 9: a relation declared over a type bound to ANOTHER model
# ---------------------------------------------------------------------------

_RFOREIGN = Registry()


class ForeignRenderCategoryType(DjangoObjectType):
    """Category node standing in as the RENDERING type of a "Post.author".

    Publishes an "id" like every node does, which is the same-named field the
    withdrawn doc rule claimed was "not an answer".
    """

    class Meta:
        """Configuration for "ForeignRenderCategoryType".

        Keeps a column of its own so the mismatch is visible in a response.
        """

        model = Category
        registry = _RFOREIGN
        only_fields = ("id", "title")


class ForeignRenderPostType(DjangoObjectType):
    """Post node declaring "author" over the category node, with no resolver.

    No resolver is the whole point: the default attribute resolver hands out
    the real "Author" row, so the target's key is served whatever type renders
    it.
    """

    author = Field(ForeignRenderCategoryType)

    class Meta:
        """Configuration for "ForeignRenderPostType".

        Keeps "author" in the projection so the declaration overrides the
        auto-derived relation instead of adding a sibling field.
        """

        model = Post
        registry = _RFOREIGN
        only_fields = ("id", "title", "author")


class ForeignRenderPostListType(DjangoListObjectType):
    """Paginated container over "ForeignRenderPostType".

    Present so the node type reaches a built schema a query can hit.
    """

    class Meta:
        """Configuration for "ForeignRenderPostListType".

        Carries a paginator only because the container requires one.
        """

        model = Post
        registry = _RFOREIGN
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class ForeignRenderQuery(ObjectType):
    """Root query exposing the mis-rendered relation.

    Paginated so the query can select through the relation and read the key it
    hands out.
    """

    posts = DjangoListObjectField(ForeignRenderPostListType)


foreign_render_schema = DjangoGraphQLSchema(
    query=ForeignRenderQuery, registries=isolated_pair(_RFOREIGN)
)


# ---------------------------------------------------------------------------
# 10: a concrete field whose target field is itself
# ---------------------------------------------------------------------------

_RSELF = Registry()


class SelfKeyedNodeType(DjangoObjectType):
    """Node over the model whose primary key relates to its own table.

    The relation field and the primary key are ONE field here, so following the
    relation to its target lands back on the field the walk started from.
    """

    class Meta:
        """Configuration for "SelfKeyedNodeType".

        Publishes the self-relation, which is what gives the walk somewhere to
        recurse into.
        """

        model = SelfKeyedNode
        registry = _RSELF


class SelfKeyedNodeListType(DjangoListObjectType):
    """Paginated container over "SelfKeyedNodeType".

    Present so the node type reaches a built schema.
    """

    class Meta:
        """Configuration for "SelfKeyedNodeListType".

        Carries a paginator only because the container requires one.
        """

        model = SelfKeyedNode
        registry = _RSELF
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class SelfKeyedQuery(ObjectType):
    """Root query exposing the self-keyed node list.

    Present only so the node type reaches a built schema; nothing queries it.
    """

    nodes = DjangoListObjectField(SelfKeyedNodeListType)


self_keyed_schema = DjangoGraphQLSchema(
    query=SelfKeyedQuery, registries=isolated_pair(_RSELF)
)


def _post_only_grant() -> frozenset[str]:
    """Return the permissions that keep "Post" and drop "Author".

    Returns:
        The read permissions the post node implies, with nothing else.
    """
    perms = implicit_perms_for_type(
        PrunedPostType._meta.graphql_output_type,
        prune_schema_source.graphql_schema,
    )
    return frozenset(perms or ())


def _full_grant() -> frozenset[str]:
    """Return the permissions that keep both nodes in the pruned clone.

    Returns:
        The union of the post and author read permissions.
    """
    author = implicit_perms_for_type(
        PrunedAuthorType._meta.graphql_output_type,
        prune_schema_source.graphql_schema,
    )
    return _post_only_grant() | frozenset(author or ())


class TestAMaskedDeclarationDoesNotPublishTheColumn:
    """A resolver serves what it returns, so the name is published and not the value.

    Case 1: the read oracle the projection exists to close, rebuilt out of the
    type's own declaration.
    """

    def test_a_declared_resolver_masks_the_column(self) -> None:
        """The redacted "bio" publishes its name and withholds its value.

        Fails CLOSED on purpose: no build-time analysis can read a resolver
        body, so a resolver that happens to return the column loses it too.
        """
        node = MaskedBioAuthorType._meta.graphql_output_type
        assert "bio" in node.fields
        assert not publishes_column_value(node, Author._meta.get_field("bio"))

    def test_the_unprojected_columns_are_still_published(self) -> None:
        """The masking answer must be about "bio" alone.

        Guards the assertion above against a predicate that simply says no.
        """
        node = MaskedBioAuthorType._meta.graphql_output_type
        assert publishes_column_value(node, Author._meta.get_field("name"))

    def test_a_column_the_projection_removed_is_not_published(self) -> None:
        """A column with no field at all is the simplest unpublished case.

        Absence and masking are the same answer.
        """
        node = KeylessAuthorType._meta.graphql_output_type
        assert not publishes_column_value(node, Author._meta.get_field("bio"))


class TestAVerbatimRepublicationPublishesTheColumn:
    """A declaration that serves the column's own value keeps it published.

    Case 2, and the over-refusal that had to die with it: stamping EVERY
    declared field carrying a resolver cost a type that projects nothing its
    ordering and, through the primary key, its cursor pagination.
    """

    def test_a_declaration_without_a_resolver_publishes_the_column(self) -> None:
        """The default resolver reads the attribute, so the value is the column's.

        The ordering axis already pins this as legitimate; the filter axis
        refused it, and this is the half that survives.
        """
        node = PassthroughBioAuthorType._meta.graphql_output_type
        assert publishes_column_value(node, Author._meta.get_field("bio"))

    def test_the_same_name_source_shortcut_publishes_the_column(self) -> None:
        """The documented shortcut reads the column itself off the row.

        Reproduced before it was encoded: the compiled field carried the masked
        stamp, so a type declaring no projection at all lost the column.
        """
        node = SourcedBioAuthorType._meta.graphql_output_type
        assert publishes_column_value(node, Author._meta.get_field("bio"))

    def test_the_shortcut_keeps_the_primary_key_published(self) -> None:
        """The key is the term every cursor page needs for its tiebreak.

        The same type publishes its key normally, so the shortcut must not cost
        the pk either.
        """
        node = SourcedBioAuthorType._meta.graphql_output_type
        assert publishes_column_value(node, Author._meta.pk)

    def test_a_source_naming_another_attribute_masks_the_column(self) -> None:
        """A redirected source is a mask, not a republication.

        The shortcut is accepted for the SAME name only; anything else serves a
        value the column does not hold.
        """
        node = SourcedElsewhereAuthorType._meta.graphql_output_type
        assert "bio" in node.fields
        assert not publishes_column_value(node, Author._meta.get_field("bio"))


class TestAFieldOwningNoColumnPublishesNothing:
    """A field with no column on this model has no value to publish here.

    The predicate's FIRST clause, and the one a mutant survived: drop the
    "concrete" test and a reverse relation stops answering False and starts
    answering whatever its TARGET says about the key it points at -- which for
    any node publishing an "id" is True. The rest of the predicate cannot catch
    it, because every later rule is written for a field that owns a column.

    This is a fail-closed clause on the boundary both projection axes read, so
    flipping it hands the ordering allowlist a name that ranks by no column on
    the row at all.
    """

    def test_a_reverse_one_to_one_publishes_no_column(self) -> None:
        """The key lives on the OTHER model, so this one publishes no value.

        The type publishes the relation and the target publishes the key the
        relation points at, so every rule below the "concrete" clause answers
        True -- and the answer is wrong: an author row holds no profile column
        to rank by.
        """
        node = ReverseAuthorType._meta.graphql_output_type
        assert "authorProfile" in node.fields
        assert not publishes_column_value(
            node, Author._meta.get_field("author_profile")
        )

    def test_a_reverse_foreign_key_publishes_no_column(self) -> None:
        """A to-many owns no column on the declaring model either.

        Pinned beside the one-to-one because the two reach the clause by
        different routes, and only one of them has to survive for the ordering
        allowlist to admit a name that ranks by nothing.
        """
        node = KeyedAuthorType._meta.graphql_output_type
        assert "posts" in node.fields
        assert not publishes_column_value(node, Author._meta.get_field("posts"))


class TestAForwardRelationDoesNotPublishTheKey:
    """The foreign key column holds the TARGET's key, so the target answers for it.

    Case 3: publishing the relation publishes the target's rows, not the key's
    value -- and the key's value is what the column ranks and the cursor prints.
    """

    def test_a_keyless_target_leaves_the_foreign_key_unpublished(self) -> None:
        """No type in this schema exposes an author's key, so neither does the column.

        Reproduced first: the ordering allowlist admitted "author_id" here.
        """
        node = KeylessPostType._meta.graphql_output_type
        assert "author" in node.fields
        assert not publishes_column_value(node, Post._meta.get_field("author"))

    def test_a_keyed_target_publishes_the_foreign_key(self) -> None:
        """The key is readable through the relation, so the column is published.

        The fix must cost no legitimate ordering.
        """
        node = KeyedPostType._meta.graphql_output_type
        assert publishes_column_value(node, Post._meta.get_field("author"))

    def test_a_declared_relation_publishes_no_key_of_its_own(self) -> None:
        """A relation served by a resolver answers for no key on the row.

        This fixture's resolver hands out an UNSAVED stand-in, so no row's
        author is readable through it at all -- and a carve-out that let the
        declaration ride through unstamped published "author_id" to the
        ordering allowlist anyway: a live ranking oracle over a key no type in
        the schema serves. The shape is indistinguishable at build time from
        the documented to-one scoping hatch, whose resolver returns a SCOPED
        target and still ranks the rows it hides, so both fail closed.
        """
        node = MaskedRelationPostType._meta.graphql_output_type
        assert "author" in node.fields
        assert not publishes_column_value(node, Post._meta.get_field("author"))

    def test_a_relation_name_over_another_models_type_publishes_no_key(self) -> None:
        """A declared type that does not serve the TARGET answers for nothing.

        Two independent reasons now: the declaration is stamped, AND the walk
        would land in an unrelated field map where "id" is published by every
        node and would have said yes. The second is what the assertion is for.
        """
        node = WrongTargetPostType._meta.graphql_output_type
        assert "author" in node.fields
        assert not publishes_column_value(node, Post._meta.get_field("author"))

    def test_a_relation_name_over_a_leaf_publishes_no_key(self) -> None:
        """A declaration compiling to a scalar publishes no relation to ask.

        Nothing traverses through a leaf, so there is no target type to ask for
        the key even before the mask stamp is read.
        """
        node = ScalarRelationPostType._meta.graphql_output_type
        assert "author" in node.fields
        assert not publishes_column_value(node, Post._meta.get_field("author"))


class TestAnUnregisteredRelationTargetPublishesNothing:
    """A relation the output compiler drops is not in the SDL at all.

    Case 4: the compiler refuses to emit a to-one relation whose target model
    has no registered type, so the type publishes neither the relation nor the
    foreign key behind it.
    """

    def test_the_dropped_relation_is_absent_from_the_sdl(self) -> None:
        """The fixture only means something if the compiler really dropped it.

        Guards the assertion below against a silently registered target.
        """
        node = KeylessPostType._meta.graphql_output_type
        assert "category" not in node.fields

    def test_the_dropped_relation_publishes_no_column(self) -> None:
        """No field, no published value -- the same answer absence always gives.

        The predicate reads the compiled field map, so it inherits this from the
        compiler instead of re-deriving it.
        """
        node = KeylessPostType._meta.graphql_output_type
        assert not publishes_column_value(node, Post._meta.get_field("category"))


class TestMultiTableInheritancePublishesTheParentKey:
    """The child's own pk is the parent link, and the parent's key is published.

    Case 5: asking whether the parent-link FIELD is in the SDL answers the wrong
    question -- the two hold the same value on every row.
    """

    def test_the_parent_link_is_not_in_the_sdl(self) -> None:
        """The compiler drops the link as join plumbing.

        Guards the assertion below: without this the next test could pass for
        the wrong reason.
        """
        node = MtiRestaurantType._meta.graphql_output_type
        assert "mtiplacePtr" not in node.fields
        assert "id" in node.fields

    def test_the_parent_links_value_is_published_as_the_inherited_key(self) -> None:
        """The child publishes the parent's key, so the link column is published.

        This is the term every cursor page over the child needs.
        """
        node = MtiRestaurantType._meta.graphql_output_type
        assert publishes_column_value(node, MtiRestaurant._meta.pk)

    def test_hiding_the_inherited_key_unpublishes_the_parent_link(self) -> None:
        """With the inherited key projected away there is no readable key left.

        The walk follows the link to the key it points at; hiding that key
        withdraws the link's value with it.
        """
        node = KeylessMtiRestaurantType._meta.graphql_output_type
        assert not publishes_column_value(node, MtiRestaurant._meta.pk)


class TestThePredicateAnswersAboutTheTypeItIsHanded:
    """No registry lookup: the caller names the type, and that type answers.

    Case 6: the registry is a last-wins index a type can leave with
    "Meta.skip_registry", which turned a registry-resolved guard into a no-op.
    """

    def test_the_registry_slot_belongs_to_the_other_type(self) -> None:
        """The fixture only means something if the lookup really answers wrong.

        Pins the contradiction a registry-resolved guard would read.
        """
        assert _RSKIP.get_type_for_model(Author) is RegisteredAuthorType

    def test_the_opted_out_type_answers_with_its_own_projection(self) -> None:
        """The serving type hides the column, and the serving type is what is asked.

        The registry would have said the column is published.
        """
        node = OptedOutAuthorType._meta.graphql_output_type
        assert not publishes_column_value(node, Author._meta.get_field("bio"))

    def test_the_registered_type_still_publishes_the_column(self) -> None:
        """The two types answer differently about the same model column.

        Which is the whole point of taking the type explicitly.
        """
        node = RegisteredAuthorType._meta.graphql_output_type
        assert publishes_column_value(node, Author._meta.get_field("bio"))


class TestThePrunedCloneAnswersForItself:
    """A permission-scoped schema publishes less, and it is a different clone.

    Case 7: the predicate reads the compiled type it is given and follows
    relations through that type's field map, so passing the SERVING schema's
    type is what makes the answer describe the schema serving the request.
    """

    def test_the_pruned_schema_drops_the_relation(self) -> None:
        """The fixture only means something if the prune really removes it.

        Guards the rest of this class against a schema the pruner never
        touched.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _post_only_grant())
        assert "author" not in pruned.type_map["PrunedPostType"].fields
        assert "PrunedAuthorType" not in pruned.type_map

    def test_the_full_schema_publishes_the_foreign_key(self) -> None:
        """A caller the pruner never touched keeps the column.

        The contrast that makes the next assertion about the prune and not
        about the projection.
        """
        node = prune_schema_source.graphql_schema.type_map["PrunedPostType"]
        assert publishes_column_value(node, Post._meta.get_field("author"))

    def test_the_pruned_clone_does_not_publish_the_foreign_key(self) -> None:
        """The clone denies the relation exists, so it publishes no key behind it.

        Same model column, same predicate, different compiled type, different
        answer.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _post_only_grant())
        node = pruned.type_map["PrunedPostType"]
        assert not publishes_column_value(node, Post._meta.get_field("author"))

    def test_the_clones_relation_points_at_the_clone(self) -> None:
        """A surviving relation is rebuilt against the pruned target type.

        This is why the relation hop needs no extra plumbing: whatever the
        clone's target type publishes is what the recursion reads.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _full_grant())
        relation = pruned.type_map["PrunedPostType"].fields["author"]
        assert relation.type is pruned.type_map["PrunedAuthorType"]
        assert publishes_column_value(
            pruned.type_map["PrunedPostType"], Post._meta.get_field("author")
        )


class TestTheDomainIsAConcreteColumn:
    """The predicate answers about a COLUMN, and fails closed off that domain.

    A field that owns no column -- a reverse relation, a many-to-many, a generic
    foreign key -- has no value for a type to publish, and asking about the
    traversability of such a relation is a different question this predicate
    does not answer.
    """

    def test_a_reverse_relation_owns_no_column(self) -> None:
        """A reverse accessor is not a column on this model.

        Answering True here would let a caller read the predicate as a
        statement about relation traversal, which it is not.
        """
        node = KeyedAuthorType._meta.graphql_output_type
        assert not publishes_column_value(node, Author._meta.get_field("posts"))

    def test_a_type_with_no_field_map_publishes_nothing(self) -> None:
        """No SDL to read, no published value.

        The same fail-closed rule the ordering allowlist already applies to a
        caller with no compiled type.
        """
        assert not publishes_column_value(None, Author._meta.get_field("bio"))


class TestASelfTargetingKeyStopsTheWalk:
    """Case 10: the one field shape whose target is the field itself.

    A one-to-one relation to "self" declared as the primary key is BOTH the
    relation and the key it points at, so the rule that sends a forward
    relation's question to the target type sends it straight back here. The
    clause that stops the walk is unreachable by every other model this suite
    ships -- no other concrete field is its own "target_field" -- and deleting
    it does not merely change an answer: the recursion runs until the
    interpreter stops it, and the "RecursionError" surfaces as a schema that
    cannot be built.
    """

    def test_the_fixture_really_targets_itself(self) -> None:
        """The clause only means something if Django produces this shape.

        Guards the assertions below against a model whose target field is some
        other column after all.
        """
        pk = SelfKeyedNode._meta.pk
        assert pk is SelfKeyedNode._meta.get_field("link")
        assert pk.target_field is pk
        assert SelfKeyedNode.check() == []

    def test_the_predicate_answers_without_recursing(self) -> None:
        """The type publishes the relation, so it publishes the key it holds.

        The answer is read off THIS field, never fetched from a target type,
        which is the whole content of the clause.
        """
        node = self_keyed_schema.graphql_schema.type_map["SelfKeyedNodeType"]
        assert publishes_column_value(node, SelfKeyedNode._meta.pk)

    def test_hiding_the_relation_hides_the_key(self) -> None:
        """Stopping the walk still respects the projection.

        A stop that answered True unconditionally would publish the key of
        every type that hides it.
        """
        node = self_keyed_schema.graphql_schema.type_map["SelfKeyedNodeType"]
        removed = node.fields.pop("link")
        try:
            assert not publishes_column_value(node, SelfKeyedNode._meta.pk)
        finally:
            node.fields["link"] = removed


@pytest.mark.django_db
class TestARelationRenderedByAnotherModelsTypeStillServesTheKey(TestCase):
    """A declared relation's TYPE is a rendering choice, not the value's source.

    Case 9. "author = Field(CategoryType)" on a "Post" node publishes the
    relation under a type bound to a different model, and the guide once
    promised the predicate would answer "No" for "author_id" on the grounds
    that no target answers for the key. It does not, and it must not: the
    declaration carries no resolver, so graphql-core's default attribute
    resolver hands out "post.author" -- the REAL "Author" row -- and the
    same-named "id" field on the rendering type reads straight off it. The key
    is served, and refusing to rank by a value the very same request returns is
    the drift between SDL and guard the predicate was written to end.

    The shape stays a schema bug: the rendering type's own columns come back
    "None". It is not a projection boundary.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a post whose author's key differs from the post's own.

        Two filler authors push the real one off "1", so the id the response
        carries cannot be mistaken for the post's.

        """
        Author.objects.create(name="filler-one", bio="")
        Author.objects.create(name="filler-two", bio="")
        cls.author = Author.objects.create(name="real", bio="")
        Post.objects.create(title="t", author=cls.author)

    def test_the_relation_hands_out_the_targets_real_key(self) -> None:
        """The response carries the author's own primary key.

        The rendering type does not replace the related row's identity.
        """
        result = graphql_sync(
            foreign_render_schema.graphql_schema,
            "{ posts { results { author { id } } } }",
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        served = result.data["posts"]["results"][0]["author"]["id"]
        assert served == str(self.author.pk)

    def test_the_predicate_agrees_the_key_is_published(self) -> None:
        """So the foreign key column stays orderable and filterable.

        The predicate follows the value the relation actually publishes.
        """
        node = ForeignRenderPostType._meta.graphql_output_type
        assert publishes_column_value(node, Post._meta.get_field("author"))
