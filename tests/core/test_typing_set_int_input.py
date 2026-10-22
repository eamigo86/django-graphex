"""Public GraphQL input contract for exact ``typing.Set[int]`` annotations."""

from __future__ import annotations

import warnings
from typing import Optional, Set

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
from pydantic_core import core_schema

from django_graphex.core import InputType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.mutation import Mutation
from django_graphex.core.schema_pruner import prune_schema


class TypingSetIntPayload(InputType):
    """Expose the one approved typing alias on a public mutation."""

    numbers: Set[int]  # noqa: UP006


def _schema(
    model: type[InputType] = TypingSetIntPayload, *, name: str = "TypingSetIntPayload"
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Build a mutation and capture its resolver-facing mapping."""
    received: list[dict[str, object]] = []
    input_type = compile_input_type(model, name=name)

    class EchoTypingSetInt(Mutation):
        """Return success after capturing the input."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled input to the public mutation."""

            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Capture the value delivered by GraphQL to the resolver.

            Args:
                _root: Unused mutation root.
                _info: Unused GraphQL execution context.
                payload: Coerced input mapping.

            Returns:
                A successful mutation result.
            """
            received.append(payload.copy())
            return {"result": "ok"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("MutationRoot", {"echo": EchoTypingSetInt.Field()}),
    )
    return schema, received


def test_typing_set_int_prints_int_list() -> None:
    """Publish the approved input list rather than the String fallback."""
    schema, _received = _schema()
    assert "numbers: [Int!]!" in print_schema(schema)


def test_typing_set_int_list_reaches_resolver_as_set() -> None:
    """Deduplicate a supplied list into the resolver's actual Python set."""
    schema, received = _schema()
    result = graphql_sync(
        schema,
        "mutation($payload: TypingSetIntPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert result.data == {"echo": {"result": "ok"}}
    assert received == [{"numbers": {1, 2}}]
    assert type(received[0]["numbers"]) is set


@pytest.mark.parametrize("value", [3, [3], 3.0, []])
def test_typing_set_int_variable_uses_native_list_coercion(value: object) -> None:
    """Keep native singleton and integral-float variable behavior."""
    schema, received = _schema()
    result = graphql_sync(
        schema,
        "mutation($payload: TypingSetIntPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": value}},
    )
    assert result.errors is None
    expected = set() if value == [] else {3}
    assert received == [{"numbers": expected}]
    assert type(received[0]["numbers"]) is set


def test_typing_set_int_inline_values_use_native_coercion() -> None:
    """Coerce inline scalar and duplicate-list inputs before resolution."""
    schema, received = _schema()
    for literal in ("3", "[2, 1, 2]"):
        result = graphql_sync(
            schema, f"mutation {{ echo(payload: {{numbers: {literal}}}) {{ result }} }}"
        )
        assert result.errors is None
    assert received == [{"numbers": {3}}, {"numbers": {1, 2}}]


