"""Public input mutation contract for direct integer-or-string unions."""

from __future__ import annotations

from typing import Union

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import Field

from django_graphex.core import InputType, Mutation, field
from django_graphex.core.input_compiler import RelationInputField, compile_input_type
from django_graphex.core.schema_pruner import prune_schema


class TypingIntStringInput(InputType):
    """Declare an int or string union with typing.Union, int first.

    The value field is Union of int and str.
    """

    value: Union[int, str]


class PipeIntStringInput(InputType):
    """Declare an int or string union with the pipe operator, int first.

    The value field is int or str.
    """

    value: int | str


class TypingStringIntInput(InputType):
    """Declare an int or string union with typing.Union, string first.

    The value field is Union of str and int.
    """

    value: Union[str, int]


class PipeStringIntInput(InputType):
    """Declare an int or string union with the pipe operator, string first.

    The value field is str or int.
    """

    value: str | int


def _schema(
    model: type[InputType],
    *,
    input_type: GraphQLInputObjectType | None = None,
    field_name: str = "value",
) -> tuple[GraphQLSchema, list[object]]:
    """Mount the compiled input on a public mutation.

    Args:
        model: Model declaring a direct union input field.
        input_type: Optional compiled input type with field metadata.
        field_name: Resolver-facing field to capture.

    Returns:
        Schema and values captured at the resolver boundary.
    """
    received: list[object] = []
    input_type = input_type or compile_input_type(model, name=model.__name__)

    class Echo(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload[field_name])
            return {"result": "ok"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("MutationRoot", {"echo": Echo.Field()}),
    )
    return schema, received


@pytest.mark.parametrize(
    "model",
    [
        TypingIntStringInput,
        PipeIntStringInput,
        TypingStringIntInput,
        PipeStringIntInput,
    ],
)
def test_direct_union_publishes_shared_scalar(model: type[InputType]) -> None:
    """Publish the same strict scalar for either spelling and member order.

    Args:
        model: Input model declaring the field under test.
    """
    schema, _received = _schema(model)
    assert "value: IntOrString!" in print_schema(schema)


def test_integer_variable_reaches_resolver_without_string_cast() -> None:
    """Keep an integer input on its original Python branch.

    Scenario: integer variable reaches resolver without string cast.
    """
    schema, received = _schema(TypingIntStringInput)
    result = graphql_sync(
        schema,
        "mutation($payload: TypingIntStringInput!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": 123}},
    )
    assert result.errors is None
    assert received == [123]
    assert type(received[0]) is int


def test_plain_string_input_is_not_split_or_cast() -> None:
    """Retain the supported String input behavior as a control.

    Scenario: plain string input is not split or cast.
    """

    class R08qPlainInput(InputType):
        value: str

    schema, received = _schema(R08qPlainInput)
    assert "value: String!" in print_schema(schema)
    result = graphql_sync(
        schema,
        'mutation { echo(payload: {value: "123"}) { result } }',
    )
    assert result.errors is None
    assert received == ["123"]


@pytest.mark.parametrize(
    "model",
    [
        TypingIntStringInput,
        PipeIntStringInput,
        TypingStringIntInput,
        PipeStringIntInput,
    ],
)
@pytest.mark.parametrize("value", [-(2**31), 0, 123, 2**31 - 1, "123", "ABC"])
def test_direct_union_preserves_variable_branch(
    model: type[InputType], value: int | str
) -> None:
    """Accept signed Int32 values and text without converting Python types.

    Args:
        model: Input model declaring the field under test.
        value: Value supplied by the parametrized case.
    """
    schema, received = _schema(model)
    query = f"mutation($payload: {model.__name__}!) {{ echo(payload: $payload) {{ result }} }}"
    result = graphql_sync(schema, query, variable_values={"payload": {"value": value}})
    assert result.errors is None
    assert received == [value]
    assert type(received[0]) is type(value)


