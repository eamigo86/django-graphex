"""Public mutation regressions for exact float-set input spellings."""

from __future__ import annotations

import enum
import math
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


class FloatSetPepPayload(InputType):
    """Declare the exact PEP 585 float-set input."""

    amounts: set[float]


class FloatSetTypingPayload(InputType):
    """Declare the exact typing alias float-set input."""

    amounts: Set[float]  # noqa: UP006


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

    class EchoFloatSet(Mutation):
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
            mutation=GraphQLObjectType("MutationRoot", {"echo": EchoFloatSet.Field()}),
        ),
        received,
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [([1.5, 1.5, 2.0], {1.5, 2.0}), (2, {2.0})],
)
def test_float_sets_publish_list_and_reach_resolver_as_set(
    model: type[InputType], name: str, value: object, expected: set[float]
) -> None:
    """Both spellings use native list coercion and Python-set materialization."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(model, name=name)
        assert "amounts: [Float!]!" in print_schema(schema)
    assert not [item for item in caught if item.category is UserWarning]
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]
    assert type(received[0]["amounts"]) is set
    assert all(type(item) is float for item in received[0]["amounts"])


def test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback() -> None:
    """Custom equality must not admit an unrelated outer annotation."""

    class EqualToFloatSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the outer-annotation equality trap."""
            return other is Set[float] or type.__eq__(cls, other)  # noqa: UP006

    class CustomFloatScalar(metaclass=EqualToFloatSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom annotation while accepting a string."""
            return core_schema.str_schema()

    class FloatSetCustomOuterPayload(InputType):
        value: CustomFloatScalar

    assert (
        FloatSetCustomOuterPayload.model_fields["value"].annotation is CustomFloatScalar
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            FloatSetCustomOuterPayload, name="FloatSetCustomOuterPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: FloatSetCustomOuterPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


def test_custom_leaf_comparing_equal_to_float_keeps_fallback() -> None:
    """A custom set leaf is not the approved float despite equality."""

    class EqualToFloatMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf-equality trap."""
            return other is float or type.__eq__(cls, other)

    class CustomFloatLeaf(metaclass=EqualToFloatMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom leaf annotation while accepting a string."""
            return core_schema.str_schema()

    class FloatSetCustomLeafPayload(InputType):
        value: Set[CustomFloatLeaf]  # noqa: UP006

    assert (
        FloatSetCustomLeafPayload.model_fields["value"].annotation.__args__[0]
        is CustomFloatLeaf
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            FloatSetCustomLeafPayload, name="FloatSetCustomLeafPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: FloatSetCustomLeafPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


class NativeFloatChild(float):
    """Exercise a hashable float subclass accepted by native GraphQLFloat."""


class NativeIntChild(int):
    """Exercise a hashable int subclass accepted by native GraphQLFloat."""


class NativeIntEnum(enum.IntEnum):
    """Exercise a hashable integer enum accepted by native GraphQLFloat."""

    TWO = 2


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, {0.0}),
        ([], set()),
        ([1.5, 1.5, 2], {1.5, 2.0}),
        ([NativeFloatChild(1.5), NativeIntChild(2), NativeIntEnum.TWO], {1.5, 2.0}),
    ],
)
def test_native_numeric_variables_become_float_set(
    model: type[InputType], name: str, value: object, expected: set[float]
) -> None:
    """Retain zero and native-accepted numeric subclasses without recasting."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]
    assert type(received[0]["amounts"]) is set
    assert all(type(item) is float for item in received[0]["amounts"])


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("literal", "expected"),
    [("0", {0.0}), ("[]", set()), ("[1.5, 1.5, 2]", {1.5, 2.0})],
)
def test_inline_numeric_singleton_empty_and_duplicates(
    model: type[InputType], name: str, literal: str, expected: set[float]
) -> None:
    """Apply native list coercion and set conversion to inline Float literals."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}"
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    "value", [True, False, "1.5", math.nan, math.inf, -math.inf, {"x": 1.5}, [None]]
)
def test_invalid_native_float_variables_fail_before_resolver(
    model: type[InputType], name: str, value: object
) -> None:
    """Reject invalid supplied leaves before the resolver without casts."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    "literal",
    [
        "true",
        '"1.5"',
        "{x: 1.5}",
        "[null]",
        "1e999",
        "-1e999",
        "[1e999]",
        "[-1e999]",
    ],
)
def test_invalid_native_float_literals_fail_before_resolver(
    model: type[InputType], name: str, literal: str
) -> None:
    """Use native GraphQLFloat literal validation on public mutations."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("annotation", "name"),
    [
        (set[float], "FloatSetOverflowPepDefaults"),
        (Set[float], "FloatSetOverflowTypingDefaults"),  # noqa: UP006
    ],
)
def test_literal_overflow_rejects_even_with_malformed_legacy_defaults(
    annotation: object, name: str
) -> None:
    """Reject supplied overflow while retaining omitted malformed defaults."""
    model = type(
        name,
        (InputType,),
        {
            "__module__": __name__,
            "__annotations__": {"amounts": annotation, "factory_amounts": annotation},
            "amounts": [math.inf],
            "factory_amounts": Field(default_factory=lambda: [math.inf]),
        },
    )
    schema, received = _schema(model, name=name)
    omitted = graphql_sync(schema, "mutation { echo(payload: {}) { result } }")
    assert omitted.errors is None
    assert received == [{"amounts": [math.inf], "factory_amounts": [math.inf]}]
    for literal in ("1e999", "-1e999", "[1e999]", "[-1e999]"):
        supplied = graphql_sync(
            schema,
            f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}",
        )
        assert supplied.errors
        assert len(received) == 1
        supplied_factory = graphql_sync(
            schema,
            "mutation { echo(payload: {factoryAmounts: " + literal + "}) { result } }",
        )
        assert supplied_factory.errors
        assert len(received) == 1


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("literal", ["1e999", "-1e999"])
def test_overflowing_variable_default_never_reaches_resolver(
    model: type[InputType], name: str, literal: str
) -> None:
    """Reject a literal variable default before invoking the mutation."""
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        "mutation($amounts: [Float!]! = "
        + literal
        + ") { echo(payload: {amounts: $amounts}) { result } }",
    )
    assert result.errors
    assert "nonfinite Float" in str(result.errors[0])
    assert received == []


@pytest.mark.parametrize(
    ("annotation", "name"),
    [
        (set[float], "FloatSetOverflowPepPruned"),
        (Set[float], "FloatSetOverflowTypingPruned"),  # noqa: UP006
    ],
)
def test_literal_overflow_rejects_through_alias_and_pruned_clone(
    annotation: object, name: str
) -> None:
    """Keep fixed-default distinction on a surviving alias after pruning."""
    model = type(
        name,
        (InputType,),
        {
            "__module__": __name__,
            "__annotations__": {
                "visible_amounts": annotation,
                "hidden_amounts": annotation,
            },
            "visible_amounts": Field(alias="visible", default=[math.inf]),
            "hidden_amounts": Field(alias="hidden", default_factory=lambda: [math.inf]),
        },
    )
    full_input = compile_input_type(model, name=name)
    full_input.fields["hidden"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Record the surviving public input mapping.

        Args:
            _root: Unused query root.
            _info: Unused execution context.
            payload: Coerced input mapping.

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
    assert set(pruned.type_map[name].fields) == {"visible"}
    omitted = graphql_sync(pruned, "query { probe(payload: {}) }")
    assert omitted.errors is None
    assert received == [{"visible_amounts": [math.inf]}]
    supplied = graphql_sync(pruned, "query { probe(payload: {visible: 1e999}) }")
    assert supplied.errors
    assert len(received) == 1


def test_exact_float_sets_have_list_introspection_without_warning() -> None:
    """Both approved spellings publish non-null Float list items."""
    for model, name in (
        (FloatSetPepPayload, "FloatSetPepPayload"),
        (FloatSetTypingPayload, "FloatSetTypingPayload"),
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            schema, _received = _schema(model, name=name)
            result = graphql_sync(
                schema,
                '{ __type(name: "'
                + name
                + '") { inputFields { name type { kind ofType { kind ofType { kind name } } } } } }',
            )
        assert result.errors is None
        assert not [item for item in caught if item.category is UserWarning]
        assert result.data["__type"]["inputFields"] == [
            {
                "name": "amounts",
                "type": {
                    "kind": "NON_NULL",
                    "ofType": {
                        "kind": "LIST",
                        "ofType": {"kind": "NON_NULL", "name": None},
                    },
                },
            }
        ]


def test_required_float_set_rejects_omission() -> None:
    """Retain required-field semantics for approved exact annotations."""
    schema, received = _schema(FloatSetPepPayload, name="FloatSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: FloatSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_optional_float_sets_keep_omission_and_null() -> None:
    """Preserve outer Optional and explicit-null behavior for both spellings."""

    class FloatSetOptionalPayload(InputType):
        pep_amounts: set[float] | None = None
        alias_amounts: Set[float] | None = None  # noqa: UP006

    schema, received = _schema(FloatSetOptionalPayload, name="FloatSetOptionalPayload")
    sdl = print_schema(schema)
    assert "pepAmounts: [Float!] = null" in sdl
    assert "aliasAmounts: [Float!] = null" in sdl
    query = "mutation($payload: FloatSetOptionalPayload!) { echo(payload: $payload) { result } }"
    for payload in (
        {},
        {"pepAmounts": None, "aliasAmounts": None},
        {"pepAmounts": [1.5], "aliasAmounts": 0},
    ):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"pep_amounts": None, "alias_amounts": None},
        {"pep_amounts": None, "alias_amounts": None},
        {"pep_amounts": {1.5}, "alias_amounts": {0.0}},
    ]


def test_fixed_and_factory_defaults_keep_lifecycle() -> None:
    """Retain valid fixed sets and fresh per-object factory defaults."""
    calls: list[int] = []

    def make_set() -> set[float]:
        """Return a fresh Float set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {float(calls[-1])}

    class FloatSetDefaultsPayload(InputType):
        pep_amounts: set[float] = {1.5, 2.0}
        alias_amounts: Set[float] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(FloatSetDefaultsPayload, name="FloatSetDefaultsPayload")
    assert calls == []
    query = "mutation($payload: FloatSetDefaultsPayload!) { echo(payload: $payload) { result } }"
    for _ in range(2):
        assert (
            graphql_sync(schema, query, variable_values={"payload": {}}).errors is None
        )
    assert calls == [1, 2]
    assert received == [
        {"pep_amounts": {1.5, 2.0}, "alias_amounts": {1.0}},
        {"pep_amounts": {1.5, 2.0}, "alias_amounts": {2.0}},
    ]
    assert all(type(item["pep_amounts"]) is set for item in received)


