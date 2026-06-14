"""WU2 (reworked): GENUINE cross-process SDL parity seed gate (D7).

Spawns TWO subprocesses — one with ``GDX_BACKEND=graphene`` and one with
``GDX_BACKEND=native`` — each building the SAME minimal seed schema (a Query
with ONE ``DjangoObjectField`` on the real ``Category`` model) and printing its
SDL via ``graphql.utilities.print_schema``. After ``normalize_sdl`` (ordering
only), the two SDL strings MUST be byte-equal.

This is NOT a tautology: the native subprocess assembles the schema through the
native root compiler (proven by the in-process anti-tautology tests in
``test_native_root_compiler.py`` / ``test_native_schema_assembly.py``); the
graphene subprocess uses graphene.Schema. Both render the same node SDL.

This test runs under either backend's pytest process (it spawns its own
subprocesses with the backend flag set explicitly), but is marked native_only
so it lives with the native suite.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.native_only

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)


def _run_seed(backend: str) -> str:
    """Run the seed SDL printer in a subprocess with the given backend."""
    env = dict(os.environ)
    env["GDX_BACKEND"] = backend
    # Ensure the subprocess can import the `tests` package and django_graphex.
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "tests.native._sdl_parity_seed"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"seed subprocess (GDX_BACKEND={backend}) failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert proc.stdout.strip(), (
        f"seed subprocess (GDX_BACKEND={backend}) produced empty SDL.\n"
        f"STDERR:\n{proc.stderr}"
    )
    return proc.stdout


def test_cross_process_sdl_parity_seed():
    """The seed schema SDL is byte-equal between graphene and native backends."""
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene")
    native_sdl = _run_seed("native")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    assert graphene_norm == native_norm, (
        "Cross-process SDL parity FAILED (seed).\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_seed_native_subprocess_uses_native_assembly():
    """ANTI-TAUTOLOGY (cross-process): the native subprocess's SDL must come
    from native assembly, not a graphene fallback.

    The seed printer prints a sentinel marker on stderr identifying which
    assembly path produced the SDL; assert the native path was taken.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["GDX_SEED_TRACE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.native._sdl_parity_seed"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "GDX_SEED_PATH=native" in proc.stderr, (
        "ANTI-TAUTOLOGY FAILURE: native subprocess did NOT take the native "
        f"assembly path.\nSTDERR:\n{proc.stderr}"
    )
