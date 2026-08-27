# -*- coding: utf-8 -*-
"""The filter axis must answer the projection question with the SHARED predicate.

Two writers implemented the two projection axes -- ordering and filtering --
separately, and each invented its own notion of "hidden". The ordering axis
reads the COMPILED type ("core.output_compiler.publishes_column_value"); the
filter axis re-read "Meta.only_fields" / "Meta.exclude_fields" by hand. The two
answers then contradicted each other on the very same declaration: a column
re-published verbatim by an explicit class attribute is ORDERABLE (the ordering
axis pins that as legitimate) and was REFUSED as a filter.

That is the drift the ordering axis already suffered internally -- a hand copy
of the output compiler's rules going out of sync with the compiler -- repeated
BETWEEN axes. One predicate, consumed by both, is the only shape that cannot
drift, so everything pinned here is a consequence of consuming it.

Four blockers close with it:

  - the guard resolved the projection through "registry.get_type_for_model",
    a last-wins index a type opts out of with the public "Meta.skip_registry",
    which made the guard a NO-OP for such a type;
  - a relation-DIRECT lookup ("filter_fields = {'owner': ('exact',)}") compares
    the TARGET's primary key, but the guard measured the hop against the hop
    OWNER's type, so it cleared a key the target type projects away;
  - a relation whose target model has no registered type was SKIPPED, while
    the output compiler DROPS that relation from the SDL entirely -- leaving a
    full nested filter input over a model unreachable in the schema;
  - "@filter_field" is the rename hatch out of every refusal above, and the
    one thing the compiler can read about it is its NAME.

The residual stays open and stated: an "@filter_field" body is user Python, so
a method named anything else may still reach a hidden column. See
"tests/test_filter_projection_boundary.py" for that boundary.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.core import CharField, ObjectType
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.filtering import filter_field
from django_graphex.filtering.native_schema import build_filter_input_type
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post


class TestTheDeclarationDecidesWithTheSharedPredicate:
    """A declared attribute that re-publishes a column keeps it filterable.

    This is the case the two axes disagreed on. The output compiler stamps a
    declared class attribute that publishes a column's NAME over a resolver of
    its own; the SAME-NAME "source=" shortcut is provably a read of that very
    attribute, so it is NOT stamped and the column is genuinely served.
    """

    def test_a_same_name_source_shortcut_keeps_the_column_filterable(self) -> None:
        """A projected column re-published by "source=" must stay filterable.

        The ordering axis already allows ordering by this column, because the
        type demonstrably serves its value. If this breaks, the two axes
        contradict each other again on one declaration.
        """
        reg = Registry()

        class _SourcedAuthorType(DjangoObjectType):
            """Author type re-publishing "bio" through a same-name source."""

            bio = CharField(source="bio")

            class Meta:
                """Bind to "Author", drop "bio", re-publish it verbatim."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        assert _SourcedAuthorType is not None
        filter_input = build_filter_input_type(
            Author,
            {"bio": ("exact",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        assert "bio" in filter_input.fields

    def test_a_masked_column_stays_refused(self) -> None:
        """A declared attribute serving something ELSE must still be refused.

        The compiler stamps it, so the predicate reads the stamp rather than
        guessing at the resolver. If this breaks, publishing the NAME is
        mistaken for publishing the VALUE and the oracle reopens.
        """
        reg = Registry()

        class _MaskedAuthorType(DjangoObjectType):
            """Author type publishing "bio" over a resolver of its own."""

            class Meta:
                """Bind to "Author" and drop "bio" from the output."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

            @staticmethod
            def resolve_bio(root: Any, info: Any) -> str:
                """Serve a redacted stand-in instead of the column.

                Args:
                    root: The row being resolved.
                    info: The GraphQL resolve info for the current request.

                Returns:
                    A constant placeholder.
                """
                return "redacted"

        assert _MaskedAuthorType is not None
        with pytest.raises(ImproperlyConfigured):
            build_filter_input_type(
                Author, {"bio": ("exact",)}, reg, registries=isolated_pair(reg)
            )


class TestTheGuardMeasuresTheTypeThatServesTheRequest:
    """A type that opted out of the registry must still be measured.

    "Meta.skip_registry" is a PUBLIC option, and the registry is a last-wins
    model index. Resolving the projection through it made the guard a no-op
    for exactly the type the schema is about to serve.
    """

    def test_skip_registry_type_is_still_guarded(self) -> None:
        """A "skip_registry" type filtering a hidden column must fail the build.

        If this breaks, adding one public Meta option turns the whole
        projection boundary off for that type.
        """
        reg = Registry()

        class _UnregisteredAuthorType(DjangoObjectType):
            """Author type kept out of the registry entirely."""

            class Meta:
                """Bind to "Author", drop "bio", opt out of the registry."""

                model = Author
                registry = reg
                only_fields = ("id", "name")
                skip_registry = True

        class _SkipQuery(ObjectType):
            """Root query filtering the unregistered type by a hidden column."""

            authors = DjangoFilterPaginateListField(
                _UnregisteredAuthorType,
                pagination=LimitOffsetGraphqlPagination(default_limit=10),
                fields=["bio"],
            )

        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_SkipQuery, registries=isolated_pair(reg))

        assert "bio" in str(exc.value)


class TestRelationDirectLookupsAskTheTarget:
    """A relation filtered without a tail compares the TARGET's primary key.

    The old guard measured that hop against the hop OWNER's type, so hiding
    the key on the target did nothing: "owner__code" was refused while the
    strictly stronger "owner" was cleared.
    """

    def test_a_target_hiding_its_key_refuses_the_direct_lookup(self) -> None:
        """Filtering a relation whose target hides its key must raise.

        If this breaks, "filter: {author: {exact: 1}}" probes a primary key
        the author type removed from the SDL, one request per candidate.
        """
        reg = Registry()

        class _KeylessAuthorType(DjangoObjectType):
            """Author type publishing only "name"."""

            class Meta:
                """Bind to "Author" and project the primary key away."""

                model = Author
                registry = reg
                only_fields = ("name",)

        class _KeyProbePostType(DjangoObjectType):
            """Post type filtering by the author relation itself."""

            class Meta:
                """Bind to "Post" with no projection of its own."""

                model = Post
                registry = reg

        assert _KeylessAuthorType is not None
        assert _KeyProbePostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        assert "author" in str(exc.value)

    def test_a_published_key_keeps_the_direct_lookup(self) -> None:
        """A relation whose target publishes its key must stay filterable.

        If this breaks, the guard over-rejects the ordinary forward FK filter
        that every list field declares.
        """
        reg = Registry()

        class _OpenAuthorType(DjangoObjectType):
            """Author type with no projection at all."""

            class Meta:
                """Bind to "Author" and publish everything."""

                model = Author
                registry = reg

        class _OpenPostType(DjangoObjectType):
            """Post type filtering by the author relation itself."""

            class Meta:
                """Bind to "Post" and publish everything."""

                model = Post
                registry = reg

        assert _OpenAuthorType is not None
        assert _OpenPostType is not None
        filter_input = build_filter_input_type(
            Post, {"author": ("exact",)}, reg, registries=isolated_pair(reg)
        )

        assert filter_input is not None
        assert "author" in filter_input.fields


class TestAToManyHopIsMeasuredOnTheRowsItReaches:
    """A to-many relation is published as a CONTAINER, not as the node.

    "<Model>ListType" publishes only its results and its count, so measuring a
    tail column against the container refuses every reverse-relation path ever
    declared. The walk unwraps it to the node the container paginates, which is
    where the projection actually lives.
    """

    def test_a_reverse_relation_tail_is_measured_on_the_node(self) -> None:
        """A published tail behind a to-many hop must stay filterable.

        If this breaks, "posts__title" is refused on a post type that publishes
        "title" perfectly well, because the container was asked instead.
        """
        reg = Registry()

        class _ContainerPostType(DjangoObjectType):
            """Post type publishing "title"."""

            class Meta:
                """Bind to "Post" with no projection."""

                model = Post
                registry = reg

        class _ContainerAuthorType(DjangoObjectType):
            """Author type reaching its posts through the reverse relation."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        assert _ContainerPostType is not None
        assert _ContainerAuthorType is not None
        filter_input = build_filter_input_type(
            Author, {"posts__title": ("icontains",)}, reg, registries=isolated_pair(reg)
        )

        assert filter_input is not None
        assert "posts" in filter_input.fields

    def test_a_hidden_tail_behind_a_to_many_hop_is_refused(self) -> None:
        """A tail the NODE projects away must be refused across the to-many hop.

        If this breaks, unwrapping the container went too far the other way and
        the hop clears whatever the node hides.
        """
        reg = Registry()

        class _HiddenTitlePostType(DjangoObjectType):
            """Post type projecting "title" away."""

            class Meta:
                """Bind to "Post" and publish only "id"."""

                model = Post
                registry = reg
                only_fields = ("id",)

        class _HiddenTitleAuthorType(DjangoObjectType):
            """Author type reaching its posts through the reverse relation."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        assert _HiddenTitlePostType is not None
        assert _HiddenTitleAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author,
                {"posts__title": ("icontains",)},
                reg,
                registries=isolated_pair(reg),
            )

        assert "title" in str(exc.value)


class TestARelationTheSchemaCannotReachFailsClosed:
    """A relation the output compiler DROPS must not stay filterable.

    The compiler drops a to-one relation whose target model has no registered
    type (it logs a warning and emits nothing). The old guard skipped the hop
    for exactly that case, so the filter input kept a full nested input over a
    model that has no type anywhere in the schema.
    """

    def test_an_unregistered_relation_target_refuses_the_path(self) -> None:
        """Spanning a relation the SDL does not publish must raise.

        If this breaks, "category__title" filters a model with no GraphQL type
        at all -- a substring oracle over rows the schema cannot even name.
        """
        reg = Registry()

        class _OrphanRelationPostType(DjangoObjectType):
            """Post type whose "category" target model is unregistered."""

            class Meta:
                """Bind to "Post" and register no "Category" type."""

                model = Post
                registry = reg

        assert _OrphanRelationPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post,
                {"category__title": ("exact", "icontains")},
                reg,
                registries=isolated_pair(reg),
            )

        assert "category" in str(exc.value)


class TestTheDecoratorCannotRenameItsWayPastTheGuard:
    """The one checkable thing about "@filter_field" is its NAME.

    A build refused above is one rename away from shipping: turn
    "bio: ('icontains',)" into "@filter_field() def bio(...)" and the same
    "<Model>FilterInput.bio" appears over the same hidden column. The body
    stays unreadable, but that spelling does not.
    """

    def test_a_custom_filter_named_after_a_hidden_column_is_refused(self) -> None:
        """An "@filter_field" spelled like a projected column must raise.

        If this breaks, the decorator is a documented one-line bypass of every
        refusal this module pins.
        """
        reg = Registry()

        class _RenamedAuthorType(DjangoObjectType):
            """Author type re-opening "bio" through a custom filter."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

            @filter_field()
            def bio(cls, queryset: Any, info: Any, value: str) -> Any:
                """Filter by the hidden column under its own name.

                Args:
                    queryset: The queryset being filtered.
                    info: The GraphQL resolve info for the current request.
                    value: The value supplied by the caller.

                Returns:
                    The filtered queryset.
                """
                return queryset.filter(bio__icontains=value)

        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author,
                {"name": ("exact",)},
                reg,
                custom_filters=_RenamedAuthorType._dgx_custom_filters,
                registries=isolated_pair(reg),
            )

        assert "bio" in str(exc.value)
