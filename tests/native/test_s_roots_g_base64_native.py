"""S-ROOTS-g — Base64FileInput ported to a native ``InputType`` (Pydantic).

These tests describe the GRAPHENE-FREE Base64 upload contract:

- ``Base64FileInput`` is a native ``InputType`` (a Pydantic ``BaseModel``
  subclass), NOT a ``graphene.InputObjectType``.
- A VALIDATED instance (the value that arrives in a native resolver after
  ``model_validate`` / ``coerce_input``) exposes ``filename`` / ``data`` /
  ``content_type`` as plain Pydantic attributes (snake_case).
- ``to_uploaded_file()`` reads those validated Pydantic attributes (NOT a
  graphene ``InputObjectTypeContainer``) and produces a Django
  ``SimpleUploadedFile`` end-to-end.
- The input compiles to a ``GraphQLInputObjectType`` with camelCase wire keys
  (``contentType``) so the SDL wire contract is preserved.

The retired graphene-only assertions (``_meta.container`` /
``issubclass(graphene.InputObjectType)``) live in the legacy
``tests/test_base64_upload.py`` and are S7-pruned — they are intentionally NOT
reproduced here.
"""

from __future__ import annotations

import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from graphql import GraphQLError

from django_graphex.uploads import Base64FileInput, decode_base64_file

_HELLO_BYTES = b"hello world"
_HELLO_B64 = base64.b64encode(_HELLO_BYTES).decode()

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
_TINY_PNG_B64 = base64.b64encode(_TINY_PNG).decode()


# ---------------------------------------------------------------------------
# Native nature: Base64FileInput is a native InputType (Pydantic BaseModel)
# ---------------------------------------------------------------------------


def test_base64_file_input_is_native_input_type():
    """Base64FileInput is a native InputType (Pydantic BaseModel), not graphene."""
    from pydantic import BaseModel

    from django_graphex.native.base import InputType

    assert issubclass(Base64FileInput, InputType)
    assert issubclass(Base64FileInput, BaseModel)


def test_base64_file_input_fields_declared():
    """The Pydantic model declares filename, data, and content_type fields."""
    fields = Base64FileInput.model_fields
    assert "filename" in fields
    assert "data" in fields
    assert "content_type" in fields


# ---------------------------------------------------------------------------
# Validated instance: to_uploaded_file reads validated Pydantic attrs
# ---------------------------------------------------------------------------


def test_validated_instance_to_uploaded_file():
    """A validated instance .to_uploaded_file() → SimpleUploadedFile (real decode)."""
    # This is the shape that arrives in a native resolver: a validated Pydantic
    # instance (camelCase wire key contentType maps to snake content_type).
    value = Base64FileInput.model_validate(
        {"filename": "photo.png", "data": _TINY_PNG_B64, "contentType": "image/png"}
    )
    # Validated attrs are plain Pydantic attributes (snake_case).
    assert value.filename == "photo.png"
    assert value.content_type == "image/png"

    result = value.to_uploaded_file(max_size=1024)
    assert isinstance(result, SimpleUploadedFile)
    assert result.name == "photo.png"
    assert result.content_type == "image/png"
    assert result.read() == _TINY_PNG


def test_validated_instance_default_content_type():
    """When contentType is omitted, content_type defaults to octet-stream."""
    value = Base64FileInput.model_validate(
        {"filename": "blob.bin", "data": _HELLO_B64}
    )
    assert value.content_type is None  # absent → None on the model

    result = value.to_uploaded_file(max_size=1024)
    # decode_base64_file applies the application/octet-stream default.
    assert result.content_type == "application/octet-stream"
    assert result.read() == _HELLO_BYTES


def test_validated_instance_over_limit_raises():
    """to_uploaded_file(max_size=N) enforces a per-file cap on the validated value."""
    large_data = base64.b64encode(b"x" * 200).decode()
    value = Base64FileInput.model_validate(
        {"filename": "big.bin", "data": large_data}
    )
    with pytest.raises(GraphQLError, match="exceeds"):
        value.to_uploaded_file(max_size=50)


# ---------------------------------------------------------------------------
# Compile: Base64FileInput compiles to a GraphQLInputObjectType (wire contract)
# ---------------------------------------------------------------------------


def test_base64_file_input_compiles_to_graphql_input_type():
    """Base64FileInput compiles to a GraphQLInputObjectType with camelCase keys."""
    from graphql import GraphQLInputObjectType

    from django_graphex.native.input_compiler import compile_input_type

    gql_input = compile_input_type(Base64FileInput, name="Base64FileInput")
    assert isinstance(gql_input, GraphQLInputObjectType)

    field_keys = set(gql_input.fields.keys())
    # Wire keys are camelCase: contentType (not content_type).
    assert "filename" in field_keys
    assert "data" in field_keys
    assert "contentType" in field_keys
    # out_name delivers the snake attribute name to the resolver.
    assert gql_input.fields["contentType"].out_name == "content_type"


# ---------------------------------------------------------------------------
# decode_base64_file module helper still works (unchanged contract)
# ---------------------------------------------------------------------------


def test_decode_base64_file_helper_unchanged():
    """decode_base64_file(dict) still decodes to a SimpleUploadedFile."""
    result = decode_base64_file(
        {"filename": "hello.txt", "content_type": "text/plain", "data": _HELLO_B64},
        max_size=1024,
    )
    assert isinstance(result, SimpleUploadedFile)
    assert result.name == "hello.txt"
    assert result.read() == _HELLO_BYTES
    assert result.content_type == "text/plain"
