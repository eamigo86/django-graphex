"""Public mutation input regressions for the two approved string-set spellings."""

from __future__ import annotations

import enum
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


class StringSetPepPayload(InputType):
    """Declare the approved PEP 585 string-set input.

    The field uses the builtin set spelling.
    """

    colors: set[str]


class StringSetTypingPayload(InputType):
    """Declare the approved typing alias string-set input.

    The field uses the typing.Set spelling.
    """

    colors: Set[str]  # noqa: UP006


def _schema(
    model: type[InputType], *, name: str
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Mount a compiled input on a mutation and capture its resolver values.

    Args:
        model: Input model under test.
        name: Unique public GraphQL input name.

    Returns:
        Schema and captured resolver input mappings.
    """
    received: list[dict[str, object]] = []
    input_type = compile_input_type(model, name=name)

    class EchoStringSet(Mutation):
        """Capture the public mutation input."""

        result = field(GraphQLString)

        class Arguments:
            """Bind the compiled input type."""

            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Return success after recording resolver-facing values.

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
            mutation=GraphQLObjectType("MutationRoot", {"echo": EchoStringSet.Field()}),
        ),
        received,
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
def test_exact_string_sets_publish_list_and_reach_resolver_as_set(
    model: type[InputType], name: str
) -> None:
    """Both approved spellings use native list coercion and set materialization.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
    """
    schema, received = _schema(model, name=name)
    assert "colors: [String!]!" in print_schema(schema)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"colors": ["red", "red", "blue"]}},
    )
    assert result.errors is None
    assert received == [{"colors": {"red", "blue"}}]
    assert type(received[0]["colors"]) is set


def test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback() -> None:
    """Custom equality must not admit an unrelated annotated scalar.

    Scenario: custom outer annotation comparing equal to alias keeps fallback.
    """

    class EqualToStringSetMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the outer-annotation equality trap."""
            return other is Set[str] or type.__eq__(cls, other)  # noqa: UP006

    class CustomStringScalar(metaclass=EqualToStringSetMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the exact custom annotation while accepting a string."""
            return core_schema.str_schema()

    class StringSetCustomOuterPayload(InputType):
        value: CustomStringScalar

    assert (
        StringSetCustomOuterPayload.model_fields["value"].annotation
        is CustomStringScalar
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            StringSetCustomOuterPayload, name="StringSetCustomOuterPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    query = "mutation($payload: StringSetCustomOuterPayload!) { echo(payload: $payload) { result } }"
    result = graphql_sync(
        schema, query, variable_values={"payload": {"value": "legacy"}}
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


def test_custom_string_set_leaf_comparing_equal_to_str_keeps_fallback() -> None:
    """A custom set leaf is not the approved str leaf despite equality.

    Scenario: custom string set leaf comparing equal to str keeps fallback.
    """

    class EqualToStrMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            """Expose the leaf-equality trap."""
            return other is str or type.__eq__(cls, other)

    class CustomStringLeaf(metaclass=EqualToStrMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom leaf annotation while accepting a string."""
            return core_schema.str_schema()

    class StringSetCustomLeafPayload(InputType):
        value: Set[CustomStringLeaf]  # noqa: UP006

    assert (
        StringSetCustomLeafPayload.model_fields["value"].annotation.__args__[0]
        is CustomStringLeaf
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, received = _schema(
            StringSetCustomLeafPayload, name="StringSetCustomLeafPayload"
        )
        assert "value: String!" in print_schema(schema)
    assert any("unsupported input field type" in str(item.message) for item in caught)
    query = "mutation($payload: StringSetCustomLeafPayload!) { echo(payload: $payload) { result } }"
    result = graphql_sync(
        schema, query, variable_values={"payload": {"value": "legacy"}}
    )
    assert result.errors is None
    assert received == [{"value": "legacy"}]


class NativeStringSubclass(str):
    """A hashable string value accepted by native GraphQLString.

    Instances compare as strings and can be stored in a set.
    """


class NativeStringEnum(enum.StrEnum):
    """A hashable string enum accepted by native GraphQLString.

    Members compare as strings and can be stored in a set.
    """

    RED = "red"


@pytest.mark.parametrize("value", [NativeStringSubclass("red"), NativeStringEnum.RED])
@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
def test_native_string_values_still_become_a_python_set(
    value: str, model: type[InputType], name: str
) -> None:
    """Preserve native acceptance of str subclasses without custom casting.

    Args:
        value: Value supplied by the parametrized case.
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"colors": [value]}},
    )
    assert result.errors is None
    assert received == [{"colors": {value}}]
    assert type(received[0]["colors"]) is set


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
def test_approved_string_sets_have_list_introspection_without_warning(
    model: type[InputType], name: str
) -> None:
    """The published input field is a non-null list of non-null strings.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
    """
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
            "name": "colors",
            "type": {
                "kind": "NON_NULL",
                "ofType": {
                    "kind": "LIST",
                    "ofType": {
                        "kind": "NON_NULL",
                        "name": None,
                    },
                },
            },
        }
    ]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [("ab", {"ab"}), ([], set()), (["red", "red", "blue"], {"red", "blue"})],
)
def test_variable_singleton_empty_and_duplicates(
    model: type[InputType], name: str, value: object, expected: set[str]
) -> None:
    """Retain whole-string singleton and ordinary list coercion.

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
        variable_values={"payload": {"colors": value}},
    )
    assert result.errors is None
    assert received == [{"colors": expected}]
    assert type(received[0]["colors"]) is set


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
@pytest.mark.parametrize(
    ("literal", "expected"),
    [('"ab"', {"ab"}), ("[]", set()), ('["red", "red", "blue"]', {"red", "blue"})],
)
def test_inline_singleton_empty_and_duplicates(
    model: type[InputType], name: str, literal: str, expected: set[str]
) -> None:
    """Apply native literal validation before set materialization.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
        expected: Result the parametrized case expects.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{colors: {literal}}}) {{ result }} }}"
    )
    assert result.errors is None
    assert received == [{"colors": expected}]


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("value", [1, True, 2.5, {"x": "y"}, [None], [1], [True]])
def test_invalid_native_string_variables_fail_before_resolver(
    model: type[InputType], name: str, value: object
) -> None:
    """Do not cast invalid variable values or nullable list items.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        value: Value supplied by the parametrized case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema,
        f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"colors": value}},
    )
    assert result.errors
    assert received == []


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (StringSetPepPayload, "StringSetPepPayload"),
        (StringSetTypingPayload, "StringSetTypingPayload"),
    ],
)
@pytest.mark.parametrize("literal", ["1", "true", "2.5", '{x: "y"}', "[null]"])
def test_invalid_native_string_literals_fail_before_resolver(
    model: type[InputType], name: str, literal: str
) -> None:
    """Use GraphQLString's native literal boundary.

    Args:
        model: Input model declaring the field under test.
        name: GraphQL input type name used for the compiled model.
        literal: GraphQL literal source written inline by the case.
    """
    schema, received = _schema(model, name=name)
    result = graphql_sync(
        schema, f"mutation {{ echo(payload: {{colors: {literal}}}) {{ result }} }}"
    )
    assert result.errors
    assert received == []


