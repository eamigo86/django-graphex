"""Public mutation regressions for exact finite Decimal-set input spellings."""

from __future__ import annotations

import decimal
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


class DecimalSetPepPayload(InputType):
    """Declare the exact PEP 585 Decimal-set input.

    The field uses the builtin set spelling.
    """

    amounts: set[decimal.Decimal]


class DecimalSetTypingPayload(InputType):
    """Declare the exact typing alias Decimal-set input.

    The field uses the typing.Set spelling.
    """

    amounts: Set[decimal.Decimal]  # noqa: UP006


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

    class EchoDecimalSet(Mutation):
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
            mutation=GraphQLObjectType(
                "MutationRoot", {"echo": EchoDecimalSet.Field()}
            ),
        ),
        received,
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DecimalSetPepPayload, "DecimalSetPepPayload"),
        (DecimalSetTypingPayload, "DecimalSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["10.10", "10.10", "2.0"], {decimal.Decimal("10.10"), decimal.Decimal("2.0")}),
        ("1E+999999", {decimal.Decimal("1E+999999")}),
    ],
)
def test_decimal_sets_publish_list_and_reach_resolver_as_set(
    model: type[InputType],
    name: str,
    value: object,
    expected: set[decimal.Decimal],
) -> None:
    """Both spellings preserve native precision and Python-set materialization.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
        expected: Result the parametrized case expects.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(model, name=name)
        assert "amounts: [Decimal!]!" in print_schema(schema)
    assert not [item for item in caught if item.category is UserWarning]
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]
    assert type(received[0]["amounts"]) is set
    assert all(type(item) is decimal.Decimal for item in received[0]["amounts"])


def test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback() -> None:
    """Custom equality must not admit an unrelated outer annotation.

    Scenario: custom outer annotation comparing equal to alias keeps fallback.
    """

    class EqualToDecimalSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the outer-annotation equality trap."""
            return other is Set[decimal.Decimal] or type.__eq__(cls, other)  # noqa: UP006

    class CustomDecimalScalar(metaclass=EqualToDecimalSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom annotation while accepting a string."""
            return core_schema.str_schema()

    class DecimalSetCustomOuterPayload(InputType):
        value: CustomDecimalScalar

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            DecimalSetCustomOuterPayload, name="DecimalSetCustomOuterPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: DecimalSetCustomOuterPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


def test_custom_leaf_comparing_equal_to_decimal_keeps_fallback() -> None:
    """A custom set leaf is not Decimal despite equality.

    Scenario: custom leaf comparing equal to decimal keeps fallback.
    """

    class EqualToDecimalMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf-equality trap."""
            return other is decimal.Decimal or type.__eq__(cls, other)

    class CustomDecimalLeaf(metaclass=EqualToDecimalMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom leaf annotation while accepting a string."""
            return core_schema.str_schema()

    class DecimalSetCustomLeafPayload(InputType):
        value: Set[CustomDecimalLeaf]  # noqa: UP006

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            DecimalSetCustomLeafPayload, name="DecimalSetCustomLeafPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: DecimalSetCustomLeafPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DecimalSetPepPayload, "DecimalSetPepPayload"),
        (DecimalSetTypingPayload, "DecimalSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([], set()),
        (0, {decimal.Decimal(0)}),
        (decimal.Decimal("1.2300"), {decimal.Decimal("1.2300")}),
        (
            ["1.2300", decimal.Decimal("1.23"), 2, 2.0],
            {decimal.Decimal("1.23"), decimal.Decimal(2)},
        ),
    ],
)
def test_native_finite_variables_reach_resolver_as_decimal_set(
    model: type[InputType], name: str, value: object, expected: set[decimal.Decimal]
) -> None:
    """Retain native accepted finite values and exact Decimal precision.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
        expected: Result the parametrized case expects.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]
    assert type(received[0]["amounts"]) is set
    assert all(type(item) is decimal.Decimal for item in received[0]["amounts"])


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DecimalSetPepPayload, "DecimalSetPepPayload"),
        (DecimalSetTypingPayload, "DecimalSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("[]", set()),
        ('"10.10"', {decimal.Decimal("10.10")}),
        ('["10.10", "10.10", 2, 2.0]', {decimal.Decimal("10.10"), decimal.Decimal(2)}),
        ('"1E+999999"', {decimal.Decimal("1E+999999")}),
    ],
)
def test_inline_finite_singleton_empty_and_duplicates(
    model: type[InputType], name: str, literal: str, expected: set[decimal.Decimal]
) -> None:
    """Apply native Decimal literal/list coercion without a float round-trip.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
        expected: Result the parametrized case expects.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}"
    )
    assert result.errors is None
    assert received == [{"amounts": expected}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DecimalSetPepPayload, "DecimalSetPepPayload"),
        (DecimalSetTypingPayload, "DecimalSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        decimal.Decimal("NaN"),
        decimal.Decimal("sNaN"),
        decimal.Decimal("Infinity"),
        decimal.Decimal("-Infinity"),
        ["1.5", "NaN"],
        ["1.5", "sNaN"],
    ],
)
def test_nonfinite_variables_fail_before_resolver(
    model: type[InputType], name: str, value: object
) -> None:
    """Reject supplied nonfinite Decimal values without hashing signaling NaN.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"amounts": value}},
    )
    assert result.errors
    assert received == []
    assert "nonfinite Decimal" in str(result.errors[0])


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (DecimalSetPepPayload, "DecimalSetPepPayload"),
        (DecimalSetTypingPayload, "DecimalSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    "literal",
    ['"NaN"', '"sNaN"', '"Infinity"', '"-Infinity"', '["1.5", "NaN"]'],
)
def test_nonfinite_literals_fail_before_resolver(
    model: type[InputType], name: str, literal: str
) -> None:
    """Reject nonfinite native Decimal literals at the input field boundary.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []
    assert "nonfinite Decimal" in str(result.errors[0])


@pytest.mark.parametrize("bad", [True, {"x": 1}, [None], "not-a-number"])
def test_invalid_native_variables_fail_before_resolver(bad: object) -> None:
    """Leave the native scalar's existing invalid-value policy intact.

    Args:
        bad: Invalid value supplied by the parametrized case.
    """
    schema, received = _schema(DecimalSetPepPayload, name="DecimalSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: DecimalSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"amounts": bad}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize("literal", ['"NaN"', '"sNaN"'])
def test_nonfinite_variable_default_never_reaches_resolver(literal: str) -> None:
    """Reject a nonfinite literal variable default before mutation execution.

    Args:
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(DecimalSetPepPayload, name="DecimalSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($amounts: [Decimal!]! = "
        + literal
        + ") { echo(payload: {amounts: $amounts}) { result } }",
    )
    assert result.errors
    assert "nonfinite Decimal" in str(result.errors[0])
    assert received == []


