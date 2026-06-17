"""item-b B0 — ``SchemaRegistries`` container + ``default_schema_registries()``.

These tests pin the PLUMBING contract for schema-scoped registries (item-b):

- ``SchemaRegistries`` bundles the graphene ``Registry`` + the
  ``NativeOutputRegistry`` pair AND the four compile-cache namespaces.
- ``default_schema_registries()`` returns a process-wide SINGLETON whose members
  ARE the EXISTING global instances and EXISTING module-level cache dicts (bound
  by identity, NOT copied), so every compile entrypoint that defaults to it keeps
  the single-namespace, byte-identical behavior.
- A freshly constructed non-default ``SchemaRegistries`` is independent (its caches
  are NOT the global module-level dicts) — the seam later slices (B3-B5) use to
  fork a per-schema namespace.

Run: .venv/bin/python -m pytest -q \
    tests/native/test_schema_registries.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()



def test_default_pair_returns_singleton():
    """``default_schema_registries()`` returns the SAME instance every call."""
    from django_graphex.native.base import default_schema_registries

    first = default_schema_registries()
    second = default_schema_registries()
    assert first is second


def test_default_pair_members_are_global_registries():
    """The default pair's two registries ARE the existing global instances."""
    from django_graphex.native.base import (
        default_schema_registries,
        get_shared_output_registry,
    )
    from django_graphex.registry import get_global_registry

    pair = default_schema_registries()
    assert pair.graphene is get_global_registry()
    assert pair.output is get_shared_output_registry()


def test_default_pair_caches_are_module_level_dicts():
    """Each cache field IS the existing module-level dict (identity, not a copy).

    This is the BYTE-IDENTICAL guarantee for B2: defaulting to the global pair
    reads/writes the same single-namespace caches the compiler always used.
    """
    from django_graphex.filtering.native_schema import _NATIVE_INPUT_CACHE
    from django_graphex.native.base import default_schema_registries
    from django_graphex.native.polymorphic_compiler import (
        _INTERFACE_TYPE_CACHE,
        _UNION_TYPE_CACHE,
    )
    from django_graphex.native.schema_compiler import _PLAIN_OBJECT_TYPE_CACHE

    pair = default_schema_registries()
    assert pair.plain_object_cache is _PLAIN_OBJECT_TYPE_CACHE
    assert pair.union_cache is _UNION_TYPE_CACHE
    assert pair.interface_cache is _INTERFACE_TYPE_CACHE
    assert pair.filter_input_cache is _NATIVE_INPUT_CACHE


def test_default_pair_write_through_is_visible_on_module_cache():
    """A write via the default pair's cache is observable on the module dict.

    Confirms the identity binding is live (not a snapshot): the default compile
    path and direct module-cache reads share ONE namespace.
    """
    from django_graphex.native.base import default_schema_registries
    from django_graphex.native.schema_compiler import _PLAIN_OBJECT_TYPE_CACHE

    pair = default_schema_registries()
    sentinel = object()
    key = ("__b0_probe__",)
    try:
        pair.plain_object_cache[key] = sentinel
        assert _PLAIN_OBJECT_TYPE_CACHE.get(key) is sentinel
    finally:
        pair.plain_object_cache.pop(key, None)


def test_non_default_pair_has_independent_caches():
    """A fresh ``SchemaRegistries`` is NOT bound to the global module dicts.

    This is the fork seam (B3-B5): a distinct pair gets its own cache namespace,
    so compiled types do not leak into the global single-namespace caches.
    """
    from django_graphex.filtering.native_schema import _NATIVE_INPUT_CACHE
    from django_graphex.native.base import SchemaRegistries
    from django_graphex.native.polymorphic_compiler import (
        _INTERFACE_TYPE_CACHE,
        _UNION_TYPE_CACHE,
    )
    from django_graphex.native.schema_compiler import _PLAIN_OBJECT_TYPE_CACHE

    forked = SchemaRegistries(
        graphene=object(),
        output=object(),
        plain_object_cache={},
        union_cache={},
        interface_cache={},
        filter_input_cache={},
    )
    assert forked.plain_object_cache is not _PLAIN_OBJECT_TYPE_CACHE
    assert forked.union_cache is not _UNION_TYPE_CACHE
    assert forked.interface_cache is not _INTERFACE_TYPE_CACHE
    assert forked.filter_input_cache is not _NATIVE_INPUT_CACHE


def test_resolve_registries_defaults_to_global_pair():
    """Each compiler's ``_resolve_registries(None)`` yields the default pair.

    Pins the B1 plumbing contract: a ``None`` argument at any compile entrypoint
    collapses to the SAME global pair, so no caller passing the default diverges.
    """
    from django_graphex.native import polymorphic_compiler, schema_compiler
    from django_graphex.native.base import default_schema_registries

    default = default_schema_registries()
    assert schema_compiler._resolve_registries(None) is default
    assert polymorphic_compiler._resolve_registries(None) is default

    # An explicit pair passes through untouched.
    assert schema_compiler._resolve_registries(default) is default
    assert polymorphic_compiler._resolve_registries(default) is default
