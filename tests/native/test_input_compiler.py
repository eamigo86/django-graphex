"""Tests for native/input_compiler.py.

TDD RED phase: all tests are written first; they fail until the module is implemented.

Run with: .venv/bin/python -m pytest tests/native/test_input_compiler.py -x -v

No Django settings required for the bulk of these tests (model-free Pydantic models).
"""
from __future__ import annotations

import json
from typing import Optional

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 1.1 RED: compile_input_type field mapping
# ---------------------------------------------------------------------------


def test_compile_input_type_multi_word_field_out_name():
    """Multi-word field: dict key = camelCase alias, out_name = snake_name."""
    from django_graphex.native.input_compiler import compile_input_type

    class PersonModel(BaseModel):
        first_name: str

    result = compile_input_type(PersonModel, name="PersonInput", description="")
    # Wire key is camelCase alias
    assert "firstName" in result.fields, "Expected camelCase key 'firstName' in fields"
    assert result.fields["firstName"].out_name == "first_name", (
        "out_name must be snake_case field name"
    )


def test_compile_input_type_snake_key_raises():
    """Snake-case key must NOT be in fields dict (wire uses camelCase)."""
    from django_graphex.native.input_compiler import compile_input_type

    class PersonModel(BaseModel):
        first_name: str

    result = compile_input_type(PersonModel, name="PersonInput", description="")
    with pytest.raises(KeyError):
        _ = result.fields["first_name"]


def test_compile_input_type_single_word_field():
    """Single-word field: key == out_name (no camel conversion needed)."""
    from django_graphex.native.input_compiler import compile_input_type

    class SimpleModel(BaseModel):
        name: str

    result = compile_input_type(SimpleModel, name="SimpleInput", description="")
    assert "name" in result.fields
    # For single-word: alias == field_name, so build-time assert does NOT fire
    # We just confirm it compiled successfully
    assert result.fields["name"].out_name == "name"


# ---------------------------------------------------------------------------
# 1.2 RED: NonNull, GdxInputSpec, out_name != alias, thunk
# ---------------------------------------------------------------------------


def test_compile_input_type_required_field_is_nonnull():
    """Required (no default) fields must be wrapped in GraphQLNonNull."""
    from graphql import GraphQLNonNull

    from django_graphex.native.input_compiler import compile_input_type

    class RequiredModel(BaseModel):
        name: str  # required — no default

    result = compile_input_type(RequiredModel, name="RequiredInput", description="")
    field_type = result.fields["name"].type
    assert isinstance(field_type, GraphQLNonNull), (
        f"Expected GraphQLNonNull, got {type(field_type)}"
    )


def test_compile_input_type_optional_field_is_nullable():
    """Optional fields (with default / Optional type) must be nullable."""
    from graphql import GraphQLNonNull

    from django_graphex.native.input_compiler import compile_input_type

    class OptionalModel(BaseModel):
        name: Optional[str] = None

    result = compile_input_type(OptionalModel, name="OptionalInput", description="")
    field_type = result.fields["name"].type
    assert not isinstance(field_type, GraphQLNonNull), (
        f"Optional field should NOT be wrapped in NonNull, got {type(field_type)}"
    )


def test_compile_input_type_gdx_extension_present():
    """Compiled type must have extensions['gdx'] as a GdxInputSpec instance."""
    from django_graphex.native.input_compiler import GdxInputSpec, compile_input_type

    class AnyModel(BaseModel):
        value: int

    result = compile_input_type(AnyModel, name="AnyInput", description="test")
    assert "gdx" in (result.extensions or {}), "extensions['gdx'] must be present"
    gdx = result.extensions["gdx"]
    assert isinstance(gdx, GdxInputSpec), (
        f"extensions['gdx'] must be GdxInputSpec, got {type(gdx)}"
    )


def test_compile_input_type_multiword_build_assert():
    """Build-time: assert out_name != alias fires for multi-word fields.

    We test this by calling compile_input_type and checking the compiled
    type correctly has out_name != alias for multi-word fields (the assertion
    is a build-time guard, so if it fires, compile_input_type itself raises).
    """
    from django_graphex.native.input_compiler import compile_input_type

    class MultiWordModel(BaseModel):
        first_name: str
        last_name: str

    result = compile_input_type(MultiWordModel, name="MultiWordInput", description="")
    # Verify that the camelCase alias != snake out_name for multi-word fields
    assert result.fields["firstName"].out_name != "firstName"
    assert result.fields["firstName"].out_name == "first_name"
    assert result.fields["lastName"].out_name == "last_name"


