"""Public mutation input regressions for approved boolean-set spellings."""

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
from pydantic_core import core_schema

from django_graphex.core import InputType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.mutation import Mutation


class BooleanSetPepPayload(InputType):
    """Declare a PEP 585 boolean-set input.

    The field uses the builtin set spelling.
    """

    flags: set[bool]


class BooleanSetTypingPayload(InputType):
    """Declare a typing alias boolean-set input.

    The field uses the typing.Set spelling.
    """

    flags: Set[bool]  # noqa: UP006


def _schema(
    model: type[InputType], *, name: str
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Mount a compiled input on a public mutation and capture resolver values.

    Args:
        model: Input model under test.
        name: Unique GraphQL input name.

    Returns:
        Schema and captured resolver input mappings.
    """
    received: list[dict[str, object]] = []
    input_type = compile_input_type(model, name=name)

    class EchoBooleanSet(Mutation):
        """Capture the public mutation input."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled input."""

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
                "MutationRoot", {"echo": EchoBooleanSet.Field()}
            ),
        ),
        received,
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [([True, False, True], {True, False}), (False, {False})],
)
def test_boolean_sets_publish_list_and_reach_resolver_as_set(
    model: type[InputType], name: str, value: object, expected: set[bool]
) -> None:
    """Both spellings use native list coercion and Python-set materialization.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
        expected: Result the parametrized case expects.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(model, name=name)
        assert "flags: [Boolean!]!" in print_schema(schema)
    assert not [item for item in caught if item.category is UserWarning]
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"flags": value}},
    )
    assert result.errors is None
    assert received == [{"flags": expected}]
    assert type(received[0]["flags"]) is set


def test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback() -> None:
    """Custom equality must not admit an unrelated outer annotation.

    Scenario: custom outer annotation comparing equal to alias keeps fallback.
    """

    class EqualToBooleanSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the outer-annotation equality trap."""
            return other is Set[bool] or type.__eq__(cls, other)  # noqa: UP006

    class CustomBooleanScalar(metaclass=EqualToBooleanSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom annotation while accepting a string."""
            return core_schema.str_schema()

    class BooleanSetCustomOuterPayload(InputType):
        value: CustomBooleanScalar

    assert (
        BooleanSetCustomOuterPayload.model_fields["value"].annotation
        is CustomBooleanScalar
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            BooleanSetCustomOuterPayload, name="BooleanSetCustomOuterPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: BooleanSetCustomOuterPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


def test_custom_leaf_comparing_equal_to_bool_keeps_fallback() -> None:
    """A custom set leaf is not the approved bool despite equality.

    Scenario: custom leaf comparing equal to bool keeps fallback.
    """

    class EqualToBoolMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf-equality trap."""
            return other is bool or type.__eq__(cls, other)

    class CustomBooleanLeaf(metaclass=EqualToBoolMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom leaf annotation while accepting a string."""
            return core_schema.str_schema()

    class BooleanSetCustomLeafPayload(InputType):
        value: Set[CustomBooleanLeaf]  # noqa: UP006

    assert (
        BooleanSetCustomLeafPayload.model_fields["value"].annotation.__args__[0]
        is CustomBooleanLeaf
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            BooleanSetCustomLeafPayload, name="BooleanSetCustomLeafPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    result = graphql_sync(
        schema,
        "mutation($payload: BooleanSetCustomLeafPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"value": "legacy"}},
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [(False, {False}), ([], set()), ([True, False, True], {True, False})],
)
def test_variable_singleton_empty_and_duplicates(
    model: type[InputType], name: str, value: object, expected: set[bool]
) -> None:
    """Apply native list coercion without dropping false or duplicates.

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
        variable_values={"payload": {"flags": value}},
    )
    assert result.errors is None
    assert received == [{"flags": expected}]
    assert type(received[0]["flags"]) is set


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("literal", "expected"),
    [("false", {False}), ("[]", set()), ("[true, false, true]", {True, False})],
)
def test_inline_singleton_empty_and_duplicates(
    model: type[InputType], name: str, literal: str, expected: set[bool]
) -> None:
    """Use the same native list and set conversion for inline literals.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
        expected: Result the parametrized case expects.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{flags: {literal}}}) {{ result }} }}"
    )
    assert result.errors is None
    assert received == [{"flags": expected}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("value", [0, 1, "true", "false", 0.0, {"x": True}, [None]])
def test_invalid_native_boolean_variables_fail_before_resolver(
    model: type[InputType], name: str, value: object
) -> None:
    """Reject non-booleans and null items without casts or resolver calls.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"flags": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("literal", ["0", "1", '"true"', "0.0", "{x: true}", "[null]"])
