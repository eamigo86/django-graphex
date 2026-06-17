"""S-enum-1 — native OUTPUT choices-enum generation (focused RED-first tests).

The native OUTPUT compiler (``native/output_compiler.py``) historically rendered
a ``CharField(choices=...)`` as ``GraphQLString`` (no choices branch). The v2.0
spec renders a real ``GraphQLEnumType`` with per-choice descriptions instead.
This slice adds a native choices-enum branch that:

* compiles a choices field to a ``GraphQLEnumType`` (canonical name + value
  names matching graphene), ``MultiSelectField`` → ``GraphQLList(enum)``;
* delivers the RAW python value via ``GraphQLEnumValue.value`` (resolution
  returns the stored value, not a wrapped member);
* shares ONE canonical enum instance per (model, field) with the native
  filter-input path through the graphene ``Registry`` slot;
* stops importing graphene on the choices OUTPUT path.

These tests assert exactly those contracts.
"""
from __future__ import annotations

import pytest
from django.db import models
from graphql import (
    GraphQLEnumType,
    GraphQLList,
    GraphQLNonNull,
)

from django_graphex.registry import Registry
from tests.models import EnumCollisionItemA


def _unwrap(gql_type):
    """Strip a leading ``GraphQLNonNull`` wrapper."""
    while isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    return gql_type


def _canonical_enum_name(model, field_name):
    """Return the canonical ``to_camel_case(app_obj_field_Enum)`` enum name."""
    from django_graphex._strconv import to_camel_case

    meta = model._meta
    return to_camel_case(f"{meta.app_label}_{meta.object_name}_{field_name}_Enum")


# --------------------------------------------------------------------------- #
# (a) compiled OUTPUT field is a GraphQLEnumType with the canonical name +     #
#     expected value names.                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_choices_field_is_enum_type():
    """A choices CharField compiles to a ``GraphQLEnumType`` (not a scalar)."""
    from django_graphex.native.output_compiler import _to_graphql_field

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
def test_output_choices_enum_values_are_raw():
    """Enum values deliver the RAW stored value ('a' / 'b'), not the name."""
    from django_graphex.native.output_compiler import _to_graphql_field

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
def test_output_multiselect_choices_is_list_of_enum():
    """A MultiSelectField choices field compiles to ``[Enum]`` (a list)."""
    from django_graphex.native.output_compiler import _to_graphql_field

    # multiselectfield is an optional dependency; the converter detects it by
    # class name when the package is absent. Mirror that with a local subclass.
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


# --------------------------------------------------------------------------- #
# (d) SHARED-INSTANCE: the OUTPUT enum IS the SAME object the filter-input     #
#     path builds for the same (model, field).                                #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_output_and_filter_input_share_one_enum_instance():
    """OUTPUT and FILTER-INPUT resolve the SAME canonical enum instance."""
    from django_graphex.filtering.native_schema import _choices_enum
    from django_graphex.native.output_compiler import _to_graphql_field

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
def test_build_choices_enum_returns_none_without_choices():
    """``build_choices_enum_type`` returns None for a no-choices field."""
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
def test_output_choices_path_does_not_import_graphene():
    """The choices OUTPUT enum is built natively (graphene-free)."""
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = Registry()
    field = EnumCollisionItemA._meta.get_field("status")

    out = _to_graphql_field(field, registry, graphene_registry=registry)
    assert isinstance(_unwrap(out["status"].type), GraphQLEnumType)
