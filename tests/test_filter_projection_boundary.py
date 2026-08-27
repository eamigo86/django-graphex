# -*- coding: utf-8 -*-
"""The filter axis must honour "Meta.only_fields" / "Meta.exclude_fields".

A column a type projects away is invisible in the SDL, unselectable and (since
2.2.0's ordering work) unsortable -- and it used to stay fully FILTERABLE
whenever "filter_fields" named it. That is the strongest read oracle the
library had: "filter: {bio: {exact: "..."}}" answers in ONE request, and
"icontains" turns the same argument into a prefix walk that recovers the value
character by character. The hidden column was even published in the SDL as
"<Model>FilterInput.bio" with its full lookup set, so the oracle was
discoverable by introspection rather than guessed.

The rule pinned here is the one the library now states once, for every axis: a
projection is a SECURITY BOUNDARY, not an output shape. A "filter_fields" entry
naming a column the model's registered type projects away is a CONTRADICTION
between two Meta options, and it fails the schema build with
"ImproperlyConfigured" -- the same treatment 2.2.0 gave a projection that would
otherwise be silently dropped. Silently dropping the entry instead would repeat
the very defect 2.2.0 fixed: an option accepted and ignored.

Every door the filter input opens is covered:

  - the direct leaf lookup ("bio"),
  - the relation-spanning lookup ("author__bio"), whose nested input is built
    by the same recursive builder and is therefore checked against the RELATED
    model's projection,
  - the relation head itself ("author": {exact: 1}) when the relation is hidden,
  - the "and" / "or" / "not" combinators, which are typed as the input itself,
  - the WIDENING path, where a second context reaching the cached per-model
    input adds paths to it in place,
  - the nested-list filter, which resolves to that same cached instance.

The one door that cannot be closed by the type system is the BODY of an
"@filter_field" method: the argument is an opaque scalar and the ORM lookup
lives in user Python, where no build-time analysis can see it. That boundary is
pinned as deliberately open, so a later reader does not mistake it for covered.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.core import CharField, ObjectType
from django_graphex.fields import (
    DjangoFilterPaginateListField,
    DjangoNestedListObjectField,
)
from django_graphex.filtering import filter_field
from django_graphex.filtering.backend import NativeFilterBackend
from django_graphex.filtering.native_schema import (
    build_filter_input_type,
    filter_key_is_published,
)
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
    CustomPKProduct,
    Post,
    StaleUnionAuthor,
    StaleUnionPost,
    Tag,
)


class TestProjectedColumnIsNotFilterable:
    """A leaf column the registered type hides must not compile a filter.

    The direct door: "filter_fields" naming a column that is not in the
    type's output. One "exact" lookup answers it outright.
    """

    def test_only_fields_refuses_a_filter_on_a_hidden_column(self) -> None:
        """Filtering a column "only_fields" drops must raise ImproperlyConfigured.

        If this breaks, "filter: {bio: {exact: "..."}}" answers exactly for a
        column the SDL says does not exist.
        """
        reg = Registry()

        class _OnlyAuthorType(DjangoObjectType):
            """Author type publishing only "id" and "name"."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author,
                {"name": ("exact",), "bio": ("exact", "icontains")},
                reg,
                registries=isolated_pair(reg),
            )

        message = str(exc.value)
        assert "_OnlyAuthorType" in message
        assert "bio" in message
        assert "only_fields" in message
        assert "exclude_fields" in message

    def test_exclude_fields_refuses_a_filter_on_a_hidden_column(self) -> None:
        """Filtering a column "exclude_fields" removes must raise too.

        If this breaks, the documented way to hide a sensitive column keeps it
        readable through the filter argument.
        """
        reg = Registry()

        class _ExcludeAuthorType(DjangoObjectType):
            """Author type that excludes "bio"."""

            class Meta:
                """Bind to "Author" and exclude "bio"."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author, {"bio": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        assert "_ExcludeAuthorType" in str(exc.value)
        assert "bio" in str(exc.value)

    def test_include_fields_republishes_the_column(self) -> None:
        """A column force-included by "include_fields" stays filterable.

        If this breaks, the guard over-rejects: "include_fields" bypasses both
        skip filters in the output compiler, so the column IS published.
        """
        reg = Registry()

        class _IncludeAuthorType(DjangoObjectType):
            """Author type re-publishing "bio" through "include_fields"."""

            class Meta:
                """Bind to "Author", narrow with "only_fields", re-add "bio"."""

                model = Author
                registry = reg
                only_fields = ("id", "name")
                include_fields = ("bio",)

        assert _IncludeAuthorType is not None
        filter_input = build_filter_input_type(
            Author, {"bio": ("exact",)}, reg, registries=isolated_pair(reg)
        )

        assert filter_input is not None
        assert "bio" in filter_input.fields

    def test_unprojected_type_keeps_every_declared_filter(self) -> None:
        """A type declaring no projection must keep filtering everything.

        If this breaks, the guard fires on the ordinary configuration that has
        no projection to contradict.
        """
        reg = Registry()

        class _PlainAuthorType(DjangoObjectType):
            """Author type with no projection at all."""

            class Meta:
                """Bind to "Author" with no "only_fields" / "exclude_fields"."""

                model = Author
                registry = reg

        assert _PlainAuthorType is not None
        filter_input = build_filter_input_type(
            Author,
            {"name": ("exact",), "bio": ("icontains",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        assert {"name", "bio"} <= set(filter_input.fields)


class TestProjectionBoundaryOnRelationPaths:
    """Relation heads and relation-spanning tails obey the same rule.

    Each hop of a "__" path is measured against the type that publishes THAT
    hop, so no third type can undo a projection by reaching the column
    across a join.
    """

    def test_hidden_relation_head_refuses_a_spanning_lookup(self) -> None:
        """Declaring "author__name" on a type hiding "author" must raise.

        If this breaks, a relation the SDL denies exists is still traversable
        as a filter, which leaks both the join and the related column.
        """
        reg = Registry()

        class _NoAuthorPostType(DjangoObjectType):
            """Post type that projects the "author" relation away."""

            class Meta:
                """Bind to "Post" and publish only "id" and "title"."""

                model = Post
                registry = reg
                only_fields = ("id", "title")

        assert _NoAuthorPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author__name": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        assert "author" in str(exc.value)

    def test_hidden_relation_head_refuses_a_direct_pk_lookup(self) -> None:
        """Declaring the relation itself on a type hiding it must raise.

        If this breaks, "filter: {author: {exact: 1}}" still probes membership
        of a relation the type removed.
        """
        reg = Registry()

        class _NoAuthorPkPostType(DjangoObjectType):
            """Post type hiding "author" while filtering by its primary key."""

            class Meta:
                """Bind to "Post" and exclude the "author" relation."""

                model = Post
                registry = reg
                exclude_fields = ("author",)

        assert _NoAuthorPkPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        assert "author" in str(exc.value)

    def test_related_types_projection_governs_the_nested_input(self) -> None:
        """A tail hidden by the RELATED type must raise from the recursion.

        If this breaks, hiding "bio" on the author type is undone by any other
        type that declares "author__bio", because the nested filter input is
        built by the same recursive builder.
        """
        reg = Registry()

        class _VisibleAuthorType(DjangoObjectType):
            """Author type hiding "bio" while remaining otherwise public."""

            class Meta:
                """Bind to "Author" and exclude "bio"."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        class _SpanningPostType(DjangoObjectType):
            """Post type reaching the author's hidden column through a lookup."""

            class Meta:
                """Bind to "Post" with no projection of its own."""

                model = Post
                registry = reg

        assert _VisibleAuthorType is not None
        assert _SpanningPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author__bio": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        message = str(exc.value)
        assert "_VisibleAuthorType" in message
        assert "bio" in message