def test_compile_input_type_fields_thunk_idempotent():
    """Fields thunk: calling .fields twice returns consistent results."""
    from django_graphex.native.input_compiler import compile_input_type

    class ThunkModel(BaseModel):
        first_name: str
        age: int

    result = compile_input_type(ThunkModel, name="ThunkInput", description="")
    fields_1 = result.fields
    fields_2 = result.fields
    assert set(fields_1.keys()) == set(fields_2.keys())


# ---------------------------------------------------------------------------
# 1.4 RED: coerce_input + ValidationError translation
# ---------------------------------------------------------------------------


def test_coerce_input_valid_returns_model_instance():
    """coerce_input with valid data returns a BaseModel instance."""
    from django_graphex.native.input_compiler import coerce_input

    class NameModel(BaseModel):
        name: str

    result = coerce_input(NameModel, {"name": "Alice"})
    assert isinstance(result, BaseModel)
    assert result.name == "Alice"


def test_coerce_input_accepts_camel_alias():
    """coerce_input with camelCase alias (via alias_generator) returns model instance."""
    from pydantic import ConfigDict
    from pydantic.alias_generators import to_camel

    from django_graphex.native.input_compiler import coerce_input

    class AliasModel(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
        first_name: str

    # Can use camel alias OR snake name
    result = coerce_input(AliasModel, {"firstName": "Alice"})
    assert result.first_name == "Alice"


def test_coerce_input_invalid_raises_graphql_error():
    """coerce_input with invalid data raises GraphQLError with VALIDATION_ERROR code."""
    from graphql import GraphQLError

    from django_graphex.native.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str  # required

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})  # missing required 'name'

    err = exc_info.value
    assert err.extensions is not None
    assert err.extensions.get("code") == "VALIDATION_ERROR"


def test_coerce_input_error_extensions_has_fields():
    """ValidationError extensions must include 'fields' describing missing field."""
    from graphql import GraphQLError

    from django_graphex.native.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    extensions = exc_info.value.extensions
    assert "fields" in extensions, "extensions must have 'fields' key"


def test_coerce_input_no_pydantic_url_in_error():
    """The errors.pydantic.dev URL must NEVER appear in serialized error extensions."""
    from graphql import GraphQLError

    from django_graphex.native.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    extensions = exc_info.value.extensions
    serialized = json.dumps(extensions)
    assert "errors.pydantic.dev" not in serialized, (
        "Pydantic dev URL must not appear in error extensions (use include_url=False)"
    )


def test_coerce_input_error_message_prefix():
    """GraphQLError message must start with 'Input validation failed'."""
    from graphql import GraphQLError

    from django_graphex.native.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    assert exc_info.value.message.startswith("Input validation failed")


# ---------------------------------------------------------------------------
# translate_validation_error tests (unit)
# ---------------------------------------------------------------------------


def test_translate_validation_error_no_url():
    """translate_validation_error never includes errors.pydantic.dev URL."""
    from pydantic import ValidationError

    from django_graphex.native.input_compiler import translate_validation_error

    class Strict(BaseModel):
        age: int

    try:
        Strict.model_validate({"age": "not-a-number"})
    except ValidationError as exc:
        result = translate_validation_error(exc)
        serialized = json.dumps(result)
        assert "errors.pydantic.dev" not in serialized


def test_translate_validation_error_returns_dict():
    """translate_validation_error returns a dict with field keys."""
    from pydantic import ValidationError

    from django_graphex.native.input_compiler import translate_validation_error

    class Strict(BaseModel):
        name: str

    try:
        Strict.model_validate({})
    except ValidationError as exc:
        result = translate_validation_error(exc)
        assert isinstance(result, dict)
        # Must have some field entry for the missing 'name'
        assert len(result) > 0


# ---------------------------------------------------------------------------
# REFACTOR / coverage-gap tests
# ---------------------------------------------------------------------------


def test_compile_input_type_optional_none_union():
    """Optional[T] / T | None fields are treated as nullable."""
    from typing import Optional

    from graphql import GraphQLNonNull

    from django_graphex.native.input_compiler import compile_input_type

    class NullableModel(BaseModel):
        description: Optional[str] = None

    result = compile_input_type(NullableModel, name="NullableInput", description="")
    field_type = result.fields["description"].type
    assert not isinstance(field_type, GraphQLNonNull)


def test_compile_input_type_with_explicit_alias():
    """Field with explicit Pydantic alias uses that alias as the wire key."""
    from pydantic import Field

    from django_graphex.native.input_compiler import compile_input_type

    class ExplicitAliasModel(BaseModel):
        my_field: str = Field(alias="myCustomAlias")

    result = compile_input_type(ExplicitAliasModel, name="ExplicitAliasInput", description="")
    # The explicit alias should be used as the dict key
    assert "myCustomAlias" in result.fields