def test_required_decimal_set_rejects_omission() -> None:
    """Keep required-field semantics for exact Decimal-set annotations.

    Scenario: required decimal set rejects omission.
    """
    schema, received = _schema(DecimalSetPepPayload, name="DecimalSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: DecimalSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_optional_decimal_sets_keep_omission_and_null() -> None:
    """Preserve outer Optional and explicit null for both spellings.

    Scenario: optional decimal sets keep omission and null.
    """

    class DecimalSetOptionalPayload(InputType):
        pep_amounts: set[decimal.Decimal] | None = None
        alias_amounts: Set[decimal.Decimal] | None = None  # noqa: UP006

    schema, received = _schema(
        DecimalSetOptionalPayload, name="DecimalSetOptionalPayload"
    )
    sdl = print_schema(schema)
    assert "pepAmounts: [Decimal!] = null" in sdl
    assert "aliasAmounts: [Decimal!] = null" in sdl
    query = "mutation($payload: DecimalSetOptionalPayload!) { echo(payload: $payload) { result } }"
    for payload in (
        {},
        {"pepAmounts": None, "aliasAmounts": None},
        {"pepAmounts": ["1.5"], "aliasAmounts": "0"},
    ):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"pep_amounts": None, "alias_amounts": None},
        {"pep_amounts": None, "alias_amounts": None},
        {
            "pep_amounts": {decimal.Decimal("1.5")},
            "alias_amounts": {decimal.Decimal(0)},
        },
    ]