class TestSharedFilterInputCannotBeWidenedPastTheBoundary:
    """The per-model cache must not smuggle a hidden path in later.

    One "<Model>FilterInput" instance serves every context, and a context
    asking for paths it lacks WIDENS it in place. Guarding only the first
    build would leave the second door open.
    """

    def test_widening_a_cached_input_is_guarded(self) -> None:
        """A second context adding a hidden path to the cached input must raise.

        The filter input is cached per model and WIDENED in place by any later
        context asking for paths it lacks. If this breaks, a legal first build
        is followed by an illegal widening and the hidden column reappears on
        the instance every other context already references.
        """
        reg = Registry()
        registries = isolated_pair(reg)

        class _WidenAuthorType(DjangoObjectType):
            """Author type publishing only "id" and "name"."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        assert _WidenAuthorType is not None
        first = build_filter_input_type(
            Author, {"name": ("exact",)}, reg, registries=registries
        )
        assert first is not None

        with pytest.raises(ImproperlyConfigured):
            build_filter_input_type(
                Author, {"bio": ("exact",)}, reg, registries=registries
            )

        assert "bio" not in first.fields


class TestCompositionInheritsTheBoundary:
    """The combinators cannot name a field the input does not compile.

    Composition needs no guard of its own because it is typed as the input
    itself; this pins the structure that makes that true.
    """

    def test_combinators_are_typed_as_the_input_itself(self) -> None:
        """The three combinators must reference the very same input instance.

        This is why composition needs no guard of its own: "and" and "or" are
        lists OF the input and "not" IS the input, so whatever field set the
        declaration compiles is the only field set a composed filter can use.
        If this breaks — a combinator retyped to some wider sibling input —
        composition would reopen every door the declaration closed.
        """
        reg = Registry()

        class _ComboAuthorType(DjangoObjectType):
            """Author type publishing only "id" and "name"."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        assert _ComboAuthorType is not None
        filter_input = build_filter_input_type(
            Author, {"name": ("exact",)}, reg, registries=isolated_pair(reg)
        )

        assert filter_input is not None
        assert filter_input.fields["and"].type.of_type is filter_input
        assert filter_input.fields["or"].type.of_type is filter_input
        assert filter_input.fields["not"].type is filter_input
        assert "bio" not in filter_input.fields


