"""Tests for core/input_compiler.py.

TDD RED phase: all tests are written first; they fail until the module is implemented.

Run with: .venv/bin/python -m pytest tests/core/test_input_compiler.py -x -v

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


def test_compile_input_type_multi_word_field_out_name() -> None:
    """Protect the wire/accessor split for multi-word fields.

    If this regresses, "compile_input_type" would either expose the
    snake-cased key on the wire (breaking GraphQL camelCase convention) or
    lose the mapping back to the Python attribute name.
    """
    from django_graphex.core.input_compiler import compile_input_type

    class PersonModel(BaseModel):
        first_name: str

    result = compile_input_type(PersonModel, name="PersonInput", description="")
    # Wire key is camelCase alias
    assert "firstName" in result.fields, "Expected camelCase key 'firstName' in fields"
    assert result.fields["firstName"].out_name == "first_name", (
        "out_name must be snake_case field name"
    )


def test_compile_input_type_snake_key_raises() -> None:
    """Protect against the snake-case key leaking into the compiled fields dict.

    If this regresses, callers could look up a field by its Python attribute
    name and silently get a KeyError instead of being forced to use the
    camelCase wire key that GraphQL clients actually send.
    """
    from django_graphex.core.input_compiler import compile_input_type

    class PersonModel(BaseModel):
        first_name: str

    result = compile_input_type(PersonModel, name="PersonInput", description="")
    with pytest.raises(KeyError):
        _ = result.fields["first_name"]


def test_compile_input_type_single_word_field() -> None:
    """Protect single-word fields, where key and out_name coincide.

    If this regresses, the compiler could apply unnecessary camel-casing to
    already-lowercase single-word names or fail the build-time
    out_name-vs-alias assertion for a field that needs no conversion.
    """
    from django_graphex.core.input_compiler import compile_input_type

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


def test_compile_input_type_required_field_is_nonnull() -> None:
    """Protect required-field NonNull wrapping.

    If this regresses, a required Pydantic field (no default) would compile
    to a nullable GraphQL type, letting clients omit a value the server
    actually needs.
    """
    from graphql import GraphQLNonNull

    from django_graphex.core.input_compiler import compile_input_type

    class RequiredModel(BaseModel):
        name: str  # required — no default

    result = compile_input_type(RequiredModel, name="RequiredInput", description="")
    field_type = result.fields["name"].type
    assert isinstance(field_type, GraphQLNonNull), (
        f"Expected GraphQLNonNull, got {type(field_type)}"
    )


def test_compile_input_type_optional_field_is_nullable() -> None:
    """Protect optional-field nullability.

    If this regresses, an Optional Pydantic field would be wrapped in
    GraphQLNonNull, forcing clients to always supply a value that the model
    itself treats as optional.
    """
    from graphql import GraphQLNonNull

    from django_graphex.core.input_compiler import compile_input_type

    class OptionalModel(BaseModel):
        name: Optional[str] = None

    result = compile_input_type(OptionalModel, name="OptionalInput", description="")
    field_type = result.fields["name"].type
    assert not isinstance(field_type, GraphQLNonNull), (
        f"Optional field should NOT be wrapped in NonNull, got {type(field_type)}"
    )


def test_compile_input_type_gdx_extension_present() -> None:
    """Protect the extensions["gdx"] marker every compiled input type carries.

    If this regresses, downstream code that relies on introspecting
    extensions["gdx"] as a GdxInputSpec (e.g. to detect a compiled input type
    or read its metadata) would silently break.
    """
    from django_graphex.core.input_compiler import GdxInputSpec, compile_input_type

    class AnyModel(BaseModel):
        value: int

    result = compile_input_type(AnyModel, name="AnyInput", description="test")
    assert "gdx" in (result.extensions or {}), "extensions['gdx'] must be present"
    gdx = result.extensions["gdx"]
    assert isinstance(gdx, GdxInputSpec), (
        f"extensions['gdx'] must be GdxInputSpec, got {type(gdx)}"
    )


def test_compile_input_type_multiword_build_assert() -> None:
    """Protect the out_name-vs-alias split for multi-word fields.

    We test this by calling compile_input_type and checking the compiled
    type correctly has out_name != alias for multi-word fields (the assertion
    is a build-time guard, so if it fires, compile_input_type itself raises).
    If this regresses, the build-time guard could stop catching a broken
    alias/out_name mapping, or a correct mapping could start failing it.
    """
    from django_graphex.core.input_compiler import compile_input_type

    class MultiWordModel(BaseModel):
        first_name: str
        last_name: str

    result = compile_input_type(MultiWordModel, name="MultiWordInput", description="")
    # Verify that the camelCase alias != snake out_name for multi-word fields
    assert result.fields["firstName"].out_name != "firstName"
    assert result.fields["firstName"].out_name == "first_name"
    assert result.fields["lastName"].out_name == "last_name"


def test_compile_input_type_fields_thunk_idempotent() -> None:
    """Protect idempotency of the lazy fields thunk.

    If this regresses, repeated access to result.fields could return
    inconsistent field sets across calls, which would make schema
    introspection and SDL printing unreliable.
    """
    from django_graphex.core.input_compiler import compile_input_type

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


def test_coerce_input_valid_returns_model_instance() -> None:
    """Protect the happy path: valid data coerces to a BaseModel instance.

    If this regresses, coerce_input could stop returning a usable model
    instance for valid input, breaking every resolver that expects one.
    """
    from django_graphex.core.input_compiler import coerce_input

    class NameModel(BaseModel):
        name: str

    result = coerce_input(NameModel, {"name": "Alice"})
    assert isinstance(result, BaseModel)
    assert result.name == "Alice"


def test_coerce_input_accepts_camel_alias() -> None:
    """Protect camelCase alias acceptance via an alias_generator.

    If this regresses, coerce_input could reject the camelCase keys GraphQL
    clients actually send, even though the model declares an alias_generator
    for exactly that purpose.
    """
    from pydantic import ConfigDict
    from pydantic.alias_generators import to_camel

    from django_graphex.core.input_compiler import coerce_input

    class AliasModel(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
        first_name: str

    # Can use camel alias OR snake name
    result = coerce_input(AliasModel, {"firstName": "Alice"})
    assert result.first_name == "Alice"


def test_coerce_input_invalid_raises_graphql_error() -> None:
    """Protect the ValidationError-to-GraphQLError translation contract.

    If this regresses, invalid input would surface as a raw
    pydantic.ValidationError (or a GraphQLError without the
    "VALIDATION_ERROR" code), breaking clients that branch on that code.
    """
    from graphql import GraphQLError

    from django_graphex.core.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str  # required

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})  # missing required 'name'

    err = exc_info.value
    assert err.extensions is not None
    assert err.extensions.get("code") == "VALIDATION_ERROR"


def test_coerce_input_error_extensions_has_fields() -> None:
    """Protect the 'fields' key on validation-error extensions.

    If this regresses, API consumers would lose the structured per-field
    error detail needed to point a user at which input was invalid.
    """
    from graphql import GraphQLError

    from django_graphex.core.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    extensions = exc_info.value.extensions
    assert "fields" in extensions, "extensions must have 'fields' key"


def test_coerce_input_no_pydantic_url_in_error() -> None:
    """Protect against leaking the errors.pydantic.dev URL into API responses.

    If this regresses, serialized error extensions would expose an internal
    Pydantic documentation URL to API clients, leaking implementation
    details.
    """
    from graphql import GraphQLError

    from django_graphex.core.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    extensions = exc_info.value.extensions
    serialized = json.dumps(extensions)
    assert "errors.pydantic.dev" not in serialized, (
        "Pydantic dev URL must not appear in error extensions (use include_url=False)"
    )


def test_coerce_input_error_message_prefix() -> None:
    """Protect the stable "Input validation failed" message prefix.

    If this regresses, any caller pattern-matching on the GraphQLError
    message prefix (e.g. client-side error handling or log filters) would
    stop recognizing input-validation failures.
    """
    from graphql import GraphQLError

    from django_graphex.core.input_compiler import coerce_input

    class RequiredModel(BaseModel):
        name: str

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(RequiredModel, {})

    assert exc_info.value.message.startswith("Input validation failed")


# ---------------------------------------------------------------------------
# translate_validation_error tests (unit)
# ---------------------------------------------------------------------------


def test_translate_validation_error_no_url() -> None:
    """Protect against leaking the errors.pydantic.dev URL at the unit level.

    If this regresses, translate_validation_error itself (not just the
    higher-level coerce_input wrapper) would emit the internal Pydantic
    documentation URL into the translated error dict.
    """
    from pydantic import ValidationError

    from django_graphex.core.input_compiler import translate_validation_error

    class Strict(BaseModel):
        age: int

    try:
        Strict.model_validate({"age": "not-a-number"})
    except ValidationError as exc:
        result = translate_validation_error(exc)
        serialized = json.dumps(result)
        assert "errors.pydantic.dev" not in serialized


def test_translate_validation_error_returns_dict() -> None:
    """Protect the dict-with-field-keys shape of the translated error.

    If this regresses, callers that index the translated result by field
    name (e.g. to build the "fields" extensions entry) would break or
    silently receive an empty mapping.
    """
    from pydantic import ValidationError

    from django_graphex.core.input_compiler import translate_validation_error

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


def test_compile_input_type_optional_none_union() -> None:
    """Protect Optional[T] / T | None nullability (coverage-gap regression guard).

    If this regresses, an Optional-annotated field could be wrapped in
    GraphQLNonNull, forcing clients to supply a value the model treats as
    nullable.
    """
    from graphql import GraphQLNonNull

    from django_graphex.core.input_compiler import compile_input_type

    class NullableModel(BaseModel):
        description: Optional[str] = None

    result = compile_input_type(NullableModel, name="NullableInput", description="")
    field_type = result.fields["description"].type
    assert not isinstance(field_type, GraphQLNonNull)


def test_compile_input_type_with_explicit_alias() -> None:
    """Protect explicit pydantic.Field(alias=...) taking precedence as the wire key.

    If this regresses, a field that hand-declares its own wire alias would be
    exposed under the auto-generated camelCase name instead, breaking any
    client relying on the explicit alias.
    """
    from pydantic import Field

    from django_graphex.core.input_compiler import compile_input_type

    class ExplicitAliasModel(BaseModel):
        my_field: str = Field(alias="myCustomAlias")

    result = compile_input_type(
        ExplicitAliasModel, name="ExplicitAliasInput", description=""
    )
    # The explicit alias should be used as the dict key
    assert "myCustomAlias" in result.fields


def test_compile_input_type_enum_field() -> None:
    """Protect that an Enum-annotated field compiles without raising.

    If this regresses, adding an enum.Enum field to an input model would
    break schema compilation instead of degrading gracefully.
    """
    import enum

    from django_graphex.core.input_compiler import compile_input_type

    class Status(enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    class EnumModel(BaseModel):
        status: Status

    result = compile_input_type(EnumModel, name="EnumInput", description="")
    assert "status" in result.fields  # single word, no camel needed


def test_python_type_to_gql_none_type() -> None:
    """Protect the None-annotation fallback to GraphQLString.

    If this regresses, a field with no annotation (None passed through) would
    raise or resolve to the wrong scalar instead of the documented String
    fallback.
    """
    from graphql import GraphQLString

    from django_graphex.core.input_compiler import _python_type_to_gql

    result = _python_type_to_gql(None)
    assert result is GraphQLString


def test_python_type_to_gql_datetime() -> None:
    """Protect that datetime.date maps to some usable scalar, never None.

    If this regresses, a date-typed field would compile to a missing/None
    GraphQL type and blow up schema assembly.
    """
    import datetime

    from django_graphex.core.input_compiler import _python_type_to_gql

    # Should return a scalar (either GdxDate or String fallback)
    result = _python_type_to_gql(datetime.date)
    assert result is not None


def test_unwrap_optional_typing_union() -> None:
    """Protect _unwrap_optional's handling of typing.Optional / typing.Union.

    If this regresses, an Optional[str] annotation would stop unwrapping to
    (str, True), breaking nullability detection for typing-style annotations.
    """
    from typing import Optional

    from django_graphex.core.input_compiler import _unwrap_optional

    inner, is_opt = _unwrap_optional(Optional[str])
    assert inner is str
    assert is_opt is True


def test_unwrap_optional_non_optional() -> None:
    """Protect the non-Optional passthrough branch of _unwrap_optional.

    If this regresses, a plain non-Optional annotation could be
    misclassified as nullable, wrongly relaxing a required field.
    """
    from django_graphex.core.input_compiler import _unwrap_optional

    inner, is_opt = _unwrap_optional(str)
    assert inner is str
    assert is_opt is False


def test_unwrap_optional_py310_union() -> None:
    """Protect _unwrap_optional's handling of the Python 3.10+ "X | None" syntax.

    If this regresses, the newer union syntax would stop being recognized as
    Optional, causing a nullable field to compile as required.
    """
    from django_graphex.core.input_compiler import _unwrap_optional

    # Python 3.10+ union syntax: str | None
    annotation = str | None  # type: ignore[operator]
    inner, is_opt = _unwrap_optional(annotation)
    assert inner is str
    assert is_opt is True


def test_python_type_to_gql_enum() -> None:
    """Protect that a bare enum.Enum class maps to GraphQLString.

    If this regresses, an Enum type not routed through the input-model enum
    path would raise instead of degrading to the documented String
    fallback.
    """
    import enum

    from graphql import GraphQLString

    from django_graphex.core.input_compiler import _python_type_to_gql

    class MyEnum(enum.Enum):
        A = 1

    result = _python_type_to_gql(MyEnum)
    assert result is GraphQLString


def test_unwrap_optional_multi_union() -> None:
    """Protect the multi-non-None Union branch (Union[A, B] cannot collapse).

    If this regresses, a Union of more than one non-None type could crash
    _unwrap_optional instead of returning a well-typed (union, False) pair.
    """
    from typing import Union

    from django_graphex.core.input_compiler import _unwrap_optional

    # Union with multiple non-None types — not Optional
    # This tests the len(non_none) != 1 branch
    annotation = Union[str, int, None]  # 2 non-None types
    inner, is_opt = _unwrap_optional(annotation)
    # With 2 non-None types it can't collapse to a single type
    # behaviour: returns (annotation, False) since we can't express Union[str,int] as a single GQL type
    assert isinstance(is_opt, bool)


def test_python_type_to_gql_unknown_type_fallback() -> None:
    """Protect the last-resort GraphQLString fallback for unrecognized types.

    If this regresses, an annotation the compiler has no mapping for would
    raise during schema build instead of degrading to String.
    """
    from graphql import GraphQLString

    from django_graphex.core.input_compiler import _python_type_to_gql

    class SomeCustomType:
        pass

    result = _python_type_to_gql(SomeCustomType)
    assert result is GraphQLString


def test_unwrap_optional_multi_non_none_union() -> None:
    """Protect that Union[A, B, None] (2 non-None members) is NOT treated as Optional.

    If this regresses, a genuinely ambiguous union could be misreported as
    Optional, silently relaxing a field that has no single well-defined
    nullable type.
    """
    from typing import Union

    from django_graphex.core.input_compiler import _unwrap_optional

    # Union[str, int, None] → can't collapse to single type (typing.Union path)
    annotation = Union[str, int, None]
    inner, is_opt = _unwrap_optional(annotation)
    # len(non_none) == 2, so should return (annotation, False)
    assert is_opt is False


def test_unwrap_optional_py310_multi_non_none() -> None:
    """Protect that "str | int | None" (types.UnionType) is NOT treated as Optional.

    If this regresses, the Python 3.10+ union syntax with two non-None
    members could be misreported as Optional, the same ambiguity guarded by
    the typing.Union counterpart above.
    """
    from django_graphex.core.input_compiler import _unwrap_optional

    # Python 3.10+ syntax with 2 non-None types
    annotation = str | int | None  # type: ignore[operator]
    inner, is_opt = _unwrap_optional(annotation)
    assert is_opt is False


def test_native_scalar_map_import_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Protect the empty-dict fallback when the scalars module is unimportable.

    Args:
        monkeypatch: Pytest fixture used here to stash/restore
            sys.modules["django_graphex.core.scalars"] around the forced
            import failure.

    If this regresses, an environment where the scalars module cannot be
    imported would crash _native_scalar_map instead of degrading to an empty
    scalar map.
    """
    import sys

    from django_graphex.core import input_compiler

    # Temporarily make scalars unimportable
    real_scalars = sys.modules.get("django_graphex.core.scalars")
    sys.modules["django_graphex.core.scalars"] = None  # type: ignore
    try:
        result = input_compiler._native_scalar_map()
        assert result == {}
    finally:
        if real_scalars is not None:
            sys.modules["django_graphex.core.scalars"] = real_scalars
        else:
            sys.modules.pop("django_graphex.core.scalars", None)
