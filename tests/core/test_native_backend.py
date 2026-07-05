"""Tests for the native test harness utilities.

Verifies that the "normalize_sdl" utility is importable and functional.

Run with: .venv/bin/python -m pytest tests/core/test_native_backend.py -x -v
"""

from __future__ import annotations


def test_normalize_sdl_importable() -> None:
    """Assert that "normalize_sdl" is importable from the native conftest.

    If this fails, the SDL normalization helper would be unavailable to
    the tests that diff generated schemas.
    """
    from tests.core.conftest import normalize_sdl

    assert callable(normalize_sdl)


def test_normalize_sdl_sorts_types() -> None:
    """Assert that "normalize_sdl" sorts type blocks alphabetically.

    If this fails, SDL diffing between backends would be sensitive to
    type declaration order instead of content.
    """
    from tests.core.conftest import normalize_sdl

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


def test_normalize_sdl_strips_descriptions() -> None:
    """Assert that "normalize_sdl" strips description strings from SDL.

    If this fails, cosmetic description text would leak into SDL
    comparisons, causing false diffs between otherwise-equal schemas.
    """
    from tests.core.conftest import normalize_sdl

    sdl = '''
"""A description of MyType."""
type MyType {
  """field description"""
  name: String
}
'''
    normalized = normalize_sdl(sdl)
    assert '"""' not in normalized, "normalize_sdl should strip descriptions"


def test_normalize_sdl_idempotent() -> None:
    """Assert that "normalize_sdl" is idempotent — applying it twice gives the same result.

    If this fails, repeated normalization passes could keep changing the
    output, making stable SDL comparisons impossible.
    """
    from tests.core.conftest import normalize_sdl

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


def test_normalize_sdl_input_type_structure_parity() -> None:
    """Assert that input type SDL structure is consistent between normalize_sdl calls.

    Verifies that "normalize_sdl" produces stable field ordering for input
    types, enabling reliable diff comparisons between graphene and native
    backends.

    If this fails, semantically identical input types with differently
    ordered fields would compare unequal after normalization.
    """
    from tests.core.conftest import normalize_sdl

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