class TestSchemaBuildRefusesTheContradiction:
    """The guard must fire on the real schema-compile path.

    Direct calls to the builder are the unit; these build an actual schema,
    so a guard the compiler never reaches cannot pass unnoticed.
    """

    def test_per_field_fields_override_schema_raises(self) -> None:
        """A per-field "fields=" override naming a hidden column must fail too.

        "fields=" cannot narrow the shared per-model input, only widen it, so
        it is the second door into the very same type. If this breaks, a type
        with a clean "Meta.filter_fields" is reopened by one query field.
        """
        reg = Registry()

        class _OverrideAuthorType(DjangoObjectType):
            """Author type publishing only "id" and "name"."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        class _OverrideQuery(ObjectType):
            """Root query whose flat author list overrides the filter surface."""

            authors = DjangoFilterPaginateListField(
                _OverrideAuthorType,
                pagination=LimitOffsetGraphqlPagination(default_limit=10),
                fields=["bio"],
            )

        assert _OverrideAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_OverrideQuery, registries=isolated_pair(reg))

        assert "bio" in str(exc.value)

    def test_nested_list_field_schema_raises(self) -> None:
        """A nested paginated list filtering a hidden column must fail the build.

        The nested accessor resolves to the SAME cached per-model filter input
        as the root list, so if this breaks the root door is shut while the
        nested one stays open.

        A nested accessor is compiled inside the HOST type's field thunk, and
        graphql-core rewraps anything a thunk raises as "TypeError". The build
        still fails loudly and the explanation survives verbatim, with the
        "ImproperlyConfigured" reachable as the cause; both halves are pinned
        here so nobody "fixes" the wrapper by swallowing the message.
        """
        reg = Registry()

        class _NestedPostType(DjangoObjectType):
            """Post type publishing only "id" and "title"."""

            class Meta:
                """Bind to "Post" and project "views" away."""

                model = Post
                registry = reg
                only_fields = ("id", "title")
                filter_fields = {"title": ("exact",), "views": ("gte",)}

        class _NestedPostListType(DjangoListObjectType):
            """Paginated container over the projected post type."""

            class Meta:
                """Bind to "Post" and inherit the node type's declaration."""

                model = Post
                registry = reg

        class _NestedAuthorType(DjangoObjectType):
            """Author type exposing its posts as a nested paginated list."""

            posts = DjangoNestedListObjectField(_NestedPostListType, accessor="posts")

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        class _NestedAuthorListType(DjangoListObjectType):
            """Paginated container over the author type."""

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        class _NestedQuery(ObjectType):
            """Root query exposing authors, each with a nested post list."""

            authors = DjangoListObjectField(_NestedAuthorListType)

        assert _NestedPostType is not None
        assert _NestedAuthorType is not None
        with pytest.raises((ImproperlyConfigured, TypeError)) as exc:
            DjangoGraphQLSchema(query=_NestedQuery, registries=isolated_pair(reg))

        assert "views" in str(exc.value)
        assert "_NestedPostType" in str(exc.value)
        causes = []
        error: BaseException | None = exc.value
        while error is not None:
            causes.append(error)
            error = error.__cause__
        assert any(isinstance(err, ImproperlyConfigured) for err in causes)

    def test_building_a_schema_raises(self) -> None:
        """A list field filtering a hidden column must fail the schema build.

        If this breaks, the guard is unreachable from the compiler and the
        oracle ships even though the direct-call tests pass.
        """
        reg = Registry()

        class _E2EAuthorType(DjangoObjectType):
            """Author type publishing only "id" and "name"."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")
                filter_fields = {"name": ("exact",), "bio": ("exact", "icontains")}

        class _E2EAuthorListType(DjangoListObjectType):
            """Paginated container over the projected author type."""

            class Meta:
                """Bind to "Author" and inherit the node type's declaration."""

                model = Author
                registry = reg
                filter_fields = {"name": ("exact",), "bio": ("exact", "icontains")}

        class _E2EQuery(ObjectType):
            """Root query exposing the filterable author list."""

            authors = DjangoListObjectField(_E2EAuthorListType)

        assert _E2EAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_E2EQuery, registries=isolated_pair(reg))

        assert "bio" in str(exc.value)


