"""Public mutation input contract for exact Boolean-valued dictionaries."""

from __future__ import annotations

from typing import Dict

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import Field
from pydantic_core import core_schema

from django_graphex.core import InputType, Mutation, field
from django_graphex.core.input_compiler import RelationInputField, compile_input_type
from django_graphex.core.schema_pruner import prune_schema


class BuiltinBooleanMapPayload(InputType):
    """Declare a boolean map input with the builtin dict spelling.

    The mapping field uses dict of str to bool.
    """

    mapping: dict[str, bool]


class TypingBooleanMapPayload(InputType):
    """Declare a boolean map input with the typing alias spelling.

    The mapping field uses typing.Dict of str to bool.
    """

    mapping: Dict[str, bool]  # noqa: UP006


def _schema(
    model: type[InputType],
    *,
    name: str,
    input_type: GraphQLInputObjectType | None = None,
) -> tuple[GraphQLSchema, list[dict[str, object]]]:
    """Mount a public mutation and capture resolver-facing inputs.

    Args:
        model: Input model to compile.
        name: Unique GraphQL input name.
        input_type: Optional already compiled input object.

    Returns:
        Schema and captured resolver inputs.
    """
    received: list[dict[str, object]] = []
    input_type = input_type or compile_input_type(model, name=name)

    class Echo(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload.copy())
            return {"result": "ok"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("MutationRoot", {"echo": Echo.Field()}),
    )
    return schema, received


@pytest.mark.parametrize("model", [BuiltinBooleanMapPayload, TypingBooleanMapPayload])
def test_exact_boolean_map_uses_json_input(model: type[InputType]) -> None:
    """Publish JSON for both approved direct-map spellings.

    Args:
        model: Input model declaring the field under test.
    """
    schema, _received = _schema(model, name=model.__name__)
    assert "mapping: JSON!" in print_schema(schema)


@pytest.mark.parametrize("model", [BuiltinBooleanMapPayload, TypingBooleanMapPayload])
def test_boolean_map_variable_reaches_resolver(model: type[InputType]) -> None:
    """Accept native Boolean values without converting the supplied object.

    Args:
        model: Input model declaring the field under test.
    """
    schema, received = _schema(model, name=model.__name__)
    mapping = {"enabled": True, "disabled": False}
    result = graphql_sync(
        schema,
        f"mutation($payload: {model.__name__}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"mapping": mapping}},
    )
    assert result.errors is None
    assert received == [{"mapping": mapping}]
    assert received[0]["mapping"] is mapping


def test_unrelated_dictionary_leaf_keeps_string_fallback() -> None:
    """Do not generalize the approved Boolean leaf to other map values.

    Scenario: unrelated dictionary leaf keeps string fallback.
    """

    class OtherLeaf(InputType):
        mapping: Dict[str, float]  # noqa: UP006

    schema, _received = _schema(OtherLeaf, name="OtherLeaf")
    assert "mapping: String!" in print_schema(schema)


def test_list_wrapped_boolean_map_keeps_existing_fallback() -> None:
    """Do not enable an unapproved list of Boolean dictionaries.

    Scenario: list wrapped boolean map keeps existing fallback.
    """

    class Wrapped(InputType):
        mappings: list[dict[str, bool]]

    schema, _received = _schema(Wrapped, name="Wrapped")
    assert "mappings: [String!]!" in print_schema(schema)


@pytest.mark.parametrize("model", [BuiltinBooleanMapPayload, TypingBooleanMapPayload])
@pytest.mark.parametrize(
    "invalid",
    [
        1,
        0,
        "true",
        None,
        [],
        {1: True},
        {"secret": 1},
        {"secret": 0},
        {"secret": "true"},
        {"secret": None},
        {"secret": []},
        {"secret": {}},
    ],
)
def test_supplied_invalid_boolean_map_rejected_before_resolver(
    model: type[InputType], invalid: object
) -> None:
    """Reject supplied non-Booleans without leaking key names in errors.

    Args:
        model: Input model declaring the field under test.
        invalid: Invalid value supplied by the parametrized case.
    """
    schema, received = _schema(model, name=model.__name__)
    result = graphql_sync(
        schema,
        f"mutation($payload: {model.__name__}!) {{ echo(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"mapping": invalid}},
    )
    assert result.errors and not received
    if invalid is not None:
        assert f"{model.__name__}.mapping" in result.errors[0].message
    assert "secret" not in result.errors[0].message


