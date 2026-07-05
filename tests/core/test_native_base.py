"""Tests for core/base.py — ObjectType/InputType metaclass bases.

TDD RED phase: written before the module exists.
Run with: .venv/bin/python -m pytest tests/core/test_native_base.py -x -v
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 1.6 RED: ObjectType / InputType bases + metaclass identity
# ---------------------------------------------------------------------------


def test_input_type_is_pydantic_model_metaclass() -> None:
    """Assert that a model-free "InputType" subclass has Pydantic's ModelMetaclass.

    If this fails, InputType subclasses would not be true Pydantic models,
    breaking validation, serialization, and schema compilation that rely
    on the ModelMetaclass machinery.
    """
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.core.base import InputType

    class SearchInput(InputType):
        query: str
        limit: int = 10

    assert type(SearchInput) is ModelMetaclass, (
        f"Expected ModelMetaclass, got {type(SearchInput)}"
    )


def test_input_type_config_dict_alias_generator() -> None:
    """Assert that "InputType" construction accepts snake_case field names directly.

    Its ConfigDict wires pydantic's "to_camel" alias_generator.

    If this fails, constructing an InputType with snake_case kwargs would
    fail even though "populate_by_name" is expected to allow it.
    """
    from django_graphex.core.base import InputType

    class MyInput(InputType):
        first_name: str

    # With alias_generator=to_camel, the field alias should be camelCase
    # and populate_by_name=True allows snake_case construction too
    obj = MyInput(first_name="Alice")
    assert obj.first_name == "Alice"


def test_input_type_populate_by_name() -> None:
    """Assert that "InputType" allows snake_case key construction via populate_by_name.

    If this fails, "InputType" subclasses would reject snake_case kwargs,
    forcing all construction through the camelCase alias only.
    """
    from django_graphex.core.base import InputType

    class PopulateByNameInput(InputType):
        first_name: str

    # Snake key should work (populate_by_name=True)
    obj = PopulateByNameInput(first_name="Bob")
    assert obj.first_name == "Bob"


def test_input_type_camel_key_construction() -> None:
    """Assert that "InputType" supports camelCase key construction via alias_generator.

    If this fails, "model_validate" with camelCase wire keys (as GraphQL
    clients send) would fail to populate the InputType instance.
    """
    from django_graphex.core.base import InputType

    class CamelKeyInput(InputType):
        first_name: str

    # CamelCase key should also work via alias
    obj = CamelKeyInput.model_validate({"firstName": "Carol"})
    assert obj.first_name == "Carol"


def test_object_type_is_base_model() -> None:
    """Assert that "ObjectType" is a Pydantic BaseModel subclass.

    If this fails, ObjectType would lose Pydantic's validation and
    serialization behavior, breaking every dependent output type.
    """
    from django_graphex.core.base import ObjectType

    assert issubclass(ObjectType, BaseModel)


def test_input_type_is_object_type() -> None:
    """Assert that "InputType" is a subclass of "ObjectType".

    If this fails, InputType would not inherit ObjectType's shared base
    behavior, potentially diverging in validation or serialization.
    """
    from django_graphex.core.base import InputType, ObjectType

    assert issubclass(InputType, ObjectType)


def test_getitem_mixin_dict_access() -> None:
    """Assert that "InputType" instances support dict-style access via "__getitem__".

    If this fails, legacy resolvers reading input data via subscript
    access (e.g. "data['first_name']") would break with a TypeError.
    """
    from django_graphex.core.base import InputType

    class GetItemInput(InputType):
        first_name: str
        age: int = 0

    obj = GetItemInput(first_name="Alice", age=30)
    assert obj["first_name"] == "Alice"
    assert obj["age"] == 30


# ---------------------------------------------------------------------------
# 1.7 RED: __init_subclass__ registry + compile_all_inputs
# ---------------------------------------------------------------------------


def test_input_type_subclass_registers_in_registry() -> None:
    """Assert that subclassing "InputType" auto-registers the class in the input registry.

    If this fails, a declared InputType subclass would never be picked up
    by "compile_all_inputs", silently missing from the compiled schema.
    """
    from django_graphex.core.base import InputType, _gdx_input_registry

    initial_count = len(_gdx_input_registry)

    class RegistryTestInput(InputType):
        value: str

    assert len(_gdx_input_registry) == initial_count + 1
    assert RegistryTestInput in _gdx_input_registry


def test_compile_all_inputs_sets_meta_on_each() -> None:
    """Assert that "compile_all_inputs" sets "_meta.graphql_input_type" on each registered class.

    If this fails, a registered InputType subclass would have no compiled
    GraphQLInputObjectType attached after the compile pass runs.
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.core.base import InputType, compile_all_inputs

    class CompileTestInput(InputType):
        value: str

    # Run compile
    compile_all_inputs()

    assert hasattr(CompileTestInput, "_meta"), "InputType subclass should have _meta"
    assert CompileTestInput._meta.graphql_input_type is not None
    assert isinstance(CompileTestInput._meta.graphql_input_type, GraphQLInputObjectType)


def test_compile_all_inputs_duplicate_name_raises() -> None:
    """Assert that "compile_all_inputs" raises ImproperlyConfigured on duplicate GraphQL names.

    If this fails, two distinct input classes resolving to the same
    GraphQL name would compile silently, producing an ambiguous or
    last-write-wins schema instead of failing fast.
    """
    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.core.base import (
        InputType,
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
    DupInputB.__name__ = DupInputA.__name__  # make them collide

    try:
        with pytest.raises(ImproperlyConfigured, match="duplicate"):
            compile_all_inputs()
    finally:
        DupInputB.__name__ = "DupInputB"  # restore


def test_compile_all_inputs_model_rebuild_errors() -> None:
    """Assert that "compile_all_inputs" re-raises model_rebuild errors as ImproperlyConfigured.

    If this fails, a Pydantic model-rebuild failure (e.g. an unresolved
    forward reference) would surface as a raw, hard-to-diagnose exception
    instead of a clear ImproperlyConfigured naming the offending class.
    """
    from unittest.mock import patch

    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.core.base import (
        InputType,
        compile_all_inputs,
    )

    class RebuildTestInput(InputType):
        value: str

    # Simulate a PydanticUserError during model_rebuild by patching
    with patch.object(
        RebuildTestInput,
        "model_rebuild",
        side_effect=Exception("unresolved ref 'FooType'"),
    ):
        with pytest.raises(ImproperlyConfigured, match="RebuildTestInput"):
            compile_all_inputs()