class TestCustomFilterBodyIsADocumentedBoundary:
    """An "@filter_field" body is user Python and stays deliberately open.

    Pinned so the open boundary is a recorded decision rather than an
    oversight a later reader mistakes for coverage.
    """

    def test_custom_filter_still_compiles_on_a_projected_type(self) -> None:
        """A custom filter must still mount on a type that hides a column.

        Its argument is an opaque scalar and its ORM lookup lives inside user
        Python, so no build-time analysis can decide whether it touches a
        hidden column. Refusing every "@filter_field" on a projected type would
        punish the honest majority for a body the compiler cannot read. This
        test pins the boundary as OPEN and documented, not as covered.
        """
        reg = Registry()

        class _CustomAuthorType(DjangoObjectType):
            """Author type hiding "bio" while exposing a custom search filter."""

            class Meta:
                """Bind to "Author" and project "bio" away."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

            @filter_field()
            def search(cls, queryset: Any, info: Any, value: str) -> Any:
                """Filter by a free-text term.

                Args:
                    queryset: The queryset being filtered.
                    info: The GraphQL resolve info for the current request.
                    value: The value supplied by the caller.

                Returns:
                    The queryset, unchanged.
                """
                return queryset

        filter_input = build_filter_input_type(
            Author,
            {"name": ("exact",)},
            reg,
            custom_filters=_CustomAuthorType._dgx_custom_filters,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        assert "search" in filter_input.fields


class TestARelationDeclaredWithoutATailIsMeasuredToo:
    """ "posts: {exact: 1}" filters by the TARGET's primary key, so ask for it.

    The predicate's rule 2 covers a CONCRETE forward relation, because the
    foreign key is a column on this model. A reverse foreign key and a
    many-to-many own no column here, so the last-hop check skipped them
    entirely -- while the byte-identical spelling with the tail ("posts__id")
    was refused. Same query, two spellings, opposite answers.
    """

    def test_a_reverse_relation_head_is_measured_against_the_target(self) -> None:
        """ "posts" alone must be refused exactly as "posts__id" is.

        If this breaks, the target's hidden primary key is probed one lookup at
        a time through a relation declared without a tail.
        """
        reg = Registry()

        class _KeylessPostType(DjangoObjectType):
            """Post type publishing no key of its own."""

            class Meta:
                """Bind to "Post" and project the primary key away."""

                model = Post
                registry = reg
                only_fields = ("title",)

        class _ReverseAuthorType(DjangoObjectType):
            """Author type reaching the keyless post through its reverse FK."""

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        assert _KeylessPostType is not None
        assert _ReverseAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author, {"posts": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        message = str(exc.value)
        assert "_KeylessPostType" in message
        assert "id" in message

    def test_the_tail_spelling_of_the_same_query_is_refused(self) -> None:
        """The contrast case: the two spellings must agree.

        Pins that the arm above closes a real inconsistency rather than
        inventing a new refusal.
        """
        reg = Registry()

        class _KeylessTailPostType(DjangoObjectType):
            """Post type publishing no key of its own."""

            class Meta:
                """Bind to "Post" and project the primary key away."""

                model = Post
                registry = reg
                only_fields = ("title",)

        class _ReverseTailAuthorType(DjangoObjectType):
            """Author type reaching the keyless post through its reverse FK."""

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        assert _KeylessTailPostType is not None
        assert _ReverseTailAuthorType is not None
        with pytest.raises(ImproperlyConfigured):
            build_filter_input_type(
                Author, {"posts__id": ("exact",)}, reg, registries=isolated_pair(reg)
            )

    def test_a_many_to_many_head_is_measured_against_the_target(self) -> None:
        """A many-to-many owns no column here either, and is checked the same.

        If this breaks, "tags: {exact: 1}" probes a key the tag type hides.
        """
        reg = Registry()

        class _KeylessTagType(DjangoObjectType):
            """Tag type publishing no key of its own."""

            class Meta:
                """Bind to "Tag" and project the primary key away."""

                model = Tag
                registry = reg
                only_fields = ("label",)

        class _TaggedPostType(DjangoObjectType):
            """Post type reaching the keyless tag through its M2M."""

            class Meta:
                """Bind to "Post" with no projection of its own."""

                model = Post
                registry = reg

        assert _KeylessTagType is not None
        assert _TaggedPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"tags": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        assert "_KeylessTagType" in str(exc.value)

    def test_a_published_target_key_still_compiles(self) -> None:
        """The fix must cost no legitimate relation-head filter.

        If this breaks, every reverse-relation filter in the wild is refused.
        """
        reg = Registry()

        class _KeyedPostType(DjangoObjectType):
            """Post type publishing its primary key."""

            class Meta:
                """Bind to "Post" with no projection."""

                model = Post
                registry = reg

        class _KeyedAuthorType(DjangoObjectType):
            """Author type reaching the keyed post through its reverse FK."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        assert _KeyedPostType is not None
        assert _KeyedAuthorType is not None
        built = build_filter_input_type(
            Author, {"posts": ("exact",)}, reg, registries=isolated_pair(reg)
        )
        assert built is not None
        assert "posts" in built.fields


