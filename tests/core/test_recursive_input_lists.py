"""Public recursive input-list contract for supported scalar leaves."""

from __future__ import annotations

from typing import Dict

import pytest
from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString, graphql_sync

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.schema import DjangoGraphQLSchema


class RecursiveIntRowsPayload(InputType):
    """Declare a doubly nested list of integers.

    The rows field is list of list of int.
    """

    rows: list[list[int]]


def test_nested_integer_lists_use_recursive_graphql_wrappers() -> None:
    """Compile nested supported scalars and deliver their structured values.

    Scenario: nested integer lists use recursive graphql wrappers.
    """
    input_type = compile_input_type(
        RecursiveIntRowsPayload, name="RecursiveIntRowsPayload"
    )
    received: list[dict[str, object]] = []

    class SubmitRecursiveRows(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "accepted"}

    class RecursiveRowsQuery(ObjectType):
        ping = field(GraphQLString)

    class RecursiveRowsMutations(ObjectType):
        submitRecursiveRows = SubmitRecursiveRows.Field()

    schema = DjangoGraphQLSchema(
        query=RecursiveRowsQuery, mutation=RecursiveRowsMutations
    ).graphql_schema
    assert str(input_type.fields["rows"].type) == "[[Int!]!]!"
    result = graphql_sync(
        schema,
        "mutation($payload: RecursiveIntRowsPayload!) { "
        "submitRecursiveRows(payload: $payload) { result } }",
        variable_values={"payload": {"rows": [[1, 2], [3]]}},
    )
    assert result.errors is None
    assert received == [{"rows": [[1, 2], [3]]}]


