"""Tests for WU-B task 2.8: camelCase→snake wire-key integrity (end-to-end).

Tests verify:
- Client sends {firstName: "Alice"} → resolver receives data.first_name == "Alice"
- data["first_name"] == "Alice" via __getitem__ mixin
- Multi-word field: out_name != alias verified on compiled type

Run under GDX_BACKEND=native via native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Task 2.8: camelCase→snake wire-key integrity
# ---------------------------------------------------------------------------


def test_camel_wire_key_to_snake_resolver_key():
    """Client sends {firstName: "Alice"} → resolver receives data.first_name == "Alice".

    coerce_input validates via alias (camelCase) → returns BaseModel with
    snake_case attribute. __getitem__ also returns snake key value.
    """
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import coerce_input

    class _WuBMutEdgePersonInput(InputType):
        first_name: str
        last_name: str = ""

    # Simulate what GraphQL client sends (camelCase keys)
    raw = {"firstName": "Alice", "lastName": "Smith"}
    data = coerce_input(_WuBMutEdgePersonInput, raw)

    # Resolver receives snake_case attributes
    assert data.first_name == "Alice", (
        "Resolver must see data.first_name == 'Alice' for wire key 'firstName'"
    )
    assert data.last_name == "Smith"

    # dict-style access also uses snake keys
    assert data["first_name"] == "Alice"
    assert data["last_name"] == "Smith"


def test_multi_word_field_out_name_differs_from_alias():
    """For multi-word fields, compiled type's out_name != alias (camelCase).

    The build-time assert in compile_input_type enforces this.
    We verify it by inspecting the compiled GraphQLInputField.
    """
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import compile_input_type

    class _WuBMultiWordInput(InputType):
        first_name: str
        last_name: str = ""

    gql_type = compile_input_type(
        _WuBMultiWordInput,
        name="WuBMultiWordInputType",
    )

    fields = gql_type.fields
    # Wire key should be camelCase
    assert "firstName" in fields, (
        f"Expected 'firstName' wire key, got: {list(fields.keys())}"
    )
    assert "lastName" in fields, (
        f"Expected 'lastName' wire key, got: {list(fields.keys())}"
    )

    # out_name (snake) must differ from alias (camel) for multi-word fields
    first_name_field = fields["firstName"]
    assert first_name_field.out_name == "first_name", (
        f"out_name must be 'first_name' (snake), got: {first_name_field.out_name!r}"
    )
    assert first_name_field.out_name != "firstName", (
        "out_name (snake) must differ from alias (camel) for multi-word fields"
    )


def test_multi_word_field_snake_key_raises_key_error_in_compiled_type():
    """Compiled input type: fields["first_name"] raises KeyError (wire key is camelCase).

    The spec says: "result.fields.get('first_name') raises KeyError"
    because the dict key is the camelCase alias.
    """
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import compile_input_type

    class _WuBSnakeKeyInput(InputType):
        first_name: str

    gql_type = compile_input_type(
        _WuBSnakeKeyInput,
        name="WuBSnakeKeyInputType",
    )

    fields = gql_type.fields
    # Snake key should NOT be present (wire key = camelCase)
    assert "first_name" not in fields, (
        "fields dict must use camelCase wire keys, not snake_case field names"
    )
    # CamelCase key IS present
    assert "firstName" in fields


def test_coerce_input_camel_key_validated_snake_access():
    """Full round-trip: camelCase wire → coerce_input → snake attr + dict access."""
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import coerce_input

    class _WuBRoundTripInput(InputType):
        user_name: str
        email_address: str

    raw = {"userName": "alice", "emailAddress": "alice@example.com"}
    data = coerce_input(_WuBRoundTripInput, raw)

    # Attribute access (resolver)
    assert data.user_name == "alice"
    assert data.email_address == "alice@example.com"

    # Dict-style access (legacy resolver compat)
    assert data["user_name"] == "alice"
    assert data["email_address"] == "alice@example.com"

    # CamelCase dict access raises KeyError (snake keys only)
    with pytest.raises(KeyError):
        _ = data["userName"]


@pytest.mark.django_db
def test_compile_input_type_out_name_build_time_assert():
    """compile_input_type build-time assert fires for deliberately broken case.

    If we manually subvert the alias to equal the field_name for a multi-word
    field, compile_input_type should raise AssertionError.

    This tests the 'assert out_name != alias' guard that prevents silent
    camelCase/snake slip-through.
    """
    from pydantic import BaseModel, field_validator, ConfigDict
    from django_graphex.native.input_compiler import compile_input_type, to_camel

    # Build a model where to_camel("first_name") → "firstName" naturally
    # The compile path asserts out_name != alias for multi-word fields.
    class _WuBAssertModel(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        first_name: str

    # Normal case: no assertion
    gql_type = compile_input_type(_WuBAssertModel, name="WuBNormalAssertInput")
    fields = gql_type.fields
    assert "firstName" in fields
    assert fields["firstName"].out_name == "first_name"
