# -*- coding: utf-8 -*-
"""Tests for the public Django* base types (native backend).

Phase 7 graphene-removal: ``DjangoObjectType`` / ``DjangoInputObjectType`` /
``DjangoListObjectType`` are now NATIVE types (a Pydantic ``ModelMetaclass`` base,
NOT a graphene ``ObjectType`` subclass). Their compiled GraphQL types live on
``_meta.graphql_output_type`` / ``_meta.graphql_input_type`` (graphql-core
``GraphQLObjectType`` / ``GraphQLInputObjectType``) rather than in the graphene
``_meta.fields`` descriptor dict, which is empty on native. Each field/integration
assertion below was CONVERTED to read the native compiled type, preserving the
original coverage (the types are model-coupled and produce the expected GraphQL
fields).

Run: GDX_BACKEND=native .venv/bin/python -m pytest tests/test_base_types.py \
    -q -o addopts=""
"""

from django.test import TestCase
from graphql import GraphQLInputObjectType, GraphQLObjectType

from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoObjectType,
)

from .models import BasicModel


class BasicDjangoType(DjangoObjectType):
    """Test Django object type."""

    class Meta:
        model = BasicModel


class BasicInputType(DjangoInputObjectType):
    """Test Django input type."""

    class Meta:
        model = BasicModel


class BasicListType(DjangoListObjectType):
    """Test Django list type."""

    class Meta:
        model = BasicModel


class BaseTypesTest(TestCase):
    """Test cases for base types."""

    def setUp(self):
        """Set up test data."""
        self.basic_model = BasicModel.objects.create(text="Test Model")

    def test_django_object_type_creation(self):
        """Test DjangoObjectType creation."""
        obj_type = BasicDjangoType()
        self.assertIsNotNone(obj_type)

        # Should be based on the model
        self.assertEqual(obj_type._meta.model, BasicModel)

    def test_django_input_object_type_creation(self):
        """Test DjangoInputObjectType creation."""
        input_type = BasicInputType()
        self.assertIsNotNone(input_type)

        # Should be based on the model
        self.assertEqual(input_type._meta.model, BasicModel)

    def test_django_list_object_type_creation(self):
        """Test DjangoListObjectType creation."""
        list_type = BasicListType()
        self.assertIsNotNone(list_type)

        # Should be based on the model
        self.assertEqual(list_type._meta.model, BasicModel)

    def test_object_type_has_fields(self):
        """Test that the object type compiles its model fields.

        On native the fields live on the compiled ``graphql_output_type`` (the
        graphene ``_meta.fields`` descriptor dict is empty on native).
        """
        fields = BasicDjangoType._meta.graphql_output_type.fields
        self.assertIsInstance(fields, dict)
        self.assertIn("text", fields)

    def test_input_type_has_fields(self):
        """Test that the input type compiles its model fields.

        On native the input fields live on the compiled ``graphql_input_type``.
        """
        fields = BasicInputType._meta.graphql_input_type.fields
        self.assertIsInstance(fields, dict)
        self.assertIn("text", fields)

    def test_list_type_has_fields(self):
        """Test that the list type exposes the results/count container fields.

        The list container's compiled output type carries ``results`` plus the
        ``count`` field, which is exposed on the wire as ``totalCount``.
        """
        fields = BasicListType._meta.graphql_output_type.fields
        self.assertIsInstance(fields, dict)
        self.assertIn("results", fields)
        # `count` is exposed in the schema as `totalCount`.
        self.assertIn("totalCount", fields)

    def test_type_inheritance(self):
        """Test that types inherit correctly."""
        # Check inheritance
        self.assertTrue(issubclass(BasicDjangoType, DjangoObjectType))
        self.assertTrue(issubclass(BasicInputType, DjangoInputObjectType))
        self.assertTrue(issubclass(BasicListType, DjangoListObjectType))

    def test_graphql_type_production(self):
        """Test that the types compile to graphql-core types.

        Native equivalent of the old "graphene integration" check: instead of
        asserting the types are graphene ``ObjectType`` / ``InputObjectType``
        subclasses (they are not on native), assert each compiles to the
        corresponding graphql-core type.
        """
        self.assertIsInstance(
            BasicDjangoType._meta.graphql_output_type, GraphQLObjectType
        )
        self.assertIsInstance(
            BasicInputType._meta.graphql_input_type, GraphQLInputObjectType
        )

    def test_model_meta_attribute(self):
        """Test model meta attribute."""
        # All types should have model in meta
        self.assertEqual(BasicDjangoType._meta.model, BasicModel)
        self.assertEqual(BasicInputType._meta.model, BasicModel)
        self.assertEqual(BasicListType._meta.model, BasicModel)
