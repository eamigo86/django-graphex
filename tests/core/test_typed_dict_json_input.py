"""Public contract for strict typed dictionary input fields."""

from __future__ import annotations

import json
import warnings
from typing import Any, Dict

import pytest
from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLNonNull,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import BaseModel, Field

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import RelationInputField, compile_input_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


class VariableTypedMapPayload(InputType):
    """Declare a typed map next to a raw map for variable tests.

    The mapping field is dict of str to int and raw is a bare dict.
    """

    mapping: dict[str, int]
    raw: dict


class InvalidTypedMapPayload(InputType):
    """Declare a typed map used to submit invalid variables.

    The mapping field is dict of str to int.
    """

    mapping: dict[str, int]


class HttpTypedMapPayload(InputType):
    """Declare a typed map used by the HTTP tests.

    The mapping field is dict of str to int.
    """

    mapping: dict[str, int]


class TypingAliasMapPayload(InputType):
    """Declare a typed map with typing.Dict next to a raw map.

    The mapping field is typing.Dict of str to int and raw is a bare dict.
    """

    mapping: Dict[str, int]
    raw: dict


class HttpTypingAliasMapPayload(InputType):
    """Declare a typing.Dict typed map used by the HTTP tests.

    The mapping field is typing.Dict of str to int.
    """

    mapping: Dict[str, int]


def test_typing_dict_alias_uses_strict_json_public_input() -> None:
    """Give the approved typing alias the existing strict JSON contract.

    Scenario: typing dict alias uses strict json public input.
    """
    received: list[dict[str, object]] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        input_type = compile_input_type(
            TypingAliasMapPayload, name="TypingAliasMapPayload"
        )
        schema = _schema_for_payload(input_type, received).graphql_schema
        assert str(input_type.fields["mapping"].type) == "JSON!"
    assert not [item for item in caught if item.category is UserWarning]

    mapping = {"count": 3}
    raw = {1: True}
    result = graphql_sync(
        schema,
        "mutation($payload: TypingAliasMapPayload!) "
        "{ submit(payload: $payload) { result } }",
        variable_values={"payload": {"mapping": mapping, "raw": raw}},
    )
    assert result.errors is None, result.errors
    assert received == [{"mapping": mapping, "raw": raw}]
    assert received[0]["mapping"] is mapping and received[0]["raw"] is raw
    assert (
        input_type.fields["mapping"].type.of_type
        is input_type.fields["raw"].type.of_type
    )

    inline = graphql_sync(
        schema,
        "mutation { submit(payload: {mapping: {large: 9223372036854775808}, "
        "raw: {enabled: true}}) { result } }",
    )
    assert inline.errors is None, inline.errors
    assert received[-1] == {"mapping": {"large": 2**63}, "raw": {"enabled": True}}


@pytest.mark.parametrize(
    "bad",
    [
        '{"count":3}',
        3.5,
        True,
        [3],
        {1: 3},
        {"count": "3"},
        {"count": True},
        {"count": 3.5},
        {"count": [3]},
    ],
)
def test_typing_alias_invalid_map_stops_mutation(bad: object) -> None:
    """Reject the same invalid shapes without echoing their supplied keys.

    Args:
        bad: Invalid value supplied by the parametrized case.
    """
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(
        compile_input_type(TypingAliasMapPayload, name="TypingAliasMapPayload"),
        received,
    ).graphql_schema
    result = graphql_sync(
        schema,
        "mutation($payload: TypingAliasMapPayload!) "
        "{ submit(payload: $payload) { result } }",
        variable_values={"payload": {"mapping": bad, "raw": {}}},
    )
    assert result.errors and received == []
    assert "TypingAliasMapPayload.mapping" in result.errors[0].message
    assert "count" not in result.errors[0].message


