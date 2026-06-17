"""Tests for the native test harness utilities.

Verifies that the ``normalize_sdl`` utility is importable and functional.

Run with: .venv/bin/python -m pytest tests/native/test_native_backend.py -x -v
"""
from __future__ import annotations


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
