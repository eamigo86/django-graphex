"""R6 coverage — behavioral tests for "native.registry_compiler" uncovered branches.

The mutual-recursion / self-ref / BuildError happy paths are covered by
"test_registry_compiler.py"; the fork-pair machinery by the schema-assembly
tests. This file pins the remaining cleanly-unit-testable branches by asserting
ACTUAL behaviour:

- "_compile_one": returns an already-compiled type immediately (idempotent);
  returns the in-progress stub during a cycle.
- "_make_fields_thunk": a related model that is NEITHER compiled NOR in-progress
  is DROPPED (rank-6) with a logged warning — never emitted as a String.
- "compile_all" Phase 1: a class exposing "model_rebuild" has it invoked, and a
  "model_rebuild" that raises is swallowed (the type still compiles).
- "compile_all_outputs": returns early when the global output registry is empty.

Run: .venv/bin/python -m pytest \
    tests/core/test_registry_compiler_coverage.py -q -o addopts=""
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import logging  # noqa: E402

import pytest  # noqa: E402
from graphql import GraphQLObjectType  # noqa: E402

# ---------------------------------------------------------------------------
# _compile_one — already-compiled short-circuit + in-progress stub return
# ---------------------------------------------------------------------------


def test_compile_one_returns_already_compiled_type() -> None:
    """Ships broken if "_compile_one" rebuilds a type instead of returning the
    already-compiled instance untouched (idempotency regression).
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        _compile_one,
        _reset_in_progress,
    )

    _reset_in_progress()
    registry = NativeOutputRegistry()

    class ModelPre:
        pass

    sentinel = GraphQLObjectType("Pre", fields=lambda: {})
    registry.set_compiled(ModelPre, sentinel)

    result = _compile_one("Pre", ModelPre, [], registry)
    # Identity: the exact pre-registered instance is returned, untouched.
    assert result is sentinel


def test_compile_one_returns_in_progress_stub_during_cycle() -> None:
    """Ships broken if "_compile_one" fails to return the in-progress stub for
    a model while a recursive compilation cycle is still open.
    """
    from django_graphex.core import registry_compiler
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        _compile_one,
        _reset_in_progress,
    )

    _reset_in_progress()
    registry = NativeOutputRegistry()

    class ModelCyc:
        pass

    stub = GraphQLObjectType("Cyc", fields=lambda: {})
    registry_compiler._in_progress[id(ModelCyc)] = stub
    try:
        result = _compile_one("Cyc", ModelCyc, [], registry)
        assert result is stub
    finally:
        _reset_in_progress()


# ---------------------------------------------------------------------------
# _make_fields_thunk — unregistered related model is DROPPED (rank-6), warned
# ---------------------------------------------------------------------------


def test_unregistered_related_model_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ships broken if a related model that is never compiled or in-progress
    stops being dropped from the field set, or the drop stops being logged
    with a warning naming both the field and the target (rank-6 contract).

    Args:
        caplog: Captures log records so the warning text can be asserted.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class Owner:
        pass

    class Ghost:  # referenced but NEVER registered → never compiled/in-progress
        pass

    # Owner references Ghost, but only Owner is registered.
    registry.register("Owner", Owner, related_models=[Ghost])

    with caplog.at_level(
        logging.WARNING, logger="django_graphex.core.registry_compiler"
    ):
        compile_all(registry)

    compiled = registry.get_compiled(Owner)
    assert isinstance(compiled, GraphQLObjectType)
    # The ghost relation field was DROPPED — not emitted as a String stand-in.
    assert "ghost" not in compiled.fields
    assert compiled.fields == {}

    # The warning is diagnosable: it names the field and the unregistered target.
    msg = caplog.text
    assert "ghost" in msg
    assert "Ghost" in msg


def test_registered_related_model_resolves_to_its_compiled_type() -> None:
    """Ships broken if a related model that IS registered fails to resolve to
    its compiled instance on the parent's relation field.

    Contrast partner to the drop test: confirms the non-dropped arm wires the
    relation field to the real type (loop-capture-safe).
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    registry = NativeOutputRegistry()

    class Parent:
        pass

    class Child:
        pass

    registry.register("Parent", Parent, related_models=[Child])
    registry.register("Child", Child)

    compile_all(registry)

    parent = registry.get_compiled(Parent)
    child = registry.get_compiled(Child)
    assert "child" in parent.fields
    assert parent.fields["child"].type is child


# ---------------------------------------------------------------------------
# compile_all Phase 1 — model_rebuild invoked; a raising model_rebuild swallowed
# ---------------------------------------------------------------------------


def test_compile_all_invokes_model_rebuild_when_present() -> None:
    """Ships broken if a class exposing "model_rebuild" stops having it
    invoked exactly once during compile_all Phase 1.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    calls: list[str] = []

    class HasRebuild:
        @classmethod
        def model_rebuild(cls):
            calls.append("rebuilt")

    registry = NativeOutputRegistry()
    registry.register("HasRebuild", HasRebuild)

    compile_all(registry)

    assert calls == ["rebuilt"], "model_rebuild must be invoked exactly once"
    assert isinstance(registry.get_compiled(HasRebuild), GraphQLObjectType)


def test_compile_all_swallows_model_rebuild_exception() -> None:
    """Ships broken if a raising "model_rebuild" propagates instead of being
    swallowed by compile_all Phase 1, which would abort compilation.

    Raises:
        RuntimeError: Raised by the local "RebuildBoom.model_rebuild" fixture
            itself; compile_all must swallow it internally so it never
            reaches this test.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
    )

    class RebuildBoom:
        @classmethod
        def model_rebuild(cls):
            raise RuntimeError("boom — must be swallowed by Phase 1")

    registry = NativeOutputRegistry()
    registry.register("RebuildBoom", RebuildBoom)

    # Must NOT propagate the RuntimeError.
    compile_all(registry)

    assert isinstance(registry.get_compiled(RebuildBoom), GraphQLObjectType)


# ---------------------------------------------------------------------------
# compile_all_outputs — empty global registry returns early
# ---------------------------------------------------------------------------


def test_compile_all_outputs_returns_early_when_registry_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ships broken if compile_all_outputs stops being a no-op when the
    global output registry is empty.

    Patches the global "_gdx_output_registry" to empty so the early-return arm
    runs without touching the real app-ready state.

    Args:
        monkeypatch: Used to force the global output registry to be empty.
    """
    from django_graphex.core import base, registry_compiler

    monkeypatch.setattr(base, "_gdx_output_registry", [], raising=False)

    # Must return without raising and without compiling anything.
    assert registry_compiler.compile_all_outputs() is None