def test_typing_alias_wrappers_defaults_and_pruned_clone() -> None:
    """Keep optional lists, fresh factories and surviving clone checks.

    Scenario: typing alias wrappers defaults and pruned clone.
    """
    calls: list[int] = []
    received: list[dict[str, object]] = []

    def fresh_map() -> dict[str, int]:
        calls.append(len(calls) + 1)
        return {"sequence": calls[-1]}

    class TypingAliasWrappedPayload(InputType):
        a_map: Dict[str, int] | None = None
        maps: list[Dict[str, int] | None] | None = None
        fixed: Dict[str, int] = {"base": 1}
        fresh: Dict[str, int] = Field(default_factory=fresh_map)
        removed_map: Dict[str, int] | None = None

    input_type = compile_input_type(
        TypingAliasWrappedPayload, name="TypingAliasWrappedPayload"
    )
    input_type.fields["removedMap"].extensions = {
        "gdx_required_perms": frozenset({"test.hidden"})
    }
    full = _schema_for_payload(input_type, received).graphql_schema
    clone = prune_schema(full, frozenset())
    assert "fixed: JSON = { base: 1 }" in print_schema(full)
    metadata = graphql_sync(
        full,
        '{ __type(name: "TypingAliasWrappedPayload") '
        "{ inputFields { name defaultValue } } }",
    )
    assert metadata.errors is None
    defaults = {
        item["name"]: item["defaultValue"]
        for item in metadata.data["__type"]["inputFields"]
    }
    assert defaults["fixed"] == "{ base: 1 }"
    assert defaults["fresh"] is None and calls == []
    assert set(clone.get_type("TypingAliasWrappedPayload").fields) == {
        "aMap",
        "maps",
        "fixed",
        "fresh",
    }
    query = "mutation { submit(payload: {}) { result } }"
    for schema in (full, clone):
        omitted = graphql_sync(schema, query)
        assert omitted.errors is None, omitted.errors
    assert received == [
        {
            "a_map": None,
            "maps": None,
            "fixed": {"base": 1},
            "fresh": {"sequence": 1},
            "removed_map": None,
        },
        {"a_map": None, "maps": None, "fixed": {"base": 1}, "fresh": {"sequence": 2}},
    ]
    assert calls == [1, 2]
    valid_map = {"large": 2**63}
    variables = {"payload": {"aMap": valid_map, "maps": [{"x": 1}, None]}}
    variable_query = (
        "mutation($payload: TypingAliasWrappedPayload!) "
        "{ submit(payload: $payload) { result } }"
    )
    valid = graphql_sync(clone, variable_query, variable_values=variables)
    assert valid.errors is None, valid.errors
    assert received[-1]["a_map"] is valid_map
    assert received[-1]["maps"] == [{"x": 1}, None]
    explicit_null = graphql_sync(
        clone, "mutation { submit(payload: {aMap: null, maps: null}) { result } }"
    )
    assert explicit_null.errors is None, explicit_null.errors
    assert received[-1]["a_map"] is received[-1]["maps"] is None
    before = len(received)
    for payload in ({"aMap": {"secret": True}}, {"maps": [{"secret": True}]}):
        invalid = graphql_sync(
            clone, variable_query, variable_values={"payload": payload}
        )
        assert invalid.errors and len(received) == before
        assert "secret" not in invalid.errors[0].message


@pytest.mark.parametrize("inline", [False, True])
def test_typing_alias_http_error_is_safe(inline: bool) -> None:
    """Expose deliberate alias validation errors under production settings.

    Args:
        inline: Whether to supply an invalid GraphQL literal.
    """
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(
        compile_input_type(HttpTypingAliasMapPayload, name="HttpTypingAliasMapPayload"),
        received,
    )
    query = (
        "mutation { submit(payload: {mapping: {secret: true}}) { result } }"
        if inline
        else "mutation($payload: HttpTypingAliasMapPayload!) "
        "{ submit(payload: $payload) { result } }"
    )
    body: dict[str, object] = {"query": query}
    if not inline:
        body["variables"] = {"payload": {"mapping": {"secret": True}}}
    request = RequestFactory().post(
        "/graphql/", data=json.dumps(body), content_type="application/json"
    )
    with override_settings(DEBUG=False):
        response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code != 500
    assert payload["errors"] and received == []
    assert "HttpTypingAliasMapPayload.mapping" in payload["errors"][0]["message"]
    assert "secret" not in payload["errors"][0]["message"]
    assert (
        payload["errors"][0].get("extensions", {}).get("code")
        != "INTERNAL_SERVER_ERROR"
    )


def test_typed_dictionary_accepts_json_object_before_mutation() -> None:
    """Compile a typed map as JSON and deliver its original object to mutate.

    Scenario: typed dictionary accepts json object before mutation.
    """
    received: list[dict[str, object]] = []

    class FirstTypedMapPayload(InputType):
        mapping: dict[str, int]

    input_type = compile_input_type(FirstTypedMapPayload, name="TypedDictPayload")

    class Submit(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "accepted"}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class Mutations(ObjectType):
        submit = Submit.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutations).graphql_schema
    result = graphql_sync(
        schema,
        "mutation { submit(payload: {mapping: {count: 3}}) { result } }",
    )
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "accepted"}}
    assert received == [{"mapping": {"count": 3}}]
    assert str(input_type.fields["mapping"].type) == "JSON!"


