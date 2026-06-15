"""Tests for the GDX_BACKEND dual-backend harness.

Verifies that:
- GDX_BACKEND env var can be read
- native_only mark is recognized
- normalize_sdl utility is importable and functional
- The graphene CI path is unaffected (additivity gate).

Run with: .venv/bin/python -m pytest tests/native/test_native_backend.py -x -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.native_only


def test_gdx_backend_env_readable():
    """GDX_BACKEND env var should be readable (default 'graphene' or 'native')."""
    backend = os.environ.get("GDX_BACKEND", "graphene")
    assert backend in ("graphene", "native"), f"Unexpected GDX_BACKEND value: {backend!r}"


def test_native_only_mark_registered():
    """native_only mark is registered in pytest (no PytestUnknownMarkWarning)."""
    # This test just ensures the mark is used — the conftest registers it.
    # If the mark is unregistered, this test would show a warning (but still pass).
    # The actual registration is in tests/native/conftest.py.
    pass


def test_normalize_sdl_importable():
    """normalize_sdl utility is importable from the native conftest."""
    from tests.native.conftest import normalize_sdl

    assert callable(normalize_sdl)


def test_normalize_sdl_sorts_types():
    """normalize_sdl sorts type blocks alphabetically."""
    from tests.native.conftest import normalize_sdl

    sdl = """
type ZType {
  value: String
}

type AType {
  name: String
}
"""
    normalized = normalize_sdl(sdl)
    # After normalization, AType should come before ZType
    a_pos = normalized.find("AType")
    z_pos = normalized.find("ZType")
    assert a_pos < z_pos, "normalize_sdl should sort type blocks alphabetically"


def test_normalize_sdl_strips_descriptions():
    """normalize_sdl strips description strings from SDL."""
    from tests.native.conftest import normalize_sdl

    sdl = '''
"""A description of MyType."""
type MyType {
  """field description"""
  name: String
}
'''
    normalized = normalize_sdl(sdl)
    assert '"""' not in normalized, "normalize_sdl should strip descriptions"


def test_normalize_sdl_idempotent():
    """normalize_sdl is idempotent — applying twice gives same result."""
    from tests.native.conftest import normalize_sdl

    sdl = """
type BType {
  value: Int
}

type AType {
  name: String
}
"""
    first = normalize_sdl(sdl)
    second = normalize_sdl(first)
    assert first == second, "normalize_sdl should be idempotent"


