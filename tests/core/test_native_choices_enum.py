"""S-enum-1 — native OUTPUT choices-enum generation (focused RED-first tests).

The native OUTPUT compiler ("core/output_compiler.py") historically rendered
a "CharField(choices=...)" as "GraphQLString" (no choices branch). The v2.0
spec renders a real "GraphQLEnumType" with per-choice descriptions instead.
This slice adds a native choices-enum branch that:

* compiles a choices field to a "GraphQLEnumType" (canonical name + value
  names matching graphene), "MultiSelectField" -> "GraphQLList(enum)";
* delivers the RAW python value via "GraphQLEnumValue.value" (resolution
  returns the stored value, not a wrapped member);
* shares ONE canonical enum instance per (model, field) with the native
  filter-input path through the graphene "Registry" slot;
* stops importing graphene on the choices OUTPUT path.

These tests assert exactly those contracts.
"""

from __future__ import annotations

import sys
from types import ModuleType

import pytest
from django.db import models
from django.test.utils import isolate_apps
from graphql import (
    GraphQLEnumType,
    GraphQLList,
    GraphQLNonNull,
)

from django_graphex.registry import Registry
from tests.models import EnumCollisionItemA


def _unwrap(gql_type):
    """Strip a leading GraphQLNonNull wrapper."""
    while isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    return gql_type


def _canonical_enum_name(model, field_name):
    """Return the canonical to_camel_case(app_obj_field_Enum) enum name."""
    from django_graphex._strconv import to_camel_case

    meta = model._meta
    return to_camel_case(f"{meta.app_label}_{meta.object_name}_{field_name}_Enum")


# --------------------------------------------------------------------------- #
# (a) compiled OUTPUT field is a GraphQLEnumType with the canonical name +     #
#     expected value names.                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_choices_field_is_enum_type() -> None:
    """Assert that a choices CharField compiles to a "GraphQLEnumType", not a scalar.

    If this fails, a model field declaring choices would still render as
    a plain GraphQLString, losing the enum's value constraints in the SDL.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    registry = Registry()
    field = EnumCollisionItemA._meta.get_field("status")

    out = _to_graphql_field(field, registry, graphene_registry=registry)

    assert "status" in out
    enum_type = _unwrap(out["status"].type)
    assert isinstance(enum_type, GraphQLEnumType), (
        f"choices output must be a GraphQLEnumType, got {enum_type!r}"
    )
    assert enum_type.name == _canonical_enum_name(EnumCollisionItemA, "status")
    # STATUS_CHOICES = [("a", "Alpha"), ("b", "Beta")] -> value names A / B.
    assert set(enum_type.values) == {"A", "B"}


# --------------------------------------------------------------------------- #
# (b) GraphQLEnumValue.value is the RAW python value (resolution-faithful).    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_choices_enum_values_are_raw() -> None:
    """Assert that enum values deliver the raw stored value ("a" / "b"), not the name.

    If this fails, resolving a choices field would return the enum
    member's symbolic name instead of the actual stored database value.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    registry = Registry()
    field = EnumCollisionItemA._meta.get_field("status")
    out = _to_graphql_field(field, registry, graphene_registry=registry)
    enum_type = _unwrap(out["status"].type)

    assert enum_type.values["A"].value == "a"
    assert enum_type.values["B"].value == "b"
    # Per-choice descriptions (the choice LABELS) are preserved (oracle req #7).
    assert enum_type.values["A"].description == "Alpha"
    assert enum_type.values["B"].description == "Beta"


# --------------------------------------------------------------------------- #
# (c) MultiSelectField -> GraphQLList(enum).                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_multiselect_choices_is_list_of_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert that a MultiSelectField choices field compiles to a list of enum.

    If this fails, a multi-select choices field would compile to a bare
    enum (or scalar) instead of a GraphQLList wrapping the enum type.

    Args:
        monkeypatch: Pytest fixture used to simulate an absent optional package.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    # multiselectfield is an optional dependency; force the absent-package path
    # so this contract is independent of the active test environment.
    monkeypatch.setitem(sys.modules, "multiselectfield", None)

    class MultiSelectField(models.CharField):
        pass

    field = MultiSelectField(max_length=20, choices=[("a", "Alpha"), ("b", "Beta")])
    field.name = "status"
    field.model = EnumCollisionItemA

    registry = Registry()
    out = _to_graphql_field(field, registry, graphene_registry=registry)

    list_type = _unwrap(out["status"].type)
    assert isinstance(list_type, GraphQLList), (
        f"MultiSelectField output must be a list, got {list_type!r}"
    )
    assert isinstance(_unwrap(list_type.of_type), GraphQLEnumType)


