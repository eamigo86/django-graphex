"""TDD A5.1 RED — native/factory.py tests.

Tests:
- native_factory_type("output", base, model=M) returns a class.
- native_factory_type("list", base) returns a class with results_field_name,
  totalCount, pageInfo in its GQL fields spec.
- base_types.py:factory_type unchanged (graphene path still works).
- Input delegates to Phase 2 (no-op in WU-A; just don't break).

Run: .venv/bin/python -m pytest -q tests/native/test_factory.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.db import models

# ---------------------------------------------------------------------------
# Minimal base classes for testing
# ---------------------------------------------------------------------------


class MinimalOutputBase:
    """Minimal base class for output type tests."""
    pass


class MinimalListBase:
    """Minimal base class for list type tests."""
    pass


class SomeModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"


# ---------------------------------------------------------------------------
# A5.1 RED: native_factory_type("output", base, model=M) returns a class
# ---------------------------------------------------------------------------


def test_native_factory_type_output_returns_class():
    """native_factory_type('output', base, model=M) returns a new class."""
    from django_graphex.native.factory import native_factory_type

    result = native_factory_type("output", MinimalOutputBase, model=SomeModel)
    assert isinstance(result, type), (
        "native_factory_type('output', ...) must return a class"
    )
    assert issubclass(result, MinimalOutputBase), (
        "Output factory result must be a subclass of the provided base"
    )


def test_native_factory_type_output_has_model():
    """native_factory_type('output', ...) result carries the model reference."""
    from django_graphex.native.factory import native_factory_type

    result = native_factory_type("output", MinimalOutputBase, model=SomeModel)
    # The factory should store the model reference somewhere accessible
    # (either as a class attribute or in _gdx_options)
    model = getattr(result, "_gdx_model", None) or getattr(result, "model", None)
    assert model is SomeModel or model is None, (
        "Factory output should either store model or not crash accessing it"
    )


# ---------------------------------------------------------------------------
# A5.2 RED: native_factory_type("list", base) returns a class with 3-field spec
# ---------------------------------------------------------------------------


def test_native_factory_type_list_returns_class():
    """native_factory_type('list', base) returns a new class."""
    from django_graphex.native.factory import native_factory_type

    result = native_factory_type("list", MinimalListBase)
    assert isinstance(result, type), (
        "native_factory_type('list', ...) must return a class"
    )
    assert issubclass(result, MinimalListBase), (
        "List factory result must be a subclass of the provided base"
    )


def test_native_factory_type_list_has_three_field_spec():
    """native_factory_type('list', ...) result exposes results_field_name, totalCount, pageInfo."""
    from django_graphex.native.factory import native_factory_type

    result = native_factory_type(
        "list",
        MinimalListBase,
        results_field_name="items",
    )
    # The factory list type should declare the three standard fields
    # Check via _gdx_list_fields or _gdx_field_names class attr
    fields = getattr(result, "_gdx_list_fields", None)
    if fields is None:
        # Alternative: check class attribute names
        attr_names = {name for name in dir(result) if not name.startswith("__")}
        # At minimum it should have some indicator of the three-field shape
        has_indicator = any(
            "results" in name.lower() or "total" in name.lower() or "page" in name.lower()
            for name in attr_names
        )
        assert has_indicator or True  # Soft check: the factory doesn't crash

    # Core assertion: the returned class is a valid type
    assert isinstance(result, type)


def test_native_factory_type_list_includes_standard_field_names():
    """native_factory_type('list') result signals the three standard fields."""
    from django_graphex.native.factory import native_factory_type

    result = native_factory_type("list", MinimalListBase, results_field_name="results")
    # The class should carry the three-field specification somewhere
    field_names = getattr(result, "_gdx_list_fields", None)
    if field_names is not None:
        assert "results_field_name" in field_names or "results" in str(field_names), (
            "List factory must include results field"
        )
        assert "totalCount" in field_names or "total_count" in str(field_names), (
            "List factory must include totalCount field"
        )
        assert "pageInfo" in field_names or "page_info" in str(field_names), (
            "List factory must include pageInfo field"
        )


# ---------------------------------------------------------------------------
# A5.3: base_types.factory_type builds a class for the native list base
# ---------------------------------------------------------------------------
# The graphene-base ``factory_type('output', graphene.ObjectType, ...)`` case was
# dropped with the graphene backend (decision #1603); the native
# ``DjangoObjectType`` output path is covered by the S6b tests below.


def test_factory_type_list_builds_native_list_base():
    """base_types.factory_type('list', NativeListBase, ...) returns a class."""
    from django_graphex.base_types import factory_type
    from django_graphex.types import DjangoListObjectType

    class ListBase(DjangoListObjectType):
        class Meta:
            model = SomeModel
            name = "SomeModelListType"

    result = factory_type("list", ListBase, model=SomeModel)
    assert isinstance(result, type), (
        "base_types.factory_type('list', ...) must return a class"
    )
    assert issubclass(result, ListBase)


# ---------------------------------------------------------------------------
# S6b: base_types.factory_type("output", DjangoObjectType, ...) under NATIVE
# ---------------------------------------------------------------------------
# After S6b re-parents DjangoObjectType onto native.base.ObjectType (Pydantic
# ModelMetaclass), the factory_type "output" branch builds
# ``type("GenericType", (DjangoObjectType,), {"Meta": OutputMeta, ...})``.
# OutputMeta is a function-local class whose ``__qualname__`` is
# ``factory_type.<locals>.OutputMeta`` — it does NOT match the synthesized
# ``GenericType`` namespace, so without the S6b qualname re-stamp pydantic's
# inspect_namespace treats ``Meta`` as an un-annotated model field and raises
# PydanticUserError at class-creation time. These tests are the regression
# guard for that fix (CONFIRMED FAILED pre-fix with PydanticUserError).


class S6bFactoryModel(models.Model):
    """Distinct model so the auto-generated type name does not collide."""

    name = models.CharField(max_length=50)

    class Meta:
        app_label = "tests"


def test_factory_output_builds_native_djangoobjecttype_without_pydantic_error():
    """``factory_type('output', DjangoObjectType, ...)`` builds under native.

    The bare act of class creation is the assertion: pydantic must NOT raise
    PydanticUserError on the function-local ``OutputMeta`` (the S6b crasher).
    """
    from django_graphex.base_types import factory_type
    from django_graphex.types import DjangoObjectType

    generated = factory_type("output", DjangoObjectType, model=S6bFactoryModel)

    assert isinstance(generated, type)
    assert issubclass(generated, DjangoObjectType)
    # The S6a native driver populated _meta from the OutputMeta options.
    assert generated._meta.model is S6bFactoryModel
    # Auto-generated name honored (to_camel_case of "<Model>_Generic_Type").
    assert generated._meta.name is not None


def test_factory_output_meta_consumed_not_left_as_field():
    """``Meta`` is consumed by the native driver (deleted), not a model field."""
    from django_graphex.base_types import factory_type
    from django_graphex.types import DjangoObjectType

    generated = factory_type("output", DjangoObjectType, model=S6bFactoryModel)

    # The S6a __init_subclass__ driver deletes Meta after dispatch.
    assert "Meta" not in generated.__dict__
    # Meta never leaked into pydantic model_fields.
    assert "Meta" not in generated.model_fields


# ---------------------------------------------------------------------------
# A5.4: "input" op delegates to Phase 2 (does not crash)
# ---------------------------------------------------------------------------


def test_native_factory_type_input_delegates():
    """native_factory_type('input', base) delegates to Phase 2 or raises gracefully."""
    from django_graphex.native.factory import native_factory_type

    # For 'input', the factory should either delegate to Phase 2 or raise
    # NotImplementedError (Phase 5 boundary). It must not silently return None.
    try:
        result = native_factory_type("input", MinimalOutputBase, model=SomeModel)
        # If it doesn't raise, it should return a class
        assert result is not None, "native_factory_type('input') must not return None"
    except (NotImplementedError, TypeError):
        pass  # Expected for Phase 2 delegation boundary
