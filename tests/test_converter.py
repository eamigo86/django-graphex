# -*- coding: utf-8 -*-
"""Tests for Django field -> GraphQL conversion (native backend).

Phase 7 graphene-removal: the public conversion of a Django model into a GraphQL
OUTPUT type is now performed by the NATIVE output compiler
("django_graphex.core.output_compiler"). It reads "model._meta" directly and
maps each Django scalar field to a graphql-core scalar (CharField->GraphQLString,
DateField->GdxDate, ...). The legacy graphene "convert_django_field" SCALAR
dispatchers return a dead-scalar sentinel (the
graphene scalar descriptor is never read on the native output path), so the OLD
"isinstance(out, graphene.String)" assertions no longer describe native
behavior. Each scalar test below was CONVERTED to drive the SAME conceptual code
path on native — "_to_graphql_field" — and assert the graphql-core scalar it
produces, preserving the original per-field-type coverage.

RELATION conversion (FK / M2M / reverse) is performed by "convert_django_field",
which now returns a graphene-free "NativeRelationField" presence/ordering marker
that the native output thunk consumes (the marker keeps the field in
"_meta.fields" so the native compiler can build the output field from
"model._meta" directly). The pure helpers "convert_choice_name" /
"choice_enum_name" / "get_choices" and the choices->enum conversion are
backend-independent and are exercised through their original entry points.

Run: .venv/bin/python -m pytest tests/test_converter.py -q -o addopts=""
"""

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
from django_graphex.core.output_compiler import _to_graphql_field
from django_graphex.core.scalars import (
    GdxDate,
    GdxDateTime,
    GdxJSON,
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
    """A model exercising one field of every scalar/relation type under test.

    Used as the fixture model for the field->GraphQL conversion assertions
    below; not itself a test case.
    """

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
        """Register this ORM fixture under the "tests" app label.

        Required so Django can resolve the model without a real installed
        app owning it.
        """

        app_label = "tests"


class ConverterTest(TestCase):
    """Test cases for native Django-field -> GraphQL-scalar conversion.

    Covers every scalar/relation field type on "TestModel", asserting each
    converts to the expected graphql-core type on the native output path.
    """

    def test_convert_char_field(self) -> None:
        """CharField must convert to GraphQLString on the native output path.

        Ships broken if the native scalar dispatcher stops recognizing
        CharField and falls back to the wrong GraphQL scalar.
        """
        field = TestModel._meta.get_field("char_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_text_field(self) -> None:
        """TextField must convert to GraphQLString on the native output path.

        Ships broken if TextField loses its GraphQLString mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("text_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_integer_field(self) -> None:
        """IntegerField must convert to GraphQLInt on the native output path.

        Ships broken if IntegerField loses its GraphQLInt mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("integer_field")
        self.assertIs(_native_scalar(field), GraphQLInt)

    def test_convert_float_field(self) -> None:
        """FloatField must convert to GraphQLFloat on the native output path.

        Ships broken if FloatField loses its GraphQLFloat mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("float_field")
        self.assertIs(_native_scalar(field), GraphQLFloat)

    def test_convert_decimal_field(self) -> None:
        """DecimalField must convert to GraphQLFloat, matching graphene-django #1508.

        Ships broken if DecimalField stops mapping to GraphQLFloat, breaking
        parity with the historical graphene-django behavior.
        """
        field = TestModel._meta.get_field("decimal_field")
        self.assertIs(_native_scalar(field), GraphQLFloat)

    def test_convert_boolean_field(self) -> None:
        """BooleanField must convert to GraphQLBoolean on the native output path.

        Ships broken if BooleanField loses its GraphQLBoolean mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("boolean_field")
        self.assertIs(_native_scalar(field), GraphQLBoolean)

    def test_convert_date_field(self) -> None:
        """DateField must convert to GdxDate, which renders as the "CustomDate" scalar.

        Ships broken if DateField stops mapping to the custom GdxDate scalar
        on the native output path.
        """
        field = TestModel._meta.get_field("date_field")
        self.assertIs(_native_scalar(field), GdxDate)

    def test_convert_datetime_field(self) -> None:
        """DateTimeField must convert to GdxDateTime, rendering as "CustomDateTime".

        Ships broken if DateTimeField stops mapping to the custom GdxDateTime
        scalar on the native output path.
        """
        field = TestModel._meta.get_field("datetime_field")
        self.assertIs(_native_scalar(field), GdxDateTime)

    def test_convert_time_field(self) -> None:
        """TimeField must convert to GdxTime, which renders as the "CustomTime" scalar.

        Ships broken if TimeField stops mapping to the custom GdxTime scalar
        on the native output path.
        """
        field = TestModel._meta.get_field("time_field")
        self.assertIs(_native_scalar(field), GdxTime)

    def test_convert_email_field(self) -> None:
        """EmailField must convert to GraphQLString on the native output path.

        Ships broken if EmailField loses its GraphQLString mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("email_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_url_field(self) -> None:
        """URLField must convert to GraphQLString on the native output path.

        Ships broken if URLField loses its GraphQLString mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("url_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_slug_field(self) -> None:
        """SlugField must convert to GraphQLString on the native output path.

        Ships broken if SlugField loses its GraphQLString mapping in the
        native scalar dispatcher.
        """
        field = TestModel._meta.get_field("slug_field")
        self.assertIs(_native_scalar(field), GraphQLString)

    def test_convert_uuid_field(self) -> None:
        """UUIDField must convert to GdxUUID, which renders as the "UUID" scalar.

        Ships broken if UUIDField stops mapping to the custom GdxUUID scalar
        on the native output path.
        """
        field = TestModel._meta.get_field("uuid_field")
        self.assertIs(_native_scalar(field), GdxUUID)

    def test_convert_json_field(self) -> None:
        """JSONField must convert to GdxJSON (v2 RAW-JSON default), rendering as "JSON".

        Ships broken if JSONField stops mapping to the custom GdxJSON scalar
        on the native output path.
        """
        field = TestModel._meta.get_field("json_field")
        self.assertIs(_native_scalar(field), GdxJSON)

    def test_convert_choice_field(self) -> None:
        """A choices field must convert to the native OUTPUT dead-scalar sentinel.

        S-enum-2: the native output compiler renders the enum from
        "model._meta" directly, so the field-conversion path only needs to
        return the sentinel rather than a graphene Enum descriptor.
        """
        from django_graphex.converter import _DEAD_SCALAR

        field = TestModel._meta.get_field("choice_field")

        # Need to mock a registry for choices
        from django_graphex.registry import get_global_registry

        registry = get_global_registry()

        graphql_field = convert_django_field_with_choices(field, registry=registry)

        # S-enum-2: on the native OUTPUT path (input_flag is None) a choices
        # field returns the dead-scalar sentinel — the native output compiler
        # renders the enum from ``model._meta`` directly (S-enum-1); the old
        # graphene ``Enum`` descriptor was dead weight that only pinned graphene
        # at class-definition time.
        self.assertIs(graphql_field, _DEAD_SCALAR)

    def test_convert_foreign_key_field(self) -> None:
        """A to-ONE ForeignKey must convert to a NativeRelationField marker.

        S-rel-2: on the native OUTPUT path the conversion returns a
        graphene-free "NativeRelationField" presence/ordering marker; the
        native output type itself is built from "model._meta" directly.
        """
        from django_graphex.core.descriptors import NativeRelationField

        field = TestModel._meta.get_field("user")
        graphql_field = convert_django_field(field)

        # S-rel-2: on the native OUTPUT path a to-ONE ForeignKey converts to a
        # graphene-free ``NativeRelationField`` presence/ordering marker (the
        # native output type is built from ``model._meta`` directly; the old
        # graphene ``Dynamic`` was dead weight that only pinned graphene).
        self.assertIsInstance(graphql_field, NativeRelationField)

    def test_convert_many_to_many_field(self) -> None:
        """A to-MANY ManyToManyField must convert to a NativeRelationField marker.

        S-rel-3: on the native OUTPUT path the conversion returns a
        graphene-free "NativeRelationField" presence/ordering marker; the
        native output builds the "<Model>ListType" results/totalCount
        container from "model._meta" directly.
        """
        from django_graphex.core.descriptors import NativeRelationField

        field = TestModel._meta.get_field("basics")
        graphql_field = convert_django_field(field)

        # S-rel-3: on the native OUTPUT path a to-MANY ManyToManyField converts
        # to a graphene-free ``NativeRelationField`` presence/ordering marker
        # (the native output type builds the ``<Model>ListType`` results/
        # totalCount container from ``model._meta`` directly; the old graphene
        # ``Dynamic`` was dead weight that only pinned graphene).
        self.assertIsInstance(graphql_field, NativeRelationField)

    def test_convert_choice_name(self) -> None:
        """convert_choice_name must uppercase and normalize dashes/spaces to underscores.

        Ships broken if generated enum value names stop matching GraphQL's
        allowed identifier charset or lose their uppercase convention.
        """
        # Test various choice name conversions
        self.assertEqual(convert_choice_name("CHOICE_A"), "CHOICE_A")
        self.assertEqual(
            convert_choice_name("choice-with-dashes"), "CHOICE_WITH_DASHES"
        )
        self.assertEqual(
            convert_choice_name("choice with spaces"), "CHOICE_WITH_SPACES"
        )

    def test_get_choices(self) -> None:
        """get_choices must yield (name, value, description) tuples for each choice.

        Ships broken if the choice enum builder receives malformed tuples and
        produces an incomplete or mis-ordered GraphQL enum.
        """
        field = TestModel._meta.get_field("choice_field")
        choices = list(get_choices(field.choices))

        self.assertIsInstance(choices, list)
        self.assertEqual(len(choices), 2)
        # get_choices returns (name, value, description) tuples
        choice_values = [(choice[1], choice[2]) for choice in choices]
        self.assertIn((1, "Choice A"), choice_values)
        self.assertIn((2, "Choice B"), choice_values)

    def test_nullable_field_conversion(self) -> None:
        """A nullable scalar field must render nullable, not wrapped in NonNull.

        On the native OUTPUT path every non-pk scalar is nullable
        (graphene-django #1494 parity), so "_to_graphql_field" returns the bare
        scalar with no "GraphQLNonNull" wrapper.
        """
        field = TestModel._meta.get_field("float_field")
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        self.assertNotIsInstance(gql_type, GraphQLNonNull)
        self.assertIs(gql_type, GraphQLFloat)

    def test_required_field_conversion(self) -> None:
        """A required (non-pk) CharField must render as a plain nullable String.

        Output fields are intentionally NOT wrapped in "GraphQLNonNull" on the
        native path (only the pk is non-null on output, graphene-django #1494
        parity); requiredness is enforced by the input/serializer path, not the
        output type.
        """
        field = TestModel._meta.get_field("char_field")
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        self.assertIs(gql_type, GraphQLString)
        self.assertNotIsInstance(gql_type, GraphQLNonNull)

    def test_field_with_default_conversion(self) -> None:
        """A field with a default must still convert by its underlying type.

        Confirms the "default" attribute does not influence the resolved
        scalar type (IntegerField still maps to GraphQLInt).
        """
        field = TestModel._meta.get_field("integer_field")
        self.assertIs(_native_scalar(field), GraphQLInt)

    def test_auto_field_conversion(self) -> None:
        """The model pk (AutoField) converts to a non-null GraphQL ID ("id: ID!").

        Ships broken if the pk field stops being wrapped in GraphQLNonNull,
        letting clients query a nullable id on the output type.
        """
        field = TestModel._meta.get_field("id")  # Auto-created id field
        field_map = _to_graphql_field(field, _StubRegistry())
        gql_type = next(iter(field_map.values())).type

        # The pk is the ONLY non-null OUTPUT scalar.
        self.assertIsInstance(gql_type, GraphQLNonNull)
        self.assertIs(gql_type.of_type, GraphQLID)


class ConverterUtilsTest(TestCase):
    """Test cases for converter utility functions (backend-independent).

    Covers choice-name normalization and choice-tuple extraction, which are
    shared by the output, filter-input, and mutation-input paths.
    """

    def test_convert_choices_with_enum(self) -> None:
        """Test conversion of choices creates proper enum.

        S-enum-2 (OUTPUT) + S-input-5 (INPUT) retired graphene on the choices
        converter path: on native it returns the dead-scalar sentinel for BOTH
        output and input, and the choices enum is built by the native canonical
        builder "build_choices_enum_type" (a graphql-core "GraphQLEnumType"
        shared by the output + filter-input + mutation-input paths).
        """
        field = TestModel._meta.get_field("choice_field")

        from graphql import GraphQLEnumType

        from django_graphex.converter import (
            _DEAD_SCALAR,
            build_choices_enum_type,
        )
        from django_graphex.registry import Registry

        for input_flag in (None, "create", "update"):
            out = convert_django_field_with_choices(
                field, registry=Registry(), input_flag=input_flag
            )
            self.assertIs(out, _DEAD_SCALAR)
        enum = build_choices_enum_type(field, Registry())
        self.assertIsInstance(enum, GraphQLEnumType)
        self.assertEqual(set(enum.values.keys()), {"CHOICE_A", "CHOICE_B"})

    def test_choices_extraction(self) -> None:
        """Test choices extraction from different field types.

        Ships broken if integer-keyed choices stop yielding the expected
        (value, description) pairs in declaration order.
        """
        # Test with integer choices
        field = TestModel._meta.get_field("choice_field")
        choices = list(get_choices(field.choices))

        self.assertEqual(len(choices), 2)
        # get_choices returns (name, value, description) tuples
        choice_values = [(choice[1], choice[2]) for choice in choices]
        self.assertEqual(choice_values[0], (1, "Choice A"))
        self.assertEqual(choice_values[1], (2, "Choice B"))

    def test_choice_name_normalization(self) -> None:
        """Test choice name normalization for GraphQL.

        Ships broken if mixed-case, dashed, or spaced choice names stop
        normalizing to valid upper-snake-case GraphQL enum value names.
        """
        # Test various name formats
        self.assertEqual(convert_choice_name("simple"), "SIMPLE")
        self.assertEqual(convert_choice_name("ALREADY_UPPER"), "ALREADY_UPPER")
        self.assertEqual(convert_choice_name("with-dashes"), "WITH_DASHES")
        self.assertEqual(convert_choice_name("with spaces"), "WITH_SPACES")
        self.assertEqual(convert_choice_name("mixed_Case-Format"), "MIXED_CASE_FORMAT")


class FieldConversionIntegrationTest(TestCase):
    """Integration tests for field conversion.

    Exercises the full model-to-GraphQL-type compilation path end to end,
    beyond the single-field unit assertions in "ConverterTest".
    """

    def test_model_to_graphql_type_conversion(self) -> None:
        """Test complete model to GraphQL OUTPUT type conversion.

        On native, the model -> GraphQL OUTPUT type is built by the native output
        compiler and exposed as "_meta.graphql_output_type" (a graphql-core
        "GraphQLObjectType"). Assert it carries the converted fields.
        """
        from django_graphex.types import DjangoObjectType

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

    def test_input_type_conversion(self) -> None:
        """Test model to input type conversion.

        On native the INPUT type is compiled to a graphql-core
        "GraphQLInputObjectType" exposed via "_meta.graphql_input_type".
        """
        from django_graphex.types import DjangoInputObjectType

        class TestModelInput(DjangoInputObjectType):
            class Meta:
                model = TestModel

        # Should be able to create input type
        input_type = TestModelInput()
        self.assertIsNotNone(input_type)

        # The compiled native input type carries the converted fields.
        fields = TestModelInput._meta.graphql_input_type.fields
        self.assertIn("charField", fields)

    def test_relationship_field_conversion(self) -> None:
        """Test relationship field conversion.

        Ships broken if to-one or to-many relation fields stop converting to
        the graphene-free NativeRelationField marker the native output
        compiler expects.
        """
        from django_graphex.core.descriptors import NativeRelationField

        # Test that foreign keys and m2m fields are converted correctly
        user_field = TestModel._meta.get_field("user")
        basics_field = TestModel._meta.get_field("basics")

        user_graphql_field = convert_django_field(user_field)
        basics_graphql_field = convert_django_field(basics_field)

        # S-rel-2: User field (to-ONE FK) converts to a graphene-free
        # "NativeRelationField" marker on the native OUTPUT path.
        self.assertIsInstance(user_graphql_field, NativeRelationField)
        # S-rel-3: Basics field (to-MANY M2M) ALSO converts to a graphene-free
        # "NativeRelationField" marker on the native OUTPUT path (the native
        # output builds the "<Model>ListType" container from "model._meta").
        self.assertIsInstance(basics_graphql_field, NativeRelationField)