def test_fixed_and_factory_defaults_keep_lifecycle() -> None:
    """Retain valid fixed sets and fresh per-object factory defaults.

    Scenario: fixed and factory defaults keep lifecycle.
    """
    calls: list[int] = []

    def make_set() -> set[decimal.Decimal]:
        """Return a fresh Decimal set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {decimal.Decimal(calls[-1])}

    class DecimalSetDefaultsPayload(InputType):
        pep_amounts: set[decimal.Decimal] = {decimal.Decimal("1.50")}
        alias_amounts: Set[decimal.Decimal] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(
        DecimalSetDefaultsPayload, name="DecimalSetDefaultsPayload"
    )
    assert calls == []
    query = "mutation($payload: DecimalSetDefaultsPayload!) { echo(payload: $payload) { result } }"
    for _ in range(2):
        assert (
            graphql_sync(schema, query, variable_values={"payload": {}}).errors is None
        )
    assert calls == [1, 2]
    assert received == [
        {
            "pep_amounts": {decimal.Decimal("1.50")},
            "alias_amounts": {decimal.Decimal(1)},
        },
        {
            "pep_amounts": {decimal.Decimal("1.50")},
            "alias_amounts": {decimal.Decimal(2)},
        },
    ]


@pytest.mark.parametrize(
    ("annotation", "name"),
    [
        (set[decimal.Decimal], "DecimalSetLegacyPepPayload"),
        (Set[decimal.Decimal], "DecimalSetLegacyTypingPayload"),  # noqa: UP006
    ],
)
def test_malformed_legacy_defaults_stay_omittable_but_supplied_nonfinite_fails(
    annotation: object, name: str
) -> None:
    """Preserve malformed omissions and reject explicit nonfinite input.

    Args:
        annotation: Field annotation under test.
        name: GraphQL input type name used for the compiled model.
    """
    calls: list[int] = []

    def bad_factory() -> list[decimal.Decimal]:
        """Return an unchanged malformed legacy factory value."""
        calls.append(1)
        return [decimal.Decimal("sNaN")]

    model = type(
        name,
        (InputType,),
        {
            "__module__": __name__,
            "__annotations__": {"amounts": annotation, "factory_amounts": annotation},
            "amounts": [decimal.Decimal("NaN")],
            "factory_amounts": Field(default_factory=bad_factory),
        },
    )
    schema, received = _schema(model, name=name)
    omitted = graphql_sync(schema, "mutation { echo(payload: {}) { result } }")
    assert omitted.errors is None
    assert len(received) == 1
    assert type(received[0]["amounts"]) is list
    assert type(received[0]["factory_amounts"]) is list
    assert received[0]["amounts"][0].is_qnan()
    assert received[0]["factory_amounts"][0].is_snan()
    assert calls == [1]
    for literal in ('"NaN"', '"sNaN"', '"Infinity"', '"-Infinity"'):
        supplied = graphql_sync(
            schema, f"mutation {{ echo(payload: {{amounts: {literal}}}) {{ result }} }}"
        )
        assert supplied.errors
        assert "nonfinite Decimal" in str(supplied.errors[0])
        assert len(received) == 1
        assert calls == [1]


def test_nonfinite_supplied_field_precedes_omitted_sibling_factory() -> None:
    """Reject bad input before running any omitted sibling factory.

    Scenario: nonfinite supplied field precedes omitted sibling factory.
    """
    calls: list[int] = []

    def sibling_factory() -> str:
        """Record factory execution while returning its default."""
        calls.append(1)
        return "unused"

    class DecimalSetFactoryOrderPayload(InputType):
        amounts: set[decimal.Decimal]
        sibling: str = Field(default_factory=sibling_factory)

    schema, received = _schema(
        DecimalSetFactoryOrderPayload, name="DecimalSetFactoryOrderPayload"
    )
    result = graphql_sync(
        schema,
        'mutation { echo(payload: {amounts: "sNaN"}) { result } }',
    )
    assert result.errors
    assert "nonfinite Decimal" in str(result.errors[0])
    assert received == []
    assert calls == []


def test_alias_selection_replacement_and_pruning_project_metadata() -> None:
    """Convert only final and permission-surviving resolver names.

    Scenario: alias selection replacement and pruning project metadata.
    """

    class DecimalSetSelectionPayload(InputType):
        kept_amounts: set[decimal.Decimal] = Field(alias="keptAmounts")
        removed_amounts: Set[decimal.Decimal] | None = None  # noqa: UP006

    selected = compile_input_type(
        DecimalSetSelectionPayload,
        name="DecimalSetSelectedPayload",
        only_fields=("kept_amounts",),
        exclude_fields=("removed_amounts",),
    )
    assert set(selected.fields) == {"keptAmounts"}
    assert selected.out_type.set_decimal_fields == {"kept_amounts"}
    included = compile_input_type(
        DecimalSetSelectionPayload,
        name="DecimalSetIncludedPayload",
        only_fields=("kept_amounts",),
        exclude_fields=("removed_amounts",),
        include_fields=("removed_amounts",),
    )
    assert set(included.fields) == {"keptAmounts", "removedAmounts"}
    assert included.out_type.set_decimal_fields == {"kept_amounts", "removed_amounts"}
    replaced = compile_input_type(
        DecimalSetSelectionPayload,
        name="DecimalSetReplacedPayload",
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
    assert replaced.out_type.set_decimal_fields == {"kept_amounts"}

    full_input = compile_input_type(
        DecimalSetSelectionPayload, name="DecimalSetPrunedPayload"
    )
    full_input.fields["removedAmounts"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the permission-pruned mapping.

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
    clone = pruned.type_map["DecimalSetPrunedPayload"]
    assert set(clone.fields) == {"keptAmounts"}
    assert clone.out_type.set_decimal_fields == {"kept_amounts"}
    result = graphql_sync(
        pruned,
        "query($payload: DecimalSetPrunedPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"keptAmounts": ["1.5", "1.5"]}},
    )
    assert result.errors is None
    assert received == [{"kept_amounts": {decimal.Decimal("1.5")}}]
    invalid = graphql_sync(pruned, 'query { probe(payload: {keptAmounts: "sNaN"}) }')
    assert invalid.errors
    assert len(received) == 1


def test_pruned_clone_preserves_fixed_default_identity() -> None:
    """Keep omitted malformed fixed defaults while rejecting supplied values.

    Scenario: pruned clone preserves fixed default identity.
    """

    class DecimalSetPrunedDefaultPayload(InputType):
        kept_amounts: set[decimal.Decimal] = Field(
            alias="keptAmounts", default=[decimal.Decimal("NaN")]
        )
        hidden_amounts: Set[decimal.Decimal] | None = None  # noqa: UP006

    input_type = compile_input_type(
        DecimalSetPrunedDefaultPayload, name="DecimalSetPrunedDefaultPayload"
    )
    input_type.fields["hiddenAmounts"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Record the surviving default or supplied input.

        Args:
            _root: Unused root.
            _info: Unused context.
            payload: GraphQL-coerced mapping.

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
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    pruned = prune_schema(full, frozenset())
    clone = pruned.type_map["DecimalSetPrunedDefaultPayload"]
    assert set(clone.fields) == {"keptAmounts"}
    assert set(clone.out_type.set_decimal_defaults) == {"kept_amounts"}
    omitted = graphql_sync(pruned, "query { probe(payload: {}) }")
    assert omitted.errors is None
    assert len(received) == 1
    assert type(received[0]["kept_amounts"]) is list
    assert received[0]["kept_amounts"][0].is_qnan()
    supplied = graphql_sync(pruned, 'query { probe(payload: {keptAmounts: "sNaN"}) }')
    assert supplied.errors
    assert len(received) == 1


def test_other_leaves_and_nested_forms_keep_fallback() -> None:
    """Do not promote unapproved leaves or nested set shapes.

    Scenario: other leaves and nested forms keep fallback.
    """

    class DecimalSetUnsupportedPayload(InputType):
        pep_complex: set[complex]
        alias_complex: Set[complex]  # noqa: UP006
        nested: list[set[decimal.Decimal]]
        bare: set

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            DecimalSetUnsupportedPayload, name="DecimalSetUnsupportedPayload"
        ).fields
    assert {key: str(value.type) for key, value in fields.items()} == {
        "pepComplex": "String!",
        "aliasComplex": "String!",
        "nested": "[String!]!",
        "bare": "String!",
    }
    assert len([item for item in caught if item.category is UserWarning]) >= 3