def test_invalid_native_boolean_literals_fail_before_resolver(
    model: type[InputType], name: str, literal: str
) -> None:
    """Use GraphQLBoolean's native literal boundary.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{flags: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


def test_approved_boolean_sets_have_list_introspection_without_warning() -> None:
    """Both spellings publish non-null lists of non-null Boolean items.

    Scenario: approved boolean sets have list introspection without warning.
    """
    for model, name in (
        (BooleanSetPepPayload, "BooleanSetPepPayload"),
        (BooleanSetTypingPayload, "BooleanSetTypingPayload"),
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
        fields = result.data["__type"]["inputFields"]
        assert fields == [
            {
                "name": "flags",
                "type": {
                    "kind": "NON_NULL",
                    "ofType": {
                        "kind": "LIST",
                        "ofType": {"kind": "NON_NULL", "name": None},
                    },
                },
            }
        ]


def test_required_boolean_set_rejects_omission() -> None:
    """Retain required-field semantics for approved sets.

    Scenario: required boolean set rejects omission.
    """
    schema, received = _schema(BooleanSetPepPayload, name="BooleanSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: BooleanSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_optional_boolean_sets_keep_omission_and_null() -> None:
    """Preserve outer Optional and explicit-null behavior for both spellings.

    Scenario: optional boolean sets keep omission and null.
    """

    class BooleanSetOptionalPayload(InputType):
        pep_flags: set[bool] | None = None
        alias_flags: Set[bool] | None = None  # noqa: UP006

    schema, received = _schema(
        BooleanSetOptionalPayload, name="BooleanSetOptionalPayload"
    )
    sdl = print_schema(schema)
    assert "pepFlags: [Boolean!] = null" in sdl
    assert "aliasFlags: [Boolean!] = null" in sdl
    query = "mutation($payload: BooleanSetOptionalPayload!) { echo(payload: $payload) { result } }"
    for payload in (
        {},
        {"pepFlags": None, "aliasFlags": None},
        {"pepFlags": [True], "aliasFlags": False},
    ):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"pep_flags": None, "alias_flags": None},
        {"pep_flags": None, "alias_flags": None},
        {"pep_flags": {True}, "alias_flags": {False}},
    ]


def test_fixed_and_factory_defaults_keep_lifecycle() -> None:
    """Keep valid fixed sets and fresh per-object factory defaults.

    Scenario: fixed and factory defaults keep lifecycle.
    """
    from pydantic import Field

    calls: list[int] = []

    def make_set() -> set[bool]:
        """Return a fresh boolean set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {bool(calls[-1] % 2)}

    class BooleanSetDefaultsPayload(InputType):
        pep_flags: set[bool] = {True, False}
        alias_flags: Set[bool] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(
        BooleanSetDefaultsPayload, name="BooleanSetDefaultsPayload"
    )
    assert calls == []
    query = "mutation($payload: BooleanSetDefaultsPayload!) { echo(payload: $payload) { result } }"
    for _ in range(2):
        assert (
            graphql_sync(schema, query, variable_values={"payload": {}}).errors is None
        )
    assert calls == [1, 2]
    assert received == [
        {"pep_flags": {True, False}, "alias_flags": {True}},
        {"pep_flags": {True, False}, "alias_flags": {False}},
    ]
    assert all(type(item["pep_flags"]) is set for item in received)


def test_alias_selection_replacement_and_pruning_project_metadata() -> None:
    """Convert only emitted and permission-surviving resolver out-names.

    Scenario: alias selection replacement and pruning project metadata.
    """
    from pydantic import Field

    from django_graphex.core.input_compiler import RelationInputField
    from django_graphex.core.schema_pruner import prune_schema

    class BooleanSetSelectionPayload(InputType):
        kept_flags: set[bool] = Field(alias="keptFlags")
        removed_flags: Set[bool] | None = None  # noqa: UP006

    selected = compile_input_type(
        BooleanSetSelectionPayload,
        name="BooleanSetSelectedPayload",
        only_fields=("kept_flags",),
        exclude_fields=("removed_flags",),
    )
    assert set(selected.fields) == {"keptFlags"}
    assert selected.out_type.set_bool_fields == {"kept_flags"}
    included = compile_input_type(
        BooleanSetSelectionPayload,
        name="BooleanSetIncludedPayload",
        only_fields=("kept_flags",),
        exclude_fields=("removed_flags",),
        include_fields=("removed_flags",),
    )
    assert set(included.fields) == {"keptFlags", "removedFlags"}
    assert included.out_type.set_bool_fields == {"kept_flags", "removed_flags"}
    replaced = compile_input_type(
        BooleanSetSelectionPayload,
        name="BooleanSetReplacedPayload",
        relation_fields=(
            RelationInputField(
                out_name="removed_flags",
                alias="removedFlags",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedFlags"].type) == "ID"
    assert replaced.out_type.set_bool_fields == {"kept_flags"}

    full_input = compile_input_type(
        BooleanSetSelectionPayload, name="BooleanSetPrunedPayload"
    )
    full_input.fields["removedFlags"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture pruned input.

        Args:
            _root: Unused root.
            _info: Unused execution context.
            payload: Permission-pruned mapping.

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
    clone = pruned.type_map["BooleanSetPrunedPayload"]
    assert set(clone.fields) == {"keptFlags"}
    assert clone.out_type.set_bool_fields == {"kept_flags"}
    result = graphql_sync(
        pruned,
        "query($payload: BooleanSetPrunedPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"keptFlags": [False, False, True]}},
    )
    assert result.errors is None
    assert received == [{"kept_flags": {False, True}}]


def test_other_set_leaves_and_nested_forms_keep_fallback() -> None:
    """Do not promote unapproved leaves, bare sets or nested set forms.

    Scenario: other set leaves and nested forms keep fallback.
    """

    class BooleanSetUnsupportedPayload(InputType):
        pep_bytes: set[bytes]
        alias_bytes: Set[bytes]  # noqa: UP006
        nested: list[set[bool]]
        bare: set

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            BooleanSetUnsupportedPayload, name="BooleanSetUnsupportedPayload"
        ).fields
    assert {key: str(value.type) for key, value in fields.items()} == {
        "pepBytes": "String!",
        "aliasBytes": "String!",
        "nested": "[String!]!",
        "bare": "String!",
    }
    assert len([item for item in caught if item.category is UserWarning]) >= 3
