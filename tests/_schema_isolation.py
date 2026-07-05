"""Per-schema registry isolation helpers for the top-level test suite.

The native compile path historically resolved relation / list-container /
optimizer types against PROCESS-GLOBAL registries (a single graphene
"Registry" + the shared "NativeOutputRegistry", keyed by model, last-wins).
When two test MODULES define output types over the SAME model with the SAME
type name (e.g. "PostListType", "ArticleGenericType") and are collected
together, the global last-wins slot makes two distinct same-named
"GraphQLObjectType" instances reachable in one schema, and graphql-core raises
"Schema must contain uniquely named types" at build time (issue #1590).

item-b (B0-B5) gave "DjangoGraphQLSchema" a "registries=" kwarg + a
lazy-fork: a schema built with a DISTINCT "SchemaRegistries" pair (its
graphene "Registry" AND "NativeOutputRegistry" both distinct from the
global ones) forks PAIR-LOCAL output instances, so two schemas over the same
model coexist with no collision and no cross-schema leak.

This module is the test-side glue: declare a module-scoped graphene "Registry",
tag each output type's "Meta.registry" with it, then build the schema with
"isolated_pair(<that registry>)". The pair carries the module's graphene
registry plus a FRESH "NativeOutputRegistry" and fresh compile caches, which
triggers the fork and keeps the module's types out of the shared global
namespace.
"""

from __future__ import annotations

from typing import Any

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
