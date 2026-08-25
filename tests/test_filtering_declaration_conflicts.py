# -*- coding: utf-8 -*-
"""Regressions for conflicting "filter_fields" / "@filter_field" declarations.

Three ways a filter declaration could conflict with itself used to resolve by
LAST-WRITER-WINS inside the native filter-input field thunk, silently dropping
the losing half of the declaration:

(a) a "@filter_field" method named like a "filter_fields" key overwrote the
    compiled "<Model><Field>Lookups" entry, so the field became unfilterable
    both ways and "to_q" blew up with a raw "AttributeError" at query time;
(b) declaring a relation ("author") AND a path through it ("author__name")
    dropped the nested "<Related>FilterInput" because the relation-direct loop
    ran second and overwrote the same camelCase key;
(c) an explicit NESTED lookup tuple ("author__name": ("icontains",)) was
    replaced wholesale by the related model's ROOT declaration, because
    "_canonical_filter_fields" short-circuited on PATH membership alone and
    never checked that the root's lookups actually covered the request.

Every test builds through "registries=isolated_pair(...)" so the per-model
filter-input cache is test-local and one case cannot hand its widened shape to
the next.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.filtering import filter_field
from django_graphex.filtering.native_schema import build_filter_input_type
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post


class TestCustomFilterNameCollision:
    """A "@filter_field" named like a "filter_fields" key must fail loudly.

    Guards defect (a): the custom-filter loop ran last and overwrote the
    compiled lookups input, so "title" silently became a bare "String" and
    both filter shapes stopped working.
    """

    def test_collision_raises_at_build_time(self) -> None:
        """A custom filter named like a compiled key must raise ImproperlyConfigured.

        If this breaks, the declared "title" lookups input is silently
        replaced by the custom filter's scalar and "filter: {title: ...}"
        fails at query time with a raw "AttributeError" instead.
        """
        reg = Registry()

        class _CollidingPostType(DjangoObjectType):
            """Post type whose custom filter collides with a filter_fields key."""

            class Meta:
                """Bind the type to "Post" with a colliding "title" declaration."""

                model = Post
                filter_fields = {"title": ("exact", "icontains")}
                registry = reg
                skip_registry = True

            @filter_field()
            def title(cls, queryset: Any, info: Any, value: str) -> Any:
                """Filter by title, colliding with the "title" lookups entry.

                Args:
                    queryset: The queryset being filtered.
                    info: The GraphQL resolve info for the current request.
                    value: The value supplied by the caller.

                Returns:
                    The queryset, unchanged.
                """
                return queryset

        with pytest.raises(ImproperlyConfigured) as exc:
            build_filter_input_type(
                Post,
                {"title": ("exact", "icontains")},
                reg,
                custom_filters=_CollidingPostType._dgx_custom_filters,
                registries=isolated_pair(reg),
            )

        message = str(exc.value)
        assert "title" in message
        assert "filter_field" in message

    def test_non_colliding_custom_filter_still_builds(self) -> None:
        """A custom filter with its own name must still mount next to the lookups.

        If this breaks, the new collision guard would over-reject ordinary
        "@filter_field" declarations.
        """
        reg = Registry()

        class _SearchPostType(DjangoObjectType):
            """Post type with a non-colliding "search" custom filter."""

            class Meta:
                """Bind the type to "Post" with a "title" lookups declaration."""

                model = Post
                filter_fields = {"title": ("exact",)}
                registry = reg
                skip_registry = True

            @filter_field()
            def search(cls, queryset: Any, info: Any, value: str) -> Any:
                """Filter by a free-text search term.

                Args:
                    queryset: The queryset being filtered.
                    info: The GraphQL resolve info for the current request.
                    value: The value supplied by the caller.

                Returns:
                    The queryset, unchanged.
                """
                return queryset

        filter_input = build_filter_input_type(
            Post,
            {"title": ("exact",)},
            reg,
            custom_filters=_SearchPostType._dgx_custom_filters,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        assert filter_input.fields["title"].type.name == "PostTitleLookups"
        assert "search" in filter_input.fields


class TestRelationDeclaredBothWays:
    """Declaring a relation AND a path through it must keep both halves.

    Guards defect (b): "author" landed in "relation_direct" and "author__name"
    in "relations"; the second loop overwrote the first, so the nested
    "AuthorFilterInput" never mounted.
    """

    def test_nested_filter_input_survives_the_direct_declaration(self) -> None:
        """ "author" + "author__name" must mount the nested "AuthorFilterInput".

        If this breaks, an explicitly declared nested filter vanishes from the
        schema and "filter: {author: {name: {...}}}" is rejected by validation.
        """
        reg = Registry()

        filter_input = build_filter_input_type(
            Post,
            {"author": ("exact",), "author__name": ("icontains",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        nested = filter_input.fields["author"].type
        assert nested.name == "AuthorFilterInput"
        assert "icontains" in nested.fields["name"].type.fields

    def test_direct_relation_lookups_move_onto_the_nested_input(self) -> None:
        """The direct relation lookups must resurface under the related pk name.

        If this breaks, "author": ("exact",) is silently dropped instead of
        being reachable as "filter: {author: {id: {exact: ...}}}".
        """
        reg = Registry()

        filter_input = build_filter_input_type(
            Post,
            {"author": ("exact",), "author__name": ("icontains",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        nested = filter_input.fields["author"].type
        assert "exact" in nested.fields["id"].type.fields
        assert nested.fields["id"].out_name == "id"


class TestNestedLookupsNotReplacedByRoot:
    """An explicit nested lookup tuple must survive the root declaration.

    Guards defect (c): "_canonical_filter_fields" short-circuited on path
    membership alone, so a root declaring "name": ("exact",) discarded a
    nested request for "author__name": ("icontains",).
    """

    def test_requested_lookup_is_unioned_with_the_root(self) -> None:
        """A nested "icontains" must survive a root that only declares "exact".

        If this breaks, the declared nested lookup is silently unusable and
        the query fails with "Field 'icontains' is not defined by type".
        """
        reg = Registry()

        class _RootAuthorType(DjangoObjectType):
            """Author type declaring the narrower root filter declaration."""

            class Meta:
                """Bind the type to "Author" with an "exact"-only declaration."""

                model = Author
                filter_fields = {"name": ("exact",)}
                registry = reg

        assert _RootAuthorType is not None

        filter_input = build_filter_input_type(
            Post,
            {"author__name": ("icontains",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        lookups = filter_input.fields["author"].type.fields["name"].type
        assert set(lookups.fields) == {"exact", "icontains"}

    def test_covered_request_still_reuses_the_root_declaration(self) -> None:
        """A request the root already covers must reuse the root shape verbatim.

        If this breaks, the coverage check would widen types that never
        diverged and the canonical root shape would stop being canonical.
        """
        reg = Registry()

        class _WideAuthorType(DjangoObjectType):
            """Author type declaring a superset root filter declaration."""

            class Meta:
                """Bind the type to "Author" with an "exact"/"icontains" set."""

                model = Author
                filter_fields = {"name": ("exact", "icontains")}
                registry = reg

        assert _WideAuthorType is not None

        filter_input = build_filter_input_type(
            Post,
            {"author__name": ("icontains",)},
            reg,
            registries=isolated_pair(reg),
        )

        assert filter_input is not None
        lookups = filter_input.fields["author"].type.fields["name"].type
        assert list(lookups.fields) == ["exact", "icontains"]