@pytest.mark.parametrize("value", [True, "3", 3.5, [None], [True], ["3"], [2147483648]])
def test_invalid_typing_set_int_variable_fails_before_resolver(value: object) -> None:
    """Use strict native GraphQLInt validation without custom casts."""
    schema, received = _schema()
    result = graphql_sync(
        schema,
        "mutation($payload: TypingSetIntPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"numbers": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize("literal", ["true", '"3"', "3.0", "[null]"])
def test_invalid_typing_set_int_literal_fails_before_resolver(literal: str) -> None:
    """Reject an invalid inline item before mutation execution."""
    schema, received = _schema()
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{numbers: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


def test_typing_set_int_optional_omission_and_null_are_unchanged() -> None:
    """Retain the established outer Optional and default behavior."""

    class OptionalTypingSetPayload(InputType):
        """Expose a nullable typing alias."""

        numbers: Optional[Set[int]] = None  # noqa: UP006, UP045

    schema, received = _schema(
        OptionalTypingSetPayload, name="OptionalTypingSetPayload"
    )
    assert "numbers: [Int!] = null" in print_schema(schema)
    query = (
        "mutation($payload: OptionalTypingSetPayload!) "
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


def test_typing_set_int_required_field_stays_required() -> None:
    """Reject omission of a required typing alias field."""
    schema, received = _schema()
    result = graphql_sync(
        schema,
        "mutation($payload: TypingSetIntPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_typing_set_int_fixed_and_factory_defaults_keep_lifecycle() -> None:
    """Keep fixed defaults and fresh omitted-field factories separate."""
    calls: list[int] = []

    def make_set() -> set[int]:
        """Return a fresh set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {calls[-1]}

    class DefaultTypingSetPayload(InputType):
        """Expose fixed and factory-backed typing aliases."""

        numbers: Set[int] = {2, 1}  # noqa: UP006
        fresh_numbers: Set[int] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(DefaultTypingSetPayload, name="DefaultTypingSetPayload")
    assert calls == []
    query = (
        "mutation($payload: DefaultTypingSetPayload!) "
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


def test_typing_set_int_alias_uses_resolver_field_name() -> None:
    """Materialize the set under the emitted field's snake out-name."""

    class AliasTypingSetPayload(InputType):
        """Use an explicit multiword wire alias."""

        chosen_numbers: Set[int] = Field(alias="chosenNumbers")  # noqa: UP006

    schema, received = _schema(AliasTypingSetPayload, name="AliasTypingSetPayload")
    assert "chosenNumbers: [Int!]!" in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation($payload: AliasTypingSetPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"chosenNumbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert received == [{"chosen_numbers": {1, 2}}]


def test_pruned_typing_set_int_metadata_keeps_only_visible_field() -> None:
    """Project the existing set conversion through permission pruning."""

    class ScopedTypingSetPayload(InputType):
        """Expose one public and one restricted typing alias."""

        public_numbers: Set[int]  # noqa: UP006
        hidden_numbers: Optional[Set[int]] = None  # noqa: UP006, UP045

    input_type = compile_input_type(
        ScopedTypingSetPayload, name="ScopedTypingSetPayload"
    )
    input_type.fields["hiddenNumbers"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the permission-scoped resolver mapping.

        Args:
            _root: Unused query root.
            _info: Unused GraphQL execution context.
            payload: Input mapping after permission pruning.

        Returns:
            A successful query result.
        """
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
    clone = pruned.type_map["ScopedTypingSetPayload"]
    assert set(clone.fields) == {"publicNumbers"}
    assert clone.out_type.set_int_fields == {"public_numbers"}
    result = graphql_sync(
        pruned,
        "query($payload: ScopedTypingSetPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"publicNumbers": [2, 1, 2]}},
    )
    assert result.errors is None
    assert received == [{"public_numbers": {1, 2}}]


def test_typing_set_int_emits_no_fallback_warning() -> None:
    """Distinguish the approved typing alias from other set fallbacks."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            TypingSetIntPayload, name="TypingSetIntPayload"
        ).fields
    assert str(fields["numbers"].type) == "[Int!]!"
    assert not [item for item in caught if item.category is UserWarning]


def test_unrelated_custom_scalar_equality_keeps_string_fallback() -> None:
    """Do not compare an unrelated annotation with the approved typing alias."""

    class EqualToTypingSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the equality trap without changing class identity."""
            return other is Set[int] or type.__eq__(cls, other)  # noqa: UP006

    class EqualityScalar(metaclass=EqualToTypingSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Accept a string while retaining this exact field annotation."""
            return core_schema.str_schema()

    class EqualityScalarPayload(InputType):
        value: EqualityScalar

    assert EqualityScalarPayload.model_fields["value"].annotation is EqualityScalar
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(EqualityScalarPayload, name="EqualityScalarPayload")
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    query = "mutation($payload: EqualityScalarPayload!) { echo(payload: $payload) { result } }"
    accepted = graphql_sync(
        schema, query, variable_values={"payload": {"value": "legacy"}}
    )
    rejected = graphql_sync(
        schema, query, variable_values={"payload": {"value": [2, 1, 2]}}
    )
    assert accepted.errors is None
    assert received == [{"value": "legacy"}]
    assert rejected.errors


def test_typing_set_custom_leaf_equality_keeps_string_fallback() -> None:
    """Do not admit a typing set whose leaf only compares equal to int."""

    class EqualToIntMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf equality trap without making it int."""
            return other is int or type.__eq__(cls, other)

    class EqualityLeaf(metaclass=EqualToIntMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Accept a string while retaining this exact set leaf."""
            return core_schema.str_schema()

    class EqualityLeafPayload(InputType):
        value: Set[EqualityLeaf]  # noqa: UP006

    assert (
        EqualityLeafPayload.model_fields["value"].annotation.__args__[0] is EqualityLeaf
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(EqualityLeafPayload, name="EqualityLeafPayload")
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    query = "mutation($payload: EqualityLeafPayload!) { echo(payload: $payload) { result } }"
    accepted = graphql_sync(
        schema, query, variable_values={"payload": {"value": "legacy"}}
    )
    rejected = graphql_sync(
        schema, query, variable_values={"payload": {"value": [2, 1, 2]}}
    )
    assert accepted.errors is None
    assert received == [{"value": "legacy"}]
    assert rejected.errors
