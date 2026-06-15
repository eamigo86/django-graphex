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

# S6b: graphene-vs-native SDL parity for seeds that build DjangoObjectType /
# DjangoListObjectType is RETIRED. Those types are re-parented off graphene, so
# the GRAPHENE subprocess (``_run_seed("graphene", ...)``) can no longer assemble
# a graphene.Schema from them ("Expected Graphene type, but received: <native
# type>") — the graphene SDL baseline no longer exists. Native SDL correctness
# for these seeds is still proven WITHOUT a graphene baseline by the matching
# ``*_native_subprocess_uses_native_assembly`` anti-tautology tests (which run the
# NATIVE subprocess only and assert the native assembly path produced the SDL) and
# by tests/native/test_native_schema_assembly.py. The graphene-baseline path is
# removed in S7 (graphene root/schema pruning).
_graphene_baseline_retired = pytest.mark.skip(
    reason="S6b: graphene SDL baseline retired — DjangoObjectType / "
    "DjangoListObjectType re-parented off graphene; graphene.Schema can no longer "
    "build from them. Native correctness proven by the native-only anti-tautology "
    "tests + test_native_schema_assembly.py. Graphene path pruned in S7."
)

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)


def _run_seed(backend: str, seed: str = "node") -> str:
    """Run the seed SDL printer in a subprocess with the given backend + seed."""
    env = dict(os.environ)
    env["GDX_BACKEND"] = backend
    env["GDX_SEED"] = seed
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
        f"seed subprocess (GDX_BACKEND={backend}, GDX_SEED={seed}) failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert proc.stdout.strip(), (
        f"seed subprocess (GDX_BACKEND={backend}, GDX_SEED={seed}) produced empty"
        f" SDL.\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


@_graphene_baseline_retired
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


# --------------------------------------------------------------------------- #
# WU4 — ArticleFilterInput cross-process SDL parity (binding minimum)          #
# --------------------------------------------------------------------------- #
def test_cross_process_filter_input_sdl_parity():
    """The ``<Model>FilterInput`` SDL is byte-equal between graphene and native.

    This is the WU4 binding gate ("ArticleFilterInput SDL identical to graphene").
    The filter input exercises scalar lookups, a choices enum, a nested relation
    filter input, and the recursive ``and`` / ``or`` / ``not`` combinators — the
    full A1-A6 surface.
    """
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene", seed="filter")
    native_sdl = _run_seed("native", seed="filter")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    assert graphene_norm == native_norm, (
        "Cross-process FilterInput SDL parity FAILED.\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_filter_seed_native_subprocess_uses_native_builder():
    """ANTI-TAUTOLOGY (cross-process): the native filter seed's SDL must come
    from the native graphql-core filter builder (gdx-bearing input type), not a
    graphene type smuggled in.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["GDX_SEED"] = "filter"
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
        "ANTI-TAUTOLOGY FAILURE: native filter seed did NOT use the native "
        f"filter builder.\nSTDERR:\n{proc.stderr}"
    )


# --------------------------------------------------------------------------- #
# Slices B + C — OUTPUT scalar NAME + nullability cross-process SDL parity     #
# (#1494 nullability + scalar-NAME parity sibling)                            #
# --------------------------------------------------------------------------- #
@_graphene_baseline_retired
def test_cross_process_scalar_node_sdl_parity():
    """The OUTPUT node type with Date/DateTime/Time/UUID/Decimal/JSON +
    non-null CharField is byte-equal between graphene and native.

    This is the Slice B + C binding deliverable: it proves the native output
    compiler renders the SAME scalar NAMES (``CustomDate`` / ``CustomDateTime``
    / ``CustomTime`` / ``UUID`` / ``Float`` for Decimal / ``JSONString``) and the
    SAME nullability (model scalars nullable, pk ``id: ID!``) as graphene-django.

    Before the fix this FAILS: native emits ``GdxDate!`` / ``GdxDecimal!`` /
    ``String!`` while graphene emits ``CustomDate`` / ``Float`` / ``String``.
    """
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene", seed="node_scalars")
    native_sdl = _run_seed("native", seed="node_scalars")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    assert graphene_norm == native_norm, (
        "Cross-process scalar-node SDL parity FAILED (Slices B+C).\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_scalar_node_seed_native_subprocess_uses_native_assembly():
    """ANTI-TAUTOLOGY: the native scalar-node seed's SDL must come from native
    assembly (the gdx-bearing canonical output type), not a graphene fallback.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["GDX_SEED"] = "node_scalars"
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
        "ANTI-TAUTOLOGY FAILURE: native scalar-node seed did NOT take the "
        f"native assembly path.\nSTDERR:\n{proc.stderr}"
    )


