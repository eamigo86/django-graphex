"""Public metadata contract for concrete raw JSON input defaults."""

from __future__ import annotations

import sys

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    build_schema,
    graphql_sync,
    parse,
    print_ast,
    print_schema,
    print_type,
)
from pydantic import Field

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.scalars import GdxJSON
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema


def test_fixed_json_object_default_prints_and_introspects() -> None:
    """Expose a fixed JSON input object default through the public schema.

    Scenario: fixed json object default prints and introspects.
    """
    received: list[dict[str, object]] = []

    class FixedObjectJsonPayload(InputType):
        mapping: dict[str, int] = {"views": 0}

    input_type = compile_input_type(FixedObjectJsonPayload, name="FixedJsonPayload")

    class Submit(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "ok"}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class Mutations(ObjectType):
        submit = Submit.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutations).graphql_schema
    sdl = print_schema(schema)
    assert "mapping: JSON = { views: 0 }" in sdl
    parse(sdl)
    assert "mapping: JSON = { views: 0 }" in print_schema(build_schema(sdl))
    metadata = graphql_sync(
        schema,
        '{ __type(name: "FixedJsonPayload") { inputFields { name defaultValue } } }',
    )
    assert metadata.errors is None
    assert metadata.data == {
        "__type": {"inputFields": [{"name": "mapping", "defaultValue": "{ views: 0 }"}]}
    }
    result = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    assert result.errors is None
    assert received == [{"mapping": {"views": 0}}]
    explicit = graphql_sync(
        schema, "mutation { submit(payload: {mapping: null}) { result } }"
    )
    assert explicit.errors is None
    assert received[-1] == {"mapping": None}
    supplied = graphql_sync(
        schema,
        "mutation($payload: FixedJsonPayload!) { submit(payload: $payload) { result } }",
        variable_values={"payload": {"mapping": {"views": 3}}},
    )
    assert supplied.errors is None
    assert received[-1] == {"mapping": {"views": 3}}


def test_bare_json_default_roundtrips_nested_literal_and_pruned_schema() -> None:
    """Keep representable nested defaults printable after permission pruning.

    Scenario: bare json default roundtrips nested literal and pruned schema.
    """
    received: list[dict[str, object]] = []
    fixed = {"flag": True, "nested": [None, {"text": 'a"b', "large": 2**63}]}

    class NestedJsonPayload(InputType):
        raw_data: dict = fixed

    input_type = compile_input_type(NestedJsonPayload, name="NestedJsonPayload")

    class SubmitNested(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "ok"}

    class QueryNested(ObjectType):
        ping = field(GraphQLString)

    class MutationsNested(ObjectType):
        submitNested = SubmitNested.Field()

    full = DjangoGraphQLSchema(
        query=QueryNested, mutation=MutationsNested
    ).graphql_schema
    for schema in (full, prune_schema(full, frozenset())):
        sdl = print_schema(schema)
        assert "rawData: JSON =" in sdl
        assert "large: 9223372036854775808" in sdl
        parse(sdl)
        assert "rawData: JSON =" in print_schema(build_schema(sdl))
        result = graphql_sync(
            schema, "mutation { submitNested(payload: {}) { result } }"
        )
        assert result.errors is None, result.errors
        assert received[-1] == {"raw_data": fixed}


def test_non_name_json_default_keeps_runtime_without_invalid_sdl_promise() -> None:
    """Preserve an ineligible raw default instead of publishing invalid SDL.

    Scenario: non name json default keeps runtime without invalid sdl promise.
    """

    class NonNameJsonPayload(InputType):
        raw: dict = {"x-y": 1}

    input_type = compile_input_type(NonNameJsonPayload, name="NonNameJsonPayload")
    assert input_type.fields["raw"].default is None
    assert input_type.fields["raw"].default_value == {"x-y": 1}
    assert GdxJSON.parse_value({"x-y": 1}) == {"x-y": 1}


def test_oversized_json_integer_default_preserves_public_runtime() -> None:
    """Keep an unprintable integer default available to a public resolver.

    Scenario: oversized json integer default preserves public runtime.
    """
    fixed = {"large": 10**4300}

    class OversizedIntegerJsonPayload(InputType):
        raw: dict = fixed

    input_type = compile_input_type(
        OversizedIntegerJsonPayload, name="OversizedIntegerJsonPayload"
    )
    field = input_type.fields["raw"]
    assert field.default is None
    assert field.default_value is fixed
    assert GdxJSON.value_to_literal(fixed) is None
    received: list[object] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        received.append(payload["raw"])
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "OversizedIntegerDefaultQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None
    assert result.data == {"probe": "ok"}
    assert received == [fixed]
    assert received[0] == fixed


