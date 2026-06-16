# -*- coding: utf-8 -*-
"""Tests for django_graphex.types module."""

from django.test import TestCase

from django_graphex.fields import DjangoListObjectField, DjangoObjectField
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
        # The uniform list shape always exposes results + totalCount. Under the
        # native backend the live container is the compiled
        # ``_meta.graphql_output_type`` (a graphql-core ``GraphQLObjectType``);
        # the dead graphene ``_meta.fields`` descriptors are no longer built.
        from django_graphex.native.registry_compiler import compile_all_outputs

        compile_all_outputs()
        meta = BasicListType._meta
        gql = meta.graphql_output_type
        self.assertIsNotNone(gql)
        fields = gql.fields  # force thunk eval
        # `results` carries the list rows; `count` is exposed as `totalCount`.
        self.assertIn(meta.results_field_name, fields)
        self.assertIn("totalCount", fields)

    def test_input_type_fields(self):
        """Test input type fields."""
        # The input type mirrors the model's concrete fields. Under the native
        # backend the input lands as a compiled graphql-core
        # ``GraphQLInputObjectType`` on ``_meta.graphql_input_type``.
        gql_input = BasicInputType._meta.graphql_input_type
        self.assertIsNotNone(gql_input)
        fields = gql_input.fields  # force thunk eval
        self.assertIn("text", fields)

    def test_serializer_type_query_fields(self):
        """Test serializer type query field creation.

        ``QueryFields()`` returns a single-object retrieve field and a list
        field. Under the native backend these are the library's own
        ``DjangoObjectField`` / ``DjangoListObjectField`` descriptors (the
        public, graphene-free query-field API).
        """
        retrieve_field, list_field = BasicSerializerType.QueryFields()
        self.assertIsInstance(retrieve_field, DjangoObjectField)
        self.assertIsInstance(list_field, DjangoListObjectField)

    def test_serializer_type_mutation_fields(self):
        """Test serializer type mutation field creation.

        Native mutation schema assembly: ``CreateField`` / ``UpdateField`` /
        ``DeleteField`` return graphql-core ``GraphQLField`` objects whose
        ``.type`` is the canonical compiled output type and whose ``.args`` are
        graphql-core ``GraphQLArgument`` instances — the genuine native mutation
        field shape.
        """
        from graphql import (
            GraphQLArgument,
            GraphQLField,
            GraphQLNonNull,
            GraphQLObjectType,
        )

        from django_graphex._strconv import to_camel_case

        from django_graphex.native.schema_compiler import (
            _compile_plain_object_type,
        )

        # MutationFields() returns (create, delete, update) — keep this order so
        # the per-field assertions below reference the correct operation.
        (
            create_field,
            delete_field,
            update_field,
        ) = BasicSerializerType.MutationFields()

        for field in (create_field, update_field, delete_field):
            # Native: a raw graphql-core GraphQLField.
            self.assertIsInstance(field, GraphQLField)
            # Its args are graphql-core GraphQLArgument instances.
            for arg in field.args.values():
                self.assertIsInstance(arg, GraphQLArgument)
            # Its output type is the compiled mutation PAYLOAD wrapper
            # (ok / errors + the model output field).
            out = field.type
            if isinstance(out, GraphQLNonNull):
                out = out.of_type
            self.assertIsInstance(out, GraphQLObjectType)
            # The payload carries ok / errors + the output field — matching the
            # DjangoModelType mutation SDL (`...: ThisType` where
            # ThisType = { <model>, ok, errors }).
            self.assertIn("ok", out.fields)
            self.assertIn("errors", out.fields)
            self.assertIn(BasicSerializerType._meta.output_field_name, out.fields)

        # The wire arg names are camelCase (graphql-core does NOT auto-camelCase);
        # the create input arg is the camelCased `new_<model>` and the delete arg
        # is `id`. Each keeps out_name=snake.
        create_arg_name = to_camel_case(BasicSerializerType._meta.input_field_name)
        self.assertIn(create_arg_name, create_field.args)
        self.assertEqual(
            create_field.args[create_arg_name].out_name,
            BasicSerializerType._meta.input_field_name,
        )
        self.assertIn("id", delete_field.args)

        # The create field's output payload is the canonical compiled instance
        # (single-instance memoized), not a fresh per-call rebuild —
        # identity-stable with the plain-object compiler's cache.
        create_out = create_field.type
        if isinstance(create_out, GraphQLNonNull):
            create_out = create_out.of_type
        self.assertIs(
            create_out,
            _compile_plain_object_type(BasicSerializerType),
        )

    def test_list_type_retrieve_field(self):
        """Test list type retrieve field.

        ``RetrieveField()`` returns the single-object retrieve descriptor — the
        library's ``DjangoObjectField`` (graphene-free public field API).
        """
        retrieve_field = BasicListType.RetrieveField()
        self.assertIsInstance(retrieve_field, DjangoObjectField)

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
