# -*- coding: utf-8 -*-
"""Tests for issue #52: enum registry key collision + self-referential O2O.

RED phase: these tests MUST FAIL before the fix is applied, then pass after.

Defect A — Enum registry key collision for same-class-name models across apps:
  Two models sharing the same object_name ("Item") but with *different* choices
  on a same-named field ("status") must produce two DISTINCT enum types, not
  collide into one.

Defect B — Genuine self-referential OneToOneField silently dropped:
  A model with "spouse = OneToOneField('self', ...)" must have that field present
  in both the output GraphQL type and the create/update input types.
"""

from __future__ import annotations

from django_graphex.converter import (
    build_choices_enum_type,
    convert_field_to_djangomodel,
)
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

from .models import EnumCollisionItemA, EnumCollisionItemB, PersonWithSpouse

# ---------------------------------------------------------------------------
# Defect A — Enum key collision
# ---------------------------------------------------------------------------


class TestEnumKeyCollision:
    """Two models sharing object_name but different choices must not collide.

    Covers both the model-instance-patched simulation and the direct
    distinct-model-class case.
    """

    def test_same_object_name_different_app_produces_distinct_enums(self) -> None:
        """Two models sharing object_name "Item" with divergent choices must
        produce two distinct enums.

        Simulates the cross-app collision: two models both called "Item" but
        with divergent status choices must not collide into a single enum.
        """
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

            # S-input-5: both the OUTPUT and the INPUT converter paths now return
            # the dead-scalar sentinel (graphene-free). The choices enum is built +
            # KEYED by the native canonical builder ``build_choices_enum_type``
            # (keyed by ``(app_label, object_name, field_name)`` like the converter
            # was), so the cross-app collision contract is asserted on it.
            enum_a = build_choices_enum_type(field_a, local_registry)
            enum_b = build_choices_enum_type(field_b, local_registry)
        finally:
            field_a.model = original_a
            field_b.model = original_b

        # The two enums must be distinct objects.
        assert enum_a is not enum_b, (
            "Two models sharing object_name 'Item' but with different choices on "
            "'status' must NOT share the same enum type."
        )

        # Each enum must carry its own members.
        members_a = set(enum_a.values.keys())
        members_b = set(enum_b.values.keys())

        assert members_a == {"A", "B"}, f"ItemA enum members wrong: {members_a}"
        assert members_b == {"X", "Y", "Z"}, f"ItemB enum members wrong: {members_b}"

    def test_distinct_model_classes_produce_independent_enums(self) -> None:
        """Using distinct model classes, each field must produce its own enum.

        S-input-5: both the OUTPUT and INPUT converter paths return the dead-scalar
        sentinel (graphene-free); the native "build_choices_enum_type" builds +
        keys the enum from "model._meta".
        """
        local_registry = Registry()

        field_a = EnumCollisionItemA._meta.get_field("status")
        field_b = EnumCollisionItemB._meta.get_field("status")

        enum_a = build_choices_enum_type(field_a, local_registry)
        enum_b = build_choices_enum_type(field_b, local_registry)

        assert enum_a is not enum_b

        members_a = set(enum_a.values.keys())
        members_b = set(enum_b.values.keys())

        assert members_a == {"A", "B"}
        assert members_b == {"X", "Y", "Z"}

    def test_input_flag_enums_keyed_independently_per_model_class(self) -> None:
        """The same fix must apply to the native enums per model class.

        S-input-5: the INPUT choices surface now uses the SHARED native enum (the
        same "build_choices_enum_type" slot the OUTPUT path uses), so the
        per-model-class keying contract is asserted on that builder.
        """
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

            enum_a_create = build_choices_enum_type(field_a, local_registry)
            enum_b_create = build_choices_enum_type(field_b, local_registry)
        finally:
            field_a.model = original_a
            field_b.model = original_b

        assert enum_a_create is not enum_b_create, (
            "Native enums for same-named fields on same-object_name models "
            "must not collide."
        )


# ---------------------------------------------------------------------------
# Defect B — Genuine self-referential OneToOneField silently dropped
# ---------------------------------------------------------------------------


class TestSelfReferentialO2O:
    """PersonWithSpouse.spouse must appear in output and input GraphQL types.

    Also covers the MTI parent_link guard that must not misfire on it.
    """

    def test_self_ref_o2o_output_field_present(self) -> None:
        """The "spouse" field must be present in the DjangoObjectType.

        If this breaks, a genuine self-referential OneToOneField would be
        silently dropped from the generated GraphQL output type.
        """
        local_registry = Registry()

        class PersonType(DjangoObjectType):
            """Local DjangoObjectType wrapping PersonWithSpouse for the assertion."""

            class Meta:
                model = PersonWithSpouse
                registry = local_registry

        field_names = list(PersonType._meta.fields.keys())
        assert "spouse" in field_names, (
            f"'spouse' (self-referential O2O) must appear in PersonType fields. "
            f"Got: {field_names}"
        )

    def test_self_ref_o2o_output_converter_does_not_drop(self) -> None:
        """The self-ref O2O OUTPUT converter must never silently drop the field.

        S-rel-2 retired graphene on the to-ONE relation OUTPUT path: a genuine
        self-referential OneToOne now converts to a graphene-free
        "NativeRelationField" presence/ordering marker (the issue #52 trap is
        the MTI parent_link guard incorrectly firing on a genuine self-ref O2O,
        which would drop the field).
        """
        from django_graphex.converter import _DEAD_SCALAR
        from django_graphex.core.descriptors import NativeRelationField

        local_registry = Registry()
        field = PersonWithSpouse._meta.get_field("spouse")

        # Register a PersonType so the registry lookup can succeed.
        class PersonType(DjangoObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = local_registry

        converted = convert_field_to_djangomodel(
            field, registry=local_registry, input_flag=None, nested_field=False
        )

        assert isinstance(converted, NativeRelationField), (
            "self-ref O2O OUTPUT must return a graphene-free "
            f"NativeRelationField marker (S-rel-2); got {converted!r}"
        )
        assert converted is not None and converted is not _DEAD_SCALAR, (
            "the self-ref O2O marker must NEVER be None / dead-scalar — that "
            "is the issue #52 silent-drop trap (parent_link guard firing)."
        )

    def test_self_ref_o2o_present_in_create_input_type(self) -> None:
        """The spouse field (as an ID) must be present in the create input type.

        If this breaks, a genuine self-referential OneToOneField would be
        silently dropped from the generated create-input GraphQL type.
        """
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

    def test_mti_parent_link_flag_identifies_real_mti_fields(self) -> None:
        """ "parent_link=True" must correctly identify MTI auto-generated fields.

        If this breaks, the MTI parent_link guard could misclassify a genuine
        self-referential O2O as an MTI-generated field and drop it.
        """
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