def _schema_for_payload(
    input_type: Any, received: list[dict[str, object]]
) -> DjangoGraphQLSchema:
    """Mount an input type on a public mutation that records each invocation.

    Args:
        input_type: Compiled input type.
        received: Resolver invocation log.

    Returns:
        A native schema with the mounted mutation.
    """

    class Submit(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "accepted"}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class Mutations(ObjectType):
        submit = Submit.Field()

    return DjangoGraphQLSchema(query=Query, mutation=Mutations)


@pytest.mark.parametrize(
    "mapping",
    [{}, {"count": 3}, {"large": 2**63}],
)
def test_variable_typed_maps_accept_plain_integers_and_share_json(
    mapping: dict[str, int],
) -> None:
    """Retain raw dictionary values and reuse the existing JSON scalar.

    Args:
        mapping: Mapping supplied through the variable.
    """
    received: list[dict[str, object]] = []

    input_type = compile_input_type(VariableTypedMapPayload, name="StrictPayload")
    schema = _schema_for_payload(input_type, received).graphql_schema
    sdl = print_schema(schema)
    assert "mapping: JSON!" in sdl and "raw: JSON!" in sdl
    assert (
        input_type.fields["mapping"].type.of_type
        is input_type.fields["raw"].type.of_type
    )
    query = (
        "mutation($payload: StrictPayload!) { submit(payload: $payload) { result } }"
    )
    raw = {1: True}
    result = graphql_sync(
        schema, query, variable_values={"payload": {"mapping": mapping, "raw": raw}}
    )
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "accepted"}}
    assert received == [{"mapping": mapping, "raw": raw}]
    assert received[0]["mapping"] is mapping
    assert received[0]["raw"] is raw


@pytest.mark.parametrize(
    "bad",
    [
        '{"count":3}',
        3.5,
        True,
        [3],
        {1: 3},
        {"count": "3"},
        {"count": True},
        {"count": 3.5},
        {"count": [3]},
    ],
)
def test_invalid_typed_map_variable_is_rejected_before_resolver(bad: object) -> None:
    """Reject wrong shapes without leaking supplied keys or values.

    Args:
        bad: Invalid value supplied by the parametrized case.
    """
    received: list[dict[str, object]] = []

    schema = _schema_for_payload(
        compile_input_type(InvalidTypedMapPayload, name="StrictPayload"), received
    ).graphql_schema
    result = graphql_sync(
        schema,
        "mutation($payload: StrictPayload!) { submit(payload: $payload) { result } }",
        variable_values={"payload": {"mapping": bad}},
    )
    assert result.errors
    assert received == []
    assert "StrictPayload.mapping" in result.errors[0].message
    assert "count" not in result.errors[0].message
    assert '{"count":3}' not in result.errors[0].message


def test_inline_typed_map_and_nullability_keep_graphql_coercion() -> None:
    """Accept inline objects while retaining omission and explicit null.

    Scenario: inline typed map and nullability keep graphql coercion.
    """
    received: list[dict[str, object]] = []

    class WrappedTypedMapPayload(InputType):
        mapping: dict[str, int] | None = None
        maps: list[dict[str, int] | None] | None = None

    schema = _schema_for_payload(
        compile_input_type(WrappedTypedMapPayload, name="WrappedMapInput"), received
    ).graphql_schema
    valid = graphql_sync(
        schema,
        "mutation { submit(payload: {mapping: {large: 9223372036854775808}, "
        "maps: [{x: 1}, null]}) { result } }",
    )
    assert valid.errors is None, valid.errors
    assert received[-1] == {"mapping": {"large": 2**63}, "maps": [{"x": 1}, None]}
    omitted = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    explicit_null = graphql_sync(
        schema, "mutation { submit(payload: {mapping: null, maps: null}) { result } }"
    )
    assert omitted.errors is explicit_null.errors is None
    assert received[-2] == {"mapping": None, "maps": None}
    assert received[-1] == {"mapping": None, "maps": None}
    before = len(received)
    invalid = graphql_sync(
        schema,
        'mutation { submit(payload: {mapping: {x: "3"}}) { result } }',
    )
    invalid_list = graphql_sync(
        schema,
        "mutation { submit(payload: {maps: [{x: true}]}) { result } }",
    )
    assert invalid.errors and invalid_list.errors
    assert len(received) == before
    assert "WrappedMapInput.maps[0]" in invalid_list.errors[0].message


