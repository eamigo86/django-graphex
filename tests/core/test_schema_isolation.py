"""Regression tests for the test suite's temporary default registry pair."""

from __future__ import annotations

import pytest

import django_graphex.core.base as base_module
import django_graphex.registry as registry_module
from tests._schema_isolation import isolated_default_pair


@pytest.mark.parametrize("cache_initialized", [False, True])
def test_isolated_default_pair_restores_prior_cache(
    monkeypatch: pytest.MonkeyPatch, cache_initialized: bool
) -> None:
    """Restore the exact prior cache after using temporary global registries.

    Args:
        monkeypatch: Restores the original cache after this test.
        cache_initialized: Selects an absent or already-created prior pair.
    """
    monkeypatch.setattr(base_module, "_default_schema_registries", None)
    previous_pair = (
        base_module.default_schema_registries() if cache_initialized else None
    )
    previous_registry = registry_module.registry
    previous_output = base_module._gdx_shared_output_registry
    previous_entries = list(base_module._gdx_output_registry)

    with isolated_default_pair():
        temporary_pair = base_module.default_schema_registries()
        assert temporary_pair is not previous_pair
        assert temporary_pair.graphene is registry_module.registry
        assert temporary_pair.output is base_module._gdx_shared_output_registry

    assert base_module._default_schema_registries is previous_pair
    assert registry_module.registry is previous_registry
    assert base_module._gdx_shared_output_registry is previous_output
    assert base_module._gdx_output_registry == previous_entries


def test_isolated_default_pair_restores_after_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore an absent cache and the other globals when a scope raises.

    Args:
        monkeypatch: Restores the original cache after this test.
    """
    monkeypatch.setattr(base_module, "_default_schema_registries", None)
    previous_registry = registry_module.registry
    previous_output = base_module._gdx_shared_output_registry
    previous_entries = list(base_module._gdx_output_registry)

    with pytest.raises(ValueError, match="temporary scope failed"):
        with isolated_default_pair():
            temporary_pair = base_module.default_schema_registries()
            assert temporary_pair.graphene is registry_module.registry
            raise ValueError("temporary scope failed")

    assert base_module._default_schema_registries is None
    assert registry_module.registry is previous_registry
    assert base_module._gdx_shared_output_registry is previous_output
    assert base_module._gdx_output_registry == previous_entries


def test_isolated_default_pair_restores_each_nested_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the outer temporary pair live after an inner scope exits.

    Args:
        monkeypatch: Restores the original cache after this test.
    """
    monkeypatch.setattr(base_module, "_default_schema_registries", None)
    previous_registry = registry_module.registry
    previous_output = base_module._gdx_shared_output_registry
    previous_entries = list(base_module._gdx_output_registry)

    with isolated_default_pair():
        outer_pair = base_module.default_schema_registries()
        outer_registry = registry_module.registry
        outer_output = base_module._gdx_shared_output_registry
        outer_entries = list(base_module._gdx_output_registry)

        with isolated_default_pair():
            inner_pair = base_module.default_schema_registries()
            assert inner_pair is not outer_pair
            assert inner_pair.graphene is registry_module.registry
            assert inner_pair.output is base_module._gdx_shared_output_registry

        assert base_module._default_schema_registries is outer_pair
        assert registry_module.registry is outer_registry
        assert base_module._gdx_shared_output_registry is outer_output
        assert base_module._gdx_output_registry == outer_entries

    assert base_module._default_schema_registries is None
    assert registry_module.registry is previous_registry
    assert base_module._gdx_shared_output_registry is previous_output
    assert base_module._gdx_output_registry == previous_entries