def test_required_string_set_rejects_omission() -> None:
    """Keep required-field semantics for approved sets.

    Scenario: required string set rejects omission.
    """
    schema, received = _schema(StringSetPepPayload, name="StringSetPepPayload")
    result = graphql_sync(
        schema,
        "mutation($payload: StringSetPepPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert result.errors
    assert received == []


def test_optional_string_sets_keep_omission_and_null() -> None:
    """Preserve outer Optional and explicit-null behavior for both spellings.

    Scenario: optional string sets keep omission and null.
    """

    class StringSetOptionalPayload(InputType):
        pep_colors: set[str] | None = None
        alias_colors: Set[str] | None = None  # noqa: UP006

    schema, received = _schema(
        StringSetOptionalPayload, name="StringSetOptionalPayload"
    )
    sdl = print_schema(schema)
    assert "pepColors: [String!] = null" in sdl
    assert "aliasColors: [String!] = null" in sdl
    query = "mutation($payload: StringSetOptionalPayload!) { echo(payload: $payload) { result } }"
    for payload in (
        {},
        {"pepColors": None, "aliasColors": None},
        {"pepColors": ["red"], "aliasColors": "blue"},
    ):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"pep_colors": None, "alias_colors": None},
        {"pep_colors": None, "alias_colors": None},
        {"pep_colors": {"red"}, "alias_colors": {"blue"}},
    ]