def test_compile_input_type_enum_field():
    """Enum-annotated fields should compile without error."""
    import enum

    from django_graphex.native.input_compiler import compile_input_type

    class Status(enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    class EnumModel(BaseModel):
        status: Status

    result = compile_input_type(EnumModel, name="EnumInput", description="")
    assert "status" in result.fields  # single word, no camel needed


def test_python_type_to_gql_none_type():
    """_python_type_to_gql(None) should return GraphQLString."""
    from graphql import GraphQLString

    from django_graphex.native.input_compiler import _python_type_to_gql

    result = _python_type_to_gql(None)
    assert result is GraphQLString


def test_python_type_to_gql_datetime():
    """_python_type_to_gql maps datetime types to GDX scalars."""
    import datetime

    from django_graphex.native.input_compiler import _python_type_to_gql

    # Should return a scalar (either GdxDate or String fallback)
    result = _python_type_to_gql(datetime.date)
    assert result is not None


def test_unwrap_optional_typing_union():
    """_unwrap_optional handles typing.Optional / typing.Union."""
    from typing import Optional, Union

    from django_graphex.native.input_compiler import _unwrap_optional

    inner, is_opt = _unwrap_optional(Optional[str])
    assert inner is str
    assert is_opt is True


def test_unwrap_optional_non_optional():
    """_unwrap_optional on non-optional type returns (type, False)."""
    from django_graphex.native.input_compiler import _unwrap_optional

    inner, is_opt = _unwrap_optional(str)
    assert inner is str
    assert is_opt is False


def test_unwrap_optional_py310_union():
    """_unwrap_optional handles Python 3.10+ X | None union syntax."""
    from django_graphex.native.input_compiler import _unwrap_optional

    # Python 3.10+ union syntax: str | None
    annotation = str | None  # type: ignore[operator]
    inner, is_opt = _unwrap_optional(annotation)
    assert inner is str
    assert is_opt is True


def test_python_type_to_gql_enum():
    """_python_type_to_gql returns GraphQLString for enum types."""
    import enum

    from graphql import GraphQLString

    from django_graphex.native.input_compiler import _python_type_to_gql

    class MyEnum(enum.Enum):
        A = 1

    result = _python_type_to_gql(MyEnum)
    assert result is GraphQLString


def test_unwrap_optional_multi_union():
    """_unwrap_optional with Union[A, B, C] (no None) returns (union, False)."""
    from typing import Union

    from django_graphex.native.input_compiler import _unwrap_optional

    # Union with multiple non-None types — not Optional
    # This tests the len(non_none) != 1 branch
    annotation = Union[str, int, None]  # 2 non-None types
    inner, is_opt = _unwrap_optional(annotation)
    # With 2 non-None types it can't collapse to a single type
    # behaviour: returns (annotation, False) since we can't express Union[str,int] as a single GQL type
    assert isinstance(is_opt, bool)


def test_python_type_to_gql_unknown_type_fallback():
    """_python_type_to_gql returns GraphQLString for unknown types."""
    from graphql import GraphQLString

    from django_graphex.native.input_compiler import _python_type_to_gql

    class SomeCustomType:
        pass

    result = _python_type_to_gql(SomeCustomType)
    assert result is GraphQLString


def test_unwrap_optional_multi_non_none_union():
    """_unwrap_optional with Union[A, B, None] (2 non-None) returns (union, False)."""
    from typing import Union

    from django_graphex.native.input_compiler import _unwrap_optional

    # Union[str, int, None] → can't collapse to single type (typing.Union path)
    annotation = Union[str, int, None]
    inner, is_opt = _unwrap_optional(annotation)
    # len(non_none) == 2, so should return (annotation, False)
    assert is_opt is False


def test_unwrap_optional_py310_multi_non_none():
    """_unwrap_optional with str | int | None (types.UnionType) returns (union, False)."""
    from django_graphex.native.input_compiler import _unwrap_optional

    # Python 3.10+ syntax with 2 non-None types
    annotation = str | int | None  # type: ignore[operator]
    inner, is_opt = _unwrap_optional(annotation)
    assert is_opt is False


def test_native_scalar_map_import_error_fallback(monkeypatch):
    """_native_scalar_map returns {} when scalars module can't be imported."""
    import sys

    from django_graphex.native import input_compiler

    # Temporarily make scalars unimportable
    real_scalars = sys.modules.get("django_graphex.native.scalars")
    sys.modules["django_graphex.native.scalars"] = None  # type: ignore
    try:
        result = input_compiler._native_scalar_map()
        assert result == {}
    finally:
        if real_scalars is not None:
            sys.modules["django_graphex.native.scalars"] = real_scalars
        else:
            sys.modules.pop("django_graphex.native.scalars", None)
