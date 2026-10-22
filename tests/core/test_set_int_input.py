"""Public GraphQL input contract for exact ``set[int]`` annotations."""

from __future__ import annotations

import warnings
from typing import Set

import pytest
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
from pydantic import Field

from django_graphex.core import InputType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.mutation import Mutation
from django_graphex.core.schema_pruner import prune_schema


class SetIntRedPayload(InputType):
    """Expose the approved exact set annotation once per test module."""

    numbers: set[int]


def _set_schema(
    model: type[InputType] | None = None, *, name: str = "SetIntRedPayload"
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Build a public mutation and retain its resolver-facing values."""
    received: list[dict[str, object]] = []

    input_type = compile_input_type(model or SetIntRedPayload, name=name)

    class EchoSetIntRed(Mutation):
        """Capture coerced input without Pydantic model validation."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled input to a public mutation."""

            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Capture the input GraphQL passes to the mutation resolver.

            Args:
                _root: Unused root object.
                _info: Unused execution context.
                payload: GraphQL-coerced input mapping.

            Returns:
                A successful mutation payload.
            """
            received.append(payload.copy())
            return {"result": "ok"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("MutationRoot", {"echo": EchoSetIntRed.Field()}),
    )
    return schema, received


def test_exact_set_int_prints_int_list() -> None:
    """Expose the approved Int list rather than the legacy String fallback."""
    schema, _received = _set_schema()
    assert "numbers: [Int!]!" in print_schema(schema)


def test_set_int_variable_is_deduplicated_for_resolver() -> None:
    """Deliver a Python set after GraphQL accepts an integer list."""
    schema, received = _set_schema()
    result = graphql_sync(
        schema,
        "mutation($payload: SetIntRedPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert result.data == {"echo": {"result": "ok"}}
    assert received == [{"numbers": {1, 2}}]
    assert type(received[0]["numbers"]) is set


@pytest.mark.parametrize("value", [3, [3], 3.0])
def test_graphql_singleton_coercion_yields_python_set(value: object) -> None:
    """Use ordinary list coercion for scalar variables and deduplicate lists."""
    schema, received = _set_schema()
    result = graphql_sync(
        schema,
        "mutation($payload: SetIntRedPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": value}},
    )
    assert result.errors is None
    assert received == [{"numbers": {3}}]
    assert type(received[0]["numbers"]) is set


def test_inline_set_int_values_use_the_same_boundary() -> None:
    """Coerce inline scalar/list values before resolver set materialization."""
    schema, received = _set_schema()
    scalar = graphql_sync(schema, "mutation { echo(payload: {numbers: 3}) { result } }")
    array = graphql_sync(
        schema, "mutation { echo(payload: {numbers: [2, 1, 2]}) { result } }"
    )
    assert scalar.errors is None
    assert array.errors is None
    assert received == [{"numbers": {3}}, {"numbers": {1, 2}}]


@pytest.mark.parametrize("value", [True, "3", 3.5, [True], ["3"], [None], [2147483648]])
def test_invalid_variable_int_values_fail_before_resolver(value: object) -> None:
    """Leave validation to GraphQLInt with no boolean or string casting."""
    schema, received = _set_schema()
    result = graphql_sync(
        schema,
        "mutation($payload: SetIntRedPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize("literal", ["true", '"3"', "3.0", "[null]"])
def test_invalid_inline_int_values_fail_before_resolver(literal: str) -> None:
    """Reject invalid inline literals before the mutation resolver runs."""
    schema, received = _set_schema()
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{numbers: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


def test_optional_set_int_keeps_null_and_omission_defaults() -> None:
    """Preserve the existing outer Optional and explicit-null behavior."""

    class OptionalSetIntPayload(InputType):
        """Expose a nullable approved set field."""

        numbers: set[int] | None = None

    schema, received = _set_schema(OptionalSetIntPayload, name="OptionalSetIntPayload")
    assert "numbers: [Int!] = null" in print_schema(schema)
    query = (
        "mutation($payload: OptionalSetIntPayload!) "
        "{ echo(payload: $payload) { result } }"
    )
    for payload in ({}, {"numbers": None}, {"numbers": [2, 1, 2]}):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"numbers": None},
        {"numbers": None},
        {"numbers": {1, 2}},
    ]


def test_fixed_set_default_and_fresh_factory_keep_existing_lifecycle() -> None:
    """Keep fixed/default-factory values usable without freezing factories."""
    calls: list[int] = []

    def make_set() -> set[int]:
        """Build a distinct set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {calls[-1]}

    class DefaultSetIntPayload(InputType):
        """Mix a concrete set default and a fresh factory default."""

        numbers: set[int] = {2, 1}
        fresh_numbers: set[int] = Field(default_factory=make_set)

    schema, received = _set_schema(DefaultSetIntPayload, name="DefaultSetIntPayload")
    assert calls == []
    query = (
        "mutation($payload: DefaultSetIntPayload!) "
        "{ echo(payload: $payload) { result } }"
    )
    for _ in range(2):
        result = graphql_sync(schema, query, variable_values={"payload": {}})
        assert result.errors is None
    assert calls == [1, 2]
    assert received == [
        {"numbers": {1, 2}, "fresh_numbers": {1}},
        {"numbers": {1, 2}, "fresh_numbers": {2}},
    ]
    assert all(type(item["numbers"]) is set for item in received)
    assert all(type(item["fresh_numbers"]) is set for item in received)


def test_set_field_uses_wire_alias_and_snake_resolver_name() -> None:
    """Register conversion against the emitted field and its out-name."""

    class AliasSetIntPayload(InputType):
        """Expose a multiword set field through its public alias."""

        chosen_numbers: set[int] = Field(alias="chosenNumbers")

    schema, received = _set_schema(AliasSetIntPayload, name="AliasSetIntPayload")
    assert "chosenNumbers: [Int!]!" in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation($payload: AliasSetIntPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"chosenNumbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert received == [{"chosen_numbers": {1, 2}}]


def test_permission_clone_keeps_only_surviving_set_conversion() -> None:
    """Convert a visible set and never inspect a permission-hidden one."""

    class ScopedSetIntPayload(InputType):
        """Expose a public set beside a restricted set."""

        public_numbers: set[int]
        hidden_numbers: set[int] | None = None

    input_type = compile_input_type(ScopedSetIntPayload, name="ScopedSetIntPayload")
    input_type.fields["hiddenNumbers"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the permission-scoped resolver mapping."""
        received.append(payload.copy())
        return "ok"

    full = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    pruned = prune_schema(full, frozenset())
    clone = pruned.type_map["ScopedSetIntPayload"]
    assert set(clone.fields) == {"publicNumbers"}
    assert clone.out_type.set_int_fields == {"public_numbers"}
    result = graphql_sync(
        pruned,
        "query($payload: ScopedSetIntPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"publicNumbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert received == [{"public_numbers": {1, 2}}]


def test_unapproved_set_forms_keep_legacy_fallback() -> None:
    """Do not expand the approval to other spellings, leaves or wrappers."""

    class UnsupportedSetPayload(InputType):
        """Collect representative unapproved container annotations."""

        typing_alias: Set[int]  # noqa: UP006
        string_set: set[str]
        wrapped_set: list[set[int]]
        nested_set: list[list[set[int]]]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            UnsupportedSetPayload, name="UnsupportedSetPayload"
        ).fields
    assert {key: str(item.type) for key, item in fields.items()} == {
        "typingAlias": "String!",
        "stringSet": "String!",
        "wrappedSet": "[String!]!",
        "nestedSet": "[String!]!",
    }
    assert len([item for item in caught if item.category is UserWarning]) == 4