@pytest.mark.parametrize("input_for", ["create", "update"])
@pytest.mark.django_db
@isolate_apps()
def test_multiselect_subclass_is_list_enum_on_input_and_output(
    monkeypatch: pytest.MonkeyPatch, input_for: str
) -> None:
    """Keep a renamed MultiSelectField subclass list-shaped everywhere.

    Args:
        monkeypatch: Pytest fixture used to isolate the optional integration.
        input_for: Generated CRUD input mode under test.
    """

    class MultiSelectField(models.CharField):
        pass

    module = ModuleType("multiselectfield")
    module.MultiSelectField = MultiSelectField
    monkeypatch.setitem(sys.modules, "multiselectfield", module)

    class RenamedMultiSelectField(MultiSelectField):
        pass

    class MultiSelectItem(models.Model):
        tags = RenamedMultiSelectField(
            max_length=20, choices=[("a", "Alpha"), ("b", "Beta")]
        )

        class Meta:
            app_label = "multiselect_test"

    from django_graphex.core.output_compiler import _to_graphql_field
    from django_graphex.types import DjangoInputObjectType

    registry = Registry()
    input_registry = registry
    input_kind = input_for
    field = MultiSelectItem._meta.get_field("tags")
    output = _to_graphql_field(field, registry, graphene_registry=registry)

    class MultiSelectItemInput(DjangoInputObjectType):
        class Meta:
            model = MultiSelectItem
            registry = input_registry
            input_for = input_kind

    output_type = _unwrap(output["tags"].type)
    input_type = _unwrap(
        MultiSelectItemInput._meta.graphql_input_type.fields["tags"].type
    )

    assert isinstance(output_type, GraphQLList)
    assert isinstance(_unwrap(output_type.of_type), GraphQLEnumType)
    assert isinstance(input_type, GraphQLList)
    assert isinstance(_unwrap(input_type.of_type), GraphQLEnumType)


def test_multiselect_missing_dependency_inside_installed_package_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not use the fallback when an installed integration misses a dependency.

    Args:
        monkeypatch: Pytest fixture used to inject the broken integration.

    Raises:
        ModuleNotFoundError: Simulated and asserted by the test.
    """
    module = ModuleType("multiselectfield")

    def __getattr__(name: str) -> object:
        if name == "MultiSelectField":
            raise ModuleNotFoundError(
                "missing multiselectfield dependency",
                name="multiselectfield_dependency",
            )
        raise AttributeError(name)

    module.__getattr__ = __getattr__  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "multiselectfield", module)

    from django_graphex.converter import is_multiselect_field

    with pytest.raises(
        ModuleNotFoundError, match="missing multiselectfield dependency"
    ):
        is_multiselect_field(object())


# --------------------------------------------------------------------------- #
# (d) SHARED-INSTANCE: the OUTPUT enum IS the SAME object the filter-input     #
#     path builds for the same (model, field).                                #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_and_filter_input_share_one_enum_instance() -> None:
    """Assert that the OUTPUT and FILTER-INPUT paths resolve the same canonical enum instance.

    If this fails, the schema would carry two distinct GraphQLEnumType
    objects for the same (model, field), risking duplicate-name schema
    assembly errors or identity mismatches.
    """
    from django_graphex.core.output_compiler import _to_graphql_field
    from django_graphex.filtering.native_schema import _choices_enum

    registry = Registry()
    field = EnumCollisionItemA._meta.get_field("status")

    # OUTPUT builds + registers the canonical enum.
    out = _to_graphql_field(field, registry, graphene_registry=registry)
    output_enum = _unwrap(out["status"].type)

    # FILTER-INPUT must find and reuse the SAME instance (same registry slot).
    filter_enum = _choices_enum(field, registry)

    assert output_enum is filter_enum, (
        "OUTPUT and FILTER-INPUT must share ONE canonical enum instance per "
        "(model, field); got two distinct objects"
    )
    # And the order-independence: filter-input first, output second, still one.
    registry2 = Registry()
    filter_first = _choices_enum(field, registry2)
    out2 = _to_graphql_field(field, registry2, graphene_registry=registry2)
    assert _unwrap(out2["status"].type) is filter_first


# --------------------------------------------------------------------------- #
# Defensive: a field WITHOUT usable choices yields None (caller falls back to   #
# the scalar mapping / GraphQLString).                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_build_choices_enum_returns_none_without_choices() -> None:
    """Assert that "build_choices_enum_type" returns None for a no-choices field.

    If this fails, a plain (non-choices) field would spuriously get an
    enum type instead of falling back to the caller's scalar mapping.
    """
    from django_graphex.converter import build_choices_enum_type

    field = EnumCollisionItemA._meta.get_field("id")  # auto pk, no choices
    assert build_choices_enum_type(field, Registry()) is None


# --------------------------------------------------------------------------- #
# (e) IMPORT-REMOVAL: the choices OUTPUT path is graphene-free.                #
#     S-del-backend-11: the converter has no ``_g()`` graphene accessor (the   #
#     graphene backend was deleted), so the choices OUTPUT enum is built from   #
#     ``model._meta`` natively — assert the native ``GraphQLEnumType`` result.  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_choices_path_does_not_import_graphene() -> None:
    """Assert that the choices OUTPUT enum is built natively, with no graphene involvement.

    If this fails, compiling a choices output field would depend on the
    deleted graphene accessor path instead of "model._meta" directly.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    registry = Registry()
    field = EnumCollisionItemA._meta.get_field("status")

    out = _to_graphql_field(field, registry, graphene_registry=registry)
    assert isinstance(_unwrap(out["status"].type), GraphQLEnumType)
