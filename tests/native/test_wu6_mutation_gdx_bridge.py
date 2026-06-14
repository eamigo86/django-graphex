"""WU-6: isolation tests + extensions["gdx"] bridge assertion for mutation output types.

Spec coverage:
- R8 / Spec scenario: extensions["gdx"] assertion fires on a malformed mutation output type
  (a GraphQLObjectType built as mutation output but missing the bridge payload).
- R8 positive: DjangoModelMutation's GraphQLField output type carries extensions["gdx"]
  (set by DjangoModelType's native branch in types.py).
- R6 public-export: django_graphex.Mutation is in __all__ (WU-2 done; this test guards regression).
- R9 (WU9 update): the Phase-5 boundary skip on test_serializer_type_mutation_fields
  is REMOVED — native mutation schema assembly is delivered in Phase 5 / WU9, so the
  test now runs and asserts the native GraphQLField shape.

REUSE rule (spec + design):
  The ONE owned assertion lives in native/bridge.py::assert_gdx_bridge.
  These tests CALL that function — they do NOT re-introduce a second assertion.

No schema assembly: these are isolation tests. Every test inspects built GraphQLField / GraphQLObjectType
objects directly; no GraphQLSchema execution is performed (except the minimal one-type schemas fed
to assert_gdx_bridge to trigger the assertion path).

Phase-4 gate (build-not-wired): no test claims end-to-end mutation execution under native.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# R8: assert_gdx_bridge fires on a mutation output type missing extensions["gdx"]
# ---------------------------------------------------------------------------


def test_assert_gdx_bridge_raises_for_mutation_output_type_missing_gdx():
    """assert_gdx_bridge raises when a GraphQLObjectType representing a mutation
    output is present in the schema WITHOUT extensions['gdx'].

    This is the R8 spec scenario, mutation-output-specific:
      GIVEN a mutation output type registered without extensions['gdx']
      WHEN assert_gdx_bridge(schema) is called
      THEN it raises AssertionError identifying the offending type
      AND the assertion is the EXISTING implementation from native/bridge.py
    """
    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.native.bridge import assert_gdx_bridge

    # Build a bare mutation output type (no extensions["gdx"]) —
    # simulates a hand-built mutation result that bypassed the native pipeline.
    bare_mutation_output = GraphQLObjectType(
        "CreateUserPayload",
        fields={"ok": GraphQLField(GraphQLString)},
        # Deliberately omit extensions={"gdx": ...}
    )

    # Minimal schema: a query type + the bare mutation output (so it's in type_map)
    query_type = GraphQLObjectType(
        "Query",
        fields={"_dummy": GraphQLField(GraphQLString)},
        extensions={"gdx": object()},  # Query has gdx so only CreateUserPayload fails
    )
    mutation_type = GraphQLObjectType(
        "Mutation",
        fields={"createUser": GraphQLField(bare_mutation_output)},
        extensions={"gdx": object()},  # Mutation root has gdx
    )
    schema = GraphQLSchema(query=query_type, mutation=mutation_type)

    # bare_mutation_output is in schema.type_map["CreateUserPayload"]
    assert "CreateUserPayload" in schema.type_map

    with pytest.raises(AssertionError) as exc_info:
        assert_gdx_bridge(schema)

    assert "CreateUserPayload" in str(exc_info.value), (
        "AssertionError must name the offending mutation output type"
    )
    assert "extensions['gdx']" in str(exc_info.value) or "extensions[" in str(exc_info.value), (
        "AssertionError must mention extensions['gdx'] as the missing element"
    )


def test_assert_gdx_bridge_passes_for_mutation_output_type_with_gdx():
    """assert_gdx_bridge does NOT raise when a mutation output type carries
    extensions['gdx'] — the happy path for a properly compiled mutation result type.
    """
    # Build a mutation output type WITH extensions["gdx"]
    from types import SimpleNamespace

    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.native.bridge import GdxPayload, assert_gdx_bridge
    gdx_payload = GdxPayload(SimpleNamespace(name="CreateUserPayload"))

    mutation_output = GraphQLObjectType(
        "CreateUserPayload",
        fields={"ok": GraphQLField(GraphQLString)},
        extensions={"gdx": gdx_payload},
    )

    query_type = GraphQLObjectType(
        "Query",
        fields={"_dummy": GraphQLField(GraphQLString)},
        extensions={"gdx": GdxPayload(SimpleNamespace(name="Query"))},
    )
    mutation_type = GraphQLObjectType(
        "Mutation",
        fields={"createUser": GraphQLField(mutation_output)},
        extensions={"gdx": GdxPayload(SimpleNamespace(name="Mutation"))},
    )
    schema = GraphQLSchema(query=query_type, mutation=mutation_type)

    # Must not raise
    assert_gdx_bridge(schema)


# ---------------------------------------------------------------------------
# R8 positive: DjangoModelMutation's output type carries extensions["gdx"]
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_model_mutation_output_type_carries_gdx():
    """Under GDX_BACKEND=native, the GraphQLField returned by
    DjangoModelMutation.CreateField() uses an output type that carries
    extensions['gdx'] (set by DjangoModelType's native branch in types.py).

    This is the positive integration assertion for R8: the pipeline that builds
    mutation output types correctly attaches the bridge payload.
    """
    from graphql import GraphQLField, GraphQLNonNull, GraphQLObjectType

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU6CategoryMutation(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU6CategoryMutation.CreateField()
    assert isinstance(field, GraphQLField), (
        "CreateField() must return GraphQLField under native"
    )

    # Resolve the output type (may be wrapped in NonNull or be a thunk)
    field_type = field.type
    if callable(field_type) and not isinstance(field_type, GraphQLObjectType):
        field_type = field_type()
    if isinstance(field_type, GraphQLNonNull):
        field_type = field_type.of_type

    assert isinstance(field_type, GraphQLObjectType), (
        f"Mutation output type must be GraphQLObjectType, got {type(field_type)}"
    )
    assert "gdx" in (field_type.extensions or {}), (
        f"Mutation output type {field_type.name!r} must carry extensions['gdx']. "
        "DjangoModelType's native branch (types.py) sets this via GdxPayload."
    )


@pytest.mark.django_db
def test_django_model_type_create_field_output_carries_gdx():
    """Under GDX_BACKEND=native, the output type of DjangoModelType.CreateField()
    carries extensions['gdx'].
    """
    from graphql import GraphQLField, GraphQLNonNull, GraphQLObjectType

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU6ModelTypeCategory(DjangoModelType):
        class Meta:
            model = Category

    field = _WU6ModelTypeCategory.CreateField()
    assert isinstance(field, GraphQLField)

    field_type = field.type
    if callable(field_type) and not isinstance(field_type, GraphQLObjectType):
        field_type = field_type()
    if isinstance(field_type, GraphQLNonNull):
        field_type = field_type.of_type

    assert isinstance(field_type, GraphQLObjectType), (
        f"DjangoModelType.CreateField output must be GraphQLObjectType, got {type(field_type)}"
    )
    assert "gdx" in (field_type.extensions or {}), (
        f"DjangoModelType.CreateField output type {field_type.name!r} must carry "
        "extensions['gdx'] (set by native branch in types.py via GdxPayload)."
    )


# ---------------------------------------------------------------------------
# R8 reuse guard: only ONE assert_gdx_bridge exists in native/bridge.py
# ---------------------------------------------------------------------------


def test_assert_gdx_bridge_is_defined_once_in_bridge():
    """assert_gdx_bridge is the ONE owned assertion — it lives in native/bridge.py.

    This test guards that no second instance of the assertion logic is introduced
    in mutation.py, types.py, or any other module (spec R8 / design REUSE rule).
    """
    import inspect

    from django_graphex.native import bridge
    from django_graphex.native.bridge import assert_gdx_bridge

    # assert_gdx_bridge must be defined IN bridge.py (not imported from elsewhere)
    assert inspect.getmodule(assert_gdx_bridge) is bridge, (
        "assert_gdx_bridge must be defined in native/bridge.py, not re-introduced elsewhere"
    )


# ---------------------------------------------------------------------------
# R6 regression guard: Mutation is in django_graphex.__all__
# ---------------------------------------------------------------------------


def test_mutation_in_public_all():
    """django_graphex.Mutation is exported in __all__ (WU-2 delivered; guard regression)."""
    import django_graphex

    assert "Mutation" in django_graphex.__all__, (
        "Mutation must be in django_graphex.__all__"
    )
    from django_graphex import Mutation
    from django_graphex.native.mutation import Mutation as NativeMutation
    assert Mutation is NativeMutation, (
        "django_graphex.Mutation must be the native Mutation class"
    )


# ---------------------------------------------------------------------------
# R9 (WU9): the Phase-5 boundary skip is REMOVED — native mutation schema
# assembly is now a delivered Phase-5 deliverable, so the formerly-skipped
# test_serializer_type_mutation_fields runs and asserts the native field shape.
# ---------------------------------------------------------------------------


def test_serializer_mutation_fields_test_is_unskipped_in_phase5():
    """``test_serializer_type_mutation_fields`` in tests/test_types.py is no
    longer skipped under native (WU9): the Phase-4 honest skip deferred native
    mutation schema assembly to Phase 5, and Phase 5 / WU9 delivers it.

    Reads the source directly and confirms the native branch now ASSERTS the
    GraphQLField shape rather than skipping it.
    """
    import pathlib

    test_types_path = pathlib.Path(__file__).parent.parent / "test_types.py"
    assert test_types_path.exists(), f"test_types.py not found at {test_types_path}"

    source = test_types_path.read_text(encoding="utf-8")

    # The test still exists.
    assert "test_serializer_type_mutation_fields" in source, (
        "test_serializer_type_mutation_fields must still exist in test_types.py"
    )
    # WU9: the native branch no longer skips — it asserts GraphQLField/GraphQLArgument.
    assert "self.skipTest(" not in source, (
        "The Phase-5 boundary skip must be REMOVED in WU9 (native mutation "
        "schema assembly is delivered): no self.skipTest() in test_types.py"
    )
    assert "GraphQLArgument" in source and "GraphQLField" in source, (
        "The un-skipped native branch must assert the native GraphQLField shape "
        "(GraphQLField output + GraphQLArgument args)"
    )
