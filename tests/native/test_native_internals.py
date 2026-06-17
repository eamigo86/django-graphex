"""Tests for WU-B task 2.10: extensions["gdx"] build-time assertion on input types.

Tests verify:
- compile_all_inputs() raises ImproperlyConfigured for a manually constructed
  GraphQLInputObjectType registered without extensions["gdx"].
- The assertion message names the type.

Run.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Task 2.10: extensions["gdx"] assertion on compiled input types
# ---------------------------------------------------------------------------


def test_compile_input_type_always_carries_gdx_extension():
    """Every GraphQLInputObjectType from compile_input_type carries extensions["gdx"]."""
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import GdxInputSpec, compile_input_type

    class _WuBGdxExtInput(InputType):
        name: str

    gql_type = compile_input_type(_WuBGdxExtInput, name="WuBGdxExtInputType")

    assert "gdx" in (gql_type.extensions or {}), (
        "compile_input_type must set extensions['gdx'] on the compiled type"
    )
    assert isinstance(gql_type.extensions["gdx"], GdxInputSpec), (
        "extensions['gdx'] must be a GdxInputSpec instance"
    )


def test_assert_gdx_bridge_catches_input_type_without_extension():
    """assert_gdx_bridge raises AssertionError for a GraphQLInputObjectType missing gdx.

    This is the Phase 1 bridge assertion extended to cover input types.
    A manually constructed GraphQLInputObjectType without extensions["gdx"]
    must be caught at build time.
    """
    from graphql import (
        GraphQLField,
        GraphQLInputField,
        GraphQLInputObjectType,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.native.bridge import GdxPayload, assert_gdx_bridge
    # Build a bare input type with NO extensions["gdx"]
    bare_input_type = GraphQLInputObjectType(
        "BareInput",
        fields={"name": GraphQLInputField(GraphQLString)},
    )

    # Build a minimal schema with a query type (has gdx) and the bare input type
    # To include the input type in the schema, we need to reference it from a field arg
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.native.ir import GdxMeta
    gdx_payload = GdxPayload(GdxMeta(name="Query"))

    query_type = GraphQLObjectType(
        "Query",
        fields=lambda: {
            "hello": GraphQLField(
                GraphQLString,
                args={"input": GraphQLArgument(bare_input_type)},
                resolve=lambda root, info, **kwargs: "hello",
            )
        },
        extensions={"gdx": gdx_payload},
    )

    # Build the schema — this registers BareInput in the type map
    schema = GraphQLSchema(query=query_type)

    # assert_gdx_bridge must catch the bare input type
    with pytest.raises(AssertionError, match="BareInput"):
        assert_gdx_bridge(schema)


def test_assert_gdx_bridge_passes_for_compiled_input_type():
    """assert_gdx_bridge passes when all input types carry extensions["gdx"]."""
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInputObjectType,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.native.base import InputType
    from django_graphex.native.bridge import GdxPayload, assert_gdx_bridge
    from django_graphex.native.input_compiler import GdxInputSpec, compile_input_type
    from django_graphex.native.ir import GdxMeta

    class _WuBPassInput(InputType):
        name: str

    # Compile via compile_input_type (sets extensions["gdx"])
    compiled_input = compile_input_type(_WuBPassInput, name="WuBPassInputType")

    gdx_payload = GdxPayload(GdxMeta(name="Query"))
    query_type = GraphQLObjectType(
        "Query",
        fields=lambda: {
            "hello": GraphQLField(
                GraphQLString,
                args={"input": GraphQLArgument(compiled_input)},
                resolve=lambda root, info, **kwargs: "hello",
            )
        },
        extensions={"gdx": gdx_payload},
    )

    schema = GraphQLSchema(query=query_type)

    # Should not raise
    assert_gdx_bridge(schema)


def test_gdx_input_spec_carries_pydantic_model():
    """GdxInputSpec.pydantic_model references the source Pydantic model."""
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import GdxInputSpec, compile_input_type

    class _WuBSpecInput(InputType):
        value: int = 0

    gql_type = compile_input_type(_WuBSpecInput, name="WuBSpecInputType")
    spec = gql_type.extensions["gdx"]

    assert isinstance(spec, GdxInputSpec)
    assert spec.pydantic_model is _WuBSpecInput, (
        "GdxInputSpec.pydantic_model must reference the source Pydantic model"
    )
    assert spec.name == "WuBSpecInputType"


@pytest.mark.django_db
def test_build_model_schema_result_carries_gdx_after_compile():
    """A model-derived Pydantic model produces a compiled type with gdx extension."""
    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import GdxInputSpec, compile_input_type
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_type = compile_input_type(pydantic_model, name="WuBCategoryGdxInput")

    spec = gql_type.extensions.get("gdx")
    assert spec is not None, "Compiled input type must carry extensions['gdx']"
    assert isinstance(spec, GdxInputSpec)
