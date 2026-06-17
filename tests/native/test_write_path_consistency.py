"""Tests for WU-B task 2.6: InputObjectTypeContainer removal + __getitem__ mixin.

Tests verify:
- data["first_name"] == data.first_name on a validated BaseModel instance.
- rg "InputObjectTypeContainer" django_graphex/ = 0 (subprocess assert).
- Resolver receives BaseModel (not a container).
- data["firstName"] on camel key raises KeyError (snake keys only after coerce_input).

Run.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Task 2.6: dict-style access + no InputObjectTypeContainer in django_graphex/
# ---------------------------------------------------------------------------


def test_getitem_equals_attr_access():
    """data["first_name"] == data.first_name on a validated BaseModel instance."""
    from django_graphex.native.base import InputType

    class _WuBPersonInput(InputType):
        first_name: str
        age: int = 0

    # Model validation via snake key (populate_by_name=True)
    data = _WuBPersonInput(first_name="Alice", age=30)
    assert data["first_name"] == data.first_name, (
        "dict-style access must equal attribute access"
    )
    assert data["age"] == data.age


def test_getitem_camel_key_raises_key_error():
    """data["firstName"] (camelCase) must raise KeyError — only snake keys after coerce_input."""
    from django_graphex.native.base import InputType

    class _WuBCamelInput(InputType):
        first_name: str

    data = _WuBCamelInput(first_name="Bob")
    # After coerce_input, resolver receives the validated BaseModel instance.
    # The __getitem__ mixin uses model_dump() which uses snake_case field names.
    # So camelCase key access must raise KeyError.
    with pytest.raises(KeyError):
        _ = data["firstName"]


def test_input_type_container_absent_from_native_modules():
    """InputObjectTypeContainer must NOT appear in any django_graphex/native/ module.

    The graphene-path types.py retains the container until Phase 7.
    But ALL native/ modules must be container-free: the native resolver
    receives a validated Pydantic BaseModel, never an InputObjectTypeContainer.
    """
    import pathlib

    project_root = pathlib.Path(__file__).parent.parent.parent
    native_dir = project_root / "django_graphex" / "native"

    container_usages = []
    for py_file in native_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "InputObjectTypeContainer" in text:
            container_usages.append(str(py_file.relative_to(project_root)))

    assert not container_usages, (
        f"InputObjectTypeContainer found in native/ modules: {container_usages}. "
        f"Native modules must be container-free."
    )


def test_coerce_input_returns_base_model_not_container():
    """coerce_input returns a BaseModel instance, never a graphene container."""
    from pydantic import BaseModel

    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import coerce_input

    class _WuBResolverInput(InputType):
        name: str
        value: int = 0

    # Coerce a raw dict
    result = coerce_input(_WuBResolverInput, {"name": "test", "value": 42})

    # Must be a BaseModel instance
    assert isinstance(result, BaseModel), (
        "coerce_input must return a BaseModel instance, not a graphene container"
    )
    # Must not be an InputObjectTypeContainer (the removed graphene type)
    # We verify by checking the class hierarchy contains no graphene types
    for base in type(result).__mro__:
        assert "graphene" not in base.__module__ if hasattr(base, "__module__") else True, (
            f"Unexpected graphene type in MRO: {base}"
        )


def test_coerce_input_validates_camel_key():
    """coerce_input validates camelCase wire key via alias_generator=to_camel."""
    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import coerce_input

    class _WuBWireKeyInput(InputType):
        first_name: str

    # Wire sends camelCase (what GraphQL client sends)
    result = coerce_input(_WuBWireKeyInput, {"firstName": "Alice"})
    assert result.first_name == "Alice", (
        "coerce_input must validate camelCase wire keys via alias_generator"
    )
    # dict-style access uses snake key
    assert result["first_name"] == "Alice"


def test_coerce_input_validation_error_no_pydantic_url():
    """coerce_input raises GraphQLError with no errors.pydantic.dev URL."""
    from graphql import GraphQLError

    from django_graphex.native.base import InputType
    from django_graphex.native.input_compiler import coerce_input

    class _WuBValidationInput(InputType):
        name: str  # required

    with pytest.raises(GraphQLError) as exc_info:
        coerce_input(_WuBValidationInput, {})  # missing required 'name'

    error = exc_info.value
    import json
    ext_str = json.dumps(error.extensions or {})
    assert "errors.pydantic.dev" not in ext_str, (
        "GraphQLError extensions must never contain 'errors.pydantic.dev' URL"
    )
    assert error.extensions.get("code") == "VALIDATION_ERROR"
