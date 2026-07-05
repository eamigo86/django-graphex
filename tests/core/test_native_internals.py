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


def test_compile_input_type_always_carries_gdx_extension() -> None:
    """Assert that every "compile_input_type" result carries extensions["gdx"].

    If this fails, a compiled input type would lack the gdx bridge
    metadata build-time validation and downstream tooling depend on.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import GdxInputSpec, compile_input_type

    class _WuBGdxExtInput(InputType):
        name: str

    gql_type = compile_input_type(_WuBGdxExtInput, name="WuBGdxExtInputType")

    assert "gdx" in (gql_type.extensions or {}), (
        "compile_input_type must set extensions['gdx'] on the compiled type"
    )
    assert isinstance(gql_type.extensions["gdx"], GdxInputSpec), (
        "extensions['gdx'] must be a GdxInputSpec instance"
    )


def test_assert_gdx_bridge_catches_input_type_without_extension() -> None:
    """Assert that "assert_gdx_bridge" raises for an input type missing extensions["gdx"].

    This is the Phase 1 bridge assertion extended to cover input types. A
    manually constructed GraphQLInputObjectType without extensions["gdx"]
    must be caught at build time.

    If this fails, an input type built outside the compile_input_type path
    could reach schema assembly without the required gdx bridge metadata.
    """
    from graphql import (
        GraphQLField,
        GraphQLInputField,
        GraphQLInputObjectType,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.core.bridge import GdxPayload, assert_gdx_bridge

    # Build a bare input type with NO extensions["gdx"]
    bare_input_type = GraphQLInputObjectType(
        "BareInput",
        fields={"name": GraphQLInputField(GraphQLString)},
    )

    # Build a minimal schema with a query type (has gdx) and the bare input type
    # To include the input type in the schema, we need to reference it from a field arg
    from graphql import GraphQLArgument

    from django_graphex.core.ir import GdxMeta

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


def test_assert_gdx_bridge_passes_for_compiled_input_type() -> None:
    """Assert that "assert_gdx_bridge" passes when all input types carry extensions["gdx"].

    If this fails, a properly compiled input type would spuriously fail
    the bridge assertion despite carrying valid gdx metadata.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.core.base import InputType
    from django_graphex.core.bridge import GdxPayload, assert_gdx_bridge
    from django_graphex.core.input_compiler import compile_input_type
    from django_graphex.core.ir import GdxMeta

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


def test_gdx_input_spec_carries_pydantic_model() -> None:
    """Assert that "GdxInputSpec.pydantic_model" references the source Pydantic model.

    If this fails, the gdx bridge metadata would lose its link back to the
    original Pydantic model, breaking any tooling that needs to re-derive
    validation from the compiled GraphQL input type.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import GdxInputSpec, compile_input_type

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
def test_build_model_schema_result_carries_gdx_after_compile() -> None:
    """Assert that a model-derived Pydantic model compiles with the gdx extension.

    If this fails, input types built via "build_model_schema" (the Django
    model shortcut) would not carry the required gdx bridge metadata.
    """
    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import GdxInputSpec, compile_input_type
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_type = compile_input_type(pydantic_model, name="WuBCategoryGdxInput")

    spec = gql_type.extensions.get("gdx")
    assert spec is not None, "Compiled input type must carry extensions['gdx']"
    assert isinstance(spec, GdxInputSpec)
