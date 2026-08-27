# -*- coding: utf-8 -*-
"""Tests for the two facts a NAME in the SDL cannot answer about ordering.

Round 5 moved the ordering allowlist off a hand-written mirror of "Meta" and
onto the compiled type's own field map: whatever the SDL publishes is what
"ordering" may name. That closed the drift, and left two questions the field
NAME alone cannot answer.

  - WHOSE VALUE does the name serve? A declared class attribute wins over the
    model-derived field of the same name ("types._compile_declared_fields"), so
    a type that hides "bio" through "only_fields" and then declares
    "bio = CharField()" with a "resolve_bio" returning a redacted string
    publishes the NAME while withholding the VALUE. Sorting by it ranks the rows
    by the raw column -- a read oracle over a value the response never carries,
    and, on the cursor paginator, a verbatim print of the column into
    "startCursor". A declaration with NO resolver is the opposite case: its
    default resolver reads the attribute, so the value IS served and the column
    stays orderable. Both are pinned here, side by side, because the predicate
    is exactly the difference between them.

  - WHICH SCHEMA is asking? Under "PERMISSION_SCOPED_SCHEMA" the pruned schema
    is a CLONE, and "core.schema_pruner._rebuild_field" carries "resolve"
    through verbatim -- so the pruned container's results resolver held the FULL
    schema's paginator, whose allowlist was derived from the PRE-prune node
    type. A caller denied "view_author" got a schema with no "author" field on
    the post node and no author type at all, and could still rank the rows by
    "authorId".

Failing closed is the tie-break in both. A "resolve_bio" that happens to return
the real column costs its type the ordering term; the alternative is trusting a
resolver body no build-time analysis can read.
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import CharField, ObjectType
from django_graphex.core.perm_labels import implicit_perms_for_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination,
    projected_ordering_attnames,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import Author, Post

# ---------------------------------------------------------------------------
# A declared field that MASKS the column it shadows
# ---------------------------------------------------------------------------

_RMASK = Registry()


class MaskedBioAuthorType(DjangoObjectType):
    """Author node that hides "bio" and re-publishes the NAME over a redaction.

    "only_fields" drops the model-derived "bio"; the declared attribute below
    puts the name back with a resolver that never reads the column. The SDL
    therefore advertises "bio" while every response carries a constant.
    """

    bio = CharField()

    class Meta:
        """Configuration for "MaskedBioAuthorType".

        Restricts the model-derived fields to "id" and "name" so the declared
        "bio" is the only thing publishing that name.
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


class MaskedBioAuthorListType(DjangoListObjectType):
    """Paginated container over "MaskedBioAuthorType".

    Present so the node type reaches a schema and its "ordering" argument can
    be exercised against the masked name.
    """

    class Meta:
        """Configuration for "MaskedBioAuthorListType".

        Declares no projection of its own; the node type's applies.
        """

        model = Author
        registry = _RMASK
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class MaskQuery(ObjectType):
    """Root query exposing the author list whose node masks "bio".

    Feeds the masking tests below.
    """

    authors = DjangoListObjectField(MaskedBioAuthorListType)


mask_schema = DjangoGraphQLSchema(query=MaskQuery, registries=isolated_pair(_RMASK))


# ---------------------------------------------------------------------------
# The same declaration WITHOUT a resolver: the value is served, so it is orderable
# ---------------------------------------------------------------------------

_RPASS = Registry()


class PassthroughBioAuthorType(DjangoObjectType):
    """Author node that hides "bio" and re-publishes it with the default resolver.

    The contrast case. No "resolve_bio" is declared, so the compiled field keeps
    graphql-core's default attribute resolver and serves the real column --
    "orderable" and "selectable" still agree, and the term must be accepted.
    """

    bio = CharField()

    class Meta:
        """Configuration for "PassthroughBioAuthorType".

        Identical projection to the masking type above; the ONLY difference is
        the absent resolver.
        """

        model = Author
        registry = _RPASS
        only_fields = ("id", "name")


# ---------------------------------------------------------------------------
# A declared field masking the PRIMARY KEY
# ---------------------------------------------------------------------------

_RMASKPK = Registry()


class MaskedPkAuthorType(DjangoObjectType):
    """Author node whose published "id" is a resolver output, not the key.

    The pk aliases ("pk", the key's name, the key's attname) ride into the
    allowlist exactly when the key's VALUE is published. A masked "id" publishes
    the name only, so the aliases must stay out -- otherwise "ordering: 'pk'"
    ranks the rows by a key the response never shows.
    """

    id = CharField()

    class Meta:
        """Configuration for "MaskedPkAuthorType".

        Keeps "name" only, so the declared "id" is the sole publisher of the
        primary key's name.
        """

        model = Author
        registry = _RMASKPK
        only_fields = ("name",)

    def resolve_id(self, info: Any) -> str:
        """Return an opaque identifier in place of the primary key.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            A constant standing in for the row's primary key.
        """
        return "opaque"


