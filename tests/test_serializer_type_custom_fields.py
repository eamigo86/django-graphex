# -*- coding: utf-8 -*-
"""Custom graphene fields declared directly on a ``DjangoModelType``.

Previously, exposing an extra field (not on the serializer) required declaring a
separate ``DjangoObjectType`` for the model so it would be picked up from the
registry. These tests cover declaring the field straight on the
``DjangoModelType`` instead.
"""

import graphene
import pytest
from django.db import models
from django.test import TestCase
from graphql import graphql_sync

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoModelType,
    DjangoObjectType,
    ObjectType,
    field,
)
from tests.models import DummyModel, UUIDItem, UUIDThing


def _compiled_output_fields(model_type):
    """Compile ``model_type``'s native output type and return its field map.

    Building a ``DjangoGraphQLSchema`` over the serializer type's ``output_type``
    is what populates ``_meta.graphql_output_type`` (the graphql-core type the
    native backend actually serves). Model-derived fields live there — not in the
    graphene ``_meta.fields`` map the converter keeps for declared fields only.
    """
    output_type = model_type._meta.output_type

    class _Q(ObjectType):
        obj = field(output_type)

    DjangoGraphQLSchema(query=_Q)
    return output_type._meta.graphql_output_type.fields


class ResolverThing(DummyModel):
    """Dedicated model so the resolver tests don't collide with the registry."""

    name = models.CharField(max_length=50)


class ResolverThing2(DummyModel):
    """A second dedicated model (one registered output type per model)."""

    name = models.CharField(max_length=50)


class _ThingFieldsMixin(DjangoModelType):
    """Abstract base contributing shared custom fields (OOP-style reuse)."""

    upper_name = graphene.String(source="name")  # inherited by subclasses
    overridden = graphene.String(source="name")  # a subclass may override it

    class Meta:
        abstract = True


class ThingModelType(_ThingFieldsMixin):
    # Declared right here -- no separate DjangoObjectType needed.
    alias = graphene.Field(graphene.String, source="name")
    overridden = graphene.Int()  # overrides the mixin's field

    class Meta:
        model = UUIDThing


class CustomFieldsOnSerializerTypeTest(TestCase):
    def test_custom_field_added_to_output_type(self):
        # The compiled native output type carries the declared custom field
        # alongside the model-derived ones (model fields live on the compiled
        # graphql-core type, not in the graphene-converter _meta.fields map).
        fields = _compiled_output_fields(ThingModelType)
        self.assertIn("alias", fields)
        self.assertIn("name", fields)

    def test_inherited_custom_field_added_to_output_type(self):
        # Field declared on the abstract mixin is inherited.
        self.assertIn("upper_name", ThingModelType._meta.output_type._meta.fields)

    def test_subclass_overrides_inherited_field(self):
        # The subclass's `overridden` (Int) wins over the mixin's (String).
        field = ThingModelType._meta.output_type._meta.fields["overridden"]
        self.assertIs(field.type, graphene.Int)

    def test_custom_field_visible_in_list_type(self):
        # The list type reuses the same item type from the registry, so the
        # custom fields show up in the list results too.
        base = ThingModelType._meta.output_list_type._meta.baseType
        self.assertIs(base, ThingModelType._meta.output_type)
        self.assertIn("alias", base._meta.fields)
        self.assertIn("upper_name", base._meta.fields)

    def test_custom_fields_not_left_on_the_wrapper_type(self):
        # Collected fields (own and inherited) are removed from the wrapper.
        wrapper_fields = ThingModelType._meta.fields
        self.assertNotIn("alias", wrapper_fields)
        self.assertNotIn("upper_name", wrapper_fields)

    def test_custom_field_resolves_from_the_instance(self):
        output_type = ThingModelType._meta.output_type

        class _Query(ObjectType):
            thing = field(output_type)

            def resolve_thing(root, info):
                return UUIDThing(name="hello")  # unsaved is fine for attr reads

        schema = DjangoGraphQLSchema(query=_Query)
        result = graphql_sync(
            schema.graphql_schema, "{ thing { name alias upperName } }"
        )
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(
            result.data["thing"],
            {"name": "hello", "alias": "hello", "upperName": "hello"},
        )


class CustomResolverTest(TestCase):
    """A custom field declared on a DjangoModelType honors its `resolve_<field>`."""

    def test_resolve_method_is_used_for_custom_field(self):
        class _ThingType(DjangoModelType):
            shout = graphene.String()  # no `source=`; resolved by the method below

            class Meta:
                model = ResolverThing

            def resolve_shout(self, info):
                return (self.name or "").upper()

        output_type = _ThingType._meta.output_type

        class _Query(ObjectType):
            thing = field(output_type)

            def resolve_thing(root, info):
                return ResolverThing(name="ada")

        schema = DjangoGraphQLSchema(query=_Query)
        result = graphql_sync(schema.graphql_schema, "{ thing { name shout } }")
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(result.data["thing"], {"name": "ada", "shout": "ADA"})

    def test_inherited_resolver_and_subclass_override(self):
        class _Base(DjangoModelType):
            label = graphene.String()

            class Meta:
                abstract = True

            def resolve_label(self, info):
                return "base"

        class _Child(_Base):
            class Meta:
                model = ResolverThing2

            def resolve_label(self, info):  # overrides the inherited resolver
                return "child"

        output_type = _Child._meta.output_type

        class _Query(ObjectType):
            thing = field(output_type)

            def resolve_thing(root, info):
                return ResolverThing2(name="x")

        schema = DjangoGraphQLSchema(query=_Query)
        result = graphql_sync(schema.graphql_schema, "{ thing { label } }")
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(result.data["thing"]["label"], "child")


class CustomFieldsConflictTest(TestCase):
    def test_warns_and_skips_when_object_type_already_registered(self):
        # Registering a DjangoObjectType first means the serializer type reuses
        # it; fields declared on the serializer type can't be injected, so we
        # warn instead of silently dropping them.
        class _ItemObjectType(DjangoObjectType):
            class Meta:
                model = UUIDItem

        with pytest.warns(UserWarning, match="already registered"):

            class ItemModelType(DjangoModelType):
                extra = graphene.Field(graphene.String, source="label")

                class Meta:
                    model = UUIDItem

        self.assertIs(ItemModelType._meta.output_type, _ItemObjectType)
        self.assertNotIn("extra", ItemModelType._meta.output_type._meta.fields)
