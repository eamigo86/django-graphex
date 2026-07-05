"""TDD A3.1 / A3.3 RED — core/registry_compiler.py tests.

Tests:
- Mutual recursion A→B→A terminates without RecursionError.
- Self-referential type compiles.
- compile_all raises a named hard error when a type lacks extensions["gdx"].
- Cycle guard: placeholder registered BEFORE recursion.
- Loop-capture correctness: thunks resolve to correct types.

Run: .venv/bin/python -m pytest -q tests/core/test_registry_compiler.py
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest  # noqa: E402
from graphql import GraphQLObjectType  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers: minimal fake "registry" for unit tests
# ---------------------------------------------------------------------------


class CompileRegistry:
    """Test registry that tracks registration order and compiled types.

    Stands in for the real DjangoObjectType Meta-driven registry so unit
    tests can register model classes and inspect compilation results without
    building actual GraphQL types up front.
    """

    def __init__(self) -> None:
        """Initialize empty compiled-type and registration-order stores.

        Sets up the two internal collections used by the rest of the class:
        the compiled-type cache and the registration-order log.
        """
        # model_cls → GraphQLObjectType
        self._compiled: dict[type, GraphQLObjectType] = {}
        # ordered list of model classes registered
        self._registration_order: list[tuple[type, str, Any]] = []

    def register_output_cls(
        self,
        model_cls: type,
        gql_name: str,
        fields_factory: Any = None,
    ) -> None:
        """Register a model class for compilation.

        Stands in for a DjangoObjectType Meta declaration.

        Args:
            model_cls: The model class being registered.
            gql_name: The GraphQL type name to associate with the model.
            fields_factory: An optional callable that will later produce the
                type's fields; not invoked here.
        """
        self._registration_order.append((model_cls, gql_name, fields_factory))

    def get_compiled(self, model_cls: type) -> GraphQLObjectType | None:
        """Look up the compiled type previously stored for a model class.

        Args:
            model_cls: The model class to look up.

        Returns:
            The compiled GraphQLObjectType, or None if not yet compiled.
        """
        return self._compiled.get(model_cls)

    def set_compiled(self, model_cls: type, gql_type: GraphQLObjectType) -> None:
        """Store the compiled type for a model class.

        Args:
            model_cls: The model class the type was compiled for.
            gql_type: The compiled GraphQLObjectType to store.
        """
        self._compiled[model_cls] = gql_type

    def iter_output_classes(self) -> list[tuple[type, str, Any]]:
        """List the registered (model_cls, gql_name, fields_factory) tuples.

        Returns:
            A copy of the registration order, in registration order.
        """
        return list(self._registration_order)


# ---------------------------------------------------------------------------
# Build a simple two-type mutual recursion scenario using the compiler
# ---------------------------------------------------------------------------


def _make_mutual_recursion_registry():
    """
    Build two GraphQLObjectType specs that reference each other:
      NodeA has a field "nodeB" → NodeB
      NodeB has a field "nodeA" → NodeA
    """
    from django_graphex.core.registry_compiler import compile_all

    # We'll use two sentinel model classes
    class ModelA:
        pass

    class ModelB:
        pass

    return ModelA, ModelB, compile_all


# ---------------------------------------------------------------------------
# A3.1 RED: Mutual recursion A→B→A terminates without RecursionError
# ---------------------------------------------------------------------------


def test_mutual_recursion_terminates() -> None:
    """Ships broken if compile_all raises RecursionError when two registered
    types reference each other (A -> B -> A).
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    # Register A with a field referencing B
    class ModelA:
        pass

    class ModelB:
        pass

    registry.register("NodeA", ModelA, related_models=[ModelB])
    registry.register("NodeB", ModelB, related_models=[ModelA])

    # Must not raise RecursionError
    compile_all(registry)

    compiled_a = registry.get_compiled(ModelA)
    compiled_b = registry.get_compiled(ModelB)

    assert isinstance(compiled_a, GraphQLObjectType), (
        "NodeA must compile to GraphQLObjectType"
    )
    assert isinstance(compiled_b, GraphQLObjectType), (
        "NodeB must compile to GraphQLObjectType"
    )
    assert compiled_a.name == "NodeA"
    assert compiled_b.name == "NodeB"