def test_surrogate_json_string_default_preserves_public_runtime() -> None:
    """Keep a non-GraphQL string default on the legacy metadata path.

    Scenario: surrogate json string default preserves public runtime.
    """
    fixed = {"text": "\ud800"}

    class SurrogateStringJsonPayload(InputType):
        raw: dict = fixed

    input_type = compile_input_type(
        SurrogateStringJsonPayload, name="SurrogateStringJsonPayload"
    )
    field = input_type.fields["raw"]
    assert field.default is None
    assert field.default_value is fixed
    assert GdxJSON.value_to_literal(fixed) is None
    received: list[object] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        received.append(payload["raw"])
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "SurrogateStringDefaultQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None
    assert result.data == {"probe": "ok"}
    assert received == [fixed]
    assert received[0] == fixed


def test_json_default_factory_is_not_frozen_in_sdl() -> None:
    """Retain a per-input factory and the omission of SDL fixed metadata.

    Scenario: json default factory is not frozen in sdl.
    """
    calls: list[int] = []

    def make_default() -> dict[str, int]:
        calls.append(len(calls) + 1)
        return {"views": calls[-1]}

    class FactoryJsonPayload(InputType):
        mapping: dict[str, int] = Field(default_factory=make_default)

    input_type = compile_input_type(FactoryJsonPayload, name="FactoryJsonPayload")
    assert input_type.fields["mapping"].default is None
    assert "mapping: JSON" in print_type(input_type)
    assert calls == []
    assert input_type.out_type({}) == {"mapping": {"views": 1}}
    assert input_type.out_type({}) == {"mapping": {"views": 2}}


def test_nullable_list_defaults_publish_metadata_and_preserve_elements() -> None:
    """Expose eligible list metadata while retaining its JSON elements.

    Scenario: nullable list defaults publish metadata and preserve elements.
    """

    class ListJsonPayload(InputType):
        mappings: list[dict[str, int] | None] | None = [{"views": 1}, None]

    input_type = compile_input_type(ListJsonPayload, name="ListJsonPayload")
    field = input_type.fields["mappings"]
    assert field.default is not None
    assert field.default.value == [{"views": 1}, None]
    received: list[object] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        received.append(payload["mappings"])
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "ListDefaultQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None
    assert received[0] == field.default.value
    assert received[0] is not field.default.value
    assert received[0][0] == field.default.value[0]
    value = {"safe": [1, None]}
    assert GdxJSON.serialize(value) is value
    assert GdxJSON.parse_value(value) is value
    assert print_ast(GdxJSON.value_to_literal(value)) == "{ safe: [1, null] }"


def test_mismatched_list_default_retains_prior_runtime_shape() -> None:
    """Do not silently wrap a previously accepted fixed object in a list.

    Scenario: mismatched list default retains prior runtime shape.
    """

    class MismatchedListDefaultPayload(InputType):
        mappings: list[dict] = {"views": 0}  # type: ignore[assignment]

    input_type = compile_input_type(
        MismatchedListDefaultPayload, name="MismatchedListDefaultPayload"
    )
    field = input_type.fields["mappings"]
    assert field.default is None
    assert field.default_value == {"views": 0}
    assert isinstance(field.type, GraphQLList)
    received: list[object] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        received.append(payload["mappings"])
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "MismatchedListQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None
    assert received[0] == field.default_value
    assert received == [{"views": 0}]


def test_ineligible_json_values_do_not_gain_metadata_or_new_validation() -> None:
    """Reject metadata conversion only, without validating runtime objects.

    Scenario: ineligible json values do not gain metadata or new validation.
    """
    cycle: list[object] = []
    cycle.append(cycle)
    for value in ({"x-y": 1}, {1: "one"}, {"bad": float("inf")}, cycle, object()):
        assert GdxJSON.value_to_literal(value) is None
    assert GdxJSON.value_to_literal({"finite": -0.0}) is not None

    deep: list[object] = []
    current = deep
    for _ in range(180):
        child: list[object] = []
        current.append(child)
        current = child
    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(200)
        assert GdxJSON.value_to_literal(deep) is None
    finally:
        sys.setrecursionlimit(previous_limit)
