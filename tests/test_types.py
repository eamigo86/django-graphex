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
        """Test serializer type mutation field creation."""
        import os

        if os.environ.get("GDX_BACKEND", "graphene") == "native":
            self.skipTest(
                "Native mutation schema assembly is deferred to Phase 5: "
                "CreateField/UpdateField build args as graphql-core GraphQLArgument, "
                "which graphene's to_arguments() rejects at field-construction time. "
                "Tracked in specs/2.0-migration-plan.md (Phase 5)."
            )
        (
            create_field,
            update_field,
            delete_field,
        ) = BasicSerializerType.MutationFields()
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
