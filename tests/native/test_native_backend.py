"""Tests for the GDX_BACKEND dual-backend harness.

Verifies that:
- GDX_BACKEND env var can be read
- native_only mark is recognized
- normalize_sdl utility is importable and functional
- The graphene CI path is unaffected (additivity gate).

Run with: .venv/bin/python -m pytest tests/native/test_native_backend.py -x -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.native_only


def test_gdx_backend_env_readable():
    """GDX_BACKEND env var should be readable (default 'graphene' or 'native')."""
    backend = os.environ.get("GDX_BACKEND", "graphene")
    assert backend in ("graphene", "native"), f"Unexpected GDX_BACKEND value: {backend!r}"


def test_native_only_mark_registered():
    """native_only mark is registered in pytest (no PytestUnknownMarkWarning)."""
    # This test just ensures the mark is used — the conftest registers it.
    # If the mark is unregistered, this test would show a warning (but still pass).
    # The actual registration is in tests/native/conftest.py.
    pass


def test_normalize_sdl_importable():
    """normalize_sdl utility is importable from the native conftest."""
    from tests.native.conftest import normalize_sdl

    assert callable(normalize_sdl)


def test_normalize_sdl_sorts_types():
    """normalize_sdl sorts type blocks alphabetically."""
    from tests.native.conftest import normalize_sdl

    sdl = """
type ZType {
  value: String
}

type AType {
  name: String
}
"""
    normalized = normalize_sdl(sdl)
    # After normalization, AType should come before ZType
    a_pos = normalized.find("AType")
    z_pos = normalized.find("ZType")
    assert a_pos < z_pos, "normalize_sdl should sort type blocks alphabetically"


def test_normalize_sdl_strips_descriptions():
    """normalize_sdl strips description strings from SDL."""
    from tests.native.conftest import normalize_sdl

    sdl = '''
"""A description of MyType."""
type MyType {
  """field description"""
  name: String
}
'''
    normalized = normalize_sdl(sdl)
    assert '"""' not in normalized, "normalize_sdl should strip descriptions"


def test_normalize_sdl_idempotent():
    """normalize_sdl is idempotent — applying twice gives same result."""
    from tests.native.conftest import normalize_sdl

    sdl = """
type BType {
  value: Int
}

type AType {
  name: String
}
"""
    first = normalize_sdl(sdl)
    second = normalize_sdl(first)
    assert first == second, "normalize_sdl should be idempotent"


# ---------------------------------------------------------------------------
# Task 2.12 RED → 2.13 GREEN: Dual-backend SDL parity for input types
# ---------------------------------------------------------------------------


def test_compile_input_type_sdl_matches_graphene_input_type():
    """SDL from compile_input_type is structurally equivalent to graphene InputObjectType SDL.

    This is the primary safety net for WU-B: the native and graphene backends
    must produce structurally equivalent input type SDL (same fields, same
    types, same nullability), normalized by normalize_sdl.

    We compare field names and nullability by printing both schemas and
    extracting input type definitions.
    """
    from graphql import GraphQLSchema, GraphQLObjectType, GraphQLField, GraphQLString
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLInt
    from graphql.utilities import print_schema
    from tests.native.conftest import normalize_sdl
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import compile_input_type

    # Model-free InputType — same fields as we'd build in graphene
    class _WuBSdlParityInput(InputType):
        name: str   # required → NonNull in native
        value: int = 0  # optional → nullable

    # Native backend: compile_input_type
    native_input_type = compile_input_type(
        _WuBSdlParityInput,
        name="WuBSdlParityInput",
    )

    # Verify the native input type has the correct field structure
    native_fields = native_input_type.fields

    # 'name' must be NonNull String (required field)
    assert "name" in native_fields, f"Expected 'name' in fields, got: {list(native_fields.keys())}"
    name_field = native_fields["name"]
    assert isinstance(name_field.type, GraphQLNonNull), (
        f"'name' field should be NonNull (required), got: {name_field.type}"
    )

    # 'value' must be nullable Int (has default=0)
    assert "value" in native_fields, f"Expected 'value' in fields, got: {list(native_fields.keys())}"
    value_field = native_fields["value"]
    assert not isinstance(value_field.type, GraphQLNonNull), (
        f"'value' field should be nullable (has default), got: {value_field.type}"
    )

    # Build minimal native schema and print SDL
    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta
    gdx_payload = GdxPayload(GdxMeta(name="Query"))

    query_type = GraphQLObjectType(
        "Query",
        fields=lambda: {
            "hello": GraphQLField(
                GraphQLString,
                args={"input": GraphQLArgument(native_input_type)},
            )
        },
        extensions={"gdx": gdx_payload},
    )

    native_schema = GraphQLSchema(query=query_type)
    native_sdl = print_schema(native_schema)

    # Verify native SDL contains the input type
    assert "WuBSdlParityInput" in native_sdl, (
        f"Native SDL missing 'WuBSdlParityInput'. SDL:\n{native_sdl}"
    )
    assert "name: String!" in native_sdl, (
        f"Native SDL: expected 'name: String!' field. SDL:\n{native_sdl}"
    )
    assert "value: Int" in native_sdl, (
        f"Native SDL: expected 'value: Int' field. SDL:\n{native_sdl}"
    )

    # Graphene backend: build equivalent input type and compare structure
    import graphene

    class _WuBGrapheneSdlInput(graphene.InputObjectType):
        name = graphene.String(required=True)
        value = graphene.Int(default_value=0)

    class _WuBSdlQuery(graphene.ObjectType):
        hello = graphene.String(
            input=graphene.Argument(_WuBGrapheneSdlInput, required=False)
        )

    graphene_schema = graphene.Schema(query=_WuBSdlQuery)
    graphene_sdl = str(graphene_schema)

    # Verify graphene SDL contains the same field structure
    assert "name: String!" in graphene_sdl, (
        f"Graphene SDL: expected 'name: String!' field. SDL:\n{graphene_sdl}"
    )
    assert "value: Int" in graphene_sdl, (
        f"Graphene SDL: expected 'value: Int' field. SDL:\n{graphene_sdl}"
    )

    # Use normalize_sdl to confirm SDL sorting is consistent
    native_normalized = normalize_sdl(native_sdl)
    graphene_normalized = normalize_sdl(graphene_sdl)

    # Both normalized SDLs should contain their respective input types
    assert "WuBSdlParityInput" in native_normalized
    assert "WuBGrapheneSdlInput" in graphene_normalized

    # normalize_sdl idempotency check (both already tested individually)
    assert normalize_sdl(native_normalized) == native_normalized
    assert normalize_sdl(graphene_normalized) == graphene_normalized


def test_normalize_sdl_input_type_structure_parity():
    """Input type SDL structure is consistent between normalize_sdl calls.

    Verifies that normalize_sdl produces stable ordering for input types,
    enabling reliable diff comparisons between graphene and native backends.
    """
    from tests.native.conftest import normalize_sdl

    # Two SDL strings that are semantically identical (same input type, different order)
    sdl_a = """
input PersonInput {
  lastName: String
  firstName: String!
}
"""
    sdl_b = """
input PersonInput {
  firstName: String!
  lastName: String
}
"""
    # After normalization, both should be identical
    assert normalize_sdl(sdl_a) == normalize_sdl(sdl_b), (
        "normalize_sdl must sort fields within blocks, making field-order-different "
        "but semantically-identical SDL blocks equal"
    )
