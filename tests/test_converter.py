# -*- coding: utf-8 -*-
"""Tests for Django field -> GraphQL conversion (native backend).

Phase 7 graphene-removal: the public conversion of a Django model into a GraphQL
OUTPUT type is now performed by the NATIVE output compiler
(``django_graphex.native.output_compiler``). It reads ``model._meta`` directly and
maps each Django scalar field to a graphql-core scalar (CharField->GraphQLString,
DateField->GdxDate, ...). The legacy graphene ``convert_django_field`` SCALAR
dispatchers return a dead-scalar sentinel under ``GDX_BACKEND=native`` (the
graphene scalar descriptor is never read on the native output path), so the OLD
``isinstance(out, graphene.String)`` assertions no longer describe native
behavior. Each scalar test below was CONVERTED to drive the SAME conceptual code
path on native — ``_to_graphql_field`` — and assert the graphql-core scalar it
produces, preserving the original per-field-type coverage.

RELATION conversion (FK / M2M / reverse) is still done by ``convert_django_field``
on both backends (it returns a graphene ``Dynamic`` descriptor that the native
output thunk consumes), so the relation tests keep exercising ``convert_django_field``
unchanged. The pure helpers ``convert_choice_name`` / ``choice_enum_name`` /
``get_choices`` and the choices->Enum conversion are backend-independent and are
likewise exercised through their original entry points.

Run: GDX_BACKEND=native .venv/bin/python -m pytest tests/test_converter.py \
    -q -o addopts=""
"""

import graphene
from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase
from graphql import (
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
)

from django_graphex.converter import (
    convert_choice_name,
    convert_django_field,
    convert_django_field_with_choices,
    get_choices,
)
from django_graphex.native.output_compiler import _to_graphql_field
from django_graphex.native.scalars import (
    GdxDate,
    GdxDateTime,
    GdxJSONString,
    GdxTime,
    GdxUUID,
)

from .models import BasicModel


class _StubRegistry:
    """Minimal registry for ``_to_graphql_field`` (scalars never touch it)."""

    def __init__(self):
        self._compiled = {}

    def get_compiled(self, model_cls):
        return self._compiled.get(model_cls)

    def register_compiled(self, model_cls, gql_type):
        self._compiled[model_cls] = gql_type


def _native_scalar(field):
    """Run the NATIVE scalar conversion for ``field`` and return its scalar.

    Drives ``_to_graphql_field`` (the live native equivalent of the retired
    graphene scalar dispatchers), unwraps ``GraphQLNonNull`` (only the pk is
    non-null on output), and returns the underlying graphql-core scalar.
    """
    field_map = _to_graphql_field(field, _StubRegistry())
    assert len(field_map) == 1, (
        f"native scalar conversion must yield exactly one field, got {field_map!r}"
    )
    gql_field = next(iter(field_map.values()))
    gql_type = gql_field.type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    return gql_type


class TestModel(models.Model):
    """Test model for converter tests."""

    __test__ = False  # ORM fixture, not a pytest test class

    # Different field types to test conversion
    char_field = models.CharField(max_length=100, help_text="Character field")
    text_field = models.TextField(blank=True)
    integer_field = models.IntegerField(default=0)
    float_field = models.FloatField(null=True)
    decimal_field = models.DecimalField(max_digits=10, decimal_places=2)
    boolean_field = models.BooleanField(default=False)
    date_field = models.DateField(null=True, blank=True)
    datetime_field = models.DateTimeField(auto_now_add=True)
    time_field = models.TimeField(null=True)
    email_field = models.EmailField(blank=True)
    url_field = models.URLField(blank=True)
    slug_field = models.SlugField(blank=True)
    uuid_field = models.UUIDField(null=True, blank=True)
    json_field = models.JSONField(null=True, blank=True)

    # Choice field
    CHOICE_A = 1
    CHOICE_B = 2
    CHOICES = (
        (CHOICE_A, "Choice A"),
        (CHOICE_B, "Choice B"),
    )
    choice_field = models.IntegerField(choices=CHOICES, default=CHOICE_A)

    # Foreign key
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)

    # Many to many
    basics = models.ManyToManyField(BasicModel, blank=True)

    class Meta:
        app_label = "tests"


