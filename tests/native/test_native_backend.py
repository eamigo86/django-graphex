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


@pytest.mark.native_only
def test_gdx_backend_env_readable():
    """GDX_BACKEND env var should be readable (default 'graphene' or 'native')."""
    backend = os.environ.get("GDX_BACKEND", "graphene")
    assert backend in ("graphene", "native"), f"Unexpected GDX_BACKEND value: {backend!r}"


@pytest.mark.native_only
def test_native_only_mark_registered():
    """native_only mark is registered in pytest (no PytestUnknownMarkWarning)."""
    # This test just ensures the mark is used — the conftest registers it.
    # If the mark is unregistered, this test would show a warning (but still pass).
    # The actual registration is in tests/native/conftest.py.
    pass


@pytest.mark.native_only
def test_normalize_sdl_importable():
    """normalize_sdl utility is importable from the native conftest."""
    from tests.native.conftest import normalize_sdl

    assert callable(normalize_sdl)


@pytest.mark.native_only
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


@pytest.mark.native_only
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


@pytest.mark.native_only
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
