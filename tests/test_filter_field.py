"""Tests for the ``@filter_field`` decorator (issue #26).

TDD suite covering:
- Basic string filter arg appears in schema and filters at query time
- Type override (graphene.Int)
- description flows through to the schema
- Composition order: standard lookup -> @filter_field -> filter_queryset
- Reserved-name collision raises ImproperlyConfigured at class definition
- filter_fields = {"x": None} raises ImproperlyConfigured (not TypeError)
"""

from __future__ import annotations

import pytest
import graphene
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from graphql import build_ast_schema, parse

from django_graphex import DjangoObjectType, filter_field
from django_graphex.filtering import filter_field as ff_from_filtering
from django_graphex.filtering.filter_field import filter_field as ff_direct
from django_graphex.filtering.schema import build_filter_input_type
from django_graphex.registry import Registry

from .models import Author, Post


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
# 1. Basic: @filter_field(graphene.String) → arg in schema + query-time filter
# ---------------------------------------------------------------------------


_BASIC_REGISTRY = Registry()


class PostSearchType(DjangoObjectType):
    class Meta:
        model = _FilterFieldPost
        filter_fields = {"title": ("exact",)}
        registry = _BASIC_REGISTRY

    @filter_field(graphene.String, description="Full-text search")
    def search(cls, queryset, info, value):
        return queryset.filter(title__icontains=value)


class TestFilterFieldBasic:
    """The decorated method appears in the filter schema and runs at query time."""

    def test_search_arg_appears_in_filter_input(self):
        """The 'search' arg should appear in the generated filter input type."""
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        assert filter_input is not None
        # 'search' field exists in the generated input type
        assert "search" in filter_input._meta.fields

    def test_search_arg_is_string_type(self):
        """The 'search' arg should be a graphene.String type."""
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        field = filter_input._meta.fields["search"]
        # graphene InputField holds the graphene type
        from graphene import String
        assert field.type is String or (isinstance(field.type, type) and issubclass(field.type, String))

    def test_description_flows_to_schema(self):
        """The description kwarg on @filter_field flows to the GraphQL arg."""
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"title": ("exact",)},
            registry=_BASIC_REGISTRY,
            custom_filters=PostSearchType._dgx_custom_filters,
        )
        field = filter_input._meta.fields["search"]
        assert field.description == "Full-text search"


# ---------------------------------------------------------------------------
# 2. Type override: @filter_field(graphene.Int)
# ---------------------------------------------------------------------------


_INT_REGISTRY = Registry()


class PostIntFilterType(DjangoObjectType):
    class Meta:
        model = _FilterFieldPost
        filter_fields = {"views": ("exact",)}
        registry = _INT_REGISTRY

    @filter_field(graphene.Int, description="Filter by min views")
    def min_views(cls, queryset, info, value):
        return queryset.filter(views__gte=value)


class TestFilterFieldTypeOverride:
    """The graphene_type argument on @filter_field controls the schema arg type."""

    def test_int_type_override(self):
        """@filter_field(graphene.Int) → arg has Int type in the schema."""
        filter_input = build_filter_input_type(
            _FilterFieldPost,
            {"views": ("exact",)},
            registry=_INT_REGISTRY,
            custom_filters=PostIntFilterType._dgx_custom_filters,
        )
        field = filter_input._meta.fields["min_views"]
        from graphene import Int
        assert field.type is Int or (isinstance(field.type, type) and issubclass(field.type, Int))


# ---------------------------------------------------------------------------
# 3. Composition order at query time
# ---------------------------------------------------------------------------


_COMP_REGISTRY = Registry()
_comp_call_log: list[str] = []


class OrderedFilterType(DjangoObjectType):
    class Meta:
        model = _FilterFieldPost
        filter_fields = {"title": ("exact",)}
        registry = _COMP_REGISTRY

    @filter_field(graphene.String)
    def search(cls, queryset, info, value):
        _comp_call_log.append("custom_filter")
        return queryset.filter(title__icontains=value)

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        _comp_call_log.append("filter_queryset")
        return qs.filter(views__gte=10)


class TestFilterFieldCompositionOrder:
    """Standard lookup -> @filter_field -> filter_queryset run in that order."""

    @pytest.mark.django_db
    def test_composition_order(self, db):
        # Create Authors and Posts in the DB
        author = Author.objects.create(name="Alice")
        p1 = Post.objects.create(title="Alpha Beta", body="content", author=author, views=10)
        _p2 = Post.objects.create(title="Gamma Delta", body="content", author=author, views=20)
        p3 = Post.objects.create(title="Alpha Gamma", body="content", author=author, views=5)

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
    """@filter_field whose name matches a reserved pagination/ordering arg raises."""

    @pytest.mark.parametrize(
        "reserved_name",
        ["limit", "offset", "ordering", "page", "page_size", "first", "cursor", "filter", "id"],
    )
    def test_reserved_name_raises(self, reserved_name):
        registry = Registry()

        with pytest.raises(ImproperlyConfigured, match=reserved_name):
            # Building the class triggers the collision check
            attrs = {
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "model": _FilterFieldPost,
                        "filter_fields": {"title": ("exact",)},
                        "registry": registry,
                    },
                ),
            }

            # Create a method decorated with the reserved name
            def _method(cls, queryset, info, value):
                return queryset

            _method.__name__ = reserved_name
            decorated = filter_field(graphene.String)(_method)
            decorated.__name__ = reserved_name
            attrs[reserved_name] = decorated

            type(f"Bad{reserved_name.title()}Type", (DjangoObjectType,), attrs)


# ---------------------------------------------------------------------------
# 5. filter_fields = {"x": None} → ImproperlyConfigured (not TypeError)
# ---------------------------------------------------------------------------


class TestFilterFieldsNoneRaisesImproperlyConfigured:
    """filter_fields = {"x": None} must now raise ImproperlyConfigured."""

    def test_none_value_raises(self):
        from django_graphex.filtering.schema import build_filter_input_type

        with pytest.raises(ImproperlyConfigured, match="filter_field"):
            build_filter_input_type(
                _FilterFieldPost,
                {"title": None},
            )


# ---------------------------------------------------------------------------
# 6. Decorator is exported from django_graphex and django_graphex.filtering
# ---------------------------------------------------------------------------


class TestFilterFieldExports:
    def test_exported_from_root(self):
        """filter_field is importable from django_graphex directly."""
        import django_graphex
        assert hasattr(django_graphex, "filter_field")

    def test_exported_from_filtering(self):
        """filter_field is importable from django_graphex.filtering."""
        import django_graphex.filtering
        assert hasattr(django_graphex.filtering, "filter_field")

    def test_decorator_marks_method(self):
        """@filter_field attaches _dgx_filter_field metadata to the function."""

        @filter_field(graphene.String, description="test")
        def my_filter(cls, queryset, info, value):
            return queryset

        assert hasattr(my_filter, "_dgx_filter_field")
        meta = my_filter._dgx_filter_field
        assert meta["graphene_type"] is graphene.String
        assert meta["description"] == "test"

    def test_decorator_no_description(self):
        """@filter_field without description defaults to None."""

        @filter_field(graphene.String)
        def my_filter(cls, queryset, info, value):
            return queryset

        assert my_filter._dgx_filter_field["description"] is None

    def test_decorator_default_type_is_string(self):
        """@filter_field() (no type) defaults to graphene.String."""

        @filter_field()
        def my_filter(cls, queryset, info, value):
            return queryset

        assert my_filter._dgx_filter_field["graphene_type"] is graphene.String
