"""Public input contract for exact string-valued typed dictionaries."""

from __future__ import annotations

import json
import warnings
from typing import Dict

import pytest
from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLNonNull,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import Field

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


class BuiltinStringMapPayload(InputType):
    mapping: dict[str, str]


class TypingStringMapPayload(InputType):
    mapping: Dict[str, str]


def _schema_for_payload(
    input_type: object, received: list[dict[str, object]]
) -> DjangoGraphQLSchema:
    """Mount a compiled input type on a public mutation.

    Args:
        input_type: Compiled input object.
        received: Resolver invocation log.

    Returns:
        Schema with the input-bearing mutation.
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
    "payload_type", [BuiltinStringMapPayload, TypingStringMapPayload]
)
def test_string_map_spellings_use_strict_json_public_input(
    payload_type: type[InputType],
) -> None:
    """Expose both approved spellings as raw JSON rather than String fallback."""
    received: list[dict[str, object]] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        input_type = compile_input_type(payload_type, name=payload_type.__name__)
        schema = _schema_for_payload(input_type, received).graphql_schema
    assert not [
        item for item in caught if "unsupported input field type" in str(item.message)
    ]
    assert "mapping: JSON!" in print_schema(schema)
    mapping = {"greeting": "hello"}
    result = graphql_sync(
        schema,
        f"mutation($payload: {payload_type.__name__}!) {{ submit(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"mapping": mapping}},
    )
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "accepted"}}
    assert received == [{"mapping": mapping}]
    assert received[0]["mapping"] is mapping


@pytest.mark.parametrize(
    "payload_type", [BuiltinStringMapPayload, TypingStringMapPayload]
)
@pytest.mark.parametrize(
    "bad",
    [
        "not an object",
        3,
        True,
        ["x"],
        {1: "x"},
        {"secret": 3},
        {"secret": True},
        {"secret": 3.5},
        {"secret": ["x"]},
        {"secret": {"x": "y"}},
        {"secret": None},
    ],
)
def test_invalid_string_map_variable_is_rejected_before_resolver(
    payload_type: type[InputType], bad: object
) -> None:
    """Reject wrong shapes without exposing supplied keys or values."""
    received: list[dict[str, object]] = []
    input_type = compile_input_type(payload_type, name=payload_type.__name__)
    schema = _schema_for_payload(input_type, received).graphql_schema
    result = graphql_sync(
        schema,
        f"mutation($payload: {payload_type.__name__}!) {{ submit(payload: $payload) {{ result }} }}",
        variable_values={"payload": {"mapping": bad}},
    )
    assert result.errors and received == []
    assert f"{payload_type.__name__}.mapping" in result.errors[0].message
    assert "secret" not in result.errors[0].message


def test_inline_string_maps_preserve_values_and_reject_nonstrings() -> None:
    """Apply the same declared contract to GraphQL object literals."""
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(
        compile_input_type(BuiltinStringMapPayload, name="BuiltinStringMapPayload"),
        received,
    ).graphql_schema
    valid = graphql_sync(
        schema, 'mutation { submit(payload: {mapping: {name: "café"}}) { result } }'
    )
    invalid = graphql_sync(
        schema, "mutation { submit(payload: {mapping: {secret: 3}}) { result } }"
    )
    assert valid.errors is None and received == [{"mapping": {"name": "café"}}]
    assert invalid.errors and len(received) == 1
    assert "BuiltinStringMapPayload.mapping" in invalid.errors[0].message
    assert "secret" not in invalid.errors[0].message


def test_wrappers_defaults_factory_and_nested_inputs_keep_string_validation() -> None:
    """Validate wrapped values without freezing an omitted-field factory."""
    received: list[dict[str, object]] = []
    calls: list[int] = []

    def fresh_map() -> dict[str, str]:
        calls.append(len(calls) + 1)
        return {"sequence": str(calls[-1])}

    class NestedStringMapChild(InputType):
        score_map: dict[str, str] = Field(alias="scoreMap")

    compile_input_type(NestedStringMapChild, name="NestedStringMapChild")

    class WrappedStringMapParent(InputType):
        child: NestedStringMapChild
        mapping: dict[str, str] = Field(default_factory=fresh_map)
        fixed: dict[str, str] = {"base": "one"}
        optional: dict[str, str] | None = None
        maps: list[dict[str, str] | None] | None = None

    input_type = compile_input_type(
        WrappedStringMapParent, name="WrappedStringMapParent"
    )
    schema = _schema_for_payload(input_type, received).graphql_schema
    assert 'fixed: JSON = { base: "one" }' in print_schema(schema)
    query = "mutation($payload: WrappedStringMapParent!) { submit(payload: $payload) { result } }"
    for number in (1, 2):
        result = graphql_sync(
            schema,
            query,
            variable_values={
                "payload": {
                    "child": {"scoreMap": {"x": "value"}},
                    "maps": [{"x": "value"}, None],
                }
            },
        )
        assert result.errors is None, result.errors
        assert received[-1]["mapping"] == {"sequence": str(number)}
    assert calls == [1, 2]
    assert received[-1]["optional"] is None
    assert received[-1]["maps"] == [{"x": "value"}, None]
    explicit_null = graphql_sync(
        schema,
        query,
        variable_values={
            "payload": {"child": {"scoreMap": {}}, "optional": None, "maps": None}
        },
    )
    assert explicit_null.errors is None
    assert received[-1]["optional"] is None and received[-1]["maps"] is None
    received.pop()
    for bad in (
        {"child": {"scoreMap": {"x": True}}},
        {"child": {"scoreMap": {"x": "ok"}}, "maps": [{"x": 3}]},
    ):
        result = graphql_sync(schema, query, variable_values={"payload": bad})
        assert result.errors and len(received) == 2


def test_permission_clone_preserves_surviving_string_map_validator() -> None:
    """Keep validators only for actual fields in a permission-pruned clone."""
    received: list[dict[str, object]] = []

    class PermissionScopedStringMapInput(InputType):
        mapping: Dict[str, str]
        hidden: Dict[str, str] | None = None

    input_type = compile_input_type(
        PermissionScopedStringMapInput, name="PermissionScopedStringMapInput"
    )
    input_type.fields["hidden"].extensions = {
        "gdx_required_perms": frozenset({"test.hidden"})
    }
    full = _schema_for_payload(input_type, received).graphql_schema
    clone = prune_schema(full, frozenset())
    cloned_input = clone.get_type("PermissionScopedStringMapInput")
    assert set(cloned_input.fields) == {"mapping"}
    assert set(cloned_input.out_type.typed_maps) == {"mapping"}
    query = "mutation($payload: PermissionScopedStringMapInput!) { submit(payload: $payload) { result } }"
    mapping = {"name": "value"}
    valid = graphql_sync(
        clone, query, variable_values={"payload": {"mapping": mapping}}
    )
    assert valid.errors is None and received[0]["mapping"] is mapping
    received.clear()
    invalid = graphql_sync(
        clone, query, variable_values={"payload": {"mapping": {"secret": True}}}
    )
    assert invalid.errors and received == []
    assert "PermissionScopedStringMapInput.mapping" in invalid.errors[0].message
    assert "secret" not in invalid.errors[0].message


def test_fixed_string_map_lists_render_only_valid_metadata() -> None:
    """Print valid fixed lists while retaining malformed default behavior."""
    received: list[dict[str, object]] = []

    class FixedStringMapListPayload(InputType):
        maps: list[dict[str, str] | None] = [{"name": "Ada"}, {"name": "Grace"}, None]

    input_type = compile_input_type(
        FixedStringMapListPayload, name="FixedStringMapListPayload"
    )
    schema = _schema_for_payload(input_type, received).graphql_schema
    assert 'maps: [JSON] = [{ name: "Ada" }, { name: "Grace" }, null]' in print_schema(
        schema
    )
    omitted = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    assert omitted.errors is None and received == [
        {"maps": [{"name": "Ada"}, {"name": "Grace"}, None]}
    ]

    class InvalidFixedStringMapListPayload(InputType):
        maps: list[dict[str, str]] = [{"name": 3}]

    invalid_type = compile_input_type(
        InvalidFixedStringMapListPayload, name="InvalidFixedStringMapListPayload"
    )
    assert invalid_type.fields["maps"].default_value == [{"name": 3}]

    class BareJsonListPayload(InputType):
        maps: list[dict] = [{"one": 1}, {"two": 2}]

    bare_type = compile_input_type(BareJsonListPayload, name="BareJsonListPayload")
    bare_schema = _schema_for_payload(bare_type, received).graphql_schema
    assert "maps: [JSON!] = [{ one: 1 }, { two: 2 }]" in print_schema(bare_schema)


@pytest.mark.parametrize("inline", [False, True])
def test_http_errors_for_invalid_string_map_are_safe(inline: bool) -> None:
    """Avoid an internal server error for deliberate input rejection.

    Args:
        inline: Whether the invalid value is a GraphQL literal.
    """
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(
        compile_input_type(TypingStringMapPayload, name="TypingStringMapPayload"),
        received,
    )
    query = (
        "mutation { submit(payload: {mapping: {secret: true}}) { result } }"
        if inline
        else "mutation($payload: TypingStringMapPayload!) { submit(payload: $payload) { result } }"
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
    assert "TypingStringMapPayload.mapping" in payload["errors"][0]["message"]
    assert "secret" not in payload["errors"][0]["message"]
    assert (
        payload["errors"][0].get("extensions", {}).get("code")
        != "INTERNAL_SERVER_ERROR"
    )
