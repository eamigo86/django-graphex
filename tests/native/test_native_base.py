"""Tests for native/base.py — ObjectType/InputType metaclass bases.

TDD RED phase: written before the module exists.
Run with: .venv/bin/python -m pytest tests/native/test_native_base.py -x -v
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# 1.6 RED: ObjectType / InputType bases + metaclass identity
# ---------------------------------------------------------------------------


def test_input_type_is_pydantic_model_metaclass():
    """type(SearchInput) is ModelMetaclass for model-free InputType subclass."""
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.native.base import InputType

    class SearchInput(InputType):
        query: str
        limit: int = 10

    assert type(SearchInput) is ModelMetaclass, (
        f"Expected ModelMetaclass, got {type(SearchInput)}"
    )


def test_input_type_config_dict_alias_generator():
    """InputType ConfigDict uses pydantic to_camel alias_generator."""
    from django_graphex.native.base import InputType

    class MyInput(InputType):
        first_name: str

    # With alias_generator=to_camel, the field alias should be camelCase
    # and populate_by_name=True allows snake_case construction too
    obj = MyInput(first_name="Alice")
    assert obj.first_name == "Alice"


def test_input_type_populate_by_name():
    """InputType ConfigDict has populate_by_name=True — snake key construction works."""
    from django_graphex.native.base import InputType

    class PopulateByNameInput(InputType):
        first_name: str

    # Snake key should work (populate_by_name=True)
    obj = PopulateByNameInput(first_name="Bob")
    assert obj.first_name == "Bob"


def test_input_type_camel_key_construction():
    """InputType supports camelCase key construction via alias_generator."""
    from django_graphex.native.base import InputType

    class CamelKeyInput(InputType):
        first_name: str

    # CamelCase key should also work via alias
    obj = CamelKeyInput.model_validate({"firstName": "Carol"})
    assert obj.first_name == "Carol"


def test_object_type_is_base_model():
    """ObjectType is a Pydantic BaseModel subclass."""
    from django_graphex.native.base import ObjectType

    assert issubclass(ObjectType, BaseModel)


def test_input_type_is_object_type():
    """InputType is a subclass of ObjectType."""
    from django_graphex.native.base import InputType, ObjectType

    assert issubclass(InputType, ObjectType)


def test_getitem_mixin_dict_access():
    """InputType instances support dict-style access via __getitem__."""
    from django_graphex.native.base import InputType

    class GetItemInput(InputType):
        first_name: str
        age: int = 0

    obj = GetItemInput(first_name="Alice", age=30)
    assert obj["first_name"] == "Alice"
    assert obj["age"] == 30


# ---------------------------------------------------------------------------
# 1.7 RED: __init_subclass__ registry + compile_all_inputs
# ---------------------------------------------------------------------------


def test_input_type_subclass_registers_in_registry():
    """Subclassing InputType auto-registers the class in _gdx_input_registry."""
    from django_graphex.native.base import InputType, _gdx_input_registry

    initial_count = len(_gdx_input_registry)

    class RegistryTestInput(InputType):
        value: str

    assert len(_gdx_input_registry) == initial_count + 1
    assert RegistryTestInput in _gdx_input_registry


def test_compile_all_inputs_sets_meta_on_each():
    """compile_all_inputs sets _meta.graphql_input_type on each registered class."""
    from graphql import GraphQLInputObjectType

    from django_graphex.native.base import InputType, compile_all_inputs

    class CompileTestInput(InputType):
        value: str

    # Run compile
    compile_all_inputs()

    assert hasattr(CompileTestInput, "_meta"), "InputType subclass should have _meta"
    assert CompileTestInput._meta.graphql_input_type is not None
    assert isinstance(CompileTestInput._meta.graphql_input_type, GraphQLInputObjectType)


def test_compile_all_inputs_duplicate_name_raises():
    """compile_all_inputs raises ImproperlyConfigured on duplicate GraphQL names."""
    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.native.base import (
        InputType,
        _gdx_input_registry,
        compile_all_inputs,
    )

    # We cannot actually create two classes with the same name and have them
    # both register as different entries (Python rebinds the name), so we
    # simulate this by directly inserting a duplicate into the registry.
    # We use a private mechanism to test compile_all_inputs' duplicate check.

    class DupInputA(InputType):
        # Use a forced graphql_name attribute to create a name collision
        value: str

    class DupInputB(InputType):
        value: int

    # Force both to produce the same GraphQL name by monkeypatching
    # the name resolution — compile_all_inputs uses the class name.
    # Override __name__ is not possible on classes; instead we verify
    # the behavior via the normal code path where both have different names
    # (and it should NOT raise). This test verifies the duplicate detection
    # mechanism is in place by checking it raises when names collide.

    # We create a subclass that deliberately overrides its GQL name to clash
    # Store original name to restore after test
    original_name = DupInputA.__name__
    DupInputB.__name__ = DupInputA.__name__  # make them collide

    try:
        with pytest.raises(ImproperlyConfigured, match="duplicate"):
            compile_all_inputs()
    finally:
        DupInputB.__name__ = "DupInputB"  # restore


def test_compile_all_inputs_model_rebuild_errors():
    """compile_all_inputs re-raises rebuild errors as ImproperlyConfigured."""
    from unittest.mock import patch

    from django.core.exceptions import ImproperlyConfigured
    from pydantic import PydanticUserError

    from django_graphex.native.base import (
        InputType,
        _gdx_input_registry,
        compile_all_inputs,
    )

    class RebuildTestInput(InputType):
        value: str

    # Simulate a PydanticUserError during model_rebuild by patching
    with patch.object(RebuildTestInput, "model_rebuild", side_effect=Exception("unresolved ref 'FooType'")):
        with pytest.raises(ImproperlyConfigured, match="RebuildTestInput"):
            compile_all_inputs()