class TestTheSharedInputIsMeasuredAgainstEveryTypeItServes:
    """One "<Model>FilterInput" name, two node types, one union of paths.

    The input is cached per MODEL and every context converges on the model's
    ROOT declaration, so two "DjangoObjectType"s over one model in one schema
    share a single instance. Measuring only the declaration in front of the
    guard left the NARROWER type's list field filterable by a column it
    projects away, with no build failure at all.
    """

    def test_the_narrow_type_cannot_serve_the_wide_types_union(self) -> None:
        """A schema mounting both types must refuse to build.

        If this breaks, the narrow list field advertises (and answers)
        "filter: {bio: {icontains: ...}}" for a column its own SDL denies.
        """
        reg = Registry()

        class _UnionWideAuthorType(DjangoObjectType):
            """Author type publishing (and filtering) the sensitive column."""

            class Meta:
                """Bind to "Author" with no projection and a wide filter set."""

                model = Author
                registry = reg
                skip_registry = True
                filter_fields = {"name": ("exact",), "bio": ("exact", "icontains")}

        class _UnionNarrowAuthorType(DjangoObjectType):
            """Author type hiding the sensitive column and filtering narrowly."""

            class Meta:
                """Bind to "Author", project "bio" away, filter only "name"."""

                model = Author
                registry = reg
                only_fields = ("id", "name")
                filter_fields = {"name": ("exact",)}

        class _UnionQuery(ObjectType):
            """Root mounting the wide list FIRST so it seeds the shared input."""

            wide = DjangoFilterPaginateListField(_UnionWideAuthorType)
            narrow = DjangoFilterPaginateListField(_UnionNarrowAuthorType)

        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_UnionQuery, registries=isolated_pair(reg))

        message = str(exc.value)
        assert "_UnionNarrowAuthorType" in message
        assert "bio" in message


class TestTheRefusalNamesTheTypeThatHasToChange:
    """An instruction the reader cannot act on is worse than no instruction.

    The refusal used to name the type it ASKED -- the root of the path -- so a
    deep hop told the reader to publish a column on a type that never had it,
    and a dropped RELATION told them to publish a name whose absence has a
    cause the message did not list.
    """

    def test_a_deep_hop_names_the_type_owning_that_hop(self) -> None:
        """The refusal must name the type the missing relation belongs to.

        If this breaks, the reader edits the root type's Meta and nothing
        changes.
        """
        reg = Registry()

        class _DeepAuthorType(DjangoObjectType):
            """Author type that projects its own reverse post relation away."""

            class Meta:
                """Bind to "Author" and publish only scalars."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        class _DeepPostType(DjangoObjectType):
            """Post type reaching a relation the AUTHOR type removed."""

            class Meta:
                """Bind to "Post" with no projection of its own."""

                model = Post
                registry = reg

        assert _DeepPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post,
                {"author__posts__title": ("exact",)},
                reg,
                registries=isolated_pair(reg),
            )

        message = str(exc.value)
        assert "_DeepAuthorType" in message
        assert "_DeepPostType" not in message

    def test_the_refusal_names_the_meta_the_entry_has_to_leave(self) -> None:
        """ "drop the entry" must point at a Meta that exists.

        A model has no "Meta.filter_fields": the declaration lives on a TYPE,
        and the input is shared per model, so the type that contributed the
        path is what the reader has to edit. If this breaks, the remedy names
        a place the entry was never written.
        """
        reg = Registry()

        class _NamedAuthorType(DjangoObjectType):
            """Author type hiding the column its own Meta then filters on."""

            class Meta:
                """Bind to "Author", hide "bio", and filter by it anyway."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)
                filter_fields = {"bio": ("icontains",)}

        class _NamedQuery(ObjectType):
            """Root mounting the contradictory list."""

            authors = DjangoFilterPaginateListField(_NamedAuthorType)

        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_NamedQuery, registries=isolated_pair(reg))

        assert "_NamedAuthorType.Meta.filter_fields entry 'bio'" in str(exc.value)

    def test_a_container_names_the_node_meta_it_inherited_from(self) -> None:
        """A container declaring no filters of its own must not take the blame.

        "DjangoListObjectType" falls back to its node's "Meta.filter_fields",
        which is the ordinary arrangement. If this breaks, the refusal names
        the container and the reader opens a "Meta" with no filter_fields in
        it at all.
        """
        reg = Registry()

        class _InheritedAuthorType(DjangoObjectType):
            """Author node hiding the column its own Meta then filters on."""

            class Meta:
                """Bind to "Author", hide "bio", and filter by it anyway."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)
                filter_fields = {"bio": ("icontains",)}

        class _InheritedAuthorListType(DjangoListObjectType):
            """Container declaring no filters, so it inherits the node's."""

            class Meta:
                """Bind to "Author" with a paginator and nothing else."""

                model = Author
                registry = reg
                pagination = LimitOffsetGraphqlPagination(
                    default_limit=10, max_limit=20
                )

        class _InheritedQuery(ObjectType):
            """Root mounting the container over the contradictory node."""

            authors = DjangoListObjectField(_InheritedAuthorListType)

        assert _InheritedAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_InheritedQuery, registries=isolated_pair(reg))

        message = str(exc.value)
        assert "_InheritedAuthorType.Meta.filter_fields entry 'bio'" in message
        assert "_InheritedAuthorListType.Meta" not in message

    def test_an_auto_expanded_container_names_the_node_it_inherited_from(
        self,
    ) -> None:
        """The synthetic container the compiler mints is not a Meta to edit.

        An auto-expanded to-many gets a container the USER never wrote --
        "get_or_create_list_object_type" mints one and seeds its Meta with the
        node's own "filter_fields" so nested lists stay filterable. Seeding it
        made the inherited declaration look self-declared, so the refusal named
        "GenericListType.Meta.filter_fields": a factory class in the library's
        own source that no reader can open, let alone edit.
        """
        reg = Registry()

        class _AutoAuthorType(DjangoObjectType):
            """Author node hiding the column its own Meta then filters on."""

            class Meta:
                """Bind to "Author", hide "bio", and filter by it anyway."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)
                filter_fields = {"bio": ("icontains",)}

        class _AutoPostType(DjangoObjectType):
            """Post node whose many-to-many mints the author's container."""

            class Meta:
                """Bind to "Post", publishing the many-to-many to Author."""

                model = Post
                registry = reg
                only_fields = ("id", "title", "co_authors")

        class _AutoQuery(ObjectType):
            """Root mounting the post list that reaches the to-many."""

            posts = DjangoFilterPaginateListField(_AutoPostType)

        assert _AutoAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_AutoQuery, registries=isolated_pair(reg))

        message = str(exc.value)
        assert "_AutoAuthorType.Meta.filter_fields entry 'bio'" in message
        assert "GenericListType" not in message

    def test_a_dropped_relation_names_its_unregistered_target(self) -> None:
        """The cause the message omitted is the one the reader has to fix.

        The compiler drops a to-one relation whose target model has no
        registered type, and "publish it on the owning type" cannot fix that.
        """
        reg = Registry()

        class _OrphanPostType(DjangoObjectType):
            """Post type whose "category" target model is unregistered."""

            class Meta:
                """Bind to "Post" with no projection at all."""

                model = Post
                registry = reg

        assert _OrphanPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post,
                {"category__title": ("exact",)},
                reg,
                registries=isolated_pair(reg),
            )

        message = str(exc.value)
        assert "Category" in message
        assert "register" in message.lower()