# ---------------------------------------------------------------------------
# Permission-scoped schema: the pruned clone must answer for ITSELF
# ---------------------------------------------------------------------------

_RPRUNE = Registry()


class PrunedAuthorType(DjangoObjectType):
    """Author node reachable only through the post node's "author" relation.

    A caller who does not hold this model's read permission loses the relation
    field, and the type falls out of the pruned schema entirely.
    """

    class Meta:
        """Configuration for "PrunedAuthorType".

        Declares no projection: everything this node loses, it loses to the
        permission prune.
        """

        model = Author
        registry = _RPRUNE


class PrunedPostType(DjangoObjectType):
    """Post node publishing the "author" relation the pruner may remove.

    The relation is what makes "author_id" orderable in the FULL schema; once
    the pruner drops the field, that column is no longer published and the
    ordering term must go with it.
    """

    class Meta:
        """Configuration for "PrunedPostType".

        Names the relation explicitly so the full schema's allowlist carries
        "author_id" and the pruned schema's must not.
        """

        model = Post
        registry = _RPRUNE
        only_fields = ("id", "title", "author")


class PrunedPostListType(DjangoListObjectType):
    """Paginated container over "PrunedPostType".

    Its results field is the one whose resolver the pruner clones verbatim, so
    it is where the pre-prune allowlist used to survive.
    """

    class Meta:
        """Configuration for "PrunedPostListType".

        Carries the paginator whose ordering allowlist the prune has to
        re-derive.
        """

        model = Post
        registry = _RPRUNE
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class PruneQuery(ObjectType):
    """Root query exposing the post list used by the pruning tests.

    Feeds both the full-schema and pruned-schema assertions below.
    """

    posts = DjangoListObjectField(PrunedPostListType)


prune_schema_source = DjangoGraphQLSchema(
    query=PruneQuery, registries=isolated_pair(_RPRUNE)
)


# ---------------------------------------------------------------------------
# The FLAT paginated list field: the same question, a different resolver shape
# ---------------------------------------------------------------------------

_RFLAT = Registry()


class FlatPrunedAuthorType(DjangoObjectType):
    """Author node reachable only through the flat list's post relation.

    Same role as "PrunedAuthorType", in the registry the flat field's schema
    is built from.
    """

    class Meta:
        """Configuration for "FlatPrunedAuthorType".

        Declares no projection: the permission prune is what removes it.
        """

        model = Author
        registry = _RFLAT


class FlatPrunedPostType(DjangoObjectType):
    """Post node served DIRECTLY by a "DjangoFilterPaginateListField".

    That field paginates inside its OWN resolver instead of a list container,
    so its paginator is stamped in "fields.py" rather than in the container
    thunk -- a second shape the pruner has to answer for.
    """

    class Meta:
        """Configuration for "FlatPrunedPostType".

        Publishes the relation, so the full schema's allowlist carries
        "author_id" and the pruned schema's must not.
        """

        model = Post
        registry = _RFLAT
        only_fields = ("id", "title", "author")


class FlatPruneQuery(ObjectType):
    """Root query exposing the flat paginated post list.

    Feeds the flat-field arm of the pruning tests below.
    """

    posts = DjangoFilterPaginateListField(
        FlatPrunedPostType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, max_limit=20),
    )


# ---------------------------------------------------------------------------
# The flat field's stamp runs while the ROOT class body is still executing
# ---------------------------------------------------------------------------
# Deriving the allowlist reads the node type's compiled field map, and reading
# it CACHES it. Here the relation target is defined AFTER the root that mounts
# the list, which is legal and ordinary; the output compiler drops a relation
# whose target is not yet registered, so forcing the field map at mount time
# would freeze "LateAuthorType" out of "LatePostType" permanently. The stamp is
# deferred for exactly this reason, and the assertion below is what says so.

_RLATE = Registry()


class LatePostType(DjangoObjectType):
    """Post node whose relation target is registered later in this module.

    Mounted on the root below before "LateAuthorType" exists, so its compiled
    field map must not be built until the schema is.
    """

    class Meta:
        """Configuration for "LatePostType".

        Names the relation, so the target's late registration is visible in the
        compiled field map rather than being projected away.
        """

        model = Post
        registry = _RLATE
        only_fields = ("id", "title", "author")


