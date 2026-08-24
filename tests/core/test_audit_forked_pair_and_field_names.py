"""Regression tests for three post-2.1.0 native-compiler defects.

Each test is built from a reproduction against the published tree:

1. A WRAPPED native root field ("field(NativeList(SomeType))" /
   "field(NativeNonNull(SomeType))") fell through to the scalar arm of
   "compile_native_root", which did NOT thread the schema's
   "SchemaRegistries" pair. The inner django-graphex output type therefore
   resolved against the process-global DEFAULT pair, so a schema built with
   "registries=" raised "BuildError: assert_schema_pair_isolation" -- a wrapped
   native root field made a per-schema registry pair unbuildable.
2. "_fork_output_class" copied the class-def "interfaces" list, which was
   compiled against the DEFAULT interface cache, while a root
   "field(SomeInterface)" compiled a fresh one from the pair's cache. Two
   distinct same-named "GraphQLInterfaceType" then reached one schema ->
   "TypeError: Schema must contain uniquely named types".
3. An explicit "name=" on a declared field was honoured on the ROOT only:
   a plain "ObjectType" body (mutation payloads, nested types) camelCased the
   ATTRIBUTE name instead, so "date_ = field(GraphQLString, name='date')"
   leaked the keyword-dodging trailing underscore onto the wire.

Run: .venv/bin/python -m pytest -q \
    tests/core/test_audit_forked_pair_and_field_names.py
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from graphql import GraphQLString, print_schema

from django_graphex.core import ObjectType as NativeRoot
from django_graphex.core.descriptors import NativeList, NativeNonNull, field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoInterfaceType, DjangoObjectType
from tests.models import Author


@pytest.fixture(autouse=True)
def _isolate_global_registries() -> Iterator[None]:
    """Snapshot and restore the process-global output registries per test.

    These tests declare THROWAWAY "DjangoObjectType" subclasses in custom
    graphene registries. A class definition still appends to the global
    "_gdx_output_registry" and writes the shared output registry (last wins),
    which would leak into LATER tests' default-pair schema builds and cause
    spurious duplicate-name collisions. Same hygiene as
    "tests/core/test_schema_lazy_fork.py".

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


def _forked_pair(graphene_registry: Registry) -> Any:
    """Build a NON-default "SchemaRegistries" pair over a graphene registry.

    A distinct pair (fresh output registry plus fresh compile caches) is what
    makes "DjangoGraphQLSchema" fork pair-local output instances, which is the
    path both isolation defects live on.

    Args:
        graphene_registry: The graphene registry the throwaway types registered
            themselves into.

    Returns:
        A non-default "SchemaRegistries" pair bound to that registry.
    """
    from django_graphex.core.base import SchemaRegistries
    from django_graphex.core.registry_compiler import NativeOutputRegistry

    return SchemaRegistries(
        graphene=graphene_registry,
        output=NativeOutputRegistry(),
        plain_object_cache={},
        union_cache={},
        interface_cache={},
        filter_input_cache={},
    )


def _build_wrapped_root_schema(label: str, wrapper: Any) -> DjangoGraphQLSchema:
    """Build a forked-pair schema whose root field is a WRAPPED native type.

    Args:
        label: A per-test discriminator folded into the GraphQL type name so
            two tests never collide on a name.
        wrapper: The lazy wrapper to apply, e.g. "NativeList" or
            "NativeNonNull".

    Returns:
        The built schema.
    """
    graphene_registry = Registry()

    class AuthorT(DjangoObjectType):
        class Meta:
            name = f"Fork{label}AuthorT"
            model = Author
            registry = graphene_registry
            only_fields = ("id", "name")

    pair = _forked_pair(graphene_registry)

    class Query(NativeRoot):
        thing = field(wrapper(AuthorT))

    return DjangoGraphQLSchema(query=Query, registries=pair)


@pytest.mark.django_db
def test_native_list_root_field_builds_under_a_forked_pair() -> None:
    """Ships broken if a "[T]" native root field bypasses the schema's pair.

    "field(NativeList(AuthorT))" matches no typed arm of the root compiler, so
    it lands on the scalar arm. That arm dropped "registries", so the inner
    "AuthorT" resolved to the class-def (DEFAULT pair) instance and the build
    aborted with "assert_schema_pair_isolation".

    TEETH: before the fix this raises "BuildError".
    """
    schema = _build_wrapped_root_schema("List", NativeList)

    sdl = print_schema(schema.graphql_schema)
    assert "thing: [ForkListAuthorT]" in sdl


@pytest.mark.django_db
def test_native_non_null_root_field_builds_under_a_forked_pair() -> None:
    """Ships broken if a "T!" native root field bypasses the schema's pair.

    Same scalar-arm defect as the list case, reported separately because a
    required root field is what a user writes and would report.

    TEETH: before the fix this raises "BuildError".
    """
    schema = _build_wrapped_root_schema("NonNull", NativeNonNull)

    sdl = print_schema(schema.graphql_schema)
    assert "thing: ForkNonNullAuthorT!" in sdl


@pytest.mark.django_db
def test_forked_pair_reuses_one_interface_instance() -> None:
    """Ships broken if a forked object type keeps DEFAULT-pair interfaces.

    The forked "AuthorT" copied the interface list compiled against the global
    interface cache, while the root "field(Named)" compiled a second instance
    from the pair's own cache. graphql-core then saw two distinct types named
    "ForkedNamed" in one schema.

    TEETH: before the fix this raises "TypeError: Schema must contain uniquely
    named types".
    """
    graphene_registry = Registry()

    class Named(DjangoInterfaceType):
        class Meta:
            name = "ForkedNamed"
            registry = graphene_registry

    class AuthorT(DjangoObjectType):
        class Meta:
            name = "ForkedNamedAuthorT"
            model = Author
            registry = graphene_registry
            only_fields = ("id", "name")
            interfaces = (Named,)

    pair = _forked_pair(graphene_registry)

    class Query(NativeRoot):
        author = field(AuthorT)
        named = field(Named)

    schema = DjangoGraphQLSchema(query=Query, registries=pair)

    graphql_schema = schema.graphql_schema
    author_type = graphql_schema.type_map["ForkedNamedAuthorT"]
    assert list(author_type.interfaces) == [graphql_schema.type_map["ForkedNamed"]]


def test_explicit_field_name_is_honoured_on_a_plain_object_type() -> None:
    """Ships broken if "name=" is honoured on the root but not on a payload.

    "date_ = field(GraphQLString, name='date')" is the documented way to dodge
    a Python keyword collision. The root compiler renders "date", but a plain
    "ObjectType" body (mutation payloads, nested types) camelCased the
    ATTRIBUTE name and rendered "date_" on the wire.

    TEETH: before the fix the payload field is named "date_".
    """

    class Payload(NativeRoot):
        date_ = field(GraphQLString, name="date")
        is_open = field(GraphQLString)

    class Query(NativeRoot):
        date_ = field(GraphQLString, name="date")
        payload = field(Payload)

    schema = DjangoGraphQLSchema(query=Query)

    payload_fields = schema.graphql_schema.type_map["Payload"].fields
    assert "date" in payload_fields
    assert "date_" not in payload_fields
    # The camelCase pass still applies when no explicit name is declared.
    assert "isOpen" in payload_fields
