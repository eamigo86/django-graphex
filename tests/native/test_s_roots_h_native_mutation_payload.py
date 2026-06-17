"""S-ROOTS-h — native hand-written ``Mutation`` output payload + native-root mount.

This is the NET-NEW slice that makes ``django_graphex.Mutation`` (native) a REAL
hand-written mutation base: a structured output payload (``ok`` / ``<obj>`` /
``error`` declared via ``field()``), arguments declared via ``class args``, and a
``Field()`` that compiles to a graphql-core ``GraphQLField`` whose type is the
compiled payload ``GraphQLObjectType`` — mountable on a NATIVE ``ObjectType`` root
(``django_graphex.ObjectType``) and EXECUTABLE end-to-end.

It also unblocks a NATIVE mutation root: a ``django_graphex.ObjectType`` holding a
raw ``GraphQLField`` class attribute (``create_x = CreateX.Field()``) must be a
valid native ObjectType (no ``PydanticUserError``) and the GraphQLField must reach
``_meta.fields`` so ``compile_native_root`` mounts it.

PARAMOUNT guards (both asserted here):
- SILENT-DROP: a ``Mutation.Field()`` declared on a native root MUST appear in the
  compiled SDL (not silently dropped).
- SILENT-NULL (the S6c payload class): the ``cls(ok=True, obj=..., error=None)``
  return value MUST round-trip to NON-NULL wire values through a real executed
  ``graphql_sync`` mutation.

Run:
    GDX_BACKEND=native .venv/bin/python -m pytest -q \
        tests/native/test_s_roots_h_native_mutation_payload.py -o addopts=""
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# 1. Mutation is a NATIVE ObjectType subclass (so field() output descriptors    #
#    + the cls(**resp) payload round-trip work)                                  #
# --------------------------------------------------------------------------- #
def test_native_mutation_is_native_objecttype_subclass():
    """``Mutation`` is a subclass of the native ``ObjectType`` base so its
    output ``field()`` descriptors compile into a payload object type and the
    ``cls(**resp)`` value-object round-trip (the silent-null safety net) works."""
    from django_graphex import Mutation
    from django_graphex.native.base import ObjectType as NativeObjectType

    assert issubclass(Mutation, NativeObjectType), (
        "native Mutation must subclass the native ObjectType base so output "
        "field() descriptors land in _meta.fields and the payload round-trips"
    )


def test_native_mutation_output_fields_land_in_meta_fields():
    """``field()`` output descriptors declared on a ``Mutation`` subclass land in
    ``_meta.fields`` (the silent-drop epicenter) alongside no spurious entries."""
    from graphql import GraphQLBoolean, GraphQLString

    from django_graphex import Mutation, field

    class _SimplePing(Mutation):
        ok = field(GraphQLBoolean)
        message = field(GraphQLString)

        @staticmethod
        def mutate(root, info):
            return _SimplePing(ok=True, message="pong")

    meta_fields = _SimplePing._meta.fields
    assert "ok" in meta_fields, "output field 'ok' dropped from _meta.fields"
    assert "message" in meta_fields, "output field 'message' dropped from _meta.fields"


def test_native_mutation_payload_value_object_roundtrips():
    """``cls(ok=True, message="pong")`` stashes the payload values as instance
    attributes (the S6c silent-null fix) — they are NOT dropped by Pydantic."""
    from graphql import GraphQLBoolean, GraphQLString

    from django_graphex import Mutation, field

    class _Ping(Mutation):
        ok = field(GraphQLBoolean)
        message = field(GraphQLString)

        @staticmethod
        def mutate(root, info):
            return _Ping(ok=True, message="pong")

    instance = _Ping(ok=True, message="pong")
    assert instance.ok is True
    assert instance.message == "pong"


# --------------------------------------------------------------------------- #
# 2. class args -> {name: GraphQLArgument} on the field                          #
# --------------------------------------------------------------------------- #
def test_native_mutation_field_args_compile_from_class_args():
    """``class args`` declarations compile to graphql-core ``GraphQLArgument``s
    on the returned field (the native arg form)."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex import Mutation, field

    class _CreateThing(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, name):
            return _CreateThing(ok=True)

    gql_field = _CreateThing.Field()
    assert isinstance(gql_field, GraphQLField)
    assert "name" in gql_field.args
    garg = gql_field.args["name"]
    assert isinstance(garg, GraphQLArgument)
    assert isinstance(garg.type, GraphQLNonNull)
    assert garg.type.of_type is GraphQLString