class LateQuery(ObjectType):
    """Root query mounting the flat list before the relation target exists.

    Declaring the field is what stamps the paginator, so this class body is the
    moment the allowlist would be derived if it were derived eagerly.
    """

    posts = DjangoFilterPaginateListField(
        LatePostType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, max_limit=20),
    )


class LateAuthorType(DjangoObjectType):
    """Author node registered AFTER the root that mounts the post list.

    Its lateness is the whole fixture: a relation whose target is unregistered
    is dropped by the output compiler.
    """

    class Meta:
        """Configuration for "LateAuthorType".

        Shares the registry the post node above resolves its relation through.
        """

        model = Author
        registry = _RLATE


late_schema = DjangoGraphQLSchema(query=LateQuery, registries=isolated_pair(_RLATE))


flat_prune_schema_source = DjangoGraphQLSchema(
    query=FlatPruneQuery, registries=isolated_pair(_RFLAT)
)


def _post_only_grant() -> frozenset[str]:
    """Return the permissions that keep "Post" but drop "Author".

    Reading the label off the compiled type rather than spelling the codename
    keeps the fixture honest if the label scheme ever changes.

    Returns:
        The read permissions the post node implies, with nothing else.
    """
    perms = implicit_perms_for_type(
        PrunedPostType._meta.graphql_output_type,
        prune_schema_source.graphql_schema,
    )
    return frozenset(perms or ())


def _flat_post_only_grant() -> frozenset[str]:
    """Return the same post-only grant, resolved against the flat schema.

    Returns:
        The read permissions the flat post node implies, with nothing else.
    """
    perms = implicit_perms_for_type(
        FlatPrunedPostType._meta.graphql_output_type,
        flat_prune_schema_source.graphql_schema,
    )
    return frozenset(perms or ())


class MaskedDeclaredFieldOrderingTests(TestCase):
    """The allowlist must follow the VALUE, not the published name.

    Pins both halves of the predicate: a declared field with a resolver loses
    its column, a declared field without one keeps it.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed authors whose "bio" order is not their "name" order.

        Sorted by name the rows read alice, bob, carol; sorted by bio they read
        bob, carol, alice, so a leaked ordering is visible in the response.
        """
        Author.objects.create(name="alice", bio="zzz")
        Author.objects.create(name="bob", bio="aaa")
        Author.objects.create(name="carol", bio="mmm")

    def test_a_masked_column_is_not_in_the_allowlist(self) -> None:
        """A declared field with its own resolver does not publish the column.

        The other two model-derived names are asserted alongside it so a wholly
        empty allowlist cannot pass this test.
        """
        allowed = projected_ordering_attnames(
            Author, MaskedBioAuthorType._meta.graphql_output_type
        )
        assert "bio" not in allowed
        assert {"id", "name"} <= allowed

    def test_the_masked_name_is_still_in_the_sdl(self) -> None:
        """The field is published; only its ORDERING is withdrawn.

        Nothing about the SDL changes -- the type still advertises the name and
        still serves the redaction.
        """
        assert "bio" in MaskedBioAuthorType._meta.graphql_output_type.fields

    def test_ordering_by_a_masked_column_is_refused(self) -> None:
        """Sorting by the redacted name must not rank the rows by the column.

        The end-to-end arm: the allowlist assertions above are what the request
        path is supposed to enforce, and this is the request path.
        """
        result = graphql_sync(
            mask_schema.graphql_schema,
            '{ authors { results(ordering: "bio") { name bio } } }',
        )
        assert result.errors, result.data
        assert "Invalid ordering field: 'bio'." in str(result.errors[0])

    def test_a_declaration_without_a_resolver_stays_orderable(self) -> None:
        """The default resolver serves the real column, so the term stands.

        The guard is drawn at the resolver, not at the declaration: refusing
        every declared field would take this legitimate case with it.
        """
        allowed = projected_ordering_attnames(
            Author, PassthroughBioAuthorType._meta.graphql_output_type
        )
        assert "bio" in allowed

    def test_a_masked_primary_key_withdraws_the_pk_aliases(self) -> None:
        """A resolver-published "id" is not the key, so "pk" cannot ride along.

        The pk aliases enter the allowlist only when the key's value is
        published, and a masked "id" publishes a constant.
        """
        allowed = projected_ordering_attnames(
            Author, MaskedPkAuthorType._meta.graphql_output_type
        )
        assert "pk" not in allowed
        assert "id" not in allowed