class ConverterTest(TestCase):
    """Test cases for native Django-field -> GraphQL-scalar conversion."""

    def test_convert_char_field(self):
        """CharField -> GraphQLString."""
        field = TestModel._meta.get_field("char_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_text_field(self):
        """TextField -> GraphQLString."""
        field = TestModel._meta.get_field("text_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_integer_field(self):
        """IntegerField -> GraphQLInt."""
        field = TestModel._meta.get_field("integer_field")
        self.assertIs(_native_scalar(field), GraphQLInt)

    def test_convert_float_field(self):
        """FloatField -> GraphQLFloat."""
        field = TestModel._meta.get_field("float_field")
        self.assertIs(_native_scalar(field), GraphQLFloat)

    def test_convert_decimal_field(self):
        """DecimalField -> GraphQLFloat (graphene-django parity, #1508)."""
        field = TestModel._meta.get_field("decimal_field")
        self.assertIs(_native_scalar(field), GraphQLFloat)

    def test_convert_boolean_field(self):
        """BooleanField -> GraphQLBoolean."""
        field = TestModel._meta.get_field("boolean_field")
        self.assertIs(_native_scalar(field), GraphQLBoolean)

    def test_convert_date_field(self):
        """DateField -> GdxDate (renders as the ``CustomDate`` scalar)."""
        field = TestModel._meta.get_field("date_field")
        self.assertIs(_native_scalar(field), GdxDate)

    def test_convert_datetime_field(self):
        """DateTimeField -> GdxDateTime (renders as ``CustomDateTime``)."""
        field = TestModel._meta.get_field("datetime_field")
        self.assertIs(_native_scalar(field), GdxDateTime)

    def test_convert_time_field(self):
        """TimeField -> GdxTime (renders as ``CustomTime``)."""
        field = TestModel._meta.get_field("time_field")
        self.assertIs(_native_scalar(field), GdxTime)

    def test_convert_email_field(self):
        """EmailField -> GraphQLString."""
        field = TestModel._meta.get_field("email_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_url_field(self):
        """URLField -> GraphQLString."""
        field = TestModel._meta.get_field("url_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_slug_field(self):
        """SlugField -> GraphQLString."""
        field = TestModel._meta.get_field("slug_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_uuid_field(self):
        """UUIDField -> GdxUUID (renders as the ``UUID`` scalar)."""
        field = TestModel._meta.get_field("uuid_field")
        self.assertIs(_native_scalar(field), GdxUUID)

    def test_convert_json_field(self):
        """JSONField -> GdxJSONString (renders as the ``JSONString`` scalar)."""
        field = TestModel._meta.get_field("json_field")
        self.assertIs(_native_scalar(field), GdxJSONString)

    def test_convert_choice_field(self):
        """Test field with choices conversion."""
        field = TestModel._meta.get_field("choice_field")

        # Need to mock a registry for choices
        from django_graphex.registry import get_global_registry

        registry = get_global_registry()

        graphql_field = convert_django_field_with_choices(field, registry=registry)

        # A choices field converts to a graphene Enum carrying both choices.
        self.assertIsInstance(graphql_field, graphene.Enum)
        self.assertEqual(
            set(graphql_field._meta.enum.__members__), {"CHOICE_A", "CHOICE_B"}
        )

    def test_convert_foreign_key_field(self):
        """Test ForeignKey field conversion (S-rel-2: native OUTPUT marker)."""
        from django_graphex.converter import _NATIVE_BACKEND
        from django_graphex.native.descriptors import NativeRelationField

        field = TestModel._meta.get_field("user")
        graphql_field = convert_django_field(field)

        if _NATIVE_BACKEND:
            # S-rel-2: on the native OUTPUT path a to-ONE ForeignKey converts to a
            # graphene-free ``NativeRelationField`` presence/ordering marker (the
            # native output type is built from ``model._meta`` directly; the old
            # graphene ``Dynamic`` was dead weight that only pinned graphene).
            self.assertIsInstance(graphql_field, NativeRelationField)
        else:
            # The graphene backend is UNCHANGED: still a graphene ``Dynamic``.
            self.assertIsInstance(graphql_field, graphene.Dynamic)

    def test_convert_many_to_many_field(self):
        """Test ManyToManyField conversion (S-rel-3: native OUTPUT marker)."""
        from django_graphex.converter import _NATIVE_BACKEND
        from django_graphex.native.descriptors import NativeRelationField

        field = TestModel._meta.get_field("basics")
        graphql_field = convert_django_field(field)

        if _NATIVE_BACKEND:
            # S-rel-3: on the native OUTPUT path a to-MANY ManyToManyField converts
            # to a graphene-free ``NativeRelationField`` presence/ordering marker
            # (the native output type builds the ``<Model>ListType`` results/
            # totalCount container from ``model._meta`` directly; the old graphene
            # ``Dynamic`` was dead weight that only pinned graphene).
            self.assertIsInstance(graphql_field, NativeRelationField)
        else:
            # The graphene backend is UNCHANGED: still a graphene ``Dynamic``.
            self.assertIsInstance(graphql_field, graphene.Dynamic)

    def test_convert_choice_name(self):
        """Test choice name conversion."""
        # Test various choice name conversions
        self.assertEqual(convert_choice_name("CHOICE_A"), "CHOICE_A")
        self.assertEqual(
            convert_choice_name("choice-with-dashes"), "CHOICE_WITH_DASHES"
        )
        self.assertEqual(
            convert_choice_name("choice with spaces"), "CHOICE_WITH_SPACES"
        )

    def test_get_choices(self):
        """Test choices extraction from field."""
        field = TestModel._meta.get_field("choice_field")
        choices = list(get_choices(field.choices))

        self.assertIsInstance(choices, list)
        self.assertEqual(len(choices), 2)
        # get_choices returns (name, value, description) tuples
        choice_values = [(choice[1], choice[2]) for choice in choices]
        self.assertIn((1, "Choice A"), choice_values)
        self.assertIn((2, "Choice B"), choice_values)

    def test_nullable_field_conversion(self):
        """A nullable scalar field is rendered nullable (not wrapped in NonNull).

        On the native OUTPUT path every non-pk scalar is nullable
        (graphene-django #1494 parity), so ``_to_graphql_field`` returns the bare
        scalar with no ``GraphQLNonNull`` wrapper.
        """
        field = TestModel._meta.get_field("float_field")
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        self.assertNotIsInstance(gql_type, GraphQLNonNull)
        self.assertIs(gql_type, GraphQLFloat)

    def test_required_field_conversion(self):
        """A required (non-pk) CharField renders as a plain nullable String.

        Output fields are intentionally NOT wrapped in ``GraphQLNonNull`` on the
        native path (only the pk is non-null on output, graphene-django #1494
        parity); requiredness is enforced by the input/serializer path, not the
        output type.
        """
        field = TestModel._meta.get_field("char_field")
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        self.assertIs(gql_type, GraphQLString)
        self.assertNotIsInstance(gql_type, GraphQLNonNull)

    def test_field_with_default_conversion(self):
        """A field with a default still converts by its type (IntegerField->Int)."""
        field = TestModel._meta.get_field("integer_field")
        self.assertIs(_native_scalar(field), GraphQLInt)

    def test_auto_field_conversion(self):
        """The model pk (AutoField) converts to a non-null GraphQL ID (``id: ID!``)."""
        field = TestModel._meta.get_field("id")  # Auto-created id field
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        # The pk is the ONLY non-null OUTPUT scalar.
        self.assertIsInstance(gql_type, GraphQLNonNull)
        self.assertIs(gql_type.of_type, GraphQLID)


class ConverterUtilsTest(TestCase):
    """Test cases for converter utility functions (backend-independent)."""

    def test_convert_choices_with_enum(self):
        """Test conversion of choices creates proper enum."""
        field = TestModel._meta.get_field("choice_field")

        from django_graphex.registry import get_global_registry

        registry = get_global_registry()

        graphql_field = convert_django_field_with_choices(field, registry=registry)

        # An integer choices field converts to a graphene Enum whose members
        # mirror the declared choice labels.
        self.assertIsInstance(graphql_field, graphene.Enum)
        self.assertEqual(
            set(graphql_field._meta.enum.__members__), {"CHOICE_A", "CHOICE_B"}
        )

    def test_choices_extraction(self):
        """Test choices extraction from different field types."""
        # Test with integer choices
        field = TestModel._meta.get_field("choice_field")
        choices = list(get_choices(field.choices))

        self.assertEqual(len(choices), 2)
        # get_choices returns (name, value, description) tuples
        choice_values = [(choice[1], choice[2]) for choice in choices]
        self.assertEqual(choice_values[0], (1, "Choice A"))
        self.assertEqual(choice_values[1], (2, "Choice B"))

    def test_choice_name_normalization(self):
        """Test choice name normalization for GraphQL."""
        # Test various name formats
        self.assertEqual(convert_choice_name("simple"), "SIMPLE")
        self.assertEqual(convert_choice_name("ALREADY_UPPER"), "ALREADY_UPPER")
        self.assertEqual(convert_choice_name("with-dashes"), "WITH_DASHES")
        self.assertEqual(convert_choice_name("with spaces"), "WITH_SPACES")
        self.assertEqual(convert_choice_name("mixed_Case-Format"), "MIXED_CASE_FORMAT")


class FieldConversionIntegrationTest(TestCase):
    """Integration tests for field conversion."""

    def test_model_to_graphql_type_conversion(self):
        """Test complete model to GraphQL OUTPUT type conversion.

        On native, the model -> GraphQL OUTPUT type is built by the native output
        compiler and exposed as ``_meta.graphql_output_type`` (a graphql-core
        ``GraphQLObjectType``). Assert it carries the converted fields.
        """
        from django_graphex import DjangoObjectType

        class TestModelType(DjangoObjectType):
            class Meta:
                model = TestModel

        # Should be able to create the type without errors
        type_instance = TestModelType()
        self.assertIsNotNone(type_instance)

        # The compiled native output type carries the converted fields.
        gql_type = TestModelType._meta.graphql_output_type
        fields = gql_type.fields
        self.assertGreater(len(fields), 10)  # Should have many fields

        # Check specific field conversions (camelCase wire names).
        self.assertIn("charField", fields)
        self.assertIn("choiceField", fields)
        self.assertIn("user", fields)

    def test_input_type_conversion(self):
        """Test model to input type conversion.

        On native the INPUT type is compiled to a graphql-core
        ``GraphQLInputObjectType`` exposed via ``_meta.graphql_input_type``.
        """
        from django_graphex import DjangoInputObjectType

        class TestModelInput(DjangoInputObjectType):
            class Meta:
                model = TestModel

        # Should be able to create input type
        input_type = TestModelInput()
        self.assertIsNotNone(input_type)

        # The compiled native input type carries the converted fields.
        fields = TestModelInput._meta.graphql_input_type.fields
        self.assertIn("charField", fields)

    def test_relationship_field_conversion(self):
        """Test relationship field conversion."""
        from django_graphex.converter import _NATIVE_BACKEND
        from django_graphex.native.descriptors import NativeRelationField

        # Test that foreign keys and m2m fields are converted correctly
        user_field = TestModel._meta.get_field("user")
        basics_field = TestModel._meta.get_field("basics")

        user_graphql_field = convert_django_field(user_field)
        basics_graphql_field = convert_django_field(basics_field)

        if _NATIVE_BACKEND:
            # S-rel-2: User field (to-ONE FK) converts to a graphene-free
            # ``NativeRelationField`` marker on the native OUTPUT path.
            self.assertIsInstance(user_graphql_field, NativeRelationField)
            # S-rel-3: Basics field (to-MANY M2M) ALSO converts to a graphene-free
            # ``NativeRelationField`` marker on the native OUTPUT path (the native
            # output builds the ``<Model>ListType`` container from ``model._meta``).
            self.assertIsInstance(basics_graphql_field, NativeRelationField)
        else:
            # The graphene backend is UNCHANGED: both stay graphene ``Dynamic``.
            self.assertIsInstance(user_graphql_field, graphene.Dynamic)
            self.assertIsInstance(basics_graphql_field, graphene.Dynamic)
