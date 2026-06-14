# -*- coding: utf-8 -*-
"""Tests for django_graphex.types module."""

import graphene
from django.test import TestCase

from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoModelType,
)

from .models import BasicModel


class BasicListType(DjangoListObjectType):
    """Test list type."""

    class Meta:
        model = BasicModel
        pagination = LimitOffsetGraphqlPagination()


class BasicInputType(DjangoInputObjectType):
    """Test input type."""

    class Meta:
        model = BasicModel


class BasicSerializerType(DjangoModelType):
    """Test serializer type."""

    class Meta:
        model = BasicModel


class TypesTest(TestCase):
    """Test cases for type classes."""

    def setUp(self):
        """Set up test data."""
        self.basic_model = BasicModel.objects.create(text="Test Model")

    def test_django_list_object_type_creation(self):
        """Test DjangoListObjectType creation."""
        list_type = BasicListType()
        self.assertIsNotNone(list_type)

        # Should carry the configured pagination strategy on its Meta.
        self.assertIsInstance(list_type._meta.pagination, LimitOffsetGraphqlPagination)

    def test_django_input_object_type_creation(self):
        """Test DjangoInputObjectType creation."""
        input_type = BasicInputType()
        self.assertIsNotNone(input_type)

        # Should be based on the model
        self.assertEqual(input_type._meta.model, BasicModel)

    def test_input_for_accepts_valid_operation(self):
        """A valid input_for is normalized and stored on _meta."""

        class UpdateInput(DjangoInputObjectType):
            class Meta:
                model = BasicModel
                input_for = "Update"  # case-insensitive

        self.assertEqual(UpdateInput._meta.input_for, "update")

    def test_input_for_rejects_invalid_operation(self):
        """An unknown input_for value fails fast with an assertion error."""
        with self.assertRaises(AssertionError):

            class BadInput(DjangoInputObjectType):
                class Meta:
                    model = BasicModel
                    input_for = "frobnicate"

    def test_django_serializer_type_creation(self):
        """Test DjangoModelType creation."""
        serializer_type = BasicSerializerType()
        self.assertIsNotNone(serializer_type)

        # Should be based on the model
        self.assertEqual(serializer_type._meta.model, BasicModel)

    def test_list_type_fields(self):
        """Test list type fields."""
        # The uniform list shape always exposes results + totalCount.
        fields = BasicListType._meta.fields
        self.assertIsInstance(fields, dict)
        # `count` is exposed in the schema as `totalCount`.
        self.assertIn("results", fields)
        self.assertIn("count", fields)

    def test_input_type_fields(self):
        """Test input type fields."""
        # The input type mirrors the model's concrete fields.
        fields = BasicInputType._meta.fields
        self.assertIsInstance(fields, dict)
        self.assertIn("text", fields)

    def test_serializer_type_query_fields(self):
        """Test serializer type query field creation."""
        retrieve_field, list_field = BasicSerializerType.QueryFields()
        self.assertIsInstance(retrieve_field, graphene.Field)
        self.assertIsInstance(list_field, graphene.Field)

    def test_serializer_type_mutation_fields(self):
        """Test serializer type mutation field creation.

        Native mutation schema assembly is delivered in Phase 5 / WU9: under
        ``GDX_BACKEND=native`` ``CreateField``/``UpdateField``/``DeleteField``
        return graphql-core ``GraphQLField`` objects (NOT graphene ``Field``)
        whose ``.type`` is the canonical compiled output type and whose ``.args``
        are graphql-core ``GraphQLArgument`` instances — the genuine native
        mutation field shape. (The honest skip this replaces deferred exactly
        this assertion to Phase 5; specs/2.0-migration-plan.md.)
        """
        import os

        # MutationFields() returns (create, delete, update) — keep this order so
        # the per-field assertions below reference the correct operation.
        (
            create_field,
            delete_field,
            update_field,
        ) = BasicSerializerType.MutationFields()

        if os.environ.get("GDX_BACKEND", "graphene") == "native":
            from graphene.utils.str_converters import to_camel_case
            from graphql import (
                GraphQLArgument,
                GraphQLField,
                GraphQLNonNull,
                GraphQLObjectType,
            )

            from django_graphex.native.schema_compiler import (
                _compile_plain_object_type,
            )

            for field in (create_field, update_field, delete_field):
                # Native: a raw graphql-core GraphQLField, NOT a graphene.Field.
                self.assertIsInstance(field, GraphQLField)
                self.assertNotIsInstance(field, graphene.Field)
                # Its args are graphql-core GraphQLArgument instances (graphene's
                # to_arguments() would have rejected these at construction — the
                # exact reason the original assertion was skipped pre-Phase-5).
                for arg in field.args.values():
                    self.assertIsInstance(arg, GraphQLArgument)
                # Its output type is the compiled mutation PAYLOAD wrapper
                # (ok / errors + the model output field) — graphene mounts
                # cls._meta.mutation_output (= this type) here, NOT the bare node.
                out = field.type
                if isinstance(out, GraphQLNonNull):
                    out = out.of_type
                self.assertIsInstance(out, GraphQLObjectType)
                # The payload carries ok / errors + the output field — matching
                # graphene's DjangoModelType mutation SDL (`...: ThisType` where
                # ThisType = { <model>, ok, errors }).
                self.assertIn("ok", out.fields)
                self.assertIn("errors", out.fields)
                self.assertIn(
                    BasicSerializerType._meta.output_field_name, out.fields
                )

            # The wire arg names are camelCase (graphql-core does NOT
            # auto-camelCase); the create input arg is the camelCased
            # `new_<model>` and the delete arg is `id`. Each keeps out_name=snake.
            create_arg_name = to_camel_case(
                BasicSerializerType._meta.input_field_name
            )
            self.assertIn(create_arg_name, create_field.args)
            self.assertEqual(
                create_field.args[create_arg_name].out_name,
                BasicSerializerType._meta.input_field_name,
            )
            self.assertIn("id", delete_field.args)

            # The create field's output payload is the canonical compiled
            # instance (single-instance memoized), not a fresh per-call rebuild —
            # identity-stable with the plain-object compiler's cache.
            create_out = create_field.type
            if isinstance(create_out, GraphQLNonNull):
                create_out = create_out.of_type
            self.assertIs(
                create_out,
                _compile_plain_object_type(BasicSerializerType),
            )
            return

        # Graphene path (default): graphene Field instances.
        self.assertIsInstance(create_field, graphene.Field)
        self.assertIsInstance(update_field, graphene.Field)
        self.assertIsInstance(delete_field, graphene.Field)

    def test_list_type_retrieve_field(self):
        """Test list type retrieve field."""
        retrieve_field = BasicListType.RetrieveField()
        self.assertIsInstance(retrieve_field, graphene.Field)

    def test_type_meta_attributes(self):
        """Test type meta attributes."""
        # Test that meta attributes are properly set
        self.assertEqual(BasicListType._meta.model, BasicModel)
        self.assertEqual(BasicInputType._meta.model, BasicModel)
        self.assertEqual(BasicSerializerType._meta.model, BasicModel)

    def test_list_type_pagination(self):
        """Test list type pagination."""
        # Check pagination configuration
        pagination = BasicListType._meta.pagination
        self.assertIsInstance(pagination, LimitOffsetGraphqlPagination)

    def test_list_type_ordering(self):
        """Ordering is configured on the pagination object, not on _meta."""
        # The list type itself carries no `ordering` on _meta; ordering is a
        # property of the pagination strategy.
        self.assertFalse(hasattr(BasicListType._meta, "ordering"))

        class OrderedListType(DjangoListObjectType):
            class Meta:
                model = BasicModel
                pagination = LimitOffsetGraphqlPagination(ordering="-text")

        self.assertEqual(OrderedListType._meta.pagination.ordering, "-text")
