# -*- coding: utf-8 -*-
"""A "DjangoModelType" mutation field must be re-forkable into a forked schema.

"schema_compiler._maybe_refork_mutation_field" re-compiles a native mutation
field's payload against the schema's own "SchemaRegistries" pair, so a schema
built with the documented "registries=" fork gets its OWN payload instead of
the one pinned at class-definition time. It keys that entirely off
"extensions['gdx_mutation_source']" -- the key "DjangoModelMutation" stamps
(mutation.py) and "DjangoModelType" did not, so its mutation fields silently
opted out of the re-fork and every forked schema shared the class-def payload.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from django_graphex.core import ObjectType
from django_graphex.core.descriptors import field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import NonEditableTag


@pytest.fixture(autouse=True)
def _isolate_global_registries() -> Iterator[None]:
    """Snapshot and restore the process-global output registries per test.

    This module declares a throwaway "DjangoObjectType" in its own graphene
    registry. A class definition still appends to the global
    "_gdx_output_registry" and writes the shared output registry (last wins),
    which would leak into later tests' default-pair builds. Same hygiene as
    "tests/core/test_audit_forked_pair_and_field_names.py".

    Yields:
        None, once, with the global registries restored afterwards.
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        get_shared_output_registry,
    )

    shared = get_shared_output_registry()
    entries_before = list(_gdx_output_registry)
    compiled_before = dict(shared._compiled)
    try:
        yield
    finally:
        _gdx_output_registry[:] = entries_before
        shared._compiled.clear()
        shared._compiled.update(compiled_before)


class TagModelType(DjangoModelType):
    """A batteries-included type whose create mutation is mounted twice.

    Once in a default-pair schema and once in a forked one, so the two
    payload instances can be compared.
    """

    class Meta:
        """Bind the type to "NonEditableTag".

        A "DjangoModelType" always uses the global registry, so there is no
        registry option to set here.
        """

        model = NonEditableTag


_R = Registry()


class ForkTagType(DjangoObjectType):
    """A type in its OWN registry, so the schema pair actually forks.

    Without at least one entry belonging to the pair's registry, nothing is
    forked and the re-fork branch is never reached.
    """

    class Meta:
        """Bind the type to "NonEditableTag" on the module registry.

        The projection keeps the forked type small and collision-free.
        """

        name = "ForkTagType"
        model = NonEditableTag
        registry = _R
        only_fields = ("id", "name")


class _Query(ObjectType):
    """Root query referencing the forked registry's type.

    A query root is mandatory, and this one also pulls the forked type in.
    """

    tag = field(ForkTagType)


class _Mutation(ObjectType):
    """Root mutation mounting the "DjangoModelType" create field.

    The field under test: its payload is what has to be re-forked.
    """

    tag_create = TagModelType.CreateField()


def _payload_of(schema: DjangoGraphQLSchema) -> Any:
    """Return the compiled mutation payload object type of "schema".

    Args:
        schema: A built "DjangoGraphQLSchema".

    Returns:
        The "GraphQLObjectType" the create mutation returns.
    """
    return schema.graphql_schema.type_map["TagModelType"]


def test_the_mutation_field_records_its_source_class() -> None:
    """The field carries the key the re-fork compiler looks up.

    The shape is the one "mutation.py" stamps and
    "schema_compiler._maybe_refork_mutation_field" reads: the MUTATION SOURCE
    CLASS itself, which it feeds to "_compile_plain_object_type".
    """
    extensions = TagModelType.CreateField().extensions or {}

    assert extensions.get("gdx_mutation_source") is TagModelType


def test_a_forked_schema_gets_its_own_mutation_payload() -> None:
    """The payload is re-compiled per pair instead of shared verbatim.

    Without the source-class key the re-fork bails out and both schemas hand
    back the single payload instance built at class-definition time.
    """
    default_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)
    forked_schema = DjangoGraphQLSchema(
        query=_Query, mutation=_Mutation, registries=isolated_pair(_R)
    )

    assert _payload_of(default_schema) is not _payload_of(forked_schema)


def test_the_re_forked_payload_keeps_its_wire_shape() -> None:
    """Re-forking must not change the payload's fields, args or resolver.

    The re-fork replaces only the payload type; everything else on the field
    must survive verbatim.
    """
    default_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)
    forked_schema = DjangoGraphQLSchema(
        query=_Query, mutation=_Mutation, registries=isolated_pair(_R)
    )

    default_field = default_schema.graphql_schema.mutation_type.fields["tagCreate"]
    forked_field = forked_schema.graphql_schema.mutation_type.fields["tagCreate"]

    assert list(_payload_of(forked_schema).fields) == list(
        _payload_of(default_schema).fields
    )
    assert list(forked_field.args) == list(default_field.args)
    assert forked_field.resolve is default_field.resolve
    assert (forked_field.extensions or {}).get("gdx_required_perms") == (
        default_field.extensions or {}
    ).get("gdx_required_perms")