class TestARelationNameOverALeafIsNotTraversable:
    """The mask stamp stops the traversal AT the masked hop, and says so.

    A declaration standing under a relation's name but compiling to a LEAF
    publishes no relation: nothing can be asked of a scalar. Reading the stamp
    is what makes the walk stop there and name the type that has to change;
    without it the walk descends INTO the scalar and the refusal blames the
    tail on "String", which no reader can act on. That line had no test in
    either direction, so mutating it away left the suite green.
    """

    def test_a_scalar_standing_in_for_a_relation_refuses_the_tail(self) -> None:
        """The refusal must blame "author" on the post type, not "name" on String.

        If this breaks, the walk descended into the scalar: still a refusal,
        but one naming a hop the reader never wrote and a type no "Meta" can
        change.
        """
        reg = Registry()

        class _LeafRelationAuthorType(DjangoObjectType):
            """Author type mounted so the relation target is registered."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        class _LeafRelationPostType(DjangoObjectType):
            """Post type publishing "author" as a plain string."""

            author = CharField()

            class Meta:
                """Bind to "Post", keeping the relation's name in the SDL."""

                model = Post
                registry = reg
                only_fields = ("id", "title", "author")

            def resolve_author(self, info: Any) -> str:
                """Return a constant instead of the related row.

                Args:
                    info: The GraphQL resolve info.

                Returns:
                    The redaction marker standing in for the relation.
                """
                return "[redacted]"

        assert _LeafRelationAuthorType is not None
        assert _LeafRelationPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author__name": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        message = str(exc.value)
        assert "traverses 'author'" in message
        assert "_LeafRelationPostType" in message
        assert "String" not in message


class TestAnEntryNamingNothingIsRefused:
    """A "pk" / "id" entry on a natural-key model compiled to nothing.

    The field thunk swallowed the "FieldDoesNotExist" and dropped the entry, so
    the declaration was accepted and ignored -- the exact defect every other
    refusal in this module exists to prevent.
    """

    def test_the_pk_alias_is_refused(self) -> None:
        """ "pk" is an ORM alias the filter builder cannot compile.

        If this breaks, the operator believes the list is filterable by its
        primary key and every request silently returns everything.
        """
        reg = Registry()

        class _PkAliasProductType(DjangoObjectType):
            """Product type over a slug-primary-key model."""

            class Meta:
                """Bind to "CustomPKProduct" with no projection."""

                model = CustomPKProduct
                registry = reg

        assert _PkAliasProductType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                CustomPKProduct,
                {"pk": ("exact",)},
                reg,
                registries=isolated_pair(reg),
            )

        assert "pk" in str(exc.value)

    def test_id_on_a_natural_key_model_is_refused(self) -> None:
        """ "id" names no column when the primary key is a slug.

        If this breaks, the entry compiles to nothing and the operator never
        learns the column is called "slug".
        """
        reg = Registry()

        class _IdAliasProductType(DjangoObjectType):
            """Product type over a slug-primary-key model."""

            class Meta:
                """Bind to "CustomPKProduct" with no projection."""

                model = CustomPKProduct
                registry = reg

        assert _IdAliasProductType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                CustomPKProduct,
                {"id": ("exact",)},
                reg,
                registries=isolated_pair(reg),
            )

        assert "id" in str(exc.value)