class PrunedSchemaOrderingTests(TestCase):
    """The allowlist must describe the schema actually serving the request.

    Under "PERMISSION_SCOPED_SCHEMA" that is a per-caller clone, not the full
    schema the paginator was first stamped against.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed two posts whose author order reverses their title order.

        Descending "author_id" therefore returns p2 then p1, which is how a
        leaked ordering shows up in the response body.
        """
        zeta = Author.objects.create(name="zeta", bio="")
        alpha = Author.objects.create(name="alpha", bio="")
        Post.objects.create(title="p1", author=zeta)
        Post.objects.create(title="p2", author=alpha)

    def test_the_pruned_schema_drops_the_relation_field(self) -> None:
        """The fixture only means anything if the prune actually removes it.

        Guards the rest of this class against silently testing an unpruned
        schema if the permission labels ever change.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _post_only_grant())
        assert "author" not in pruned.type_map["PrunedPostType"].fields
        assert "PrunedAuthorType" not in pruned.type_map

    def test_the_full_schema_still_orders_by_the_relation_column(self) -> None:
        """Nothing changes for a caller the pruner never touched.

        The full schema publishes the relation, so its foreign key stays
        orderable and the fix costs no legitimate ordering.
        """
        result = graphql_sync(
            prune_schema_source.graphql_schema,
            '{ posts { results(ordering: "-authorId") { title } } }',
        )
        assert result.errors is None, result.errors
        assert [row["title"] for row in result.data["posts"]["results"]] == [
            "p2",
            "p1",
        ]

    def test_the_pruned_schema_refuses_the_pruned_away_column(self) -> None:
        """A column the pruned SDL denies exists must not rank its rows.

        The reproduction: before the fix this returned p2, p1 -- the rows ranked
        by a foreign key the caller was denied.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _post_only_grant())
        result = graphql_sync(
            pruned, '{ posts { results(ordering: "-authorId") { title } } }'
        )
        assert result.errors, result.data
        assert "Invalid ordering field: 'author_id'." in str(result.errors[0])

    def test_the_pruned_schema_keeps_the_columns_it_publishes(self) -> None:
        """Pruning withdraws the denied column only, not the whole argument.

        Re-deriving the allowlist per clone must not degrade to the empty set,
        which would refuse every ordering in every pruned schema.
        """
        pruned = prune_schema(prune_schema_source.graphql_schema, _post_only_grant())
        result = graphql_sync(
            pruned, '{ posts { results(ordering: "-title") { title } } }'
        )
        assert result.errors is None, result.errors
        assert [row["title"] for row in result.data["posts"]["results"]] == [
            "p2",
            "p1",
        ]

    def test_a_full_grant_prunes_nothing_and_keeps_the_cycle_buildable(self) -> None:
        """A full grant prunes nothing, and the cyclic clone graph still builds.

        The rescope runs from inside the pruner's own field walk, and a full
        grant keeps the relation that closes the cycle back from the author node
        to this very container. Deriving the allowlist from a clone whose field
        map is a thunk into the running walk is re-entrant by construction, so
        this is the shape any future eager rewrite has to survive.
        """
        granted = _post_only_grant() | frozenset(
            implicit_perms_for_type(
                PrunedAuthorType._meta.graphql_output_type,
                prune_schema_source.graphql_schema,
            )
            or ()
        )
        pruned = prune_schema(prune_schema_source.graphql_schema, granted)
        assert "author" in pruned.type_map["PrunedPostType"].fields
        result = graphql_sync(
            pruned, '{ posts { results(ordering: "-authorId") { title } } }'
        )
        assert result.errors is None, result.errors
        assert [row["title"] for row in result.data["posts"]["results"]] == [
            "p2",
            "p1",
        ]

    def test_the_flat_paginated_field_is_pruned_the_same_way(self) -> None:
        """The in-resolver paginator must not keep the pre-prune allowlist.

        A flat "DjangoFilterPaginateListField" paginates in its own resolver, a
        different shape from the container's results closure, and it was open
        the same way.
        """
        pruned = prune_schema(
            flat_prune_schema_source.graphql_schema, _flat_post_only_grant()
        )
        assert "author" not in pruned.type_map["FlatPrunedPostType"].fields
        result = graphql_sync(pruned, '{ posts(ordering: "-authorId") { title } }')
        assert result.errors, result.data
        assert "Invalid ordering field: 'author_id'." in str(result.errors[0])

    def test_the_flat_field_does_not_freeze_a_late_relation_target(self) -> None:
        """Stamping the paginator must not compile the node type at mount time.

        The node's field map is cached the first time it is read. Reading it
        while the root class body still runs would drop -- permanently -- every
        relation whose target is registered further down the module.
        """
        node = late_schema.graphql_schema.type_map["LatePostType"]
        assert "author" in node.fields, sorted(node.fields)
        assert "LateAuthorType" in late_schema.graphql_schema.type_map