@pytest.mark.parametrize("model", [BuiltinBooleanMapPayload, TypingBooleanMapPayload])
def test_literals_accept_exact_bool_and_reject_numbers(
    model: type[InputType],
) -> None:
    """Apply the direct Boolean-map contract to GraphQL literals.

    Args:
        model: Input model declaring the field under test.
    """
    schema, received = _schema(model, name=model.__name__)
    ok = graphql_sync(
        schema,
        "mutation { echo(payload: {mapping: {yes: true, no: false}}) { result } }",
    )
    assert ok.errors is None
    assert received == [{"mapping": {"yes": True, "no": False}}]
    bad = graphql_sync(
        schema, "mutation { echo(payload: {mapping: {secret: 1}}) { result } }"
    )
    assert bad.errors and len(received) == 1
    assert "secret" not in bad.errors[0].message


def test_empty_map_and_optional_null_preserve_outer_rules() -> None:
    """Keep empty objects and existing outer nullability semantics.

    Scenario: empty map and optional null preserve outer rules.
    """

    class OptionalMap(InputType):
        mapping: Dict[str, bool] | None = None  # noqa: UP006

    schema, received = _schema(OptionalMap, name="OptionalMap")
    assert "mapping: JSON" in print_schema(schema)
    query = "mutation($payload: OptionalMap!) { echo(payload: $payload) { result } }"
    for payload in ({}, {"mapping": None}, {"mapping": {}}):
        result = graphql_sync(schema, query, variable_values={"payload": payload})
        assert result.errors is None
    assert received == [
        {"mapping": None},
        {"mapping": None},
        {"mapping": {}},
    ]


def test_fixed_default_omission_and_explicit_same_object_have_distinct_policy() -> None:
    """Preserve a malformed default yet reject that same object when supplied.

    Scenario: fixed default omission and explicit same object have distinct policy.
    """
    fixed = {"legacy": 1}

    class FixedMap(InputType):
        mapping: dict[str, bool] = fixed

    schema, received = _schema(FixedMap, name="FixedMap")
    baseline = print_schema(schema)
    assert "mapping: JSON = { legacy: 1 }" in baseline
    introspection = graphql_sync(
        schema, '{ __type(name: "FixedMap") { inputFields { name defaultValue } } }'
    )
    assert introspection.errors is None
    assert (
        introspection.data["__type"]["inputFields"][0]["defaultValue"]
        == "{ legacy: 1 }"
    )
    query = "mutation($payload: FixedMap!) { echo(payload: $payload) { result } }"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None
    assert received[-1]["mapping"] == fixed
    for invalid in (fixed, {"legacy": 1}):
        count = len(received)
        supplied = graphql_sync(
            schema, query, variable_values={"payload": {"mapping": invalid}}
        )
        assert supplied.errors and len(received) == count
    assert print_schema(schema) == baseline


@pytest.mark.parametrize("fixed", ["legacy", [1], 1])
def test_malformed_fixed_nonobject_default_keeps_omission_policy(
    fixed: object,
) -> None:
    """Do not newly validate a fixed default merely because it is omitted.

    Args:
        fixed: Fixed default value under test.
    """

    name = {
        str: "LegacyStringFixed",
        list: "LegacyListFixed",
        int: "LegacyIntegerFixed",
    }[type(fixed)]
    model = type(
        name,
        (InputType,),
        {"__annotations__": {"mapping": dict[str, bool]}, "mapping": fixed},
    )

    schema, received = _schema(model, name=name)
    query = f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None and received[-1]["mapping"] == fixed
    supplied = graphql_sync(
        schema, query, variable_values={"payload": {"mapping": fixed}}
    )
    assert supplied.errors and len(received) == 1


def test_unprintable_fixed_dictionary_default_keeps_original_object() -> None:
    """Retain a legacy dict subclass on omission without exempting input.

    Scenario: unprintable fixed dictionary default keeps original object.
    """

    class LegacyDict(dict):
        pass

    fixed = LegacyDict({"legacy": 1})

    class LegacySubclassMap(InputType):
        mapping: dict[str, bool] = fixed

    schema, received = _schema(LegacySubclassMap, name="LegacySubclassFixed")
    query = "mutation($payload: LegacySubclassFixed!) { echo(payload: $payload) { result } }"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None and received[-1]["mapping"] == fixed
    assert type(received[-1]["mapping"]) is LegacyDict
    supplied = graphql_sync(
        schema, query, variable_values={"payload": {"mapping": fixed}}
    )
    assert supplied.errors and len(received) == 1