# --------------------------------------------------------------------------- #
# 3. Field() output type is the compiled PAYLOAD GraphQLObjectType (not String) #
# --------------------------------------------------------------------------- #
def test_native_mutation_field_output_is_payload_object_type():
    """``Mutation.Field()`` output type is the compiled PAYLOAD
    ``GraphQLObjectType`` (carrying the declared output fields) — NOT the
    Phase-4 ``GraphQLString`` placeholder."""
    from graphql import (
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLString,
    )

    from django_graphex import Mutation, field

    class _PayloadMutation(Mutation):
        ok = field(GraphQLBoolean)
        error = field(GraphQLString)

        @staticmethod
        def mutate(root, info):
            return _PayloadMutation(ok=True, error=None)

    gql_field = _PayloadMutation.Field()
    assert isinstance(gql_field, GraphQLField)

    out = gql_field.type
    if isinstance(out, GraphQLNonNull):
        out = out.of_type
    assert isinstance(out, GraphQLObjectType), (
        "Mutation.Field() output type must be the compiled payload object type, "
        f"not a placeholder scalar — got {gql_field.type!r}"
    )
    payload_field_names = set(out.fields.keys())
    assert "ok" in payload_field_names, (
        f"payload type must expose 'ok'; got {sorted(payload_field_names)}"
    )
    assert "error" in payload_field_names, (
        f"payload type must expose 'error'; got {sorted(payload_field_names)}"
    )


def test_native_mutation_field_registered_in_identity_set():
    """``Mutation.Field()`` registers its GraphQLField id in
    ``_NATIVE_FIELD_IDENTITIES`` so ``_collect_root_attrs`` recovers it (and never
    silently drops it) when mounted on a root."""
    from graphql import GraphQLBoolean

    from django_graphex import Mutation, field
    from django_graphex.mutation import _NATIVE_FIELD_IDENTITIES

    class _RegisteredMutation(Mutation):
        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info):
            return _RegisteredMutation(ok=True)

    gql_field = _RegisteredMutation.Field()
    assert id(gql_field) in _NATIVE_FIELD_IDENTITIES, (
        "Mutation.Field() must register its identity so the native root compiler "
        "recovers it (silent-drop guard)"
    )


# --------------------------------------------------------------------------- #
# 4. Native ObjectType accepts a raw GraphQLField class attribute (so a native   #
#    RootMutation holding create_x = CreateX.Field() builds with no PydanticError)#
# --------------------------------------------------------------------------- #
def test_native_objecttype_accepts_raw_graphql_field_attr():
    """A ``django_graphex.ObjectType`` declaring a raw ``GraphQLField`` class
    attribute builds WITHOUT ``PydanticUserError`` and the field lands in
    ``_meta.fields`` (so the native root compiler can mount it)."""
    from graphql import GraphQLField, GraphQLString

    from django_graphex import ObjectType

    raw = GraphQLField(GraphQLString, resolve=lambda root, info: "hi")

    class _NativeRootWithRawField(ObjectType):
        greeting = raw

    meta_fields = _NativeRootWithRawField._meta.fields
    assert "greeting" in meta_fields, (
        "a raw GraphQLField class attr on a native ObjectType must reach "
        "_meta.fields — otherwise the native root compiler silently drops it"
    )
    assert meta_fields["greeting"] is raw


