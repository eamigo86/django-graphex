"""Per-schema registry isolation helpers for the top-level test suite.

A public DjangoObjectType now has one canonical model slot per Registry. Tests
that intentionally build distinct public schemas must use separate Registry
instances, and a schema's native output companion must resolve its relations
within that same pair. The isolated_pair helper supplies this explicit pair.

Some legacy builders use DjangoModelType or other APIs that select the default
Registry without a Meta.registry option. The per-test isolated_default_pair
scope gives those builders a fresh default pair and restores the process
singletons afterward; it never disables the duplicate-public-output guard.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from django_graphex.core.base import SchemaRegistries
from django_graphex.core.registry_compiler import NativeOutputRegistry


def isolated_pair(graphene_registry: Any) -> SchemaRegistries:
    """Return a DISTINCT "SchemaRegistries" pair for "graphene_registry".

    The pair pairs the module's own graphene "Registry" (the one the module's
    output types declare via "Meta.registry") with a FRESH
    "NativeOutputRegistry" and fresh compile caches. Both the graphene and the
    output member are therefore DISTINCT from the global default pair, so
    "DjangoGraphQLSchema(registries=isolated_pair(R))" engages the B5 lazy-fork
    and the module's types are forked pair-local instead of last-wins-stored in
    the global namespace.

    Args:
        graphene_registry: The module's graphene "Registry" instance, the same
            one used in each output type's "Meta.registry".

    Returns:
        A non-default "SchemaRegistries" pair ready to pass as "registries=".
    """
    return SchemaRegistries(
        graphene=graphene_registry,
        output=NativeOutputRegistry(),
        plain_object_cache={},
        union_cache={},
        interface_cache={},
        filter_input_cache={},
    )


@contextmanager
def isolated_default_pair() -> Iterator[None]:
    """Scope the hard-coded default pair to one generated CRUD test builder.

    DjangoModelType currently chooses the process-global Registry rather than
    accepting Meta.registry. Tests of that public builder need a fresh default
    pair for their own model graph, but must restore the module singletons and
    output entries so another test cannot inherit those registrations. The
    registration guard itself stays active inside this scope.

    Yields:
        Control while a temporary default Registry and native companion live.
    """
    import django_graphex.core.base as base_module
    import django_graphex.registry as registry_module
    from django_graphex.core.registry_compiler import NativeOutputRegistry
    from django_graphex.registry import Registry

    previous_registry = registry_module.registry
    previous_output = base_module._gdx_shared_output_registry
    entries = list(base_module._gdx_output_registry)
    registry_module.registry = Registry()
    base_module._gdx_shared_output_registry = NativeOutputRegistry()
    try:
        yield
    finally:
        registry_module.registry = previous_registry
        base_module._gdx_shared_output_registry = previous_output
        base_module._gdx_output_registry[:] = entries


@pytest.fixture
def isolated_default_registry_pair() -> Iterator[None]:
    """Give one test its own default output registry pair.

    Yields:
        Control while the test owns a temporary default registry pair.
    """
    with isolated_default_pair():
        yield
