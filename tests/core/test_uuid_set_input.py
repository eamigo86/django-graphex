"""Public mutation regressions for exact UUID-set input annotations."""

from __future__ import annotations

import uuid
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
from pydantic_core import core_schema

from django_graphex.core import InputType, field
from django_graphex.core.input_compiler import RelationInputField, compile_input_type
from django_graphex.core.mutation import Mutation
from django_graphex.core.schema_pruner import prune_schema


class UUIDSetPepPayload(InputType):
    """Declare the exact PEP 585 UUID-set input."""

    values: set[uuid.UUID]


class UUIDSetTypingPayload(InputType):
    """Declare the exact typing alias UUID-set input."""

    values: Set[uuid.UUID]  # noqa: UP006


def _schema(
    model: type[InputType], *, name: str
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Mount a compiled input on a public mutation and capture resolver values.

    Args:
        model: Input model under test.
        name: Unique GraphQL input type name.

    Returns:
        Schema and captured resolver input mappings.
    """
    received: list[dict[str, object]] = []
    input_type = compile_input_type(model, name=name)

    class EchoUUIDSet(Mutation):
        """Capture the public mutation input."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled input type."""

            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Record resolver values and return success.

            Args:
                _root: Unused root.
                _info: Unused execution context.
                payload: GraphQL-coerced input.

            Returns:
                Mutation result.
            """
            received.append(payload.copy())
            return {"result": "ok"}

    return (
        GraphQLSchema(
            query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
            mutation=GraphQLObjectType("MutationRoot", {"echo": EchoUUIDSet.Field()}),
        ),
        received,
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            ["12345678-1234-5678-1234-567812345678"] * 2,
            {uuid.UUID("12345678-1234-5678-1234-567812345678")},
        ),
        (
            "12345678123456781234567812345678",
            {uuid.UUID("12345678123456781234567812345678")},
        ),
    ],
)
def test_uuid_sets_publish_list_and_reach_resolver_as_set(
    model: type[InputType], name: str, value: object, expected: set[uuid.UUID]
) -> None:
    """Both spellings use native UUID coercion and Python-set materialization."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(model, name=name)
        assert "values: [UUID!]!" in print_schema(schema)
    assert not [item for item in caught if item.category is UserWarning]
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"values": value}},
    )
    assert result.errors is None
    assert received == [{"values": expected}]
    assert type(received[0]["values"]) is set
    assert all(type(item) is uuid.UUID for item in received[0]["values"])


def test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback() -> None:
    """Custom outer equality must not admit an unrelated annotation."""

    class EqualToUUIDSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the outer-annotation equality trap."""
            return other is Set[uuid.UUID] or type.__eq__(cls, other)  # noqa: UP006

    class CustomUUIDScalar(metaclass=EqualToUUIDSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom annotation while accepting a string."""
            return core_schema.str_schema()

    class UUIDSetCustomOuterPayload(InputType):
        value: CustomUUIDScalar

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            UUIDSetCustomOuterPayload, name="UUIDSetCustomOuterPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: UUIDSetCustomOuterPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


def test_custom_leaf_comparing_equal_to_uuid_keeps_fallback() -> None:
    """A custom set leaf is not UUID despite equality."""

    class EqualToUUIDMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf-equality trap."""
            return other is uuid.UUID or type.__eq__(cls, other)

    class CustomUUIDLeaf(metaclass=EqualToUUIDMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom leaf annotation while accepting a string."""
            return core_schema.str_schema()

    class UUIDSetCustomLeafPayload(InputType):
        value: Set[CustomUUIDLeaf]  # noqa: UP006

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            UUIDSetCustomLeafPayload, name="UUIDSetCustomLeafPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: UUIDSetCustomLeafPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