@pytest.mark.parametrize(
    ("spelling", "annotation"),
    [("Builtin", dict[str, bool]), ("Typing", Dict[str, bool])],
)
@pytest.mark.parametrize("pruned", [False, True])
def test_legacy_dictionary_subclass_default_remains_printable(
    spelling: str, annotation: object, pruned: bool
) -> None:
    """Keep legacy fixed-default metadata printable on full and pruned schemas.

    Args:
        spelling: Spelling of the field annotation under test.
        annotation: Field annotation under test.
        pruned: Whether the schema is pruned before it is inspected.
    """

    class LegacyDict(dict):
        pass

    fixed = LegacyDict({"legacy": 1})

    name = f"LegacyPrintable{spelling}{'Pruned' if pruned else 'Full'}"
    model = type(
        name,
        (InputType,),
        {"__annotations__": {"mapping": annotation}, "mapping": fixed},
    )

    schema, received = _schema(model, name=name)
    if pruned:
        schema = prune_schema(schema, frozenset())
    assert "mapping: JSON = \"{'legacy': 1}\"" in print_schema(schema)
    introspection = graphql_sync(
        schema,
        f'{{ __type(name: "{name}") {{ inputFields {{ name defaultValue }} }} }}',
    )
    assert introspection.errors is None
    assert introspection.data["__type"]["inputFields"][0]["defaultValue"] == (
        "\"{'legacy': 1}\""
    )
    query = f"mutation($payload: {name}!) {{ echo(payload: $payload) {{ result }} }}"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None
    assert received[-1]["mapping"] == fixed
    assert type(received[-1]["mapping"]) is LegacyDict
    supplied = graphql_sync(
        schema, query, variable_values={"payload": {"mapping": fixed}}
    )
    assert supplied.errors and len(received) == 1


def test_factory_omission_retains_malformed_output_but_invalid_input_stops_factory() -> (
    None
):
    """Validate supplied input before running a sibling omitted factory.

    Scenario: factory omission retains malformed output but invalid input stops factory.
    """
    calls: list[int] = []

    def legacy_factory() -> dict[str, int]:
        calls.append(len(calls))
        return {"legacy": 1}

    class FactoryMap(InputType):
        mapping: dict[str, bool] = Field(default_factory=legacy_factory)
        sibling: dict[str, bool] = Field(default_factory=legacy_factory)

    schema, received = _schema(FactoryMap, name="FactoryMap")
    query = "mutation($payload: FactoryMap!) { echo(payload: $payload) { result } }"
    omitted = graphql_sync(schema, query, variable_values={"payload": {}})
    assert omitted.errors is None
    assert received[-1] == {"mapping": {"legacy": 1}, "sibling": {"legacy": 1}}
    assert len(calls) == 2
    invalid = graphql_sync(
        schema, query, variable_values={"payload": {"mapping": {"secret": 1}}}
    )
    assert invalid.errors and len(calls) == 2 and len(received) == 1


def test_alias_and_permission_clone_keep_only_surviving_validator() -> None:
    """Project validators by final field identity and resolver-facing name.

    Scenario: alias and permission clone keep only surviving validator.
    """

    class Aliased(InputType):
        public_map: Dict[str, bool] = Field(alias="publicMap")  # noqa: UP006
        hidden_map: dict[str, bool] = Field(default_factory=dict, alias="hiddenMap")

    input_type = compile_input_type(Aliased, name="Aliased")
    input_type.fields["hiddenMap"].extensions = {
        "gdx_required_perms": frozenset({"private"})
    }
    schema, received = _schema(Aliased, name="Aliased", input_type=input_type)
    clone = prune_schema(schema, frozenset())
    cloned = clone.get_type("Aliased")
    assert set(cloned.fields) == {"publicMap"}
    assert set(cloned.out_type.boolean_maps) == {"public_map"}
    query = "mutation($payload: Aliased!) { echo(payload: $payload) { result } }"
    valid = graphql_sync(
        clone, query, variable_values={"payload": {"publicMap": {"ok": True}}}
    )
    assert valid.errors is None and received[-1] == {"public_map": {"ok": True}}
    bad = graphql_sync(
        clone, query, variable_values={"payload": {"publicMap": {"bad": 1}}}
    )
    assert bad.errors and len(received) == 1