def test_mutual_recursion_thunks_resolve_correctly() -> None:
    """Ships broken if a mutually recursive type's relation field thunk
    resolves to itself instead of the other type.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class ModelA:
        pass

    class ModelB:
        pass

    registry.register("NodeA", ModelA, related_models=[ModelB])
    registry.register("NodeB", ModelB, related_models=[ModelA])

    compile_all(registry)

    compiled_a = registry.get_compiled(ModelA)
    compiled_b = registry.get_compiled(ModelB)

    # NodeA's relation field should point to NodeB
    fields_a = compiled_a.fields
    assert "nodeB" in fields_a, f"NodeA fields: {list(fields_a.keys())}"
    from graphql import GraphQLList, GraphQLNonNull

    field_type = fields_a["nodeB"].type
    while isinstance(field_type, (GraphQLNonNull, GraphQLList)):
        field_type = field_type.of_type
    assert field_type is compiled_b, (
        f"NodeA.nodeB must resolve to compiled_b, got {field_type!r}"
    )

    # NodeB's relation field should point to NodeA
    fields_b = compiled_b.fields
    assert "nodeA" in fields_b, f"NodeB fields: {list(fields_b.keys())}"
    field_type_b = fields_b["nodeA"].type
    while isinstance(field_type_b, (GraphQLNonNull, GraphQLList)):
        field_type_b = field_type_b.of_type
    assert field_type_b is compiled_a, (
        f"NodeB.nodeA must resolve to compiled_a, got {field_type_b!r}"
    )


# ---------------------------------------------------------------------------
# A3.2 GREEN: Self-referential type compiles
# ---------------------------------------------------------------------------


def test_self_referential_type_compiles() -> None:
    """Ships broken if a self-referential type (Category -> parent ->
    Category) fails to compile or its thunk resolves to the wrong type.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class CategoryModel:
        pass

    registry.register("Category", CategoryModel, related_models=[CategoryModel])

    compile_all(registry)

    compiled = registry.get_compiled(CategoryModel)
    assert isinstance(compiled, GraphQLObjectType)
    assert compiled.name == "Category"

    # Self-referential thunk must resolve to the same type
    from graphql import GraphQLList, GraphQLNonNull

    fields = compiled.fields
    assert "category" in fields, (
        f"Self-ref field missing. Fields: {list(fields.keys())}"
    )
    field_type = fields["category"].type
    while isinstance(field_type, (GraphQLNonNull, GraphQLList)):
        field_type = field_type.of_type
    assert field_type is compiled, (
        "Self-referential thunk must resolve to the same type"
    )


# ---------------------------------------------------------------------------
# A3.3 RED: compile_all raises BuildError when a type lacks extensions["gdx"]
# ---------------------------------------------------------------------------


def test_compile_all_raises_on_missing_gdx_extensions() -> None:
    """Ships broken if compile_all stops raising BuildError for a type
    missing extensions["gdx"], or the error stops naming the offending type.
    """
    from django_graphex.core.registry_compiler import (
        BuildError,
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class ModelX:
        pass

    # Register with skip_gdx=True to simulate a type without extensions["gdx"]
    registry.register("NodeX", ModelX, skip_gdx=True)

    with pytest.raises(BuildError) as exc_info:
        compile_all(registry)

    # Error message must name the offending type
    assert "NodeX" in str(exc_info.value), (
        f"BuildError must mention 'NodeX'. Got: {exc_info.value}"
    )


def test_compile_all_no_error_when_all_types_have_gdx() -> None:
    """Ships broken if compile_all raises for a normally registered type that
    already carries extensions["gdx"].
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class ModelY:
        pass

    # Normal registration (includes extensions["gdx"])
    registry.register("NodeY", ModelY)

    # Should not raise
    compile_all(registry)

    compiled = registry.get_compiled(ModelY)
    assert isinstance(compiled, GraphQLObjectType)
    assert "gdx" in (compiled.extensions or {}), "extensions['gdx'] must be present"
