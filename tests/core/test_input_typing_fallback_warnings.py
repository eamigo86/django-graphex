"""Warnings for input annotations that retain the legacy String wire type."""

from __future__ import annotations

import json
import warnings
from typing import Literal, Union

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_schema,
)

from django_graphex.core import InputType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.mutation import Mutation


class UnsupportedTypingInput(InputType):
    """Expose unsupported forms alongside supported controls.

    The model is mounted on a native mutation to exercise public input
    compilation and GraphQL execution rather than a private scalar helper.
    """

    literal: Literal[1, 2]
    mixed_literal: Literal["a", 1]
    mapping: dict[str, str]
    numbers: set[int]
    choice: Union[int, str]
    maybe: int | None = None
    values: list[int]


def test_public_input_mutation_warns_without_changing_wire_behavior() -> None:
    """Warn for each fallback without changing the mutation wire contract.

    SDL, introspection, accepted strings, and rejected structured values
    remain identical to the legacy GraphQLString fallback.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        input_type = compile_input_type(
            UnsupportedTypingInput, name="UnsupportedTypingInput"
        )
        fields = input_type.fields

    messages = [str(item.message) for item in caught if item.category is UserWarning]
    assert len(messages) == 5
    for name, count in (("Literal", 2), ("dict", 1), ("set", 1), ("Union", 1)):
        assert sum(name in message for message in messages) == count
    assert all("GraphQLString" in message for message in messages)
    assert all("unsupported input field type" in message for message in messages)
    assert [
        str(fields[name].type)
        for name in ("literal", "mixedLiteral", "mapping", "numbers", "choice")
    ] == ["String!"] * 5
    assert str(fields["maybe"].type) == "Int"
    assert str(fields["values"].type) == "[Int!]!"

    class EchoMutation(Mutation):
        """Return the resolver-facing input mapping unchanged."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled public input type to the mutation."""

            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Echo the GraphQL-coerced payload without Pydantic validation.

            Args:
                _root: Unused mutation root.
                _info: Unused GraphQL execution context.
                payload: Input mapping produced by graphql-core.

            Returns:
                A result containing the unchanged payload as JSON.
            """
            return {"result": json.dumps(payload, sort_keys=True)}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("MutationRoot", {"echo": EchoMutation.Field()}),
    )
    sdl = print_schema(schema)
    assert "literal: String!" in sdl
    assert "mixedLiteral: String!" in sdl
    assert "mapping: String!" in sdl
    assert "numbers: String!" in sdl
    assert "choice: String!" in sdl
    assert "maybe: Int" in sdl
    assert "values: [Int!]!" in sdl
    introspection = graphql_sync(
        schema,
        '{ __type(name: "UnsupportedTypingInput") { inputFields { name type { kind name ofType { kind name } } } } }',
    )
    assert introspection.errors is None
    names = {
        entry["name"]: entry["type"]
        for entry in introspection.data["__type"]["inputFields"]
    }
    for name in ("literal", "mixedLiteral", "mapping", "numbers", "choice"):
        assert names[name]["kind"] == "NON_NULL"
        assert names[name]["ofType"] == {"kind": "SCALAR", "name": "String"}

    values = {
        "literal": "not-a-member",
        "mixedLiteral": "not-a-member",
        "mapping": "not-an-object",
        "numbers": "not-a-list",
        "choice": "not-a-union-value",
        "maybe": 7,
        "values": [1, 2],
    }
    query = "mutation($payload: UnsupportedTypingInput!) { echo(payload: $payload) { result } }"
    accepted = graphql_sync(schema, query, variable_values={"payload": values})
    assert accepted.errors is None
    assert json.loads(accepted.data["echo"]["result"]) == {
        **{key: value for key, value in values.items() if key != "mixedLiteral"},
        "mixed_literal": "not-a-member",
    }
    for name, structured in (("mapping", {"x": 1}), ("numbers", [1, 2]), ("choice", 7)):
        rejected = graphql_sync(
            schema, query, variable_values={"payload": {**values, name: structured}}
        )
        assert rejected.errors
        assert any("String" in str(error) for error in rejected.errors)


def test_supported_annotations_do_not_gain_fallback_warnings() -> None:
    """Keep supported annotations warning-free during field resolution.

    Nullable and list controls retain their existing wire types.
    """

    class SupportedInput(InputType):
        """Declare only supported scalar, optional, and list fields."""

        name: str
        maybe: int | None = None
        values: list[int]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(SupportedInput, name="SupportedInput").fields
    assert not [item for item in caught if item.category is UserWarning]
    assert {name: str(value.type) for name, value in fields.items()} == {
        "name": "String!",
        "maybe": "Int",
        "values": "[Int!]!",
    }
