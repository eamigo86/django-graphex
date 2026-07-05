"""Tests for WU-B task 2.8: camelCase→snake wire-key integrity (end-to-end).

Tests verify:
- Client sends {firstName: "Alice"} → resolver receives data.first_name == "Alice"
- data["first_name"] == "Alice" via __getitem__ mixin
- Multi-word field: out_name != alias verified on compiled type

Run.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Task 2.8: camelCase→snake wire-key integrity
# ---------------------------------------------------------------------------


def test_camel_wire_key_to_snake_resolver_key() -> None:
    """Assert that a camelCase wire key resolves to a snake_case attribute.

    "coerce_input" validates via alias (camelCase) and returns a BaseModel
    with a snake_case attribute; "__getitem__" also returns the snake key
    value.

    If this fails, a resolver reading "data.first_name" would not see the
    value the client sent as "firstName".
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import coerce_input

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


def test_multi_word_field_out_name_differs_from_alias() -> None:
    """Assert that a multi-word field's compiled out_name differs from its alias.

    The build-time assert in "compile_input_type" enforces this; this test
    verifies it by inspecting the compiled GraphQLInputField.

    If this fails, the snake_case out_name could collide with the camelCase
    alias, silently breaking the wire-to-resolver key translation.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import compile_input_type

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


def test_multi_word_field_snake_key_raises_key_error_in_compiled_type() -> None:
    """Assert that looking up a compiled type's fields by snake_case key raises KeyError.

    The spec says: "result.fields.get('first_name') raises KeyError"
    because the dict key is the camelCase alias.

    If this fails, the compiled fields mapping would expose both the
    camelCase and snake_case keys, contradicting the wire-key contract.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import compile_input_type

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


def test_coerce_input_camel_key_validated_snake_access() -> None:
    """Assert the full round trip: camelCase wire input yields snake attr and dict access.

    If this fails, "coerce_input" would not consistently translate camelCase
    wire keys into snake_case attribute and dict access, and camelCase dict
    access would not be rejected as expected.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import coerce_input

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
def test_compile_input_type_out_name_build_time_assert() -> None:
    """Assert that the normal (well-formed) compile path passes the out_name guard.

    If we manually subvert the alias to equal the field_name for a
    multi-word field, "compile_input_type" should raise AssertionError.
    This test exercises the "assert out_name != alias" guard that prevents
    silent camelCase/snake slip-through, on the normal (non-subverted) case.

    If this fails, the build-time out_name/alias guard would not be wired
    into the normal compile path.
    """
    from pydantic import BaseModel, ConfigDict

    from django_graphex.core.input_compiler import compile_input_type

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
