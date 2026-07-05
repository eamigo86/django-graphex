"""Tests for the "@filter_field" decorator (issue #26).

TDD suite covering:
- Basic string filter arg appears in schema and filters at query time
- Type override (native "GraphQLInt")
- description flows through to the schema
- Composition order: standard lookup -> @filter_field -> filter_queryset
- Reserved-name collision raises ImproperlyConfigured at class definition
- filter_fields = {"x": None} raises ImproperlyConfigured (not TypeError)

Native conversion (graphene-removal, RISK #6 verified): "@filter_field" stores
its declared scalar verbatim under the "graphql_type" metadata key, and the
native filter builder ("filtering/native_schema._custom_filter_gql_type")
accepts a native graphql-core type as-is ("isinstance(t, GraphQLType)" ->
returned unchanged); a leftover graphene type raises "TypeError". So passing
"GraphQLString" / "GraphQLInt" is the native end-state; the decorator +
builder produce the matching "Int" / "String" filter-arg SDL, asserted below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from graphql import GraphQLInt, GraphQLString

from django_graphex.filtering import filter_field
from django_graphex.filtering import filter_field as ff_from_filtering
from django_graphex.filtering.filter_field import filter_field as ff_direct
from django_graphex.filtering.native_schema import build_filter_input_type
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

from .models import Author, Post

if TYPE_CHECKING:
    from django.db.models import QuerySet

# ---------------------------------------------------------------------------
# Helper model / type for filter_field tests (isolated from shared schema)
# ---------------------------------------------------------------------------


class _FilterFieldPost(models.Model):
    """Lightweight stand-in for Post; references same DB table via proxy."""

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(
        Author, related_name="ff_posts", on_delete=models.CASCADE
    )
    views = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "tests"
        # Use the real Post table so we can create test data.
        db_table = "tests_post"
        managed = False


# ---------------------------------------------------------------------------
# 1. Basic: @filter_field(GraphQLString) → arg in schema + query-time filter
# ---------------------------------------------------------------------------


_BASIC_REGISTRY = Registry()


class PostSearchType(DjangoObjectType):
    """A "DjangoObjectType" contributing a "search" custom filter via "@filter_field".

    Used by "TestFilterFieldBasic" to exercise the default String scalar and
    description propagation.
    """

    class Meta:
        """Bind "PostSearchType" to "_FilterFieldPost" with a "title" filter field.

        No custom filter fields beyond "title" are declared here.
        """

        model = _FilterFieldPost
        filter_fields = {"title": ("exact",)}
        registry = _BASIC_REGISTRY

    @filter_field(GraphQLString, description="Full-text search")
    def search(
        cls, queryset: "QuerySet[Any]", info: Any, value: str
    ) -> "QuerySet[Any]":
        """Filter the queryset to titles containing "value" (case-insensitive).

        Args:
            queryset: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            value: The search substring supplied by the caller.

        Returns:
            queryset: The queryset filtered by "title__icontains".
        """
        return queryset.filter(title__icontains=value)


class TestFilterFieldBasic:
    """The decorated method appears in the filter schema and runs at query time.

    Covers schema presence, the compiled scalar type, and description
    propagation.
    """

    def test_search_arg_appears_in_filter_input(self) -> None:
        """The "search" arg must appear in the generated filter input type.

        If this breaks, a "@filter_field"-decorated method would silently be
        dropped from the compiled filter schema.
        """
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        assert filter_input is not None
        # Native contract: the canonical field surface is the compiled
        # ``GraphQLInputObjectType.fields`` (graphql-core), not graphene
        # ``_meta.fields``.
        assert "search" in filter_input.fields

    def test_search_arg_is_string_type(self) -> None:
        """The "search" arg must compile to the native GraphQLString scalar.

        Guards the default-type path of "@filter_field" independently of
        description propagation.
        """
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        field = filter_input.fields["search"]
        from graphql import GraphQLString

        assert field.type is GraphQLString

    def test_description_flows_to_schema(self) -> None:
        """The description kwarg on "@filter_field" must flow to the GraphQL arg.

        If this breaks, a custom filter's documentation would be silently
        dropped from the compiled schema.
        """
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        field = filter_input.fields["search"]
        assert field.description == "Full-text search"


# ---------------------------------------------------------------------------
# 2. Type override: @filter_field(GraphQLInt)
# ---------------------------------------------------------------------------


_INT_REGISTRY = Registry()


class PostIntFilterType(DjangoObjectType):
    """A "DjangoObjectType" contributing an Int-typed custom filter via "@filter_field".

    Used by "TestFilterFieldTypeOverride" to exercise the "graphql_type"
    override.
    """

    class Meta:
        """Bind "PostIntFilterType" to "_FilterFieldPost" with a "views" filter field.

        No custom filter fields beyond "views" are declared here.
        """

        model = _FilterFieldPost
        filter_fields = {"views": ("exact",)}
        registry = _INT_REGISTRY

    @filter_field(GraphQLInt, description="Filter by min views")
    def min_views(
        cls, queryset: "QuerySet[Any]", info: Any, value: int
    ) -> "QuerySet[Any]":
        """Filter the queryset to posts with at least "value" views.

        Args:
            queryset: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            value: The minimum view count supplied by the caller.

        Returns:
            queryset: The queryset filtered by "views__gte".
        """
        return queryset.filter(views__gte=value)


class TestFilterFieldTypeOverride:
    """The graphql_type argument on @filter_field controls the schema arg type.

    Covers the single Int-override scenario.
    """

    def test_int_type_override(self) -> None:
        """ "@filter_field(GraphQLInt)" must give the arg an Int type in the schema.

        If this breaks, the "graphql_type" override on "@filter_field" would
        be silently ignored in favor of the default String scalar.
        """
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"views": ("exact",)},
            registry=_INT_REGISTRY,
            custom_filters=PostIntFilterType._dgx_custom_filters,
        )
        # Native wire names are camelCase: ``min_views`` -> ``minViews``.
        field = filter_input.fields["minViews"]
        from graphql import GraphQLInt

        assert field.type is GraphQLInt


# ---------------------------------------------------------------------------
# 3. Composition order at query time
# ---------------------------------------------------------------------------


_COMP_REGISTRY = Registry()
_comp_call_log: list[str] = []


class OrderedFilterType(DjangoObjectType):
    """A "DjangoObjectType" recording custom-filter and "filter_queryset" call order.

    Used by "TestFilterFieldCompositionOrder" to assert the composition order.
    """

    class Meta:
        """Bind "OrderedFilterType" to "_FilterFieldPost" with a "title" filter field.

        No custom filter fields beyond "title" are declared here.
        """

        model = _FilterFieldPost
        filter_fields = {"title": ("exact",)}
        registry = _COMP_REGISTRY

    @filter_field(GraphQLString)
    def search(
        cls, queryset: "QuerySet[Any]", info: Any, value: str
    ) -> "QuerySet[Any]":
        """Filter the queryset to titles containing "value", logging the call.

        Args:
            queryset: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            value: The search substring supplied by the caller.

        Returns:
            queryset: The queryset filtered by "title__icontains".
        """
        _comp_call_log.append("custom_filter")
        return queryset.filter(title__icontains=value)

    @classmethod
    def filter_queryset(
        cls, qs: "QuerySet[Any]", info: Any, **kwargs: Any
    ) -> "QuerySet[Any]":
        """Filter the queryset to posts with at least 10 views, logging the call.

        Args:
            qs: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            kwargs: Additional filter arguments, unused by this override.

        Returns:
            qs: The queryset filtered by "views__gte=10".
        """
        _comp_call_log.append("filter_queryset")
        return qs.filter(views__gte=10)


class TestFilterFieldCompositionOrder:
    """Standard lookup -> @filter_field -> filter_queryset run in that order.

    Covers the single end-to-end composition scenario against a real database.
    """

    @pytest.mark.django_db
    def test_composition_order(self, db: None) -> None:
        """The three filter stages must run in lookup, custom-filter, then filter_queryset order.

        If this breaks, the composition contract for custom filters (schema
        lookups first, then "@filter_field" methods, then "filter_queryset")
        would silently change, altering which records survive a combined
        query.

        Args:
            db: The pytest-django fixture granting database access.
        """
        # Create Authors and Posts in the DB
        author = Author.objects.create(name="Alice")
        p1 = Post.objects.create(
            title="Alpha Beta", body="content", author=author, views=10
        )
        _p2 = Post.objects.create(
            title="Gamma Delta", body="content", author=author, views=20
        )
        p3 = Post.objects.create(
            title="Alpha Gamma", body="content", author=author, views=5
        )

        from django_graphex.filtering.filter_field import apply_custom_filters

        qs = _FilterFieldPost.objects.all()
        _comp_call_log.clear()

        custom_filters_def = OrderedFilterType._dgx_custom_filters

        class FakeInfo:
            context = None

        fake_filter_value = type("FV", (), {"search": "Alpha"})()

        qs_after_custom = apply_custom_filters(
            qs, custom_filters_def, FakeInfo(), fake_filter_value
        )
        # After custom filter: only p1 and p3 (contain "Alpha")
        assert set(qs_after_custom.values_list("id", flat=True)) == {p1.id, p3.id}

        # Now apply filter_queryset (views >= 10)
        qs_final = OrderedFilterType.filter_queryset(qs_after_custom, FakeInfo())
        # Only p1 remains (title contains "Alpha" AND views >= 10)
        assert set(qs_final.values_list("id", flat=True)) == {p1.id}

        assert _comp_call_log == ["custom_filter", "filter_queryset"]


# ---------------------------------------------------------------------------
# 4. Build-time: reserved-name collision → ImproperlyConfigured
# ---------------------------------------------------------------------------


class TestFilterFieldReservedNameCollision:
    """@filter_field whose name matches a reserved pagination/ordering arg raises.

    Parametrized over every reserved argument name.
    """

    @pytest.mark.parametrize(
        "reserved_name",
        [
            "limit",
            "offset",
            "ordering",
            "page",
            "page_size",
            "first",
            "cursor",
            "filter",
            "id",
        ],
    )
    def test_reserved_name_raises(self, reserved_name: str) -> None:
        """A "@filter_field" method named after a reserved arg must raise ImproperlyConfigured.

        Args:
            reserved_name: The reserved pagination/ordering/filter argument
                name used as the custom filter method's name.
        """
        registry = Registry()

        # The native "DjangoObjectType" metaclass requires a lexically-nested
        # "class Meta" (pydantic-backed namespace processing); a bare
        # "type(name, bases, ns)" namespace fails before the collision check
        # runs. Build a *real* class statement via "exec" so the metaclass
        # reaches "__init_subclass_with_meta__", where the reserved-name guard
        # lives. (Behaviour unchanged: defining a type whose "@filter_field"
        # method name collides with a reserved arg raises ImproperlyConfigured.)
        ns = {
            "DjangoObjectType": DjangoObjectType,
            "filter_field": filter_field,
            "GraphQLString": GraphQLString,
            "_FilterFieldPost": _FilterFieldPost,
            "registry": registry,
        }
        src = (
            "class _BadReservedType(DjangoObjectType):\n"
            "    class Meta:\n"
            "        model = _FilterFieldPost\n"
            "        filter_fields = {'title': ('exact',)}\n"
            "        registry = registry\n"
            "    @filter_field(GraphQLString)\n"
            f"    def {reserved_name}(cls, queryset, info, value):\n"
            "        return queryset\n"
        )

        with pytest.raises(ImproperlyConfigured, match=reserved_name):
            # Building the class triggers the collision check.
            exec(src, ns)


# ---------------------------------------------------------------------------
# 5. filter_fields = {"x": None} → ImproperlyConfigured (not TypeError)
# ---------------------------------------------------------------------------


class TestFilterFieldsNoneRaisesImproperlyConfigured:
    """filter_fields = {"x": None} must now raise ImproperlyConfigured.

    Covers the single regression scenario: a None lookup value must not raise
    a bare TypeError.
    """

    def test_none_value_raises(self) -> None:
        """ "filter_fields = {"x": None}" must raise ImproperlyConfigured, not TypeError.

        If this breaks, a misconfigured filter_fields entry would surface as
        an opaque TypeError instead of the documented configuration error.
        """
        from django_graphex.filtering.native_schema import build_filter_input_type

        with pytest.raises(ImproperlyConfigured, match="filter_field"):
            build_filter_input_type(
                _FilterFieldPost,
                {"title": None},
            )


# ---------------------------------------------------------------------------
# 6. Decorator is exported from django_graphex and django_graphex.filtering
# ---------------------------------------------------------------------------


class TestFilterFieldExports:
    """Public export surface of the "filter_field" decorator and its metadata.

    Covers import-path identity plus the decorator's default-argument
    behavior.
    """

    def test_exported_from_root_and_filtering_are_same(self) -> None:
        """ "filter_field" from all three import paths must be the same callable.

        Covers "django_graphex", "django_graphex.filtering", and the direct
        module path.
        """
        assert filter_field is ff_from_filtering
        assert filter_field is ff_direct

    def test_decorator_marks_method(self) -> None:
        """ "@filter_field" must attach "_dgx_filter_field" metadata to the function.

        The decorator stores the declared scalar VERBATIM under the
        "graphql_type" key — here the native "GraphQLString" singleton — and
        the native builder accepts it as-is.
        """

        @filter_field(GraphQLString, description="test")
        def my_filter(cls, queryset, info, value):
            return queryset

        assert hasattr(my_filter, "_dgx_filter_field")
        meta = my_filter._dgx_filter_field
        assert meta["graphql_type"] is GraphQLString
        assert meta["description"] == "test"

    def test_decorator_no_description(self) -> None:
        """ "@filter_field" without a description must default it to None.

        If this breaks, an undecorated-description filter would either raise
        or fabricate a non-None default instead of leaving it unset.
        """

        @ff_from_filtering(GraphQLString)
        def my_filter(cls, queryset, info, value):
            return queryset

        assert my_filter._dgx_filter_field["description"] is None

    def test_decorator_default_type_is_string(self) -> None:
        """ "@filter_field()" with no type argument must default to the String scalar.

        The native public contract defaults the argument scalar to
        graphql-core's "GraphQLString" (the graphene "String" default of 1.x
        was replaced when the decorator moved to a native default — see
        UPGRADE-2.0). The behaviour under test is unchanged: omitting the type
        yields a String filter argument.
        """
        from graphql import GraphQLString

        @ff_direct()
        def my_filter(cls, queryset, info, value):
            return queryset

        assert my_filter._dgx_filter_field["graphql_type"] is GraphQLString
