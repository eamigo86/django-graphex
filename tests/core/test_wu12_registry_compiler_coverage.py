"""WU12 Phase-5 carry-forward coverage — core/registry_compiler.py.

Lifts "core/registry_compiler.py" branch coverage to >=95% by exercising the
paths the full "tests/core/" suite did not reach: the in-progress-stub return
of "_get_related_type", the "compile_all" "compiled is None" BuildError, the
"compile_all_outputs" empty-registry early return, the no-"_meta" BuildError,
the canonical-None fallback, and the missing-gdx BuildError on per-class outputs.

Each test asserts the real BuildError message / stub identity — not bare
execution.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest  # noqa: E402
from graphql import GraphQLObjectType  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch

# ---------------------------------------------------------------------------
# _get_related_type — returns an in-progress stub (line 207-209)
# ---------------------------------------------------------------------------


def test_related_type_resolves_to_in_progress_stub() -> None:
    """Ships broken if a relation whose target is in "_in_progress" (not yet
    compiled) stops resolving to the stub at thunk-eval time, falling back to
    GraphQLString instead.
    """
    from django_graphex.core.registry_compiler import (
        NativeOutputRegistry,
        _compile_one,
        _in_progress,
        _reset_in_progress,
    )

    _reset_in_progress()

    class ModelA:
        pass

    class ModelB:
        pass

    registry = NativeOutputRegistry()
    # Compile A first; its thunk references B. Place a B stub in _in_progress
    # BEFORE evaluating A's fields so the relation resolves to the stub (209).
    compiled_a = _compile_one("NodeA", ModelA, [ModelB], registry)

    b_stub = GraphQLObjectType("NodeB", fields=lambda: {})
    _in_progress[id(ModelB)] = b_stub
    try:
        fields = compiled_a.fields  # forces the thunk -> _get_related_type(B)
        # B is NOT a registered entry -> field name derives from class name
        # ("ModelB" -> "modelB"). B is NOT compiled but IS in _in_progress, so the
        # relation thunk returns the stub (line 209), not the GraphQLString fallback.
        assert fields["modelB"].type is b_stub
    finally:
        _reset_in_progress()


# ---------------------------------------------------------------------------
# compile_all — BuildError when a registered type never compiled (line 281-282)
# ---------------------------------------------------------------------------


def test_compile_all_build_error_when_compiled_missing() -> None:
    """Ships broken if "compile_all" stops raising BuildError naming a type
    that produced no compiled instance (the "compiled is None" guard).
    """
    from django_graphex.core.registry_compiler import (
        BuildError,
        NativeOutputRegistry,
        compile_all,
    )

    class GhostModel:
        pass

    class _SabotageRegistry(NativeOutputRegistry):
        # Drop every set_compiled so Phase 3 sees compiled is None.
        def set_compiled(self, model_cls: type, gql_type: GraphQLObjectType) -> None:  # noqa: D401
            return None

    registry = _SabotageRegistry()
    registry.register("GhostNode", GhostModel)

    with pytest.raises(BuildError) as exc:
        compile_all(registry)
    assert "GhostNode" in str(exc.value)
    assert "failed to compile" in str(exc.value)


# ---------------------------------------------------------------------------
# compile_all_outputs — empty registry early return (line 347-348)
# ---------------------------------------------------------------------------


def test_compile_all_outputs_empty_registry_returns_early(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ships broken if "compile_all_outputs" stops returning immediately when
    the global registry is empty.

    Args:
        monkeypatch: Patches the global output registry to an empty list.
    """
    import django_graphex.core.base as base_mod
    from django_graphex.core.registry_compiler import compile_all_outputs

    monkeypatch.setattr(base_mod, "_gdx_output_registry", [])
    # Must not raise and must short-circuit — nothing to compile.
    assert compile_all_outputs() is None


# ---------------------------------------------------------------------------
# _class_instance — BuildError when a class has no graphql_output_type (359)
# ---------------------------------------------------------------------------


