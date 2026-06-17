"""WU1 TDD RED — Global output registry + compile_all_outputs at app-ready.

Tests:
  (a) _gdx_output_registry exists in django_graphex/native/base.py
  (b) Every DjangoObjectType/DjangoListObjectType in the test app is in the
      registry after app-ready (checked via registry length > 0 after calling
      compile_all_outputs())
  (c) Each entry has non-None graphql_output_type and populated extensions['gdx']
  (d) A→B→A circular reference fixture does NOT raise RecursionError

Gate spec: Domain 1 §Compile-at-app-ready + §Circular-reference-guard

Run:
    .venv/bin/python -m pytest tests/native/test_global_output_registry.py \
        -q -o addopts=""
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# (a) Global output registry exists in native/base.py
# ---------------------------------------------------------------------------


def test_gdx_output_registry_exists_in_base():
    """_gdx_output_registry must be a list defined in native/base.py."""
    from django_graphex.native import base
    assert hasattr(base, "_gdx_output_registry"), (
        "_gdx_output_registry not found in django_graphex.native.base"
    )
    assert isinstance(base._gdx_output_registry, list), (
        "_gdx_output_registry must be a list, got: "
        f"{type(base._gdx_output_registry)}"
    )


# ---------------------------------------------------------------------------
# (b) + (c) compile_all_outputs() exists and compiles every registered type
# ---------------------------------------------------------------------------


def test_compile_all_outputs_exists():
    """compile_all_outputs must be importable from registry_compiler."""
    from django_graphex.native.registry_compiler import (
        compile_all_outputs,  # noqa: F401
    )


def test_compile_all_outputs_populates_registry():
    """After compile_all_outputs(), every entry in _gdx_output_registry has
    non-None graphql_output_type and populated extensions['gdx'].

    The test app defines UserType (DjangoObjectType) and User1ListType
    (DjangoListObjectType) — these auto-register on class definition (triggered
    by schema.py import).  compile_all_outputs() must find and compile them.
    """
    from graphql import GraphQLObjectType

    # Importing the test schema triggers DjangoObjectType/DjangoListObjectType
    # __init_subclass_with_meta__ which registers into _gdx_output_registry.
    import tests.schema  # noqa: F401 — side-effect: registers test types
    from django_graphex.native.base import _gdx_output_registry
    from django_graphex.native.registry_compiler import compile_all_outputs

    # Registry must be non-empty (test schema registered types)
    assert len(_gdx_output_registry) > 0, (
        "_gdx_output_registry is empty — DjangoObjectType subclasses must "
        "auto-register into it on class creation"
    )

    compile_all_outputs()

    # Every registered entry must now have a compiled graphql_output_type
    for entry in _gdx_output_registry:
        cls = entry.cls
        cls_name = entry.gql_name
        meta = getattr(cls, "_meta", None)
        assert meta is not None, f"{cls_name} has no _meta"

        gql_type = getattr(meta, "graphql_output_type", None)
        assert gql_type is not None, (
            f"{cls_name}._meta.graphql_output_type is None after "
            "compile_all_outputs()"
        )
        assert isinstance(gql_type, GraphQLObjectType), (
            f"{cls_name}._meta.graphql_output_type must be GraphQLObjectType, "
            f"got {type(gql_type)}"
        )
        # Phase-3 assertion: extensions['gdx'] populated
        assert "gdx" in (gql_type.extensions or {}), (
            f"{cls_name}: compiled GraphQLObjectType missing extensions['gdx']"
        )


# ---------------------------------------------------------------------------
# (d) A→B→A circular reference via shared _in_progress — no RecursionError
# ---------------------------------------------------------------------------


def test_circular_reference_ab_ba_no_recursion():
    """Two DjangoObjectType subclasses referencing each other compile without
    RecursionError. The shared module-level _in_progress in registry_compiler
    must guard the cycle.

    We use plain model classes (not real Django models) to keep this a pure
    unit test, mirroring the existing test_registry_compiler.py pattern.
    """
    from graphql import GraphQLObjectType

    from django_graphex.native.registry_compiler import (
        NativeOutputRegistry,
        _reset_in_progress,
        compile_all,
    )

    class ModelCircleA:
        pass

    class ModelCircleB:
        pass

    registry = NativeOutputRegistry()
    registry.register("CircleA", ModelCircleA, related_models=[ModelCircleB])
    registry.register("CircleB", ModelCircleB, related_models=[ModelCircleA])

    _reset_in_progress()  # ensure clean state

    # Must NOT raise RecursionError
    compile_all(registry)

    compiled_a = registry.get_compiled(ModelCircleA)
    compiled_b = registry.get_compiled(ModelCircleB)

    assert isinstance(compiled_a, GraphQLObjectType), (
        "CircleA must compile to GraphQLObjectType"
    )
    assert isinstance(compiled_b, GraphQLObjectType), (
        "CircleB must compile to GraphQLObjectType"
    )

    # Both must carry extensions['gdx']
    assert "gdx" in (compiled_a.extensions or {}), (
        "CircleA compiled type missing extensions['gdx']"
    )
    assert "gdx" in (compiled_b.extensions or {}), (
        "CircleB compiled type missing extensions['gdx']"
    )

    # The types must NOT be duplicated — each appears exactly once
    all_compiled = [compiled_a, compiled_b]
    assert len(set(id(t) for t in all_compiled)) == 2, (
        "CircleA and CircleB must be distinct GraphQLObjectType instances "
        "(no duplicate types from recursion)"
    )
