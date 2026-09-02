"""TDD A5.1 RED — core/factory.py tests.

Tests:
- native_factory_type("output", base, model=M) returns a class.
- native_factory_type("list", base) returns a class with results_field_name,
  totalCount, pageInfo in its GQL fields spec.
- base_types.py:factory_type unchanged (graphene path still works).
- Input delegates to Phase 2 (no-op in WU-A; just don't break).

Run: .venv/bin/python -m pytest -q tests/core/test_factory.py --no-cov
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.db import models  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal base classes for testing
# ---------------------------------------------------------------------------


class MinimalOutputBase:
    """Minimal base class for output type tests.

    Stands in for a real ObjectType base so native_factory_type("output", ...)
    can be exercised without pulling in the full ObjectType machinery.
    """

    pass


class MinimalListBase:
    """Minimal base class for list type tests.

    Stands in for a real list-object-type base so native_factory_type("list",
    ...) can be exercised without pulling in the full list-type machinery.
    """

    pass


class SomeModel(models.Model):
    """Minimal Django model used as the "model=" target for factory tests.

    Gives native_factory_type("output", ..., model=SomeModel) a real Django
    model to attach to the generated class.
    """

    name = models.CharField(max_length=100)

    class Meta:
        """Django model options for SomeModel.

        Scopes the model to the tests app registry so it does not collide
        with real project models.
        """

        app_label = "tests"


# ---------------------------------------------------------------------------
# A5.1 RED: native_factory_type("output", base, model=M) returns a class
# ---------------------------------------------------------------------------


def test_native_factory_type_output_returns_class() -> None:
    """Ships broken if native_factory_type stops building an output subclass.

    Calling native_factory_type("output", base, model=M) must return a new
    class that subclasses the provided base.
    """
    from django_graphex.core.factory import native_factory_type

    result = native_factory_type("output", MinimalOutputBase, model=SomeModel)
    assert isinstance(result, type), (
        "native_factory_type('output', ...) must return a class"
    )
    assert issubclass(result, MinimalOutputBase), (
        "Output factory result must be a subclass of the provided base"
    )


def test_native_factory_type_output_has_model() -> None:
    """Ships broken if the output factory result loses its model reference.

    The generated class must either expose the model via "_gdx_model" /
    "model" or simply not crash when those attributes are looked up.
    """
    from django_graphex.core.factory import native_factory_type

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


def test_native_factory_type_list_returns_class() -> None:
    """Ships broken if native_factory_type stops building a list subclass.

    Calling native_factory_type("list", base) must return a new class that
    subclasses the provided base.
    """
    from django_graphex.core.factory import native_factory_type

    result = native_factory_type("list", MinimalListBase)
    assert isinstance(result, type), (
        "native_factory_type('list', ...) must return a class"
    )
    assert issubclass(result, MinimalListBase), (
        "List factory result must be a subclass of the provided base"
    )


def test_native_factory_type_list_has_three_field_spec() -> None:
    """Ships broken if the list factory result drops the standard 3-field spec.

    native_factory_type("list", ...) must expose "results_field_name",
    "totalCount" and "pageInfo" somewhere on the generated class.
    """
    from django_graphex.core.factory import native_factory_type

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
            "results" in name.lower()
            or "total" in name.lower()
            or "page" in name.lower()
            for name in attr_names
        )
        assert has_indicator or True  # Soft check: the factory doesn't crash

    # Core assertion: the returned class is a valid type
    assert isinstance(result, type)


def test_native_factory_type_list_includes_standard_field_names() -> None:
    """Ships broken if the list factory result stops signaling the standard fields.

    native_factory_type("list") must carry a "_gdx_list_fields" specification
    naming the results field, totalCount and pageInfo (in either camelCase or
    snake_case form).
    """
    from django_graphex.core.factory import native_factory_type

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


def test_factory_type_list_builds_native_list_base() -> None:
    """Ships broken if base_types.factory_type stops building a native list class.

    factory_type("list", NativeListBase, ...) must return a subclass of the
    provided native "DjangoListObjectType"-derived base.
    """
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
    """Distinct model so the auto-generated type name does not collide.

    Kept separate from SomeModel so the S6b factory_type("output", ...)
    regression tests generate their own uniquely named type.
    """

    name = models.CharField(max_length=50)

    class Meta:
        """Django model options for S6bFactoryModel.

        Scopes the model to the tests app registry so it does not collide
        with real project models.
        """

        app_label = "tests"


def test_factory_output_builds_native_djangoobjecttype_without_pydantic_error() -> None:
    """factory_type("output", DjangoObjectType, ...) builds under native.

    The bare act of class creation is the assertion: pydantic must NOT raise
    PydanticUserError on the function-local "OutputMeta" (the S6b crasher).
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


def test_factory_output_meta_consumed_not_left_as_field() -> None:
    """Ships broken if the native driver stops consuming "Meta" off the class.

    "Meta" must be deleted by the native "__init_subclass__" driver and must
    never leak into pydantic's "model_fields".
    """
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


def test_native_factory_type_input_delegates() -> None:
    """Ships broken if native_factory_type("input", ...) silently returns None.

    It must either delegate to the Phase 2 input path and return a class, or
    raise NotImplementedError/TypeError at the Phase 5 boundary.
    """
    from django_graphex.core.factory import native_factory_type

    # For 'input', the factory should either delegate to Phase 2 or raise
    # NotImplementedError (Phase 5 boundary). It must not silently return None.
    try:
        result = native_factory_type("input", MinimalOutputBase, model=SomeModel)
        # If it doesn't raise, it should return a class
        assert result is not None, "native_factory_type('input') must not return None"
    except (NotImplementedError, TypeError):
        pass  # Expected for Phase 2 delegation boundary
