"""Automatic choices-enum name collisions must fail before schema use."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test.utils import isolate_apps
from graphql import GraphQLField, GraphQLObjectType, get_named_type, graphql_sync

from django_graphex.converter import build_choices_enum_type, choices_enum_name
from django_graphex.core import ObjectType, field
from django_graphex.core.output_compiler import _to_graphql_field
from django_graphex.filtering.native_schema import _choices_enum
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoInputObjectType, DjangoObjectType


def _collision_fields() -> tuple[models.Field, models.Field]:
    """Create distinct fields whose existing automatic enum names collide.

    Returns:
        The order and line choices fields, in declaration order.
    """

    class Order(models.Model):
        line_status = models.CharField(
            max_length=12,
            choices=(("open", "Open"), ("closed", "Closed")),
        )

        class Meta:
            app_label = "shop"

    class Line(models.Model):
        status = models.CharField(
            max_length=12,
            choices=(("queued", "Queued"), ("sent", "Sent")),
        )

        class Meta:
            app_label = "shop_order"

    return Order._meta.get_field("line_status"), Line._meta.get_field("status")


@pytest.mark.parametrize("reverse", [False, True])
@isolate_apps()
def test_incompatible_choices_collision_rejects_schema(reverse: bool) -> None:
    """Reject either declaration order without replacing the first enum.

    Args:
        reverse: Whether to compile the line field before the order field.

    Raises:
        ImproperlyConfigured: The second field has an incompatible definition.
    """
    first_field, second_field = _collision_fields()
    if reverse:
        first_field, second_field = second_field, first_field
    registry = Registry()
    name = choices_enum_name(first_field)
    assert name == choices_enum_name(second_field) == "shopOrderLineStatusEnum"

    first_type = GraphQLObjectType(
        "FirstModel",
        lambda: _to_graphql_field(first_field, registry, graphene_registry=registry),
    )
    second_type = GraphQLObjectType(
        "SecondModel",
        lambda: _to_graphql_field(second_field, registry, graphene_registry=registry),
    )
    query = GraphQLObjectType(
        "Query",
        lambda: {
            "first": GraphQLField(first_type),
            "second": GraphQLField(second_type),
        },
    )
    expected_origins = (
        f"{first_field.model._meta.label}.{first_field.name}",
        f"{second_field.model._meta.label}.{second_field.name}",
    )
    with pytest.raises(ImproperlyConfigured) as error:
        DjangoGraphQLSchema(query=query)
    for detail in (name, *expected_origins):
        assert detail in str(error.value)

    original = build_choices_enum_type(first_field, registry)
    assert original is not None
    expected_values = {"QUEUED", "SENT"} if reverse else {"OPEN", "CLOSED"}
    assert set(original.values) == expected_values


@isolate_apps()
def test_distinct_registries_keep_colliding_names_isolated() -> None:
    """Keep same-name choices in separate registries independent.

    One registry must not inherit an enum built for another registry.
    """
    first_field, second_field = _collision_fields()
    first = build_choices_enum_type(first_field, Registry())
    second = build_choices_enum_type(second_field, Registry())
    assert first is not second
    assert first is not None and second is not None
    assert first.name == second.name
    assert set(first.values) == {"OPEN", "CLOSED"}
    assert set(second.values) == {"QUEUED", "SENT"}


@isolate_apps()
def test_compatible_same_name_reuses_registry_enum() -> None:
    """Reuse one enum for output, filter and an identical second field.

    An input-specific flag still selects its separate existing name.
    """
    first_field, second_field = _collision_fields()
    second_field.choices = first_field.choices
    registry = Registry()
    first = build_choices_enum_type(first_field, registry)
    assert first is not None
    assert build_choices_enum_type(first_field, registry) is first
    assert _choices_enum(first_field, registry) is first
    assert build_choices_enum_type(second_field, registry) is first
    assert (
        build_choices_enum_type(first_field, registry, input_flag="create") is not first
    )


@isolate_apps()
def test_colliding_choice_descriptions_are_incompatible() -> None:
    """Different enum member labels cannot silently inherit old metadata.

    Raises:
        ImproperlyConfigured: Same raw values with different descriptions.
    """
    first_field, second_field = _collision_fields()
    second_field.choices = (("open", "Opened"), ("closed", "Closed"))
    registry = Registry()
    first = build_choices_enum_type(first_field, registry)
    with pytest.raises(ImproperlyConfigured, match="shopOrderLineStatusEnum"):
        build_choices_enum_type(second_field, registry)
    assert build_choices_enum_type(first_field, registry) is first


@isolate_apps()
def test_generated_create_input_rejects_incompatible_enum() -> None:
    """Generated mutation inputs fail rather than use another field's choices.

    Raises:
        ImproperlyConfigured: The second input needs an incompatible enum.
    """
    first_field, second_field = _collision_fields()
    type_registry = Registry()
    order_model = first_field.model
    line_model = second_field.model

    class OrderInput(DjangoInputObjectType):
        class Meta:
            model = order_model
            registry = type_registry
            input_for = "create"

    assert "lineStatus" in OrderInput._meta.graphql_input_type.fields
    with pytest.raises(ImproperlyConfigured, match="shopOrderLineStatusEnum"):

        class LineInput(DjangoInputObjectType):
            class Meta:
                model = line_model
                registry = type_registry
                input_for = "create"

        _ = LineInput._meta.graphql_input_type.fields


@isolate_apps()
def test_filter_input_rejects_incompatible_enum() -> None:
    """Filter inputs cannot silently accept choices from another model field.

    Raises:
        ImproperlyConfigured: The second filter needs an incompatible enum.
    """
    first_field, second_field = _collision_fields()
    registry = Registry()
    first = _choices_enum(first_field, registry)
    with pytest.raises(ImproperlyConfigured, match="shopOrderLineStatusEnum"):
        _choices_enum(second_field, registry)
    assert _choices_enum(first_field, registry) is first


@isolate_apps()
def test_reordered_compatible_choices_share_public_schema_and_inputs() -> None:
    """Preserve a public schema when unique enum members only change order.

    Output serialization, generated create inputs and filters must reuse the
    incumbent enum without changing its presentation order.
    """
    first_field, second_field = _collision_fields()
    second_field.choices = tuple(reversed(first_field.choices))
    type_registry = Registry()
    first_model = first_field.model
    second_model = second_field.model

    class First(DjangoObjectType):
        class Meta:
            model = first_model
            registry = type_registry

    class Second(DjangoObjectType):
        class Meta:
            model = second_model
            registry = type_registry

    class Query(ObjectType):
        first = field(First, resolver=lambda *_: first_model(line_status="open"))
        second = field(Second, resolver=lambda *_: second_model(status="closed"))

    schema = DjangoGraphQLSchema(query=Query)
    result = graphql_sync(schema.graphql_schema, "{first{lineStatus} second{status}}")
    assert result.errors is None
    assert result.data == {
        "first": {"lineStatus": "OPEN"},
        "second": {"status": "CLOSED"},
    }

    enum_type = build_choices_enum_type(first_field, type_registry)
    assert enum_type is not None
    assert list(enum_type.values) == ["OPEN", "CLOSED"]
    assert build_choices_enum_type(second_field, type_registry) is enum_type
    assert _choices_enum(first_field, type_registry) is enum_type
    assert _choices_enum(second_field, type_registry) is enum_type

    class FirstInput(DjangoInputObjectType):
        class Meta:
            model = first_model
            registry = type_registry
            input_for = "create"

    class SecondInput(DjangoInputObjectType):
        class Meta:
            model = second_model
            registry = type_registry
            input_for = "create"

    first_input_enum = get_named_type(
        FirstInput._meta.graphql_input_type.fields["lineStatus"].type
    )
    second_input_enum = get_named_type(
        SecondInput._meta.graphql_input_type.fields["status"].type
    )
    assert first_input_enum is second_input_enum is enum_type