def test_compile_all_outputs_build_error_when_no_meta_instance(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ships broken if "compile_all_outputs" stops raising BuildError when a
    registered class has no "_meta.graphql_output_type" (the "_class_instance"
    guard).

    Args:
        monkeypatch: Patches the global output registry with a bad entry.
    """
    from types import SimpleNamespace

    import django_graphex.core.base as base_mod
    from django_graphex.core.registry_compiler import (
        BuildError,
        compile_all_outputs,
    )

    class _NoInstanceModel:
        __name__ = "NoInstanceModel"

    class _NoInstanceCls:
        _meta = SimpleNamespace(graphql_output_type=None)

    entry = SimpleNamespace(
        cls=_NoInstanceCls, model=_NoInstanceModel, gql_name="NoInstance"
    )
    monkeypatch.setattr(base_mod, "_gdx_output_registry", [entry])

    with pytest.raises(BuildError) as exc:
        compile_all_outputs()
    assert "NoInstance" in str(exc.value)
    assert "no compiled" in str(exc.value)


# ---------------------------------------------------------------------------
# compile_all_outputs — canonical-None fallback to class instance (377-378)
# ---------------------------------------------------------------------------


def test_compile_all_outputs_canonical_none_falls_back_to_class_instance(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ships broken if, when the shared registry has no canonical for the
    model, "compile_all_outputs" stops falling back to the class' own
    instance and registering it.

    Args:
        monkeypatch: Patches the global output registry and the shared output
            registry lookup.
    """
    from types import SimpleNamespace

    import django_graphex.core.base as base_mod
    from django_graphex.core.bridge import GdxPayload
    from django_graphex.core.ir import GdxMeta
    from django_graphex.core.registry_compiler import compile_all_outputs

    class _FallbackModel:
        __name__ = "FallbackModel"

    own_instance = GraphQLObjectType(
        "FallbackNode",
        fields=lambda: {
            "x": __import__("graphql").GraphQLField(__import__("graphql").GraphQLString)
        },
        extensions={"gdx": GdxPayload(GdxMeta(name="FallbackNode"))},
    )

    class _FallbackCls:
        _meta = SimpleNamespace(graphql_output_type=own_instance)

    entry = SimpleNamespace(
        cls=_FallbackCls, model=_FallbackModel, gql_name="FallbackNode"
    )

    # A shared registry that NEVER has the model canonical (returns None) so the
    # fallback branch fires; it records the set_compiled call.
    recorded = {}

    class _SharedReg:
        def get_compiled(self, model):  # noqa: D401
            return None

        def set_compiled(self, model, inst):  # noqa: D401
            recorded[model] = inst

    monkeypatch.setattr(base_mod, "_gdx_output_registry", [entry])
    monkeypatch.setattr(base_mod, "get_shared_output_registry", lambda: _SharedReg())

    compile_all_outputs()
    # The class' own instance was registered as the fallback canonical (377-378).
    assert recorded.get(_FallbackModel) is own_instance


# ---------------------------------------------------------------------------
# compile_all_outputs — BuildError when per-class instance lacks gdx (line 396)
# ---------------------------------------------------------------------------


def test_compile_all_outputs_build_error_when_instance_lacks_gdx(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ships broken if "compile_all_outputs" stops raising BuildError when a
    per-class instance is missing "extensions['gdx']".

    Args:
        monkeypatch: Patches the global output registry and the shared output
            registry lookup.
    """
    from types import SimpleNamespace

    from graphql import GraphQLField, GraphQLString

    import django_graphex.core.base as base_mod
    from django_graphex.core.registry_compiler import (
        BuildError,
        compile_all_outputs,
    )

    class _NoGdxModel:
        __name__ = "NoGdxModel"

    # A real GraphQLObjectType WITHOUT extensions['gdx'].
    no_gdx_instance = GraphQLObjectType(
        "NoGdxNode", fields=lambda: {"x": GraphQLField(GraphQLString)}
    )

    class _NoGdxCls:
        _meta = SimpleNamespace(graphql_output_type=no_gdx_instance)

    entry = SimpleNamespace(cls=_NoGdxCls, model=_NoGdxModel, gql_name="NoGdxNode")

    class _SharedReg:
        def get_compiled(self, model):  # noqa: D401
            return no_gdx_instance

        def set_compiled(self, model, inst):  # noqa: D401, ARG002
            return None

    monkeypatch.setattr(base_mod, "_gdx_output_registry", [entry])
    monkeypatch.setattr(base_mod, "get_shared_output_registry", lambda: _SharedReg())

    with pytest.raises(BuildError) as exc:
        compile_all_outputs()
    assert "NoGdxNode" in str(exc.value)
    assert "extensions['gdx']" in str(exc.value)