class NativeUUIDChild(uuid.UUID):
    """Exercise a native-accepted UUID subclass variable."""


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([], set()),
        (uuid.UUID(int=0), {uuid.UUID(int=0)}),
        (NativeUUIDChild(int=1), {uuid.UUID(int=1)}),
        (
            [
                "ABCDEFAB-1234-5678-ABCD-567812345678",
                "abcdefab12345678abcd567812345678",
            ],
            {uuid.UUID("abcdefab-1234-5678-abcd-567812345678")},
        ),
    ],
)
def test_native_uuid_variables_reach_resolver_as_exact_uuid_set(
    model: type[InputType], name: str, value: object, expected: set[uuid.UUID]
) -> None:
    """Honor native UUID normalization, subclasses, zero and deduplication."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"values": value}},
    )
    assert result.errors is None
    assert received == [{"values": expected}]
    assert all(type(item) is uuid.UUID for item in received[0]["values"])


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        (
            '"12345678123456781234567812345678"',
            {uuid.UUID("12345678123456781234567812345678")},
        ),
        ("[]", set()),
        (
            '["ABCDEFAB-1234-5678-ABCD-567812345678", "abcdefab12345678abcd567812345678"]',
            {uuid.UUID("abcdefab-1234-5678-abcd-567812345678")},
        ),
    ],
)
def test_native_uuid_literals_use_list_coercion(
    model: type[InputType], name: str, literal: str, expected: set[uuid.UUID]
) -> None:
    """Apply native UUID and list coercion to inline mutation literals."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{values: {literal}}}) {{ result }} }}"
    )
    assert result.errors is None
    assert received == [{"values": expected}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("value", ["invalid", "", True, 1, {"x": 1}, [None]])
def test_invalid_uuid_variables_reject_before_mutation(
    model: type[InputType], name: str, value: object
) -> None:
    """Reject invalid native UUID leaves without resolver execution."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"values": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("literal", ['"invalid"', "true", "1", "{x: 1}", "[null]"])
def test_invalid_uuid_literals_reject_before_mutation(
    model: type[InputType], name: str, literal: str
) -> None:
    """Keep native UUID literal validation ahead of mutation execution."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{values: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


def test_uuid_sets_introspect_as_non_null_uuid_lists() -> None:
    """Publish the exact UUID scalar and required list wrappers."""
    for model, name in (
        (UUIDSetPepPayload, "UUIDSetPepPayload"),
        (UUIDSetTypingPayload, "UUIDSetTypingPayload"),
    ):
        schema, _received = _schema(model, name=name)
        result = graphql_sync(
            schema,
            '{ __type(name: "'
            + name
            + '") { inputFields { name type { kind ofType { kind ofType { kind name } } } } } }',
        )
        assert result.errors is None
        assert result.data["__type"]["inputFields"] == [
            {
                "name": "values",
                "type": {
                    "kind": "NON_NULL",
                    "ofType": {
                        "kind": "LIST",
                        "ofType": {"kind": "NON_NULL", "name": None},
                    },
                },
            }
        ]


def test_required_uuid_set_rejects_omission() -> None:
    """Keep required-field semantics for exact UUID sets."""
    schema, received = _schema(UUIDSetPepPayload, name="UUIDSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: UUIDSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_optional_uuid_sets_keep_omission_and_null() -> None:
    """Preserve outer Optional and explicit null for both spellings."""

    class UUIDSetOptionalPayload(InputType):
        pep_values: set[uuid.UUID] | None = None
        alias_values: Set[uuid.UUID] | None = None  # noqa: UP006

    schema, received = _schema(UUIDSetOptionalPayload, name="UUIDSetOptionalPayload")
    sdl = print_schema(schema)
    assert "pepValues: [UUID!] = null" in sdl
    assert "aliasValues: [UUID!] = null" in sdl
    query = "mutation($payload: UUIDSetOptionalPayload!) { echo(payload: $payload) { result } }"
    for payload in (
        {},
        {"pepValues": None, "aliasValues": None},
        {
            "pepValues": ["12345678123456781234567812345678"],
            "aliasValues": "abcdefab12345678abcd567812345678",
        },
    ):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"pep_values": None, "alias_values": None},
        {"pep_values": None, "alias_values": None},
        {
            "pep_values": {uuid.UUID("12345678123456781234567812345678")},
            "alias_values": {uuid.UUID("abcdefab12345678abcd567812345678")},
        },
    ]


