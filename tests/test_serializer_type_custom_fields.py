# -*- coding: utf-8 -*-
"""Custom fields declared directly on a "DjangoModelType".

Previously, exposing an extra field (not on the serializer) required declaring a
separate "DjangoObjectType" for the model so it would be picked up from the
registry. These tests cover declaring the field straight on the
"DjangoModelType" instead.

S8h: the 2.0 public field-declaration API is "field()" (graphene descriptors on
a native type are no longer supported). A graphene "source='name'" becomes a
"field(GraphQLString, resolver=...)" reading the attribute off the model
instance — the native equivalent of graphene's "source" semantics.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from django.db import models
from django.test import TestCase
from graphql import GraphQLField, GraphQLInt, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from tests.models import DummyModel, UUIDItem, UUIDThing


def _read_attr(attr: str) -> Callable[[Any, Any], Any]:
    """Build a resolver that reads "attr" off the resolved model instance.

    The native "field()" equivalent of graphene's "source='attr'" for the
    plain attribute case exercised by these tests (the root is always a model
    instance, never a dict or zero-arg callable).

    Args:
        attr: The attribute name to read off the resolved root object.

    Returns:
        resolver: A two-argument (root, info) resolver returning the
            attribute's value, or None when absent.
    """

    def _resolver(root: Any, info: Any) -> Any:
        return getattr(root, attr, None)

    return _resolver


def _compiled_output_fields(
    model_type: type[DjangoModelType],
) -> dict[str, GraphQLField]:
    """Compile "model_type"'s native output type and return its field map.

    Building a "DjangoGraphQLSchema" over the serializer type's "output_type"
    is what populates "_meta.graphql_output_type" (the graphql-core type the
    native backend actually serves). Model-derived fields live there — not in the
    graphene "_meta.fields" map the converter keeps for declared fields only.

    Args:
        model_type: The "DjangoModelType" subclass whose compiled output
            fields are inspected.

    Returns:
        fields: The compiled graphql-core field map for the model type's
            output type.
    """
    output_type = model_type._meta.output_type

    class _Q(ObjectType):
        obj = field(output_type)

    DjangoGraphQLSchema(query=_Q)
    return output_type._meta.graphql_output_type.fields


class ResolverThing(DummyModel):
    """Dedicated model so the resolver tests don't collide with the registry.

    Kept separate from other test models so its registered output type
    cannot be reused by an unrelated test.
    """

    name = models.CharField(max_length=50)


class ResolverThing2(DummyModel):
    """A second dedicated model (one registered output type per model).

    Distinct from "ResolverThing" so the inheritance-override test does not
    collide with a type already registered for the base resolver tests.
    """

    name = models.CharField(max_length=50)


class _ThingFieldsMixin(DjangoModelType):
    """Abstract base contributing shared custom fields (OOP-style reuse)."""

    upper_name = field(GraphQLString, resolver=_read_attr("name"))  # inherited
    overridden = field(GraphQLString, resolver=_read_attr("name"))  # may override

    class Meta:
        abstract = True


class ThingModelType(_ThingFieldsMixin):
    """Concrete model type declaring its own custom fields on the class body.

    Also overrides the "overridden" field inherited from
    "_ThingFieldsMixin" to prove subclass declarations win.
    """

    # Declared right here -- no separate DjangoObjectType needed.
    alias = field(GraphQLString, resolver=_read_attr("name"))
    overridden = field(GraphQLInt)  # overrides the mixin's field

    class Meta:
        """Configuration for "ThingModelType".

        Declares the backing model with no further options.
        """

        model = UUIDThing


class CustomFieldsOnSerializerTypeTest(TestCase):
    """Tests for custom fields declared directly on a model type's class body.

    Covers presence, inheritance, subclass overrides, list-type visibility,
    wrapper cleanup, and instance-based resolution.
    """

    def test_custom_field_added_to_output_type(self) -> None:
        """Assert a declared custom field is compiled alongside model-derived ones.

        If this fails, a custom field declared straight on a
        "DjangoModelType" would be missing from the compiled schema output.
        """
        # The compiled native output type carries the declared custom field
        # alongside the model-derived ones (model fields live on the compiled
        # graphql-core type, not in the graphene-converter _meta.fields map).
        fields = _compiled_output_fields(ThingModelType)
        self.assertIn("alias", fields)
        self.assertIn("name", fields)

    def test_inherited_custom_field_added_to_output_type(self) -> None:
        """Assert a custom field declared on an abstract mixin is inherited.

        If this fails, custom fields declared on a shared abstract base
        would not propagate to concrete subclasses.
        """
        # Field declared on the abstract mixin is inherited.
        self.assertIn("upper_name", ThingModelType._meta.output_type._meta.fields)

    def test_subclass_overrides_inherited_field(self) -> None:
        """Assert a subclass's field declaration overrides the mixin's version.

        If this fails, a subclass could not narrow or change the type of a
        field it inherits from an abstract mixin.
        """
        # The subclass's `overridden` (Int) wins over the mixin's (String).
        declared = ThingModelType._meta.output_type._meta.fields["overridden"]
        self.assertIs(declared.type, GraphQLInt)

    def test_custom_field_visible_in_list_type(self) -> None:
        """Assert custom fields also show up on the model type's list type.

        If this fails, list-query results would be missing custom fields
        that are present on the corresponding single-object type.
        """
        # The list type reuses the same item type from the registry, so the
        # custom fields show up in the list results too.
        base = ThingModelType._meta.output_list_type._meta.baseType
        self.assertIs(base, ThingModelType._meta.output_type)
        self.assertIn("alias", base._meta.fields)
        self.assertIn("upper_name", base._meta.fields)

    def test_custom_fields_not_left_on_the_wrapper_type(self) -> None:
        """Assert collected custom fields are removed from the serializer wrapper.

        If this fails, custom fields would remain on the input/serializer
        wrapper type after being collected into the compiled output type,
        risking them being misread as serializer fields.
        """
        # Collected fields (own and inherited) are removed from the wrapper.
        wrapper_fields = ThingModelType._meta.fields
        self.assertNotIn("alias", wrapper_fields)
        self.assertNotIn("upper_name", wrapper_fields)

    def test_custom_field_resolves_from_the_instance(self) -> None:
        """Assert custom fields resolve their values off the actual instance.

        If this fails, a query selecting model-derived and custom fields
        together would return missing or incorrect values for the custom
        ones.
        """
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
    """A custom field declared on a DjangoModelType honors its "resolve_<field>".

    Covers both a directly declared resolver method and inheritance/override
    of that method across an abstract base and its subclass.
    """

    def test_resolve_method_is_used_for_custom_field(self) -> None:
        """Assert a "resolve_<field>" method resolves a resolver-less field.

        If this fails, a custom field declared without an explicit
        resolver would not fall back to a same-named "resolve_<field>"
        method defined on the type.
        """

        class _ThingType(DjangoModelType):
            shout = field(GraphQLString)  # no resolver; resolved by the method below

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

    def test_inherited_resolver_and_subclass_override(self) -> None:
        """Assert a subclass's "resolve_<field>" overrides the inherited one.

        If this fails, a subclass could not customize how an inherited
        custom field resolves, always falling back to the parent's logic.
        """

        class _Base(DjangoModelType):
            label = field(GraphQLString)

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
    """Tests for the conflict between a serializer type and a pre-existing type.

    Verifies the type reuses the already-registered object type and warns
    instead of silently dropping the fields it cannot inject.
    """

    def test_warns_and_skips_when_object_type_already_registered(self) -> None:
        """Assert a pre-registered object type causes a warning, not silent loss.

        If this fails, custom fields declared on a serializer type whose
        model already has a registered "DjangoObjectType" would either be
        silently dropped without a warning, or would corrupt the
        pre-existing registered type.
        """

        # Registering a DjangoObjectType first means the serializer type reuses
        # it; fields declared on the serializer type can't be injected, so we
        # warn instead of silently dropping them.
        class _ItemObjectType(DjangoObjectType):
            class Meta:
                model = UUIDItem

        with pytest.warns(UserWarning, match="already registered"):

            class ItemModelType(DjangoModelType):
                extra = field(GraphQLString, resolver=_read_attr("label"))

                class Meta:
                    model = UUIDItem

        self.assertIs(ItemModelType._meta.output_type, _ItemObjectType)
        self.assertNotIn("extra", ItemModelType._meta.output_type._meta.fields)