# --------------------------------------------------------------------------- #
# 5. END-TO-END: a hand-written native Mutation on a native root compiles +      #
#    EXECUTES with a non-null payload (silent-drop + silent-null guards)         #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_native_mutation_compiles_and_executes_nonnull_payload():
    """CARDINAL: a hand-written native ``Mutation`` mounted on a native
    ``ObjectType`` root compiles via ``compile_native_root`` (field PRESENT in the
    SDL — silent-drop guard) and EXECUTES via ``graphql_sync`` returning a
    NON-NULL payload (``ok`` / a nested object / ``error``) — the silent-null
    (S6c) guard, proven on the wire."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )

    from django_graphex import DjangoObjectType, Mutation, ObjectType, field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.models import Author

    class _HAuthorNode(DjangoObjectType):
        class Meta:
            model = Author

    # Compile model output types first (app-ready normally does this) so the
    # payload's object-reference field resolves to a real compiled type.
    compile_all_outputs()

    class _HCreateAuthor(Mutation):
        """Hand-written native mutation with a structured output payload."""

        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)
        author = field(_HAuthorNode)
        error = field(GraphQLString)

        @staticmethod
        def mutate(root, info, name):
            obj = Author.objects.create(name=name)
            return _HCreateAuthor(ok=True, author=obj, error=None)

    class _HRootMutation(ObjectType):
        create_author = _HCreateAuthor.Field()

    # --- SILENT-DROP GUARD: the field appears in the compiled root SDL ---
    native_root = compile_native_root(_HRootMutation, name="Mutation")
    assert isinstance(native_root, GraphQLObjectType)
    assert "createAuthor" in native_root.fields, (
        "the hand-written Mutation field VANISHED from the compiled SDL — "
        "silent drop. A stub that compiles but drops the field is a BLOCK."
    )

    # The mounted field's output type is the payload object type carrying the
    # declared output fields (not a placeholder scalar).
    out = native_root.fields["createAuthor"].type
    assert isinstance(out, GraphQLObjectType)
    assert {"ok", "author", "error"} <= set(out.fields.keys()), (
        f"payload type missing declared fields; got {sorted(out.fields.keys())}"
    )

    # --- EXECUTE: the payload round-trips to NON-NULL wire values ---
    # A trivial query root is required for a valid schema.
    query_root = GraphQLObjectType(
        "Query", {"ping": GraphQLField(GraphQLString, resolve=lambda r, i: "pong")}
    )
    schema = GraphQLSchema(query=query_root, mutation=native_root)

    document = (
        'mutation { createAuthor(name: "Grace") '
        "{ ok author { name } error } }"
    )
    result = graphql_sync(schema, document)

    assert result.errors is None, f"native mutation raised: {result.errors!r}"
    data = result.data["createAuthor"]
    # SILENT-NULL GUARD: every payload field is the real value, NOT null.
    assert data["ok"] is True, f"ok came back null/false — silent-null bug: {data!r}"
    assert data["author"] is not None, (
        f"author payload came back null — silent-null bug: {data!r}"
    )
    assert data["author"]["name"] == "Grace"
    assert data["error"] is None  # explicitly null is correct here
    # The row really landed in the DB (not a faked payload).
    assert Author.objects.filter(name="Grace").exists()


@pytest.mark.django_db
def test_native_mutation_error_path_roundtrips():
    """The error branch ``cls(ok=False, error=...)`` also round-trips on the
    wire — proving the value-object stash works for the falsy/None payload too."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )

    from django_graphex import Mutation, ObjectType, field
    from django_graphex.native.schema_compiler import compile_native_root

    class _HFailMutation(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)
        error = field(GraphQLString)

        @staticmethod
        def mutate(root, info, name):
            return _HFailMutation(ok=False, error=f"{name} already exists")

    class _HFailRoot(ObjectType):
        do_fail = _HFailMutation.Field()

    native_root = compile_native_root(_HFailRoot, name="Mutation")
    query_root = GraphQLObjectType(
        "Query", {"ping": GraphQLField(GraphQLString, resolve=lambda r, i: "pong")}
    )
    schema = GraphQLSchema(query=query_root, mutation=native_root)

    result = graphql_sync(
        schema, 'mutation { doFail(name: "dup") { ok error } }'
    )
    assert result.errors is None, result.errors
    data = result.data["doFail"]
    assert data["ok"] is False
    assert data["error"] == "dup already exists", (
        f"error string dropped/nulled — silent-null bug: {data!r}"
    )