class TestThePublicBackendSeamCanNameTheServingType:
    """The guard must not be a no-op through "FilterBackend.build_input_type".

    The seam called the builder with NO node type, so the boundary fell back to
    "registry.get_type_for_model" -- the last-wins, "Meta.skip_registry"-opt-out
    index this round removed from the compiler path for exactly this reason: it
    answers about a type that may not be the one serving the request.
    """

    def test_the_seam_forwards_the_named_type_to_the_guard(self) -> None:
        """A narrow serving type must be refused through the seam too.

        If this breaks, the registry's wide last-wins type answers and the
        narrow type's hidden column is filterable.
        """
        reg = Registry()

        class _SeamWideAuthorType(DjangoObjectType):
            """Author type holding the registry slot and publishing "bio"."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        class _SeamNarrowAuthorType(DjangoObjectType):
            """Author type that hides "bio" and opts out of the registry."""

            class Meta:
                """Bind to "Author", project "bio" away, skip the registry."""

                model = Author
                registry = reg
                skip_registry = True
                only_fields = ("id", "name")

        assert reg.get_type_for_model(Author) is _SeamWideAuthorType
        with pytest.raises(ImproperlyConfigured) as exc:
            NativeFilterBackend().build_input_type(
                Author,
                {"bio": ("exact",)},
                reg,
                node_type=_SeamNarrowAuthorType._meta.graphql_output_type,
            )

        assert "_SeamNarrowAuthorType" in str(exc.value)


class TestTheCompiledReadSideOfTheSameBoundary:
    """ "filter_key_is_published" answers what the build-time guard refuses.

    Its caller is "core.schema_pruner", which cannot raise: a permission-scoped
    clone publishes less than the schema it clones, and the filter input has to
    narrow with it rather than fail the build for a caller who did nothing
    wrong. Same two questions, same two helpers, phrased as a predicate.
    """

    def test_a_hidden_column_is_not_published(self) -> None:
        """The leaf arm: a column the serving type projects away answers False.

        If this breaks, a filter key survives into a schema whose node type
        does not serve the column it names.
        """
        reg = Registry()

        class _KeyNarrowAuthorType(DjangoObjectType):
            """Author type that projects "bio" away."""

            class Meta:
                """Bind to "Author" publishing only "id" and "name"."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        serving = _KeyNarrowAuthorType._meta.graphql_output_type
        assert filter_key_is_published(Author, "name", [serving])
        assert not filter_key_is_published(Author, "bio", [serving])

    def test_a_key_that_names_no_column_is_left_alone(self) -> None:
        """A custom "@filter_field" argument stays the open boundary here too.

        If this breaks, every custom filter argument disappears from every
        permission-scoped schema.
        """
        reg = Registry()

        class _KeyPlainAuthorType(DjangoObjectType):
            """Author type with no projection at all."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        serving = _KeyPlainAuthorType._meta.graphql_output_type
        assert filter_key_is_published(Author, "search_everything", [serving])
        assert filter_key_is_published(Author, "and", [serving])
        assert filter_key_is_published(Author, None, [serving])


class TestADeepSegmentNamingNothingIsRefusedToo:
    """A hop past the first is dropped just as silently, and refused the same.

    The walk stops at the first NON-relation segment, so a segment right after
    a relation is a real field name, and one the related model does not hold
    compiles to nothing. A trailing LOOKUP spelling compiles to nothing too,
    and is refused for the same reason rather than exempted for its looks.
    """

    def test_a_tail_naming_nothing_on_the_related_model_is_refused(self) -> None:
        """ "author__nope" must name the AUTHOR model, not the root.

        If this breaks, the nested input drops the entry and the operator reads
        their own "Meta" believing the filter exists.
        """
        reg = Registry()

        class _TailAuthorType(DjangoObjectType):
            """Author type mounted so the relation target is registered."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        class _TailPostType(DjangoObjectType):
            """Post type declaring a tail the author model does not hold."""

            class Meta:
                """Bind to "Post" with no projection."""

                model = Post
                registry = reg

        assert _TailAuthorType is not None
        assert _TailPostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post, {"author__nope": ("exact",)}, reg, registries=isolated_pair(reg)
            )

        message = str(exc.value)
        assert "nope" in message
        # The entry belongs to the declaration it was written in; only the
        # failed HOP belongs to the related model.
        assert message.startswith("Post.filter_fields entry 'author__nope'")
        assert "not a field on Author" in message

    def test_a_lookup_spelled_into_the_key_is_refused(self) -> None:
        """ "name__icontains" as a KEY compiles to nothing, so it is refused.

        Lookups are declared in the entry's VALUE. Spelled into the key, the
        whole compound lands on the model's own leaves, where no field answers
        to it and the thunk dropped it -- byte-equivalent to the "pk" spelling
        this guard already refuses. If this breaks, one dead spelling is
        refused and its twin is accepted and ignored.
        """
        reg = Registry()

        class _SpellingAuthorType(DjangoObjectType):
            """Author type with no projection at all."""

            class Meta:
                """Bind to "Author" with no projection."""

                model = Author
                registry = reg

        assert _SpellingAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Author,
                {"name__icontains": ("exact",)},
                reg,
                registries=isolated_pair(reg),
            )

        assert "icontains" in str(exc.value)