@pytest.mark.parametrize("model", [TypingIntStringInput, PipeStringIntInput])
@pytest.mark.parametrize("literal", ["-2147483648", "2147483647", '"123"', '"ABC"'])
def test_direct_union_accepts_matching_literals(
    model: type[InputType], literal: str
) -> None:
    """Preserve literal integer and string branches through public execution.

    Args:
        model: Input model declaring the field under test.
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(model)
    result = graphql_sync(
        schema,
        f"mutation {{ echo(payload: {{value: {literal}}}) {{ result }} }}",
    )
    assert result.errors is None
    expected: int | str = int(literal) if not literal.startswith('"') else literal[1:-1]
    assert received == [expected]
    assert type(received[0]) is type(expected)


@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, 2**31, -(2**31) - 1, [], {}])
def test_direct_union_rejects_invalid_variable_before_resolver(value: object) -> None:
    """Reject non-branch values and out-of-range integers before mutation.

    Args:
        value: Value supplied by the parametrized case.
    """
    schema, received = _schema(TypingIntStringInput)
    result = graphql_sync(
        schema,
        "mutation($payload: TypingIntStringInput!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    "literal", ["true", "1.0", "2147483648", "-2147483649", "[]", "{}", "null"]
)
def test_direct_union_rejects_invalid_literal_before_resolver(literal: str) -> None:
    """Reject invalid literal kinds, ranges and null for required fields.

    Args:
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(PipeIntStringInput)
    result = graphql_sync(
        schema,
        f"mutation {{ echo(payload: {{value: {literal}}}) {{ result }} }}",
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("name", "annotation"),
    [
        ("NullableTypingIntStringInput", Union[int, str, None]),
        ("NullablePipeIntStringInput", int | str | None),
        ("NullableTypingStringIntInput", Union[str, int, None]),
    ],
)
def test_outer_nullable_direct_union(name: str, annotation: object) -> None:
    """Keep only the approved outer nullable form nullable in SDL.

    Args:
        name: GraphQL input type name used for the compiled model.
        annotation: Field annotation under test.
    """
    model = type(
        name,
        (InputType,),
        {"__annotations__": {"value": annotation}, "value": None},
    )
    schema, received = _schema(model)
    assert "value: IntOrString = null" in print_schema(schema)
    query = f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}"
    for value in (None, 123, "123"):
        result = graphql_sync(
            schema, query, variable_values={"payload": {"value": value}}
        )
        assert result.errors is None
    assert received == [None, 123, "123"]


def test_nullable_union_without_default_still_accepts_null() -> None:
    """Treat the outer None member as nullable even for a required model field.

    Scenario: nullable union without default still accepts null.
    """

    class R08qNullableRequiredUnionInput(InputType):
        value: int | str | None

    schema, received = _schema(R08qNullableRequiredUnionInput)
    assert "value: IntOrString" in print_schema(schema)
    assert "value: IntOrString!" not in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation { echo(payload: {value: null}) { result } }",
    )
    assert result.errors is None and received == [None]


@pytest.mark.parametrize("legacy", [2**31, 1.0, [1], {"legacy": 1}])
@pytest.mark.parametrize("pruned", [False, True])
def test_malformed_fixed_default_preserves_omission_and_printing(
    legacy: object, pruned: bool
) -> None:
    """Print legacy defaults yet reject the same invalid object if supplied.

    Args:
        legacy: Legacy default value under test.
        pruned: Whether the schema is pruned before it is inspected.
    """
    name = f"LegacyUnion{type(legacy).__name__}{'Pruned' if pruned else 'Full'}"
    model = type(
        name,
        (InputType,),
        {"__annotations__": {"value": Union[int, str]}, "value": legacy},
    )
    schema, received = _schema(model)
    if pruned:
        schema = prune_schema(schema, frozenset())
    assert "value: IntOrString = " in print_schema(schema)
    introspection = graphql_sync(
        schema,
        f'{{ __type(name: "{name}") {{ inputFields {{ name defaultValue }} }} }}',
    )
    assert introspection.errors is None
    query = f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None and received[-1] == legacy
    supplied = graphql_sync(
        schema, query, variable_values={"payload": {"value": legacy}}
    )
    assert supplied.errors and len(received) == 1


