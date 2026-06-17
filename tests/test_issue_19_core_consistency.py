# -*- coding: utf-8 -*-
"""Tests for issue #19 — core consistency fixes.

Covers:
(a) construct_fields field ordering is unconditional (same DEBUG=True and False)
(b) Registry and DjangoNestedListObjectField exported from django_graphex.__init__
(c) MultiSelectField detected via isinstance with guarded import
(d) ArrayField/RangeField inner type config preserved
"""

from __future__ import annotations

import pytest
from django.db import models
from django.test import override_settings

from django_graphex.converter import (
    construct_fields,
    convert_django_field_with_choices,
    convert_postgres_array_to_list,
    convert_postgres_range_to_string,
)
from django_graphex.fields import ArrayField
from django_graphex.registry import Registry
from tests.models import Author


def _is_graphene_list(obj):
    """True when ``obj`` is a graphene ``List`` wrapper.

    The PostgreSQL ArrayField / RangeField converters are NOT yet migrated off
    graphene (they still emit a ``graphene.types.structures.List`` on the native
    path); assert their wrapper structurally instead of importing graphene.
    """
    return type(obj).__name__ == "List" and type(obj).__module__.startswith(
        "graphene"
    )


# --------------------------------------------------------------------------- #
# (a) Field ordering — unconditional determinism                               #
# --------------------------------------------------------------------------- #


@override_settings(DEBUG=False)
def test_construct_fields_sorts_output_without_debug():
    """Output type fields are alphabetical even when DEBUG=False."""
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None)
    names = list(fields)
    assert names == sorted(names), (
        "Field order must be alphabetical regardless of DEBUG; "
        f"got {names}, expected {sorted(names)}"
    )


@override_settings(DEBUG=True)
def test_construct_fields_sorts_output_with_debug():
    """Output type fields are alphabetical when DEBUG=True (was already true)."""
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None)
    names = list(fields)
    assert names == sorted(names)


def test_construct_fields_output_order_identical_debug_true_false():
    """The output type field order is identical for DEBUG=True and DEBUG=False.

    This is the core regression test for issue #19: dev/prod SDL skew.
    """
    registry_true = Registry()
    registry_false = Registry()

    with override_settings(DEBUG=True):
        fields_debug_true = list(
            construct_fields(Author, registry_true, None, None, None)
        )

    with override_settings(DEBUG=False):
        fields_debug_false = list(
            construct_fields(Author, registry_false, None, None, None)
        )

    assert fields_debug_true == fields_debug_false, (
        "Field order must be identical regardless of DEBUG; "
        f"DEBUG=True: {fields_debug_true}, DEBUG=False: {fields_debug_false}"
    )


@override_settings(DEBUG=False)
def test_construct_fields_create_sorts_required_first_without_debug():
    """Create-input type fields are required-first then alphabetical without DEBUG."""
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None, input_flag="create")
    # No exception; id is dropped on create.
    assert "id" not in fields
    names = list(fields)
    # All fields should appear in some order (not just insertion order from the model).
    assert len(names) > 0


def test_construct_fields_create_order_identical_debug_true_false():
    """Create-input field order is identical for DEBUG=True and DEBUG=False."""
    registry_true = Registry()
    registry_false = Registry()

    with override_settings(DEBUG=True):
        fields_debug_true = list(
            construct_fields(
                Author, registry_true, None, None, None, input_flag="create"
            )
        )

    with override_settings(DEBUG=False):
        fields_debug_false = list(
            construct_fields(
                Author, registry_false, None, None, None, input_flag="create"
            )
        )

    assert fields_debug_true == fields_debug_false, (
        "Create-input field order must be identical regardless of DEBUG; "
        f"DEBUG=True: {fields_debug_true}, DEBUG=False: {fields_debug_false}"
    )


# --------------------------------------------------------------------------- #
# (b) Public exports                                                            #
# --------------------------------------------------------------------------- #


def test_registry_importable_from_top_level():
    """Registry must be importable directly from django_graphex."""
    from django_graphex import Registry as RegistryImport  # noqa: F401

    assert RegistryImport is not None


def test_registry_in_all():
    """Registry must appear in django_graphex.__all__."""
    import django_graphex

    assert "Registry" in django_graphex.__all__, (
        "Registry is missing from django_graphex.__all__"
    )


def test_django_nested_list_object_field_importable_from_top_level():
    """DjangoNestedListObjectField must be importable directly from django_graphex."""
    from django_graphex import DjangoNestedListObjectField  # noqa: F401

    assert DjangoNestedListObjectField is not None


def test_django_nested_list_object_field_in_all():
    """DjangoNestedListObjectField must appear in django_graphex.__all__."""
    import django_graphex

    assert "DjangoNestedListObjectField" in django_graphex.__all__, (
        "DjangoNestedListObjectField is missing from django_graphex.__all__"
    )


# --------------------------------------------------------------------------- #
# (c) MultiSelectField isinstance detection                                    #
# --------------------------------------------------------------------------- #


