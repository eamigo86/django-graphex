"""Public metadata contract for fixed JSON list defaults."""

from __future__ import annotations

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLNonNull,
    GraphQLString,
    build_schema,
    graphql_sync,
    parse,
    print_schema,
)
from pydantic import Field

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema


def test_valid_fixed_json_list_default_prints_and_introspects() -> None:
    """Publish a valid fixed list default without changing its elements.

    Scenario: valid fixed json list default prints and introspects.
    """
    fixed = [{"views": 1}, None]
    received: list[dict[str, object]] = []

    class FixedListMetadataPayload(InputType):
        mappings: list[dict[str, int] | None] | None = fixed

    input_type = compile_input_type(
        FixedListMetadataPayload, name="FixedListMetadataPayload"
    )

    class SubmitFixedList(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "ok"}

    class FixedListQuery(ObjectType):
        ping = field(GraphQLString)

    class FixedListMutations(ObjectType):
        submitFixedList = SubmitFixedList.Field()

    schema = DjangoGraphQLSchema(
        query=FixedListQuery, mutation=FixedListMutations
    ).graphql_schema
    sdl = print_schema(schema)
    assert "mappings: [JSON] =" in sdl
    parse(sdl)
    assert "mappings: [JSON] =" in print_schema(build_schema(sdl))
    metadata = graphql_sync(
        schema,
        '{ __type(name: "FixedListMetadataPayload") { inputFields { name defaultValue } } }',
    )
    assert metadata.errors is None
    assert metadata.data is not None
    fields = metadata.data["__type"]["inputFields"]
    assert fields[0]["defaultValue"] is not None
    result = graphql_sync(
        schema, "mutation { submitFixedList(payload: {}) { result } }"
    )
    assert result.errors is None
    assert received == [{"mappings": fixed}]
    assert received[0]["mappings"] is not fixed
    assert received[0]["mappings"][0] == fixed[0]
    supplied = graphql_sync(
        schema,
        "mutation($payload: FixedListMetadataPayload!) { submitFixedList(payload: $payload) { result } }",
        variable_values={"payload": {"mappings": [{"views": 3}, None]}},
    )
    assert supplied.errors is None
    assert received[-1] == {"mappings": [{"views": 3}, None]}
    explicit_null = graphql_sync(
        schema, "mutation { submitFixedList(payload: {mappings: null}) { result } }"
    )
    assert explicit_null.errors is None
    assert received[-1] == {"mappings": None}


def test_empty_list_and_nested_pruned_default_remain_printable() -> None:
    """Publish empty and nested list defaults on full and pruned schemas.

    Scenario: empty list and nested pruned default remain printable.
    """

    class NestedListMetadataChild(InputType):
        values: list[dict] = []

    child = compile_input_type(NestedListMetadataChild, name="NestedListMetadataChild")

    class NestedListMetadataParent(InputType):
        child: NestedListMetadataChild

    parent = compile_input_type(
        NestedListMetadataParent, name="NestedListMetadataParent"
    )
    received: list[dict[str, object]] = []

    class SubmitNestedList(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(parent))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "ok"}

    class NestedListQuery(ObjectType):
        ping = field(GraphQLString)

    class NestedListMutations(ObjectType):
        submitNestedList = SubmitNestedList.Field()

    full = DjangoGraphQLSchema(
        query=NestedListQuery, mutation=NestedListMutations
    ).graphql_schema
    for schema in (full, prune_schema(full, frozenset())):
        sdl = print_schema(schema)
        assert "values: [JSON!] = []" in sdl
        parse(sdl)
        result = graphql_sync(
            schema,
            "mutation { submitNestedList(payload: {child: {}}) { result } }",
        )
        assert result.errors is None
        assert received[-1] == {"child": {"values": []}}
    assert child.fields["values"].default is not None


def test_invalid_list_defaults_and_factory_keep_legacy_metadata() -> None:
    """Avoid changing malformed defaults or evaluating a list factory.

    Scenario: invalid list defaults and factory keep legacy metadata.
    """

    class InvalidListMetadataPayload(InputType):
        wrong_outer: list[dict] = {"views": 0}  # type: ignore[assignment]
        wrong_element: list[dict[str, int]] = [None]  # type: ignore[list-item]
        wrong_typed_map: list[dict[str, int]] = [{"views": True}]  # type: ignore[dict-item]
        wrong_name: list[dict] = [{"x-y": 1}]
        fresh: list[dict] = Field(default_factory=lambda: [{"views": 0}])

    input_type = compile_input_type(
        InvalidListMetadataPayload, name="InvalidListMetadataPayload"
    )
    for name in ("wrongOuter", "wrongElement", "wrongTypedMap", "wrongName", "fresh"):
        assert input_type.fields[name].default is None
    assert input_type.fields["wrongOuter"].default_value == {"views": 0}
    assert input_type.fields["wrongElement"].default_value == [None]
    assert input_type.fields["wrongTypedMap"].default_value == [{"views": True}]
    assert input_type.out_type({})["fresh"] == [{"views": 0}]
    assert input_type.out_type({})["fresh"] is not input_type.out_type({})["fresh"]


@pytest.mark.parametrize(
    "case,value",
    list(
        enumerate(
            [
                {"views": 0},
                "not a list",
                ({"views": 0},),
                type("ListSubclass", (list,), {})([{"views": 0}]),
                [None],
                [{"x-y": 1}],
                [{"views": float("inf")}],
                [{"text": "\ud800"}],
                [{"large": 10**4300}],
            ]
        )
    ),
)
def test_ineligible_fixed_json_list_shapes_stay_internal(
    case: int, value: object
) -> None:
    """Do not publish malformed or unprintable list defaults.

    Args:
        case: Name or index of the parametrized case.
        value: Value supplied by the parametrized case.
    """

    payload_type = type(
        f"IneligibleListShapePayload{case}",
        (InputType,),
        {
            "__module__": __name__,
            "__annotations__": {"values": list[dict]},
            "values": value,
        },
    )

    input_type = compile_input_type(
        payload_type,
        name=f"IneligibleListShapePayload{case}",
    )
    gql_field = input_type.fields["values"]
    assert gql_field.default is None
    assert gql_field.default_value is value