def test_legacy_dictionary_subclass_default_retains_old_printing() -> None:
    """Keep old String-style SDL for an unprintable fixed default.

    Scenario: legacy dictionary subclass default retains old printing.
    """

    class LegacyDict(dict):
        pass

    legacy = LegacyDict({"legacy": 1})

    class R08qLegacyUnionInput(InputType):
        value: Union[int, str] = legacy

    schema, received = _schema(R08qLegacyUnionInput)
    assert "value: IntOrString = \"{'legacy': 1}\"" in print_schema(schema)
    omitted = graphql_sync(
        schema,
        "mutation($payload: R08qLegacyUnionInput!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert omitted.errors is None and received[-1] == legacy
    assert type(received[-1]) is LegacyDict


def test_factory_values_stay_fresh_and_bad_input_stops_sibling_factory() -> None:
    """Keep per-object factories while rejecting supplied invalid values first.

    Scenario: factory values stay fresh and bad input stops sibling factory.
    """
    calls: list[int] = []
    sibling_calls: list[int] = []

    def make_value() -> list[int]:
        calls.append(len(calls))
        return [len(calls)]

    def make_sibling() -> str:
        sibling_calls.append(len(sibling_calls))
        return "fresh"

    class R08qFactoryUnionInput(InputType):
        value: Union[int, str] = Field(default_factory=make_value)
        sibling: str = Field(default_factory=make_sibling)

    schema, received = _schema(R08qFactoryUnionInput)
    query = "mutation($payload: R08qFactoryUnionInput!) { echo(payload: $payload) { result } }"
    first = graphql_sync(schema, query, variable_values={"payload": {}})
    second = graphql_sync(schema, query, variable_values={"payload": {}})
    assert first.errors is None and second.errors is None
    assert received == [[1], [2]]
    assert len(calls) == len(sibling_calls) == 2
    bad = graphql_sync(schema, query, variable_values={"payload": {"value": 1.0}})
    assert bad.errors and len(received) == 2
    assert len(calls) == len(sibling_calls) == 2


def test_alias_projection_and_permission_pruning() -> None:
    """Retain the scalar and alias only for fields surviving pruning.

    Scenario: alias projection and permission pruning.
    """

    class R08qAliasedUnionInput(InputType):
        public_value: int | str = Field(alias="publicValue")
        hidden_value: int | str = Field(default="hidden", alias="hiddenValue")

    input_type = compile_input_type(R08qAliasedUnionInput, name="R08qAliasedUnionInput")
    input_type.fields["hiddenValue"].extensions = {
        "gdx_required_perms": frozenset({"private"})
    }

    schema, received = _schema(
        R08qAliasedUnionInput, input_type=input_type, field_name="public_value"
    )
    pruned = prune_schema(schema, frozenset())
    pruned_input = pruned.get_type("R08qAliasedUnionInput")
    assert set(pruned_input.fields) == {"publicValue"}
    assert "publicValue: IntOrString!" in print_schema(pruned)
    query = "mutation($payload: R08qAliasedUnionInput!) { echo(payload: $payload) { result } }"
    accepted = graphql_sync(
        pruned, query, variable_values={"payload": {"publicValue": 123}}
    )
    assert accepted.errors is None and received == [123]
    rejected = graphql_sync(
        pruned, query, variable_values={"payload": {"publicValue": 1.0}}
    )
    assert rejected.errors and received == [123]


def test_selected_and_replaced_fields_keep_final_wire_type() -> None:
    """Only final surviving fields own the approved scalar projection.

    Scenario: selected and replaced fields keep final wire type.
    """

    class R08qSelection(InputType):
        kept_value: int | str = Field(alias="keptValue")
        removed_value: int | str = Field(alias="removedValue")

    selected = compile_input_type(
        R08qSelection, name="SelectedUnion", only_fields=("kept_value",)
    )
    assert set(selected.fields) == {"keptValue"}
    assert str(selected.fields["keptValue"].type) == "IntOrString!"
    included = compile_input_type(
        R08qSelection,
        name="IncludedUnion",
        only_fields=("kept_value",),
        include_fields=("removed_value",),
    )
    assert set(included.fields) == {"keptValue", "removedValue"}
    excluded = compile_input_type(
        R08qSelection, name="ExcludedUnion", exclude_fields=("removed_value",)
    )
    assert set(excluded.fields) == {"keptValue"}
    replaced = compile_input_type(
        R08qSelection,
        name="ReplacedUnion",
        relation_fields=(
            RelationInputField(
                out_name="removed_value",
                alias="removedValue",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedValue"].type) == "ID"
    assert str(replaced.fields["keptValue"].type) == "IntOrString!"


def test_scalar_name_collision_reports_an_error() -> None:
    """Do not silently rename or shadow a user-defined scalar with this name.

    Scenario: scalar name collision reports an error.
    """
    schema, _received = _schema(TypingIntStringInput)
    conflicting = GraphQLScalarType(name="IntOrString")
    with pytest.raises(TypeError, match="multiple types named 'IntOrString'"):
        GraphQLSchema(
            query=schema.query_type,
            mutation=schema.mutation_type,
            types=[conflicting],
        )


def test_valid_fixed_default_and_disabled_default_emission() -> None:
    """Keep valid fixed defaults and the existing omit-defaults switch.

    Scenario: valid fixed default and disabled default emission.
    """

    class R08qValidDefaultUnionInput(InputType):
        value: int | str = 123

    schema, received = _schema(R08qValidDefaultUnionInput)
    assert "value: IntOrString = 123" in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation($payload: R08qValidDefaultUnionInput!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors is None and received == [123]
    no_defaults = compile_input_type(
        R08qValidDefaultUnionInput, name="NoDefaultsUnion", emit_defaults=False
    )
    assert no_defaults.fields["value"].default_value != 123
    assert str(no_defaults.fields["value"].type) == "IntOrString"


def test_string_fixed_default_keeps_string_branch_in_schema() -> None:
    """Render a valid text default as text without numeric conversion.

    Scenario: string fixed default keeps string branch in schema.
    """

    class R08qTextDefaultUnionInput(InputType):
        value: int | str = "123"

    schema, received = _schema(R08qTextDefaultUnionInput)
    assert 'value: IntOrString = "123"' in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation($payload: R08qTextDefaultUnionInput!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors is None and received == ["123"]
    assert type(received[0]) is str


def test_custom_equality_leaf_does_not_match_direct_union() -> None:
    """Do not invoke a custom annotation equality method to grant support.

    Scenario: custom equality leaf does not match direct union.
    """

    class EqualToIntMeta(type):
        def __eq__(cls, other: object) -> bool:
            return other is int or type.__eq__(cls, other)

        __hash__ = type.__hash__

    class CustomLeaf(metaclass=EqualToIntMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> object:
            """Allow the model declaration without changing its wire type."""
            from pydantic_core import core_schema

            return core_schema.str_schema()

    class R08qCustomInput(InputType):
        value: Union[CustomLeaf, str]

    with pytest.warns(
        UserWarning,
        match=r"unsupported input field type .*CustomLeaf.*str.*falling back to the GraphQLString scalar",
    ) as caught:
        schema, _received = _schema(R08qCustomInput)
    assert [type(warning.message) for warning in caught] == [UserWarning]
    assert "value: String!" in print_schema(schema)


def test_custom_equality_outer_does_not_match_direct_union() -> None:
    """Require a native Union origin rather than equality with one.

    Scenario: custom equality outer does not match direct union.
    """

    class EqualToUnionMeta(type):
        def __eq__(cls, other: object) -> bool:
            return other is Union[int, str] or type.__eq__(cls, other)

        __hash__ = type.__hash__

    class CustomOuter(metaclass=EqualToUnionMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> object:
            """Accept a string while keeping a distinct annotation origin."""
            from pydantic_core import core_schema

            return core_schema.str_schema()

    class R08qCustomOuterInput(InputType):
        value: CustomOuter

    with pytest.warns(
        UserWarning,
        match=r"unsupported input field type 'CustomOuter'.*falling back to the GraphQLString scalar",
    ) as caught:
        schema, _received = _schema(R08qCustomOuterInput)
    assert [type(warning.message) for warning in caught] == [UserWarning]
    assert "value: String!" in print_schema(schema)


def test_unapproved_wrapped_union_retains_string_fallback() -> None:
    """Do not grant list-wrapped unions or unrelated leaves new support.

    Scenario: unapproved wrapped union retains string fallback.
    """

    class R08qWrappedUnionInput(InputType):
        values: list[Union[int, str]]
        unrelated: Union[int, float]
        wider: Union[int, str, float, None]

    with pytest.warns(UserWarning) as caught:
        schema, _received = _schema(R08qWrappedUnionInput)
    assert len(caught) == 3
    assert all(type(warning.message) is UserWarning for warning in caught)
    for warning, members in zip(
        caught,
        (("int", "str"), ("int", "float"), ("int", "str", "float", "None")),
    ):
        message = str(warning.message)
        assert "unsupported input field type" in message
        assert "falling back to the GraphQLString scalar" in message
        assert all(member in message for member in members)
    sdl = print_schema(schema)
    assert "values: [String!]!" in sdl
    assert "unrelated: String!" in sdl
    assert "wider: String!" in sdl