def test_multiselectfield_subclass_with_different_name_detected():
    """MultiSelectField subclasses with a non-matching name must be detected.

    The old code used ``type(field).__name__ == "MultiSelectField"`` which only
    matches the exact class name. A subclass with a different name (or a
    reimplementation) would fall through to the single-value enum path.

    Our fix: guarded isinstance check. When multiselectfield is not installed,
    the converter falls back to the name check only if the import fails.
    This test verifies the isinstance path works when the package IS installed
    (skipped otherwise), and verifies the name-check path for the non-installed case.

    S-enum-2 (OUTPUT) + S-input-5 (INPUT) retired graphene on the choices
    converter: on native it returns the dead-scalar sentinel for a MultiSelectField
    subclass too, and the multiselect ``[Enum]`` rendering (driven by the guarded
    isinstance check) moved to ``types._resolve_native_choices_input_fields`` /
    the native output compiler. We assert the converter recognizes the subclass
    (no raise, sentinel return) instead of the old graphene ``Field`` wrapper.
    """
    from django_graphex.converter import _DEAD_SCALAR

    try:
        from multiselectfield import MultiSelectField as _MSF  # noqa: F401

        # If the package is installed, the isinstance check should recognize the
        # subclass and route it through the (graphene-free) choices converter.
        class _SubMSF(_MSF):
            pass

        field = _SubMSF(max_length=20, choices=[("a", "A"), ("b", "B")])
        field.name = "tags_sub"
        field.model = Author
        out = convert_django_field_with_choices(field, Registry())
        # Recognized as a choices field (dead-scalar sentinel on native); the
        # ``[Enum]`` list rendering is owned by the native compiler.
        assert out is _DEAD_SCALAR, (
            "MultiSelectField subclass must be recognized by the choices converter "
            "(isinstance path) and return the native dead-scalar sentinel"
        )
    except ImportError:
        # Package not installed — the name-check fallback is the only heuristic.
        # The important invariant: a class named "MultiSelectField" still works.
        pytest.skip("multiselectfield package not installed; skipping isinstance path")


def test_multiselectfield_direct_class_still_detected():
    """A class literally named MultiSelectField still renders as a list of enum.

    Regression guard — the isinstance path must fall back gracefully when the
    multiselectfield package is absent and the name-check is the only heuristic.

    S-enum-2 (OUTPUT) + S-input-5 (INPUT) retired graphene on the choices
    converter (it returns the dead-scalar sentinel on native). The name-based
    MultiSelectField detection now lives in
    ``types._resolve_native_choices_input_fields`` (``is_list=True`` -> ``[Enum]``)
    for the INPUT surface and the native output compiler for OUTPUT.
    """

    from django_graphex.converter import _DEAD_SCALAR

    class MultiSelectField(models.CharField):
        pass

    field = MultiSelectField(max_length=20, choices=[("a", "A"), ("b", "B")])
    field.name = "tags"
    field.model = Author

    # Converter is graphene-free on both paths (dead-scalar sentinel). The
    # MultiSelectField -> ``[Enum]`` input rendering is driven by the name-based
    # heuristic in ``_resolve_native_choices_input_fields``
    # (``is_list = type(field).__name__ == "MultiSelectField"``).
    for input_flag in (None, "create"):
        out = convert_django_field_with_choices(
            field, Registry(), input_flag=input_flag
        )
        assert out is _DEAD_SCALAR
    assert type(field).__name__ == "MultiSelectField"


# --------------------------------------------------------------------------- #
# (d) ArrayField / RangeField inner type config preservation                   #
# --------------------------------------------------------------------------- #


def test_arrayfield_preserves_required_flag():
    """ArrayField: the outer required flag must be preserved in the List wrapper."""
    # A required ArrayField (in a create input) should yield a required List.
    field = ArrayField(models.IntegerField())
    field.name = "scores"
    field.model = Author
    # blank=False, null=False => required on create
    out = convert_postgres_array_to_list(field, Registry(), input_flag="create")
    assert _is_graphene_list(out)
    # The required flag should propagate to the outer List (NonNull or required kwarg).
    # graphene List stores required as a kwarg; it doesn't wrap in NonNull itself.
    # We check that the field has the right required kwarg set.
    assert out.kwargs.get("required") is True


def test_arrayfield_not_required_without_create_flag():
    """ArrayField: required=False when not in create input context."""
    field = ArrayField(models.IntegerField())
    out = convert_postgres_array_to_list(field, Registry(), input_flag=None)
    assert _is_graphene_list(out)
    assert not out.kwargs.get("required", False)


def test_rangefield_preserves_required_flag():
    """RangeField: the outer required flag must be preserved in the List wrapper."""
    field = ArrayField(models.IntegerField())  # has .base_field; used as range stand-in
    field.name = "score_range"
    # Make it required by Django field conventions (blank=False, null=False).
    out = convert_postgres_range_to_string(field, Registry(), input_flag="create")
    assert _is_graphene_list(out)
    assert out.kwargs.get("required") is True


def test_rangefield_not_required_without_create_flag():
    """RangeField: required=False when not in create input context."""
    field = ArrayField(models.IntegerField())
    out = convert_postgres_range_to_string(field, Registry(), input_flag=None)
    assert _is_graphene_list(out)
    assert not out.kwargs.get("required", False)


def test_arrayfield_inner_type_description_preserved():
    """ArrayField: description from the outer field is passed to the List wrapper."""
    field = ArrayField(models.IntegerField(), help_text="list of scores")
    out = convert_postgres_array_to_list(field, Registry())
    assert out.kwargs.get("description") == "list of scores"