def test_alias_nested_defaults_and_pruned_fields_use_final_input_surface() -> None:
    """Validate surviving fields without freezing factories or pruned fields.

    Scenario: alias nested defaults and pruned fields use final input surface.
    """
    factory_calls: list[int] = []
    received: list[dict[str, object]] = []

    def fresh_map() -> dict[str, int]:
        factory_calls.append(len(factory_calls) + 1)
        return {"sequence": factory_calls[-1]}

    class NestedTypedMapChild(InputType):
        score_map: dict[str, int] = Field(alias="scoreMap")

    compile_input_type(NestedTypedMapChild, name="ChildMapInput")

    class NestedTypedMapParent(InputType):
        child: NestedTypedMapChild
        mapping: dict[str, int] = Field(default_factory=fresh_map)
        fixed: dict[str, int] = {"base": 1}

    parent_type = compile_input_type(NestedTypedMapParent, name="ParentMapInput")
    schema = _schema_for_payload(parent_type, received).graphql_schema
    query = (
        "mutation($payload: ParentMapInput!) { submit(payload: $payload) { result } }"
    )
    assert factory_calls == []
    first = graphql_sync(
        schema, query, variable_values={"payload": {"child": {"scoreMap": {"x": 1}}}}
    )
    second = graphql_sync(
        schema, query, variable_values={"payload": {"child": {"scoreMap": {"x": 2}}}}
    )
    assert first.errors is second.errors is None
    assert factory_calls == [1, 2]
    assert received == [
        {
            "child": {"score_map": {"x": 1}},
            "mapping": {"sequence": 1},
            "fixed": {"base": 1},
        },
        {
            "child": {"score_map": {"x": 2}},
            "mapping": {"sequence": 2},
            "fixed": {"base": 1},
        },
    ]

    class GeneratedTypedMapModel(BaseModel):
        mapping: dict[str, int] | None = None

    generated = compile_input_type(GeneratedTypedMapModel, name="GeneratedMapInput")
    generated_received: list[dict[str, object]] = []
    generated_schema = _schema_for_payload(generated, generated_received).graphql_schema
    omitted = graphql_sync(
        generated_schema,
        "mutation { submit(payload: {}) { result } }",
    )
    assert omitted.errors is None
    assert generated_received == [{}]

    pruned = compile_input_type(
        NestedTypedMapParent, name="PrunedMapInput", only_fields=("child",)
    )
    pruned_received: list[dict[str, object]] = []
    pruned_schema = _schema_for_payload(pruned, pruned_received).graphql_schema
    pruned_result = graphql_sync(
        pruned_schema,
        "mutation { submit(payload: {child: {scoreMap: {x: 1}}}) { result } }",
    )
    assert pruned_result.errors is None
    assert pruned_received == [{"child": {"score_map": {"x": 1}}}]
    assert factory_calls == [1, 2]


def test_invalid_typed_map_factory_is_rejected_before_resolver() -> None:
    """Validate a freshly generated default without coercing its values.

    Scenario: invalid typed map factory is rejected before resolver.
    """
    received: list[dict[str, object]] = []

    class InvalidFactoryTypedMapPayload(InputType):
        mapping: dict[str, int] = Field(default_factory=lambda: {"private": True})

    schema = _schema_for_payload(
        compile_input_type(InvalidFactoryTypedMapPayload, name="BadFactoryMapInput"),
        received,
    ).graphql_schema
    result = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    assert result.errors
    assert "BadFactoryMapInput.mapping" in result.errors[0].message
    assert "private" not in result.errors[0].message
    assert received == []