def test_fixed_and_factory_defaults_keep_lifecycle() -> None:
    """Do not freeze a factory or convert already valid fixed set defaults.

    Scenario: fixed and factory defaults keep lifecycle.
    """
    calls: list[int] = []

    def make_set() -> set[str]:
        """Return a fresh set for each omitted input object."""
        calls.append(len(calls) + 1)
        return {f"run{calls[-1]}"}

    class StringSetDefaultsPayload(InputType):
        pep_colors: set[str] = {"red", "blue"}
        alias_colors: Set[str] = Field(default_factory=make_set)  # noqa: UP006

    schema, received = _schema(
        StringSetDefaultsPayload, name="StringSetDefaultsPayload"
    )
    assert calls == []
    query = "mutation($payload: StringSetDefaultsPayload!) { echo(payload: $payload) { result } }"
    for _ in range(2):
        assert (
            graphql_sync(schema, query, variable_values={"payload": {}}).errors is None
        )
    assert calls == [1, 2]
    assert received == [
        {"pep_colors": {"red", "blue"}, "alias_colors": {"run1"}},
        {"pep_colors": {"red", "blue"}, "alias_colors": {"run2"}},
    ]
    assert all(type(item["pep_colors"]) is set for item in received)


def test_alias_and_emitted_field_identity() -> None:
    """Convert only the emitted field using its resolver-facing out-name.

    Scenario: alias and emitted field identity.
    """

    class StringSetAliasPayload(InputType):
        chosen_colors: Set[str] = Field(alias="chosenColors")  # noqa: UP006

    schema, received = _schema(StringSetAliasPayload, name="StringSetAliasPayload")
    assert "chosenColors: [String!]!" in print_schema(schema)
    result = graphql_sync(
        schema,
        "mutation($payload: StringSetAliasPayload!) { echo(payload: $payload) { result } }",
        variable_values={"payload": {"chosenColors": ["red", "red"]}},
    )
    assert result.errors is None
    assert received == [{"chosen_colors": {"red"}}]


def test_only_exclude_include_and_replacement_remove_stale_conversion() -> None:
    """Do not register metadata for fields absent from the emitted wire type.

    Scenario: only exclude include and replacement remove stale conversion.
    """

    class StringSetSelectionPayload(InputType):
        kept_colors: set[str]
        removed_colors: Set[str]  # noqa: UP006

    compiled = compile_input_type(
        StringSetSelectionPayload,
        name="StringSetSelectionPayload",
        only_fields=("kept_colors",),
        exclude_fields=("removed_colors",),
    )
    assert set(compiled.fields) == {"keptColors"}
    assert compiled.out_type.set_str_fields == {"kept_colors"}
    included = compile_input_type(
        StringSetSelectionPayload,
        name="StringSetIncludedPayload",
        only_fields=("kept_colors",),
        exclude_fields=("removed_colors",),
        include_fields=("removed_colors",),
    )
    assert set(included.fields) == {"keptColors", "removedColors"}
    assert included.out_type.set_str_fields == {"kept_colors", "removed_colors"}
    replaced = compile_input_type(
        StringSetSelectionPayload,
        name="StringSetReplacedPayload",
        relation_fields=(
            RelationInputField(
                out_name="removed_colors",
                alias="removedColors",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedColors"].type) == "ID"
    assert replaced.out_type.set_str_fields == {"kept_colors"}


def test_permission_clone_projects_only_surviving_string_set_metadata() -> None:
    """A pruned input must never inspect or reinsert a hidden set field.

    Scenario: permission clone projects only surviving string set metadata.
    """

    class StringSetScopedPayload(InputType):
        public_colors: set[str]
        hidden_colors: Set[str] | None = None  # noqa: UP006

    input_type = compile_input_type(
        StringSetScopedPayload, name="StringSetScopedPayload"
    )
    input_type.fields["hiddenColors"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    received: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Record values after permission pruning.

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
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    pruned = prune_schema(full, frozenset())
    clone = pruned.type_map["StringSetScopedPayload"]
    assert set(clone.fields) == {"publicColors"}
    assert clone.out_type.set_str_fields == {"public_colors"}
    result = graphql_sync(
        pruned,
        "query($payload: StringSetScopedPayload) { probe(payload: $payload) }",
        variable_values={"payload": {"publicColors": ["red", "red", "blue"]}},
    )
    assert result.errors is None
    assert received == [{"public_colors": {"red", "blue"}}]


def test_unapproved_set_leaves_and_nested_forms_keep_fallback() -> None:
    """Preserve the legacy String fallback outside both exact string leaves.

    Scenario: unapproved set leaves and nested forms keep fallback.
    """

    class StringSetUnsupportedPayload(InputType):
        pep_bytes: set[bytes]
        alias_bytes: Set[bytes]  # noqa: UP006
        nested: list[set[str]]
        bare: set

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fields = compile_input_type(
            StringSetUnsupportedPayload, name="StringSetUnsupportedPayload"
        ).fields
    assert {key: str(value.type) for key, value in fields.items()} == {
        "pepBytes": "String!",
        "aliasBytes": "String!",
        "nested": "[String!]!",
        "bare": "String!",
    }
    assert len([item for item in caught if item.category is UserWarning]) >= 3