def test_fixed_default_provenance_survives_permission_clone() -> None:
    """Clone the exact marker with its final field, not a removed sibling.

    Scenario: fixed default provenance survives permission clone.
    """
    fixed = {"legacy": 1}

    class Scoped(InputType):
        public_map: dict[str, bool] = Field(default=fixed, alias="publicMap")
        hidden_map: dict[str, bool] = Field(default_factory=dict, alias="hiddenMap")

    input_type = compile_input_type(Scoped, name="Scoped")
    input_type.fields["hiddenMap"].extensions = {
        "gdx_required_perms": frozenset({"private"})
    }
    full, received = _schema(Scoped, name="Scoped", input_type=input_type)
    clone = prune_schema(full, frozenset())
    cloned = clone.get_type("Scoped")
    assert set(cloned.fields) == {"publicMap"}
    assert set(cloned.out_type.boolean_maps) == {"public_map"}
    assert "publicMap: JSON = { legacy: 1 }" in print_schema(clone)
    query = "mutation($payload: Scoped!) { echo(payload: $payload) { result } }"
    omitted = graphql_sync(clone, query, variable_values={"payload": {}})
    assert omitted.errors is None and received[-1]["public_map"] == fixed
    invalid = graphql_sync(
        clone, query, variable_values={"payload": {"publicMap": fixed}}
    )
    assert invalid.errors and len(received) == 1


def test_field_selection_and_replacement_remove_stale_boolean_map_metadata() -> None:
    """Track only direct Boolean-map fields that survive field construction.

    Scenario: field selection and replacement remove stale boolean map metadata.
    """

    class Selection(InputType):
        kept_map: dict[str, bool] = Field(alias="keptMap")
        removed_map: Dict[str, bool] | None = None  # noqa: UP006

    selected = compile_input_type(Selection, name="Selected", only_fields=("kept_map",))
    assert set(selected.fields) == {"keptMap"}
    assert set(selected.out_type.boolean_maps) == {"kept_map"}
    included = compile_input_type(
        Selection,
        name="Included",
        only_fields=("kept_map",),
        include_fields=("removed_map",),
    )
    assert set(included.fields) == {"keptMap", "removedMap"}
    assert set(included.out_type.boolean_maps) == {"kept_map", "removed_map"}
    replaced = compile_input_type(
        Selection,
        name="Replaced",
        relation_fields=(
            RelationInputField(
                out_name="removed_map",
                alias="removedMap",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(replaced.fields["removedMap"].type) == "ID"
    assert set(replaced.out_type.boolean_maps) == {"kept_map"}


def test_custom_equality_annotations_do_not_gain_boolean_map_contract() -> None:
    """Avoid invoking custom annotation equality to admit unrelated leaves.

    Scenario: custom equality annotations do not gain boolean map contract.
    """

    class EqualToBoolMeta(type):
        def __eq__(cls, other: object) -> bool:
            return other is bool or type.__eq__(cls, other)

        __hash__ = type.__hash__

    class CustomLeaf(metaclass=EqualToBoolMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the custom annotation while accepting a string."""
            return core_schema.str_schema()

    class CustomMap(InputType):
        mapping: Dict[str, CustomLeaf]  # noqa: UP006

    schema, _received = _schema(CustomMap, name="CustomMap")
    assert "mapping: String!" in print_schema(schema)

    class EqualToMapMeta(type):
        def __eq__(cls, other: object) -> bool:
            return other is Dict[str, bool] or type.__eq__(cls, other)  # noqa: UP006

        __hash__ = type.__hash__

    class CustomOuter(metaclass=EqualToMapMeta):
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: object
        ) -> core_schema.CoreSchema:
            """Keep the outer annotation while accepting a string."""
            return core_schema.str_schema()

    class Outer(InputType):
        mapping: CustomOuter

    outer_schema, _received = _schema(Outer, name="Outer")
    assert "mapping: String!" in print_schema(outer_schema)