def test_relation_replacement_does_not_keep_typed_map_validator() -> None:
    """Use only the final emitted field after a relation override.

    Scenario: relation replacement does not keep typed map validator.
    """
    received: list[dict[str, object]] = []

    class RelationReplacedTypedMapInput(InputType):
        mapping: dict[str, int]

    input_type = compile_input_type(
        RelationReplacedTypedMapInput,
        name="ReplacedMapInput",
        relation_fields=(
            RelationInputField(
                out_name="mapping",
                alias="mapping",
                is_list=False,
                required=False,
                inject_only=False,
            ),
        ),
    )
    assert str(input_type.fields["mapping"].type) == "ID"
    schema = _schema_for_payload(input_type, received).graphql_schema
    result = graphql_sync(
        schema, 'mutation { submit(payload: {mapping: "123"}) { result } }'
    )
    assert result.errors is None, result.errors
    assert received == [{"mapping": "123"}]


def test_permission_scoped_clone_keeps_only_surviving_typed_map_checks() -> None:
    """Reject invalid maps in a real clone without restoring hidden fields.

    Scenario: permission scoped clone keeps only surviving typed map checks.
    """
    received: list[dict[str, object]] = []
    factory_calls: list[str] = []

    def hidden_factory() -> str:
        """Record any evaluation of the permission-hidden default."""
        factory_calls.append("hidden")
        return "hidden default"

    class PermissionScopedTypedMapInput(InputType):
        mapping: dict[str, int]
        hidden: str = Field(default_factory=hidden_factory)
        removed_map: dict[str, int] | None = None

    input_type = compile_input_type(
        PermissionScopedTypedMapInput, name="PermissionScopedTypedMapInput"
    )
    for name in ("hidden", "removedMap"):
        input_type.fields[name].extensions = {
            "gdx_required_perms": frozenset({"test.hidden"})
        }
    full = _schema_for_payload(input_type, received).graphql_schema
    clone = prune_schema(full, frozenset())
    cloned_input = clone.get_type("PermissionScopedTypedMapInput")
    assert cloned_input is not input_type
    assert set(cloned_input.fields) == {"mapping"}

    valid_map = {"large": 2**63}
    variable_query = (
        "mutation($payload: PermissionScopedTypedMapInput!) "
        "{ submit(payload: $payload) { result } }"
    )
    valid = graphql_sync(
        clone,
        variable_query,
        variable_values={"payload": {"mapping": valid_map}},
    )
    assert valid.errors is None, valid.errors
    assert received == [{"mapping": valid_map}]
    assert received[0]["mapping"] is valid_map
    assert factory_calls == []
    received.clear()

    invalid_cases = (
        ("mutation { submit(payload: {mapping: {secret: true}}) { result } }", None),
        (variable_query, {"payload": {"mapping": {"secret": True}}}),
    )
    for query, variables in invalid_cases:
        full_result = graphql_sync(full, query, variable_values=variables)
        assert full_result.errors and received == []
        assert "PermissionScopedTypedMapInput.mapping" in full_result.errors[0].message
        factory_calls.clear()

        cloned_result = graphql_sync(clone, query, variable_values=variables)
        assert cloned_result.errors and received == []
        assert (
            "PermissionScopedTypedMapInput.mapping" in cloned_result.errors[0].message
        )
        assert "secret" not in cloned_result.errors[0].message
        assert factory_calls == []

    assert set(cloned_input.out_type.typed_maps) == {"mapping"}
    assert set(cloned_input.out_type.factories) == set()


@pytest.mark.parametrize("inline", [False, True])
def test_production_http_preserves_deliberate_graphql_input_error(
    inline: bool,
) -> None:
    """Return a safe GraphQL error before mutation under production settings.

    Args:
        inline: Whether the invalid object is written as a GraphQL literal.
    """
    received: list[dict[str, object]] = []

    schema = _schema_for_payload(
        compile_input_type(HttpTypedMapPayload, name="HttpMapInput"), received
    )
    query = (
        "mutation { submit(payload: {mapping: {secret: true}}) { result } }"
        if inline
        else "mutation($payload: HttpMapInput!) { submit(payload: $payload) { result } }"
    )
    body: dict[str, object] = {"query": query}
    if not inline:
        body["variables"] = {"payload": {"mapping": {"secret": True}}}
    request = RequestFactory().post(
        "/graphql/",
        data=json.dumps(body),
        content_type="application/json",
    )
    with override_settings(DEBUG=False):
        response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code != 500
    assert payload["errors"]
    assert "HttpMapInput.mapping" in payload["errors"][0]["message"]
    assert "secret" not in payload["errors"][0]["message"]
    assert "INTERNAL_SERVER_ERROR" != payload["errors"][0].get("extensions", {}).get(
        "code"
    )
    assert received == []
