"""S-ROOTS-f — public ObjectType + field() root mount, native compile + execute.

The PUBLIC-API milestone (decision #1554): prove a user can declare a GraphQL
root graphene-free with ``from django_graphex import ObjectType, field`` and that
the native compiler mounts + compiles + EXECUTES every declared field — a custom
scalar field, an object-reference field, AND a model-driven ``DjangoListObjectField``
— with NONE silently dropping (the paramount S-ROOTS risk).

A field declared with ``field()`` that the mount (``native/base._mount_descriptor_fields``)
or the compiler (``schema_compiler.compile_native_root``) fails to recognize would
vanish from ``_meta.fields`` / the compiled SDL with NO error. These tests are the
defensive guard against that: they assert the field SET (every declared field
present) AND the field TYPE for each, in the COMPILED + EXECUTED schema.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# Public API export — from django_graphex import ObjectType, field             #
# --------------------------------------------------------------------------- #
def test_public_objecttype_and_field_are_exported():
    """``ObjectType`` (native base) and ``field`` (descriptor helper) are
    importable from the top-level ``django_graphex`` package and are the SAME
    objects as their canonical definitions."""
    import django_graphex
    from django_graphex import ObjectType, field
    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.native.descriptors import field as native_field

    assert ObjectType is NativeObjectType
    assert field is native_field
    assert "ObjectType" in django_graphex.__all__
    assert "field" in django_graphex.__all__


# --------------------------------------------------------------------------- #
# field() class-body descriptor lands in _meta.fields on a ROOT class          #
# --------------------------------------------------------------------------- #
def test_field_on_native_root_lands_in_meta_fields():
    """A class-body ``field(...)`` on a ``django_graphex.ObjectType`` root is
    collected into ``_meta.fields`` by the native mount (NOT silently inferred
    as a Pydantic model field, NOT dropped)."""
    from graphql import GraphQLString

    from django_graphex import ObjectType, field

    class _RootsFMountQuery(ObjectType):
        server_time = field(GraphQLString, description="ISO timestamp")

        def resolve_server_time(self, info):
            return "2026-06-15T00:00:00"

    meta_fields = _RootsFMountQuery._meta.fields
    assert "server_time" in meta_fields, (
        "field() declaration MUST land in _meta.fields — a missing key is the "
        "silent-drop epicenter"
    )
    # The mounted value exposes the compiler read-contract.
    mounted = meta_fields["server_time"]
    assert mounted.type is GraphQLString


# --------------------------------------------------------------------------- #
# Silent-drop guard — field() scalar + field() object ref + DjangoListObjectField
# all appear in the EXECUTED schema with the right types                        #
# --------------------------------------------------------------------------- #
def test_native_root_mixed_fields_compile_and_execute_no_drop():
    """A native ``ObjectType`` root declaring ALL THREE field kinds —
    a ``field()`` custom scalar, a ``field()`` object reference, AND a native
    ``DjangoListObjectField`` — compiles via ``compile_native_root`` with EVERY
    field present in the SDL (same type) and EXECUTES end-to-end.

    This is the defensive silent-drop test mandated by the S-ROOTS-f scope: a
    field declared via ``field()`` that the mount/compiler doesn't recognize
    vanishes silently → that would be a BLOCK. Here we PROVE none vanishes.
    """
    from graphql import (
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )

    from django_graphex import ObjectType, field
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.schema import User1ListType, UserType

    # Compile model output types first (app-ready normally does this).
    compile_all_outputs()

    class _RootsFMixedQuery(ObjectType):
        # 1) field() custom scalar.
        server_time = field(GraphQLString, description="ISO timestamp")
        # 2) field() object reference to a DjangoObjectType (lazy-resolved).
        me = field(UserType)
        # 3) native model-driven list field (already native, UNCHANGED idiom).
        all_users = DjangoListObjectField(User1ListType)

        def resolve_server_time(self, info):
            return "2026-06-15T00:00:00"

        def resolve_me(self, info):
            return None

    native_root = compile_native_root(_RootsFMixedQuery, name="Query")
    assert isinstance(native_root, GraphQLObjectType)

    # FIELD-SET PARITY: every declared field present in the compiled root.
    fields = native_root.fields
    assert {"serverTime", "me", "allUsers"} <= set(fields), (
        "A declared root field VANISHED from the compiled SDL — silent drop. "
        f"Got: {sorted(fields)}"
    )

    # FIELD-TYPE PARITY: each field compiled to the right graphql-core type.
    assert fields["serverTime"].type is GraphQLString
    # me -> the canonical compiled UserType output instance (identity-stable).
    assert fields["me"].type is UserType._meta.graphql_output_type
    # allUsers -> the list-container output (User1ListType's compiled type).
    assert fields["allUsers"].type is User1ListType._meta.graphql_output_type

    # EXECUTE: the scalar field resolves through its resolve_<name> method.
    schema = GraphQLSchema(query=native_root)
    result = graphql_sync(schema, "{ serverTime }")
    assert result.errors is None, result.errors
    assert result.data == {"serverTime": "2026-06-15T00:00:00"}


# --------------------------------------------------------------------------- #
# Migrated production root (tests/schema.py::Query) — native compile + execute  #
# --------------------------------------------------------------------------- #
def test_migrated_schema_query_compiles_native_with_custom_scalar_fields():
    """The MIGRATED ``tests/schema.py::Query`` (now ``django_graphex.ObjectType``
    with ``field()``-declared ``datetime`` / ``date`` / ``time`` custom scalar
    fields) compiles via the native root compiler and the three custom scalar
    fields are present with their explicit wire names + custom scalar types."""
    from graphql import GraphQLObjectType

    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.scalars import GdxDate, GdxDateTime, GdxTime
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.schema import Query

    compile_all_outputs()
    native_root = compile_native_root(Query, name="Query")
    assert isinstance(native_root, GraphQLObjectType)

    fields = native_root.fields
    # Explicit name= kwargs render WITHOUT the python-keyword trailing underscore.
    assert {"datetime", "date", "time"} <= set(fields), (
        "Custom scalar root fields dropped during migration — silent drop. "
        f"Got: {sorted(fields)}"
    )
    assert fields["datetime"].type is GdxDateTime
    assert fields["date"].type is GdxDate
    assert fields["time"].type is GdxTime

    # Model-driven fields survive the base-class swap unchanged.
    assert {"allUsers", "user", "users"} <= set(fields)


def test_migrated_schema_query_executes_custom_scalar_field():
    """The migrated ``tests/schema.py::Query`` EXECUTES its ``field()``-declared
    ``date`` custom scalar field end-to-end (resolve_date_ wired via the native
    compiler), returning the serialized custom-scalar value."""
    from graphql import GraphQLSchema, graphql_sync

    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.schema import Query

    compile_all_outputs()
    native_root = compile_native_root(Query, name="Query")
    schema = GraphQLSchema(query=native_root)

    result = graphql_sync(schema, "{ date }")
    assert result.errors is None, result.errors
    # resolve_date_ returns date(2020, 12, 31); GdxDate serializes ISO.
    assert result.data == {"date": "2020-12-31"}