def _schema_for_payload(
    input_type: object, received: list[dict[str, object]]
) -> object:
    """Expose a compiled input through a real mutation field.

    Args:
        input_type: Compiled input object.
        received: Resolver call log.

    Returns:
        Native executable GraphQL schema.
    """

    class SubmitNestedPayload(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            received.append(payload)
            return {"result": "accepted"}

    class NestedPayloadQuery(ObjectType):
        ping = field(GraphQLString)

    class NestedPayloadMutations(ObjectType):
        submitNestedPayload = SubmitNestedPayload.Field()

    return DjangoGraphQLSchema(
        query=NestedPayloadQuery, mutation=NestedPayloadMutations
    ).graphql_schema


def test_nested_list_nullability_and_singleton_coercion() -> None:
    """Retain nullable positions and GraphQL wrapping at each list level.

    Scenario: nested list nullability and singleton coercion.
    """

    class NullableRecursiveRowsPayload(InputType):
        cells: list[list[int | None] | None] | None = None
        cubes: list[list[list[int]]] | None = None

    input_type = compile_input_type(
        NullableRecursiveRowsPayload, name="NullableRecursiveRowsPayload"
    )
    assert str(input_type.fields["cells"].type) == "[[Int]]"
    assert str(input_type.fields["cubes"].type) == "[[[Int!]!]!]"
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    query = (
        "mutation($payload: NullableRecursiveRowsPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }"
    )
    for source, expected in (
        (
            {"cells": [None, [1, None]], "cubes": [[[1], [2]]]},
            {"cells": [None, [1, None]], "cubes": [[[1], [2]]]},
        ),
        ({"cells": [1, 2], "cubes": 3}, {"cells": [[1], [2]], "cubes": [[[3]]]}),
        ({"cells": None}, {"cells": None, "cubes": None}),
        ({}, {"cells": None, "cubes": None}),
    ):
        result = graphql_sync(schema, query, variable_values={"payload": source})
        assert result.errors is None, result.errors
        assert received[-1] == expected
    inline = graphql_sync(
        schema,
        "mutation { submitNestedPayload(payload: {cells: [[1, null], null], "
        "cubes: [[[3]]]}) { result } }",
    )
    assert inline.errors is None, inline.errors
    assert received[-1] == {"cells": [[1, None], None], "cubes": [[[3]]]}
    before = len(received)
    for source in ({"cubes": [[None]]}, {"cubes": [["3"]]}):
        invalid = graphql_sync(schema, query, variable_values={"payload": source})
        assert invalid.errors and len(received) == before


def test_supported_nested_input_and_literal_enum_leaves() -> None:
    """Keep nested object inputs and Literal values on their approved wires.

    Scenario: supported nested input and literal enum leaves.
    """
    from typing import Literal

    class RecursiveChildPayload(InputType):
        score: int

    compile_input_type(RecursiveChildPayload, name="RecursiveChildPayload")

    class RecursiveCompositePayload(InputType):
        children: list[list[RecursiveChildPayload]]
        statuses: list[list[Literal["draft", "published"]]]

    input_type = compile_input_type(
        RecursiveCompositePayload, name="RecursiveCompositePayload"
    )
    assert str(input_type.fields["children"].type) == "[[RecursiveChildPayload!]!]!"
    assert "RecursiveCompositePayloadStatusesEnum" in str(
        input_type.fields["statuses"].type
    )
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    valid = graphql_sync(
        schema,
        "mutation { submitNestedPayload(payload: {children: [[{score: 2}]], "
        "statuses: [[DRAFT, PUBLISHED]]}) { result } }",
    )
    assert valid.errors is None, valid.errors
    assert received == [
        {
            "children": [[{"score": 2}]],
            "statuses": [["draft", "published"]],
        }
    ]
    rejected = graphql_sync(
        schema,
        "mutation { submitNestedPayload(payload: {children: [[{score: 2}]], "
        "statuses: [[INVALID]]}) { result } }",
    )
    assert rejected.errors and len(received) == 1


class RecursiveIntMapPayload(InputType):
    """Declare nested lists of integer maps with builtin dict.

    The maps field is list of list of dict of str to int.
    """

    maps: list[list[dict[str, int]]]


class RecursiveTypingIntMapPayload(InputType):
    """Declare nested lists of integer maps with typing.Dict.

    The maps field is list of list of typing.Dict of str to int.
    """

    maps: list[list[Dict[str, int]]]


class RecursiveStringMapPayload(InputType):
    """Declare nested lists of string maps with builtin dict.

    The maps field is list of list of dict of str to str.
    """

    maps: list[list[dict[str, str]]]


class RecursiveTypingStringMapPayload(InputType):
    """Declare nested lists of string maps with typing.Dict.

    The maps field is list of list of typing.Dict of str to str.
    """

    maps: list[list[Dict[str, str]]]


@pytest.mark.parametrize(
    ("payload_type", "good", "bad"),
    [
        (RecursiveIntMapPayload, {"count": 3}, {"secret": True}),
        (RecursiveTypingIntMapPayload, {"count": 3}, {"secret": "3"}),
        (RecursiveStringMapPayload, {"name": "Ada"}, {"secret": 3}),
        (RecursiveTypingStringMapPayload, {"name": "Ada"}, {"secret": None}),
    ],
)
def test_deep_typed_maps_keep_strict_leaf_contract(
    payload_type: type[InputType], good: dict[str, object], bad: dict[str, object]
) -> None:
    """Reject invalid deep leaves with indexed paths before mutation.

    Args:
        payload_type: Input payload type under test.
        good: Valid payload accepted by the case.
        bad: Invalid value supplied by the parametrized case.
    """
    from django_graphex.core.schema_pruner import prune_schema

    input_type = compile_input_type(payload_type, name=payload_type.__name__)
    assert str(input_type.fields["maps"].type) == "[[JSON!]!]!"
    received: list[dict[str, object]] = []
    full = _schema_for_payload(input_type, received)
    schema = prune_schema(full, frozenset())
    query = (
        f"mutation($payload: {payload_type.__name__}!) {{ "
        "submitNestedPayload(payload: $payload) { result } }"
    )
    valid = graphql_sync(schema, query, variable_values={"payload": {"maps": [[good]]}})
    assert valid.errors is None, valid.errors
    assert received[-1]["maps"][0][0] is good
    invalid = graphql_sync(
        schema, query, variable_values={"payload": {"maps": [[], [bad]]}}
    )
    assert invalid.errors and len(received) == 1
    assert f"{payload_type.__name__}.maps[1][0]" in invalid.errors[0].message
    assert "secret" not in invalid.errors[0].message


def test_nested_json_fixed_default_and_factory_keep_runtime_shape() -> None:
    """Publish valid fixed metadata but run omitted factories each time.

    Scenario: nested json fixed default and factory keep runtime shape.
    """
    from graphql import build_schema, parse, print_schema
    from pydantic import Field

    calls: list[int] = []
    fixed_default = [[{"views": 1}]]

    def fresh_value() -> list[list[dict[str, int]]]:
        calls.append(len(calls) + 1)
        return [[{"count": calls[-1]}]]

    class RecursiveJsonDefaultsPayload(InputType):
        fixed: list[list[dict[str, int]]] = fixed_default
        fresh: list[list[dict[str, int]]] = Field(default_factory=fresh_value)
        raw: list[dict] = [{"views": 2}]

    input_type = compile_input_type(
        RecursiveJsonDefaultsPayload, name="RecursiveJsonDefaultsPayload"
    )
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    sdl = print_schema(schema)
    assert "fixed: [[JSON!]!] = [[{ views: 1 }]]" in sdl
    assert "raw: [JSON!] = [{ views: 2 }]" in sdl
    assert "fresh: [[JSON!]!]" in sdl and "fresh: [[JSON!]!] =" not in sdl
    parse(sdl)
    assert "fixed: [[JSON!]!] = [[{ views: 1 }]]" in print_schema(build_schema(sdl))
    for _ in range(2):
        result = graphql_sync(
            schema, "mutation { submitNestedPayload(payload: {}) { result } }"
        )
        assert result.errors is None, result.errors
    assert calls == [1, 2]
    assert received[0]["fixed"] == fixed_default
    assert received[0]["fixed"] is not fixed_default
    assert received[0]["fixed"][0][0] is fixed_default[0][0]
    assert received[0]["fresh"] == [[{"count": 1}]]
    assert received[1]["fresh"] == [[{"count": 2}]]


class RecursiveNullableInnerBareJsonDefaultPayload(InputType):
    """Declare nested lists whose inner list is nullable and holds bare JSON maps.

    The rows field carries a fixed default that includes a null inner list.
    """

    rows: list[list[dict] | None] = [None, [{"x": 1}, {"y": 2}]]


class RecursiveNullableLeafBareJsonDefaultPayload(InputType):
    """Declare nested lists whose leaf is a nullable bare JSON map.

    The rows field carries a fixed default that includes a null leaf.
    """

    rows: list[list[dict | None]] = [[None, {"x": 1}]]


@pytest.mark.parametrize(
    ("payload_type", "expected_type", "expected_default"),
    [
        (
            RecursiveNullableInnerBareJsonDefaultPayload,
            "[[JSON!]]",
            "[null, [{ x: 1 }, { y: 2 }]]",
        ),
        (
            RecursiveNullableLeafBareJsonDefaultPayload,
            "[[JSON]!]",
            "[[null, { x: 1 }]]",
        ),
    ],
)
def test_nullable_nested_bare_json_fixed_defaults_remain_printable(
    payload_type: type[InputType], expected_type: str, expected_default: str
) -> None:
    """Publish nullable nested JSON defaults without changing omitted values.

    Args:
        payload_type: Input payload type under test.
        expected_type: Printed type the case expects.
        expected_default: Printed default literal the case expects.
    """
    from graphql import build_schema, parse, print_schema

    input_type = compile_input_type(payload_type, name=payload_type.__name__)
    assert str(input_type.fields["rows"].type) == expected_type
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    sdl = print_schema(schema)
    declaration = f"rows: {expected_type} = {expected_default}"
    assert declaration in sdl
    parse(sdl)
    assert declaration in print_schema(build_schema(sdl))

    introspection = graphql_sync(
        schema,
        f'{{ __type(name: "{payload_type.__name__}") {{ '
        "inputFields { name defaultValue } } }",
    )
    assert introspection.errors is None
    assert introspection.data == {
        "__type": {"inputFields": [{"name": "rows", "defaultValue": expected_default}]}
    }

    omitted = graphql_sync(
        schema, "mutation { submitNestedPayload(payload: {}) { result } }"
    )
    assert omitted.errors is None, omitted.errors
    original = payload_type.model_fields["rows"].default
    assert received == [{"rows": original}]
    assert received[0]["rows"] is not original
    assert received[0]["rows"][-1][-1] is original[-1][-1]


def test_unsupported_nested_leaves_keep_legacy_fallback() -> None:
    """Avoid inventing wrappers for leaves outside the approved set.

    Scenario: unsupported nested leaves keep legacy fallback.
    """
    import warnings
    from typing import Union

    class UnsupportedRecursiveLeavesPayload(InputType):
        sets: list[list[set[int]]]
        maps: list[list[dict[str, float]]]
        unions: list[list[Union[int, str]]]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        input_type = compile_input_type(
            UnsupportedRecursiveLeavesPayload,
            name="UnsupportedRecursiveLeavesPayload",
        )
        fields = input_type.fields
    assert [str(fields[name].type) for name in ("sets", "maps", "unions")] == [
        "[String!]!"
    ] * 3
    assert (
        len(
            [
                item
                for item in caught
                if "unsupported input field type" in str(item.message)
            ]
        )
        == 3
    )
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    rejected = graphql_sync(
        schema,
        "mutation($payload: UnsupportedRecursiveLeavesPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }",
        variable_values={
            "payload": {"sets": [[1]], "maps": [[{"x": 1.5}]], "unions": [[1]]}
        },
    )
    assert rejected.errors and received == []


def test_deep_map_alias_factory_and_permission_clone() -> None:
    """Retain surviving validators and fresh factories in a pruned schema.

    Scenario: deep map alias factory and permission clone.
    """
    from pydantic import Field

    from django_graphex.core.schema_pruner import prune_schema

    calls: list[int] = []

    def fresh_rows() -> list[list[dict[str, int]]]:
        calls.append(len(calls) + 1)
        return [[{"count": calls[-1]}]]

    class ScopedRecursiveMapPayload(InputType):
        score_maps: list[list[dict[str, int]]] = Field(
            alias="scoreMaps", default_factory=fresh_rows
        )
        hidden_maps: list[list[dict[str, int]]] | None = None

    input_type = compile_input_type(
        ScopedRecursiveMapPayload, name="ScopedRecursiveMapPayload"
    )
    input_type.fields["hiddenMaps"].extensions = {
        "gdx_required_perms": frozenset({"test.hidden"})
    }
    received: list[dict[str, object]] = []
    schema = prune_schema(_schema_for_payload(input_type, received), frozenset())
    cloned = schema.get_type("ScopedRecursiveMapPayload")
    assert set(cloned.fields) == {"scoreMaps"}
    assert set(cloned.out_type.typed_maps) == {"score_maps"}
    query = (
        "mutation($payload: ScopedRecursiveMapPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }"
    )
    for number in (1, 2):
        omitted = graphql_sync(schema, query, variable_values={"payload": {}})
        assert omitted.errors is None, omitted.errors
        assert received[-1] == {"score_maps": [[{"count": number}]]}
    assert calls == [1, 2]
    bad = graphql_sync(
        schema,
        query,
        variable_values={"payload": {"scoreMaps": [[], [{"secret": True}]]}},
    )
    assert bad.errors and len(received) == 2
    assert "ScopedRecursiveMapPayload.scoreMaps[1][0]" in bad.errors[0].message
    assert "secret" not in bad.errors[0].message
    hidden = graphql_sync(
        schema, query, variable_values={"payload": {"hiddenMaps": [[{"x": 1}]]}}
    )
    assert hidden.errors and len(received) == 2


def test_nested_bare_json_keeps_leaf_identity_and_single_list_parity() -> None:
    """Wrap lists without copying the existing raw JSON leaf contract.

    Scenario: nested bare json keeps leaf identity and single list parity.
    """

    class RecursiveBareJsonPayload(InputType):
        nested: list[list[dict]]
        single: list[dict]

    input_type = compile_input_type(
        RecursiveBareJsonPayload, name="RecursiveBareJsonPayload"
    )
    assert str(input_type.fields["nested"].type) == "[[JSON!]!]!"
    assert str(input_type.fields["single"].type) == "[JSON!]!"
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    leaf = {1: True}
    result = graphql_sync(
        schema,
        "mutation($payload: RecursiveBareJsonPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }",
        variable_values={"payload": {"nested": [[leaf]], "single": [leaf]}},
    )
    assert result.errors is None, result.errors
    assert received[0]["nested"][0][0] is leaf
    assert received[0]["single"][0] is leaf


def test_typing_list_and_nullable_nested_map_elements() -> None:
    """Keep typing aliases and nullable strict-map leaves on their wires.

    Scenario: typing list and nullable nested map elements.
    """
    from typing import List

    class TypingRecursiveRowsPayload(InputType):
        words: List[List[str]]
        maps: list[list[dict[str, int] | None] | None] | None = None

    input_type = compile_input_type(
        TypingRecursiveRowsPayload, name="TypingRecursiveRowsPayload"
    )
    assert str(input_type.fields["words"].type) == "[[String!]!]!"
    assert str(input_type.fields["maps"].type) == "[[JSON]]"
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    query = (
        "mutation($payload: TypingRecursiveRowsPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }"
    )
    valid = graphql_sync(
        schema,
        query,
        variable_values={
            "payload": {"words": [["one"]], "maps": [None, [{"count": 2}, None]]}
        },
    )
    assert valid.errors is None, valid.errors
    assert received[-1]["maps"] == [None, [{"count": 2}, None]]
    explicit_null = graphql_sync(
        schema,
        query,
        variable_values={"payload": {"words": [["one"]], "maps": None}},
    )
    assert explicit_null.errors is None, explicit_null.errors
    assert received[-1]["maps"] is None
    invalid = graphql_sync(
        schema,
        query,
        variable_values={
            "payload": {"words": [["one"]], "maps": [None, [{"count": True}]]}
        },
    )
    assert invalid.errors and len(received) == 2
    assert "TypingRecursiveRowsPayload.maps[1][0]" in invalid.errors[0].message


@pytest.mark.parametrize(
    ("case", "default"),
    [
        ("OuterObject", {"views": 1}),
        ("NullLeaf", [[None]]),
        ("InnerObject", [{"views": 1}]),
        ("InvalidName", [[{"x-y": 1}]]),
        ("InvalidValue", [[{"views": True}]]),
    ],
)
def test_ineligible_nested_json_defaults_keep_legacy_metadata(
    case: str, default: object
) -> None:
    """Avoid publishing malformed or unprintable nested default literals.

    Args:
        case: Name or index of the parametrized case.
        default: Default value under test.
    """
    payload_type = type(
        f"RecursiveBadDefault{case}Payload",
        (InputType,),
        {
            "__annotations__": {"mappings": list[list[dict[str, int]]]},
            "mappings": default,
        },
    )
    input_type = compile_input_type(payload_type, name=payload_type.__name__)
    assert input_type.fields["mappings"].default_value == default
    assert input_type.fields["mappings"].default is None


def test_deep_typed_maps_validate_when_defaults_are_not_emitted() -> None:
    """Keep strict validation on Django-style input compilation.

    Scenario: deep typed maps validate when defaults are not emitted.
    """

    class NoDefaultsRecursiveMapPayload(InputType):
        maps: list[list[dict[str, int]]]

    input_type = compile_input_type(
        NoDefaultsRecursiveMapPayload,
        name="NoDefaultsRecursiveMapPayload",
        emit_defaults=False,
    )
    assert str(input_type.fields["maps"].type) == "[[JSON!]!]!"
    assert set(input_type.out_type.typed_maps) == {"maps"}
    received: list[dict[str, object]] = []
    schema = _schema_for_payload(input_type, received)
    invalid = graphql_sync(
        schema,
        "mutation($payload: NoDefaultsRecursiveMapPayload!) { "
        "submitNestedPayload(payload: $payload) { result } }",
        variable_values={"payload": {"maps": [[{"secret": True}]]}},
    )
    assert invalid.errors and received == []
    assert "NoDefaultsRecursiveMapPayload.maps[0][0]" in invalid.errors[0].message
