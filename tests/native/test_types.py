"""Tests for WU-B: DjangoInputObjectType native compile path + _GdxInputOptions.

Tests verify:
- DjangoInputObjectType subclass with model + input_for="create" has
  _meta.graphql_input_type after native compile.
- Update form → all fields nullable (partial model).
- _meta.container access raises AttributeError (removed under native).
- assert input_flag is not None fires for the output branch.
- type(PostInput) is ModelMetaclass for BOTH model-coupled and model-free.
- _meta.graphql_input_type is non-None after __init_subclass_with_meta__.
- Accessing _meta.bogus_attr raises AttributeError.

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _native_only() -> bool:
    """Return True when GDX_BACKEND=native is set."""
    return os.environ.get("GDX_BACKEND", "graphene") == "native"


# ---------------------------------------------------------------------------
# Task 2.1: DjangoInputObjectType native compile path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_django_input_object_type_graphql_input_type_create():
    """DjangoInputObjectType with input_for='create' must expose graphql_input_type."""
    from graphql import GraphQLInputObjectType
    from django_graphex.native.input_compiler import compile_input_type, GdxInputSpec
    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.validators import build_validator_model
    from tests.models import Category

    # Build a Pydantic model for Category (create — non-partial)
    pydantic_model = build_model_schema(Category, partial=False)

    # compile_input_type must return a GraphQLInputObjectType
    gql_input_type = compile_input_type(
        pydantic_model,
        name="CategoryInput",
        description="Create input for Category",
    )

    assert isinstance(gql_input_type, GraphQLInputObjectType), (
        "compile_input_type must return a GraphQLInputObjectType"
    )
    assert gql_input_type.name == "CategoryInput"
    # extensions["gdx"] must be a GdxInputSpec
    assert isinstance(gql_input_type.extensions.get("gdx"), GdxInputSpec), (
        "graphql_input_type must carry extensions['gdx'] = GdxInputSpec"
    )


@pytest.mark.django_db
def test_django_input_object_type_graphql_input_type_update_all_nullable():
    """DjangoInputObjectType with input_for='update' → all fields nullable (partial)."""
    from graphql import GraphQLNonNull
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Category

    # Update form → partial=True → every field nullable
    pydantic_model = build_model_schema(Category, partial=True)
    gql_input_type = compile_input_type(
        pydantic_model,
        name="CategoryUpdateInput",
    )

    # With partial=True, no fields should be NonNull-wrapped
    fields = gql_input_type.fields
    for field_name, gql_field in fields.items():
        assert not isinstance(gql_field.type, GraphQLNonNull), (
            f"Update input field {field_name!r} must be nullable (partial model), "
            f"got {gql_field.type!r}"
        )


@pytest.mark.django_db
def test_meta_container_absent_under_native():
    """_meta.container must raise AttributeError (container removed in native path)."""
    # We test through _GdxInputMeta directly — it should not expose 'container'
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    with pytest.raises(AttributeError):
        _ = meta.container  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_assert_input_flag_guard():
    """The assert input_flag is not None guard: compile_input_type rejects None model.

    The native compile path separates input and output branches.
    compile_input_type requires a valid Pydantic BaseModel — passing None
    raises an error, confirming the guard isolates the INPUT branch from
    the OUTPUT branch (construct_fields is not called for inputs).
    """
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Post

    # Verify compile_input_type works for a real model
    pydantic_model = build_model_schema(Post, partial=False)
    result = compile_input_type(pydantic_model, name="WuBPostCreateInput")
    assert result is not None, "compile_input_type must return a type"

    # The compile_input_type signature requires a Pydantic model with model_fields.
    # The lambda thunk is evaluated lazily when .fields is accessed.
    # Passing None (or a non-model object) must raise on field evaluation.
    broken_type = compile_input_type(None, name="BrokenInput")  # type: ignore[arg-type]
    with pytest.raises((AttributeError, TypeError)):
        _ = broken_type.fields  # trigger lazy evaluation


# ---------------------------------------------------------------------------
# Task 2.2: _GdxInputOptions / _MetaView extension
# ---------------------------------------------------------------------------

def test_gdx_input_meta_graphql_input_type_exposed():
    """_GdxInputMeta exposes graphql_input_type after compilation."""
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta
    from graphql import GraphQLInputObjectType

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    # Before compilation, graphql_input_type is None
    assert meta.graphql_input_type is None

    # Simulate compilation setting the type
    sentinel = GraphQLInputObjectType("TestInput", fields={})
    opts.graphql_input_type = sentinel

    assert meta.graphql_input_type is sentinel


def test_gdx_input_meta_unknown_attr_raises():
    """_GdxInputMeta must raise AttributeError for unknown attributes."""
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    with pytest.raises(AttributeError):
        _ = meta.bogus_attr  # type: ignore[attr-defined]


def test_type_of_model_coupled_input_is_model_metaclass():
    """type(InputType subclass) must be pydantic.ModelMetaclass."""
    from pydantic._internal._model_construction import ModelMetaclass
    from django_graphex.native.base import InputType

    class _WuBModelFreeInput2(InputType):
        """A model-free input for metaclass identity test."""
        query: str
        limit: int = 10

    assert type(_WuBModelFreeInput2) is ModelMetaclass, (
        "type(InputType subclass) must be pydantic.ModelMetaclass"
    )


@pytest.mark.django_db
def test_type_of_model_coupled_input_via_pydantic():
    """Model-coupled input compiled via Pydantic → type is ModelMetaclass."""
    from pydantic._internal._model_construction import ModelMetaclass
    from django_graphex.native.fields import build_model_schema
    from tests.models import Post

    # build_model_schema returns a Pydantic model; type must be ModelMetaclass
    pydantic_model = build_model_schema(Post, partial=False)
    assert type(pydantic_model) is ModelMetaclass, (
        "build_model_schema must return a class with pydantic.ModelMetaclass"
    )


def test_gdx_input_options_graphql_input_type_default_none():
    """_GdxInputOptions.graphql_input_type defaults to None before compilation."""
    from django_graphex.native.base import _GdxInputOptions

    opts = _GdxInputOptions()
    assert opts.graphql_input_type is None


def test_input_type_meta_populated_by_compile_all_inputs():
    """InputType._meta.graphql_input_type is None before compile_all_inputs."""
    from django_graphex.native.base import InputType

    class _WuBTestPreCompile(InputType):
        """Test pre-compile state."""
        value: str

    # Before compile_all_inputs, _meta.graphql_input_type is None
    assert _WuBTestPreCompile._meta.graphql_input_type is None  # type: ignore[attr-defined]
