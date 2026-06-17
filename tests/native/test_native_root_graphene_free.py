"""S-milestone-9 (graphene-removal): a FULLY-NATIVE-ROOT schema builds graphene-free.

The S-milestone-9 contract (decision #1603, gate-strategy #1608): a schema whose
EVERY root is a native ``django_graphex.ObjectType`` — Query + Mutation +
Subscription + a paginated list field — compiles and prints its SDL while graphene
is BLOCKED via ``sys.meta_path``, with ``graphene`` never re-entering
``sys.modules``.

This is the proof that the NATIVE code path is graphene-free end-to-end. The
graphene-ROOT short-circuits (``schema_compiler._is_plain_object_type`` graphene
fallback :391, ``_compile_wrapped_field_type`` graphene structures :709-710) are
DEFERRED to S-del-backend-11 — they fire ONLY for a ``graphene.ObjectType`` root,
which this test never declares. The ``get_unbound_function`` import in
``_resolver_for`` (:302) fired even for a pure-native scalar field with a
``resolve_<name>`` method (proven) — it is inlined in this slice.

Run:
    .venv/bin/python -m pytest -q tests/native/test_native_root_graphene_free.py
"""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.native_only


class _BlockGraphene:
    """A ``sys.meta_path`` finder that raises when graphene is (re-)imported."""

    def find_module(self, name, path=None):  # noqa: D401 - finder protocol
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-milestone-9 guard: {name}"
            )
        return None

    def find_spec(self, name, path=None, target=None):  # noqa: D401
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-milestone-9 guard: {name}"
            )
        return None


def _purge_graphene_modules() -> dict:
    """Remove graphene from ``sys.modules``; return the purged modules.

    The caller MUST restore the returned mapping via ``sys.modules.update(...)``
    in a ``finally`` block (the #1611 / B5 module-identity-leak trap).
    """
    saved = {
        name: mod
        for name, mod in list(sys.modules.items())
        if name == "graphene" or name.startswith("graphene.")
    }
    for name in saved:
        del sys.modules[name]
    return saved


def test_fully_native_root_schema_builds_with_graphene_blocked():
    """A fully-native schema (query+mutation+subscription+pagination) compiles +
    prints SDL with graphene blocked at ``sys.meta_path`` — no ModuleNotFoundError,
    graphene never re-enters ``sys.modules``."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLNonNull,
        GraphQLSchema,
        GraphQLString,
        print_schema,
    )

    from django_graphex import Mutation, ObjectType, field
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native.base import compile_all_inputs
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.schema import User1ListType, UserType

    # Warm up the native machinery BEFORE blocking graphene so only graphene
    # imports that fire DURING the build are caught (not unrelated warm-up).
    compile_all_outputs()
    compile_all_inputs()

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:

        class _NativeCreate(Mutation):
            class args:
                name = GraphQLArgument(GraphQLNonNull(GraphQLString))

            ok = field(GraphQLBoolean)

            @staticmethod
            def mutate(root, info, **kw):
                return _NativeCreate(ok=True)

        class _NativeQuery(ObjectType):
            # field() scalar WITH a resolve_<name> method — exercises _resolver_for
            # (the get_unbound_function fire-point) on a PURE NATIVE root.
            server_time = field(GraphQLString, description="ISO timestamp")
            # field() object reference (lazy).
            me = field(UserType)
            # native model-driven paginated list field.
            all_users = DjangoListObjectField(User1ListType)

            def resolve_server_time(self, info):
                return "now"

            def resolve_me(self, info):
                return None

        class _NativeMutation(ObjectType):
            create_thing = _NativeCreate.Field()

        class _NativeSubscription(ObjectType):
            tick = field(GraphQLString)

            def resolve_tick(self, info):
                return "tick"

        q = compile_native_root(_NativeQuery, name="Query")
        m = compile_native_root(_NativeMutation, name="Mutation")
        s = compile_native_root(_NativeSubscription, name="Subscription")
        schema = GraphQLSchema(query=q, mutation=m, subscription=s)
        sdl = print_schema(schema)

        # Field-set parity — nothing silently dropped.
        assert "serverTime" in sdl
        assert "allUsers" in sdl
        assert "createThing" in sdl
        assert "tick" in sdl

        assert "graphene" not in sys.modules, (
            "building a fully-native-root schema must not import graphene; "
            "still in sys.modules: "
            + ", ".join(n for n in sys.modules if n.startswith("graphene"))
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)


def test_native_wrapped_object_payload_and_declared_args_graphene_free():
    """Exercise the native WRAPPER + declared-arg paths under a graphene block.

    Complements the schema build above: a payload field declared via a native
    ``NativeList`` / ``NativeNonNull`` around a plain native ``ObjectType`` (the
    ErrorType-style payload, S-ROOTS-c) AND a declared scalar field carrying native
    ``args`` must compile graphene-free — proving ``_compile_wrapped_field_type``'s
    native-wrapper branch and the declared-arg converter import no graphene on the
    native path.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLList,
        GraphQLObjectType,
        GraphQLString,
    )

    from django_graphex import ObjectType, field
    from django_graphex.native.descriptors import NativeList, NativeNonNull
    from django_graphex.native.schema_compiler import (
        _build_scalar_field,
        _compile_plain_object_type,
    )

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:

        class _ErrorType(ObjectType):
            field_name = field(GraphQLString)
            messages = field(NativeNonNull(GraphQLString))

        class _PayloadType(ObjectType):
            ok = field(GraphQLBoolean)
            # native List wrapper around a plain native ObjectType (lazy).
            errors = field(NativeList(_ErrorType))

        compiled = _compile_plain_object_type(_PayloadType)
        assert isinstance(compiled, GraphQLObjectType)
        fields = compiled.fields  # forces the lazy thunk to resolve
        assert "ok" in fields and "errors" in fields
        assert isinstance(fields["errors"].type, GraphQLList)

        # Declared scalar field carrying native args — the arg converter path.
        declared = field(GraphQLString, args={"q": GraphQLArgument(GraphQLString)})
        scalar = _build_scalar_field(declared, source_cls=None, field_name="thing")
        assert "q" in scalar.args

        assert "graphene" not in sys.modules, (
            "native wrapper + declared-arg compile must not import graphene; "
            "still in sys.modules: "
            + ", ".join(n for n in sys.modules if n.startswith("graphene"))
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)