def test_alias_selection_replacement_and_pruning_project_metadata() -> None:
    """Convert only emitted and permission-surviving resolver out-names."""

    class FloatSetSelectionPayload(InputType):
        kept_amounts: set[float] = Field(alias="keptAmounts")
        removed_amounts: Set[float] | None = None  # noqa: UP006

    selected = compile_input_type(
        FloatSetSelectionPayload,
        name="FloatSetSelectedPayload",
        only_fields=("kept_amounts",),
        exclude_fields=("removed_amounts",),
    )
    assert set(selected.fields) == {"keptAmounts"}
    assert selected.out_type.set_float_fields == {"kept_amounts"}
    included = compile_input_type(
        FloatSetSelectionPayload,
        name="FloatSetIncludedPayload",
        only_fields=("kept_amounts",),
        exclude_fields=("removed_amounts",),
        include_fields=("removed_amounts",),
    )
    assert set(included.fields) == {"keptAmounts", "removedAmounts"}
    assert included.out_type.set_float_fields == {"kept_amounts", "removed_amounts"}
    replaced = compile_input_type(
        FloatSetSelectionPayload,
        name="FloatSetReplacedPayload",
        relation_fields=(
            RelationInputField(
                out_name="removed_amounts",
                alias="removedAmounts",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedAmounts"].type) == "ID"
    assert replaced.out_type.set_float_fields == {"kept_amounts"}

    full_input = compile_input_type(
        FloatSetSelectionPayload, name="FloatSetPrunedPayload"
    )
    full_input.fields["removedAmounts"].extensions = {
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
    clone = pruned.type_map["FloatSetPrunedPayload"]
    assert set(clone.fields) == {"keptAmounts"}
    assert clone.out_type.set_float_fields == {"kept_amounts"}
    result = graphql_sync(
        pruned,
        "query($payload: FloatSetPrunedPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"keptAmounts": [0, 0.0, 1.5]}},
    )
    assert result.errors is None
    assert received == [{"kept_amounts": {0.0, 1.5}}]


def test_other_set_leaves_and_nested_forms_keep_fallback() -> None:
    """Do not promote unapproved leaves, bare sets or nested set forms."""

    class FloatSetUnsupportedPayload(InputType):
        pep_bytes: set[bytes]
        alias_bytes: Set[bytes]  # noqa: UP006
        nested: list[set[float]]
        bare: set

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            FloatSetUnsupportedPayload, name="FloatSetUnsupportedPayload"
        ).fields
    assert {key: str(value.type) for key, value in fields.items()} == {
        "pepBytes": "String!",
        "aliasBytes": "String!",
        "nested": "[String!]!",
        "bare": "String!",
    }
    assert len([item for item in caught if item.category is UserWarning]) >= 3