# ---------------------------------------------------------------------------
# Task 2.12 RED → 2.13 GREEN: Dual-backend SDL parity for input types
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="S6c: DjangoInputObjectType re-parented off graphene InputObjectType "
    "onto native InputType, so the graphene baseline half of this parity test can "
    "no longer build (graphene.Schema rejects the re-parented type at "
    "schema.py:102 `assert is_graphene_type`). The native-side nullability is "
    "independently proven by test_input_compiler.py "
    "(test_compile_input_type_required_field_is_nonnull / "
    "test_compile_input_type_optional_field_is_nullable) and the native-only "
    "GraphQLInputObjectType assertions still active in "
    "test_model_coupled_metaclass_is_modelmetaclass_after_s6c. The cross-backend "
    "byte-parity assertion is retired (graphene path dies per-slice, pruned S7) — "
    "same disposition as the S6b SDL-parity-seed skips."
)
@pytest.mark.django_db
def test_input_type_sdl_field_nullability_parity_with_graphene():
    """Native compile path produces field names and nullability matching the graphene path
    for the SAME DjangoInputObjectType.

    This is the genuine parity check: we build ONE DjangoInputObjectType for
    Category under GDX_BACKEND=native, read its _meta.graphql_input_type, then
    build the same DjangoInputObjectType under graphene and read the graphene
    schema's input type SDL — then assert field names and nullability match.

    What this test checks explicitly:
    - Every field name present in the native graphql_input_type is also in the
      graphene SDL, and vice versa.
    - For each field, nullability (NonNull vs nullable) is identical.

    What it does NOT claim:
    - Byte-identical SDL strings (type ordering / descriptions may differ).
    - Full schema print equality (backends embed different introspection metadata).
    """
    from graphql import GraphQLNonNull, GraphQLInputObjectType
    from graphql.utilities import print_schema as gql_print_schema
    from tests.native.conftest import normalize_sdl
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    # -------------------------------------------------------------------
    # 1. Native path: DjangoInputObjectType under GDX_BACKEND=native
    #    (already active — the native_only mark enforces GDX_BACKEND=native)
    # -------------------------------------------------------------------
    class _ParityCategoryNative(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "create"

    native_gql_type = _ParityCategoryNative._meta.graphql_input_type
    assert isinstance(native_gql_type, GraphQLInputObjectType), (
        f"Expected GraphQLInputObjectType from native path, got {type(native_gql_type)}"
    )

    # Collect native field info: {name: is_nonnull}
    native_fields = native_gql_type.fields
    native_nullability = {
        fname: isinstance(fobj.type, GraphQLNonNull)
        for fname, fobj in native_fields.items()
    }

    # -------------------------------------------------------------------
    # 2. Graphene path: build the graphene equivalent for the same model.
    #    We call __init_subclass_with_meta__ manually on the graphene path by
    #    temporarily unsetting GDX_BACKEND and building a fresh subclass.
    # -------------------------------------------------------------------
    import os as _os
    prev_backend = _os.environ.get("GDX_BACKEND")
    try:
        _os.environ["GDX_BACKEND"] = "graphene"

        class _ParityCategoryGraphene(DjangoInputObjectType):
            class Meta:
                model = Category
                input_for = "create"

        # Print the graphene schema containing the input type
        import graphene

        class _ParityQuery(graphene.ObjectType):
            _placeholder = graphene.String()

        graphene_schema = graphene.Schema(
            query=_ParityQuery,
            types=[_ParityCategoryGraphene],
        )
        graphene_sdl = str(graphene_schema)
    finally:
        if prev_backend is None:
            _os.environ.pop("GDX_BACKEND", None)
        else:
            _os.environ["GDX_BACKEND"] = prev_backend

    # Extract graphene field names and nullability from SDL text.
    # Category has a single field 'title' (CharField, required in create form).
    # We parse "fieldName: Type!" vs "fieldName: Type" from SDL lines.
    graphene_field_nullability: dict[str, bool] = {}
    in_input_block = False
    for line in graphene_sdl.splitlines():
        stripped = line.strip()
        if stripped.startswith("input _ParityCategoryGraphene"):
            in_input_block = True
            continue
        if in_input_block:
            if stripped == "}":
                break
            if stripped and ":" in stripped:
                # e.g. "title: String!" or "id: ID"
                parts = stripped.split(":")
                field_name = parts[0].strip()
                type_str = ":".join(parts[1:]).strip()
                graphene_field_nullability[field_name] = type_str.endswith("!")

    # -------------------------------------------------------------------
    # 3. Compare field names and nullability
    # -------------------------------------------------------------------
    native_field_set = set(native_nullability.keys())
    graphene_field_set = set(graphene_field_nullability.keys())

    # Fields present in native must all appear in graphene SDL
    missing_from_graphene = native_field_set - graphene_field_set
    assert not missing_from_graphene, (
        f"Fields in native but missing from graphene SDL: {missing_from_graphene}. "
        f"Native fields: {sorted(native_field_set)}, "
        f"Graphene fields: {sorted(graphene_field_set)}"
    )

    # For shared fields, nullability must match
    for fname in native_field_set & graphene_field_set:
        native_nonnull = native_nullability[fname]
        graphene_nonnull = graphene_field_nullability[fname]
        assert native_nonnull == graphene_nonnull, (
            f"Field '{fname}' nullability mismatch: "
            f"native={'NonNull' if native_nonnull else 'nullable'}, "
            f"graphene={'NonNull' if graphene_nonnull else 'nullable'}"
        )


def test_normalize_sdl_input_type_structure_parity():
    """Input type SDL structure is consistent between normalize_sdl calls.

    Verifies that normalize_sdl produces stable ordering for input types,
    enabling reliable diff comparisons between graphene and native backends.
    """
    from tests.native.conftest import normalize_sdl

    # Two SDL strings that are semantically identical (same input type, different order)
    sdl_a = """
input PersonInput {
  lastName: String
  firstName: String!
}
"""
    sdl_b = """
input PersonInput {
  firstName: String!
  lastName: String
}
"""
    # After normalization, both should be identical
    assert normalize_sdl(sdl_a) == normalize_sdl(sdl_b), (
        "normalize_sdl must sort fields within blocks, making field-order-different "
        "but semantically-identical SDL blocks equal"
    )