# --------------------------------------------------------------------------- #
# Slices D + E + FK-relation-nullability — OUTPUT field/relation parity        #
# (declared non-model fields; to-many list containers; required FK nullable)   #
# --------------------------------------------------------------------------- #
@_graphene_baseline_retired
def test_cross_process_relation_node_sdl_parity():
    """The OUTPUT node graph with a declared non-model field, a required FK, a
    nullable FK, M2M relations, and a reverse FK is byte-equal between graphene
    and native.

    This is the Slice D + E + FK-relation-nullability binding deliverable. It
    proves the native output compiler:

    * EMITS declared non-model fields (``extra: String`` / ``computed: Int``) —
      Slice D (native previously DROPPED them).
    * Renders to-many relations as the auto-derived ``<Model>ListType``
      results/totalCount container (``tags: TagListType`` /
      ``comments: CommentListType``) — Slice E (native previously emitted a
      plain ``[Node]`` list).
    * Renders a REQUIRED FK as NULLABLE (``author: SeedAuthorType``) — the
      FK-relation-output-nullability fix (native previously emitted
      ``SeedAuthorType!``).

    Before the fix this FAILS: native drops the declared fields, emits
    ``[Node]`` for to-many, and ``Type!`` for the required FK.
    """
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene", seed="relations")
    native_sdl = _run_seed("native", seed="relations")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    assert graphene_norm == native_norm, (
        "Cross-process relation-node SDL parity FAILED (Slices D+E+FK-null).\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_relation_node_seed_native_subprocess_uses_native_assembly():
    """ANTI-TAUTOLOGY: the native relation-node seed's SDL must come from native
    assembly (the gdx-bearing canonical output type), not a graphene fallback.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["GDX_SEED"] = "relations"
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
        "ANTI-TAUTOLOGY FAILURE: native relation-node seed did NOT take the "
        f"native assembly path.\nSTDERR:\n{proc.stderr}"
    )


# --------------------------------------------------------------------------- #
# WU10 — FULL tests/schema.py cross-process SDL parity (Phase-5 closing gate)  #
# --------------------------------------------------------------------------- #
@_graphene_baseline_retired
def test_cross_process_full_schema_sdl_parity():
    """The ENTIRE ``tests/schema.py`` schema SDL is byte-equal between graphene
    and native — the BINDING Phase-5 closing gate (D7).

    Two subprocesses build the full production test schema: under ``graphene``
    via the already-built ``tests.schema.schema``; under ``native`` via
    ``DjangoGraphQLSchema(query=Query, directives=all_directives)`` (native root
    compiler + native output registry + native filter builder + forwarded
    directives, bypassing graphene.Schema). After ``normalize_sdl`` (ordering
    only), the two SDL strings MUST be byte-identical — names, args, nullability,
    defaults, the full directive block, and the explicit-name scalar fields
    (``date`` / ``datetime`` / ``time``).

    This is the sweep that surfaced (and this WU reconciled) the directive-block
    divergence (native must forward ``directives=all_directives``) and the
    explicit ``name=`` field-name divergence (``date`` not ``date_``).
    """
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene", seed="full")
    native_sdl = _run_seed("native", seed="full")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    assert graphene_norm == native_norm, (
        "Cross-process FULL-schema SDL parity FAILED (WU10 closing gate).\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_full_schema_native_subprocess_uses_native_assembly():
    """ANTI-TAUTOLOGY (cross-process): the full-schema native SDL must come from
    native assembly (the gdx-bearing graphql-core query root with no graphene
    ``_meta``), not a graphene fallback. Guards the byte-parity assertion above
    against a silent graphene smuggle.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["GDX_SEED"] = "full"
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
        "ANTI-TAUTOLOGY FAILURE: full-schema native seed did NOT take the "
        f"native assembly path.\nSTDERR:\n{proc.stderr}"
    )