class TestTheRefusalReachesTheCallerAsItself:
    """A refusal raised inside a fields thunk must not arrive as a TypeError.

    graphql-core rewraps ANYTHING a fields thunk raises as a plain
    "TypeError" whose message chains type names, and every build-time refusal
    in this module is raised from inside one. The operator was told to expect
    "ImproperlyConfigured" by the docs, the playground README and the type's
    own docstring, and got a type error naming types they never declared.
    """

    def test_the_schema_build_refuses_with_the_documented_exception(self) -> None:
        """The contradiction must surface as "ImproperlyConfigured", not "TypeError".

        If this breaks, every doc stating the contract is wrong again and the
        message the reader has to act on is buried behind a chain of generated
        type names.
        """
        reg = Registry()

        class _StaleAuthorType(DjangoObjectType):
            """Canonical author node: publishes everything, filters narrowly."""

            class Meta:
                """Bind to "Author" with no projection and the root declaration."""

                model = Author
                registry = reg
                filter_fields = {"name": ("exact",)}

        class _StalePostType(DjangoObjectType):
            """Post node filtering AUTHORS through its many-to-many relation.

            Its nested build is what mints the author filter input, with a
            path the author root never declared.
            """

            class Meta:
                """Bind to "Post" and filter through "co_authors"."""

                model = Post
                registry = reg
                filter_fields = {"co_authors__bio": ("icontains",)}

        class _StaleNarrowAuthorType(DjangoObjectType):
            """Author node hiding the sensitive column, off the registry slot.

            It keeps the reverse "posts" relation, so forcing its field map
            compiles the post list -- and, through it, the author filter input
            the guard was about to measure.
            """

            class Meta:
                """Bind to "Author", project "bio" away, filter only "name"."""

                model = Author
                registry = reg
                skip_registry = True
                exclude_fields = ("bio",)
                filter_fields = {"name": ("exact",)}

        class _StaleQuery(ObjectType):
            """Root mounting the NARROW list first, so it guards first."""

            narrow = DjangoFilterPaginateListField(_StaleNarrowAuthorType)
            posts = DjangoFilterPaginateListField(_StalePostType)

        assert _StaleAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            DjangoGraphQLSchema(query=_StaleQuery, registries=isolated_pair(reg))

        message = str(exc.value)
        assert "_StaleNarrowAuthorType" in message
        assert "bio" in message


class TestTheUnionIsMeasuredWhereItCannotBeStale:
    """The shape a build serves can be BORN inside the assertion that clears it.

    Reading a compiled field map FORCES it, and forcing the narrow type's map
    compiles the nested list fields it publishes -- one of which builds THIS
    model's filter input from another type's declaration, through the
    re-entrancy this module already documents. The union was measured against
    the PRE-assertion cache read, so on that path the guard cleared a shape
    that no longer existed by the time the build returned it, and then
    recorded the narrow type as a server of paths nothing had ever measured.

    Its models are its own: the re-entrancy only closes when the outer build
    and the field thunk share ONE filter-input cache, which means the
    process-wide pair, so the entry these types leave behind must belong to
    no other test.
    """

    def test_a_shape_created_during_the_assertion_is_measured_too(self) -> None:
        """The narrow type must not inherit a path minted while it was waiting.

        If this breaks, the narrow list field answers
        "filter: {bio: {icontains: ...}}" for a column its own SDL denies --
        the leak the union guard exists to stop, reached through the one path
        where the guard read a stale cache.
        """
        reg = Registry()

        class _StaleNarrowAuthorType(DjangoObjectType):
            """Author node hiding the sensitive column, off the registry slot.

            It keeps the reverse many-to-many, so forcing its field map
            compiles the post list -- and, through it, the author filter input
            the guard is in the middle of measuring.
            """

            class Meta:
                """Bind to the author model, hide "bio", filter only "name"."""

                model = StaleUnionAuthor
                registry = reg
                skip_registry = True
                exclude_fields = ("bio",)
                filter_fields = {"name": ("exact",)}

        class _StaleWideAuthorType(DjangoObjectType):
            """Canonical author node: publishes everything, filters narrowly.

            It owns the model's slot, so it is the type the nested build
            measures against -- and clears.
            """

            class Meta:
                """Bind to the author model with no projection at all."""

                model = StaleUnionAuthor
                registry = reg
                filter_fields = {"name": ("exact",)}

        class _StalePostType(DjangoObjectType):
            """Post node filtering AUTHORS through its many-to-many relation.

            Its nested build is what mints the author filter input, carrying a
            path the author root never declared.
            """

            class Meta:
                """Bind to the post model and filter through "co_authors"."""

                model = StaleUnionPost
                registry = reg
                filter_fields = {"co_authors__bio": ("icontains",)}

        assert _StaleWideAuthorType is not None
        assert _StalePostType is not None
        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                StaleUnionAuthor,
                {"name": ("exact",)},
                reg,
                node_type=_StaleNarrowAuthorType._meta.graphql_output_type,
            )

        message = str(exc.value)
        assert "_StaleNarrowAuthorType" in message
        assert "bio" in message