def test_fixed_and_factory_uuid_defaults_keep_lifecycle() -> None:
    """Retain valid fixed sets and fresh per-object factory defaults."""
    calls: list[int] = []

    def make_set() -> set[uuid.UUID]:
        """Return a fresh UUID set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {uuid.UUID(int=calls[-1])}

    class UUIDSetDefaultsPayload(InputType):
        pep_values: set[uuid.UUID] = {uuid.UUID(int=0)}
        alias_values: Set[uuid.UUID] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(UUIDSetDefaultsPayload, name="UUIDSetDefaultsPayload")
    assert calls == []
    query = "mutation($payload: UUIDSetDefaultsPayload!) { echo(payload: $payload) { result } }"
    for _ in range(2):
        assert (
            graphql_sync(schema, query, variable_values={"payload": {}}).errors is None
        )
    assert calls == [1, 2]
    assert received == [
        {"pep_values": {uuid.UUID(int=0)}, "alias_values": {uuid.UUID(int=1)}},
        {"pep_values": {uuid.UUID(int=0)}, "alias_values": {uuid.UUID(int=2)}},
    ]


def test_malformed_legacy_uuid_defaults_remain_unchanged() -> None:
    """Avoid extending validation to malformed omitted defaults or factories."""

    class UUIDSetLegacyDefaultsPayload(InputType):
        fixed_values: set[uuid.UUID] = ["legacy"]
        factory_values: Set[uuid.UUID] = Field(default_factory=lambda: ["legacy"])  # noqa: UP006

    schema, received = _schema(
        UUIDSetLegacyDefaultsPayload, name="UUIDSetLegacyDefaultsPayload"
    )
    omitted = graphql_sync(schema, "mutation { echo(payload: {}) { result } }")
    assert omitted.errors is None
    assert received == [{"fixed_values": ["legacy"], "factory_values": ["legacy"]}]
    supplied = graphql_sync(
        schema, 'mutation { echo(payload: {fixedValues: "invalid"}) { result } }'
    )
    assert supplied.errors
    assert len(received) == 1


def test_alias_selection_replacement_and_pruning_project_uuid_metadata() -> None:
    """Convert only emitted and permission-surviving resolver out-names."""

    class UUIDSetSelectionPayload(InputType):
        kept_values: set[uuid.UUID] = Field(alias="keptValues")
        removed_values: Set[uuid.UUID] | None = None  # noqa: UP006

    selected = compile_input_type(
        UUIDSetSelectionPayload,
        name="UUIDSetSelectedPayload",
        only_fields=("kept_values",),
        exclude_fields=("removed_values",),
    )
    assert set(selected.fields) == {"keptValues"}
    assert selected.out_type.set_uuid_fields == {"kept_values"}
    included = compile_input_type(
        UUIDSetSelectionPayload,
        name="UUIDSetIncludedPayload",
        only_fields=("kept_values",),
        exclude_fields=("removed_values",),
        include_fields=("removed_values",),
    )
    assert set(included.fields) == {"keptValues", "removedValues"}
    assert included.out_type.set_uuid_fields == {"kept_values", "removed_values"}
    replaced = compile_input_type(
        UUIDSetSelectionPayload,
        name="UUIDSetReplacedPayload",
        relation_fields=(
            RelationInputField(
                out_name="removed_values",
                alias="removedValues",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedValues"].type) == "ID"
    assert replaced.out_type.set_uuid_fields == {"kept_values"}

    full_input = compile_input_type(
        UUIDSetSelectionPayload, name="UUIDSetPrunedPayload"
    )
    full_input.fields["removedValues"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the permission-pruned input mapping.

        Args:
            _root: Unused query root.
            _info: Unused execution context.
            payload: Pruned GraphQL input mapping.

        Returns:
            Query result.
        """
        received.append(payload.copy())
        return "ok"

    full = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(full_input)},
                    resolve=resolve,
                )
            },
        )
    )
    pruned = prune_schema(full, frozenset())
    clone = pruned.type_map["UUIDSetPrunedPayload"]
    assert set(clone.fields) == {"keptValues"}
    assert clone.out_type.set_uuid_fields == {"kept_values"}
    result = graphql_sync(
        pruned,
        "query($payload: UUIDSetPrunedPayload) { probe(payload: $payload) }",
        variable_values={
            "payload": {"keptValues": ["12345678123456781234567812345678"] * 2}
        },
    )
    assert result.errors is None
    assert received == [
        {"kept_values": {uuid.UUID("12345678123456781234567812345678")}}
    ]


def test_other_set_leaves_and_nested_forms_keep_fallback() -> None:
    """Do not promote unapproved leaves, bare sets or nested set forms."""

    class UUIDSetUnsupportedPayload(InputType):
        pep_bytes: set[bytes]
        alias_bytes: Set[bytes]  # noqa: UP006
        nested: list[set[uuid.UUID]]
        bare: set

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            UUIDSetUnsupportedPayload, name="UUIDSetUnsupportedPayload"
        ).fields
    assert {key: str(value.type) for key, value in fields.items()} == {
        "pepBytes": "String!",
        "aliasBytes": "String!",
        "nested": "[String!]!",
        "bare": "String!",
    }
    assert len([item for item in caught if item.category is UserWarning]) >= 3