@_graphene_baseline_retired
def test_full_schema_parity_is_not_vacuous():
    """ANTI-TAUTOLOGY (substance): the full-schema SDL must be non-trivial.

    A parity test that compares two empty or one-line strings would pass
    vacuously. Assert the normalized graphene SDL has the substance we expect:
    the directive block (many ``directive @`` lines), the explicit-name scalar
    fields, the pagination container, and the filter input — so the byte-parity
    assertion is meaningful, not a comparison of degenerate output.
    """
    from tests.native.conftest import normalize_sdl

    graphene_norm = normalize_sdl(_run_seed("graphene", seed="full"))

    # Substance floor: the real schema is ~196 normalized lines.
    assert len(graphene_norm.splitlines()) > 120, (
        "Full-schema SDL is suspiciously short; parity may be vacuous.\n"
        f"{graphene_norm}"
    )
    # The full directive block must be present (the divergence WU10 reconciled).
    assert graphene_norm.count("directive @") >= 25, (
        "Full-schema SDL is missing the directive block; the directive-parity "
        "reconciliation would be untested."
    )
    # Explicit-name scalar fields render WITHOUT the trailing underscore.
    assert "date: CustomDate" in graphene_norm
    assert "datetime: CustomDateTime" in graphene_norm
    assert "time: CustomTime" in graphene_norm
    # Pagination container + filter input are present (B/A clusters).
    assert "TotalCount" in graphene_norm or "totalCount" in graphene_norm
    assert "Filter" in graphene_norm


# --------------------------------------------------------------------------- #
# types= forwarding — UNREFERENCED type cross-process SDL parity               #
# (graphene forwards types= to graphql-core; native must too or silently drop) #
# --------------------------------------------------------------------------- #
def test_cross_process_types_unreferenced_sdl_parity():
    """A schema built with ``types=[Unreferenced]`` is byte-equal between
    graphene and native — the ``types=`` forwarding parity gate.

    graphene's ``graphene.Schema`` forwards the ``types=`` kwarg (a list of
    graphene type CLASSES of UNREFERENCED types to force into the schema) to its
    underlying graphql-core ``GraphQLSchema``, so an unreferenced type appears in
    the printed SDL. The native ``DjangoGraphQLSchema`` assembly must forward
    ``types=`` identically (mapping each graphene class to its canonical native
    graphql-core type).

    Before the fix this FAILS: native drops the unreferenced type entirely (it
    does not forward ``types=`` to ``GraphQLSchema``), so the native SDL is
    MISSING ``SeedUnreferencedType`` while graphene's SDL contains it — a silent
    SDL-parity divergence. After the fix the unreferenced type appears in BOTH.
    """
    from tests.native.conftest import normalize_sdl

    graphene_sdl = _run_seed("graphene", seed="types_unreferenced")
    native_sdl = _run_seed("native", seed="types_unreferenced")

    graphene_norm = normalize_sdl(graphene_sdl)
    native_norm = normalize_sdl(native_sdl)

    # Substance floor: the unreferenced type MUST be present in graphene's SDL,
    # else the parity comparison would be vacuous.
    assert "SeedUnreferencedType" in graphene_norm, (
        "Substance check FAILED: graphene SDL is missing the unreferenced type; "
        "the types= parity comparison would be vacuous."
    )

    assert graphene_norm == native_norm, (
        "Cross-process types= forwarding SDL parity FAILED.\n"
        f"--- graphene (normalized) ---\n{graphene_norm}\n"
        f"--- native (normalized) ---\n{native_norm}\n"
    )


def test_types_unreferenced_seed_native_subprocess_uses_native_assembly():
    """ANTI-TAUTOLOGY (cross-process): the native types= seed's SDL must come
    from native assembly (gdx-bearing query root AND a gdx-bearing forwarded
    ``types=`` entry in the type_map), not a graphene fallback.
    """
    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["GDX_SEED"] = "types_unreferenced"
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
        "ANTI-TAUTOLOGY FAILURE: types= native seed did NOT take the native "
        f"assembly path (or the forwarded type is not the native instance).\n"
        f"STDERR:\n{proc.stderr}"
    )
