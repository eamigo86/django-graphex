# -*- coding: utf-8 -*-
"""Tests for issue #52: enum registry key collision + self-referential O2O.

RED phase: these tests MUST FAIL before the fix is applied, then pass after.

Defect A — Enum registry key collision for same-class-name models across apps:
  Two models sharing the same object_name (``Item``) but with *different* choices
  on a same-named field (``status``) must produce two DISTINCT enum types, not
  collide into one.

Defect B — Genuine self-referential OneToOneField silently dropped:
  A model with ``spouse = OneToOneField('self', ...)`` must have that field present
  in both the output GraphQL type and the create/update input types.
"""

from __future__ import annotations

import graphene

from django_graphex import DjangoObjectType
from django_graphex.converter import (
    convert_django_field_with_choices,
    convert_field_to_djangomodel,
)
from django_graphex.registry import Registry

from .models import EnumCollisionItemA, EnumCollisionItemB, PersonWithSpouse

# ---------------------------------------------------------------------------
# Defect A — Enum key collision
# ---------------------------------------------------------------------------


class TestEnumKeyCollision:
    """Two models sharing object_name but different choices must not collide."""

    def test_same_object_name_different_app_produces_distinct_enums(self):
        """Simulate the cross-app collision: two models both called 'Item' but
        with divergent status choices should produce two distinct enums."""
        local_registry = Registry()

        # Build two fields that share object_name="Item" and field name "status"
        # but belong to different model classes with different choices.
        field_a = EnumCollisionItemA._meta.get_field("status")
        field_b = EnumCollisionItemB._meta.get_field("status")

        # Patch both fields' model._meta.object_name to "Item" to simulate
        # the cross-app scenario (same class name, different apps).
        class _FakeMetaA:
            object_name = "Item"
            app_label = "app_one"

        class _FakeMetaB:
            object_name = "Item"
            app_label = "app_two"

        ModelA = type("Item", (object,), {"_meta": _FakeMetaA()})
        ModelB = type("Item", (object,), {"_meta": _FakeMetaB()})

        original_a = field_a.model
        original_b = field_b.model

        try:
            field_a.model = ModelA
            field_b.model = ModelB

            enum_a = convert_django_field_with_choices(field_a, local_registry)
            enum_b = convert_django_field_with_choices(field_b, local_registry)
        finally:
            field_a.model = original_a
            field_b.model = original_b

        # The two enums must be distinct objects.
        assert enum_a is not enum_b, (
            "Two models sharing object_name 'Item' but with different choices on "
            "'status' must NOT share the same enum type."
        )

        # Each enum must carry its own members.
        members_a = set(enum_a._meta.enum.__members__)
        members_b = set(enum_b._meta.enum.__members__)

        assert members_a == {"A", "B"}, f"ItemA enum members wrong: {members_a}"
        assert members_b == {"X", "Y", "Z"}, f"ItemB enum members wrong: {members_b}"

    def test_distinct_model_classes_produce_independent_enums(self):
        """Using distinct model classes, each field produces its own enum."""
        local_registry = Registry()

        field_a = EnumCollisionItemA._meta.get_field("status")
        field_b = EnumCollisionItemB._meta.get_field("status")

        enum_a = convert_django_field_with_choices(field_a, local_registry)
        enum_b = convert_django_field_with_choices(field_b, local_registry)

        assert enum_a is not enum_b

        members_a = set(enum_a._meta.enum.__members__)
        members_b = set(enum_b._meta.enum.__members__)

        assert members_a == {"A", "B"}
        assert members_b == {"X", "Y", "Z"}

    def test_input_flag_enums_keyed_independently_per_model_class(self):
        """The same fix must apply to input-flagged enums (create/update)."""
        local_registry = Registry()

        field_a = EnumCollisionItemA._meta.get_field("status")
        field_b = EnumCollisionItemB._meta.get_field("status")

        class _FakeMetaA:
            object_name = "Item"
            app_label = "app_one"

        class _FakeMetaB:
            object_name = "Item"
            app_label = "app_two"

        ModelA = type("Item", (object,), {"_meta": _FakeMetaA()})
        ModelB = type("Item", (object,), {"_meta": _FakeMetaB()})

        original_a = field_a.model
        original_b = field_b.model

        try:
            field_a.model = ModelA
            field_b.model = ModelB

            enum_a_create = convert_django_field_with_choices(
                field_a, local_registry, input_flag="create"
            )
            enum_b_create = convert_django_field_with_choices(
                field_b, local_registry, input_flag="create"
            )
        finally:
            field_a.model = original_a
            field_b.model = original_b

        assert enum_a_create is not enum_b_create, (
            "Input-flag enums for same-named fields on same-object_name models "
            "must not collide."
        )


# ---------------------------------------------------------------------------
# Defect B — Genuine self-referential OneToOneField silently dropped
# ---------------------------------------------------------------------------


class TestSelfReferentialO2O:
    """PersonWithSpouse.spouse must appear in output and input GraphQL types."""

    def test_self_ref_o2o_output_field_present(self):
        """The 'spouse' field must be present in the DjangoObjectType."""
        local_registry = Registry()

        class PersonType(DjangoObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = local_registry

        field_names = list(PersonType._meta.fields.keys())
        assert "spouse" in field_names, (
            f"'spouse' (self-referential O2O) must appear in PersonType fields. "
            f"Got: {field_names}"
        )

    def test_self_ref_o2o_dynamic_resolver_does_not_return_none(self):
        """The Dynamic field for spouse must not return None when resolved."""
        local_registry = Registry()
        field = PersonWithSpouse._meta.get_field("spouse")

        dynamic = convert_field_to_djangomodel(
            field, registry=local_registry, input_flag=None, nested_field=False
        )

        # Register a PersonType so the registry lookup succeeds.
        class PersonType(DjangoObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = local_registry

        # The Dynamic's inner function must return a non-None graphene Field.
        resolved = dynamic.type()
        assert resolved is not None, (
            "Dynamic resolver for a genuine self-referential O2O must not return "
            "None. The MTI parent_link guard incorrectly fired."
        )

    def test_self_ref_o2o_present_in_create_input_type(self):
        """The spouse field (as an ID) must be present in the create input type."""
        from django_graphex.types import DjangoInputObjectType

        local_registry = Registry()

        class PersonCreateInput(DjangoInputObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = local_registry
                input_for = "create"

        input_field_names = list(PersonCreateInput._meta.fields.keys())
        # In non-nested input types, O2O fields become ID scalars.
        assert "spouse" in input_field_names, (
            f"'spouse' (self-referential O2O) must appear in PersonCreateInput "
            f"fields as an ID. Got: {input_field_names}"
        )

    def test_mti_parent_link_flag_identifies_real_mti_fields(self):
        """parent_link=True correctly identifies MTI auto-generated fields."""
        field = PersonWithSpouse._meta.get_field("spouse")
        # A genuine self-ref O2O must NOT have parent_link=True.
        assert not getattr(field.remote_field, "parent_link", False), (
            "A genuine self-referential O2O must have parent_link=False, "
            "so the MTI guard does NOT skip it."
        )

    # S7 (graphene-removal): the graphene filter-input builder
    # (``filtering/schema.py``) and its ``_choices_enum`` helper were deleted. The
    # model-class enum-keying behavior it tested is the SAME registry keying
    # exercised by the converter tests above (``convert_django_field_with_choices``
    # populates distinct enums per model class); the native filter-input builder
    # (``filtering/native_schema.py``) reuses those registry-keyed enums. The
    # graphene-only ``_choices_enum`` unit test is therefore pruned (its module no
    # longer exists), not ported — the underlying behavior remains covered.
