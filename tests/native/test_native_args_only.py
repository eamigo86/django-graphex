"""S-args-8 — native arg-declaration API; the graphene.Argument bridge stripped.

Decision #1603 (CLEAN BREAK): v2.0 removes graphene entirely. The transitional
``graphene.Argument`` form for a ``Mutation.args`` (and a declared field's
``args={...}``) is replaced by the NATIVE arg API: graphql-core ``GraphQLArgument``
(or a bare graphql-core type), accepted VERBATIM by the mutation + field compile
paths WITHOUT importing graphene.

This file is the S-args-8 contract:

(a) NATIVE ARG API — a ``Mutation`` declaring ``class args`` ONLY via the native
    ``GraphQLArgument`` form compiles correctly; the compiled arg SDL is
    byte-identical to the ``graphene.Argument`` form it replaces.
(b) IMPORT-REMOVAL — with graphene blocked via ``sys.meta_path``, compiling a
    mutation + a declared field with args + a full schema imports NO graphene via
    ``native/_args.py`` / ``native/mutation.py`` (the arg seams). (The schema_compiler
    plain-object / scalar graphene FALLBACK that still fires for graphene.ObjectType
    ROOTS is open-Q#3, deferred — these tests use NATIVE roots only.)
(c) ``native/mutation.py``'s arg builder no longer references graphene on the
    native arg path (no ``from graphene import Argument``).
(d) SDL PARITY — the arg SDL of the native declaration is byte-identical to the
    graphene.Argument declaration it replaces.

Run:
    .venv/bin/python -m pytest -q tests/native/test_native_args_only.py
"""
from __future__ import annotations

import sys

import pytest


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
class _BlockGraphene:
    """A ``sys.meta_path`` finder that raises when graphene is (re-)imported.

    Installed AFTER graphene is purged from ``sys.modules`` so any fresh
    ``import graphene`` (or ``from graphene...``) during the guarded block raises
    ``ModuleNotFoundError`` — proving the guarded code path does not import
    graphene.
    """

    def find_module(self, name, path=None):  # noqa: D401 - finder protocol
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-args-8 guard: {name}"
            )
        return None

    def find_spec(self, name, path=None, target=None):  # noqa: D401
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-args-8 guard: {name}"
            )
        return None


def _purge_graphene_modules() -> dict:
    """Remove graphene from ``sys.modules``; return the purged modules.

    The caller MUST restore the returned mapping via ``sys.modules.update(...)``
    in a ``finally`` block. Leaving graphene purged would poison the SHARED
    graphene module identity for the rest of the suite — a later lazily-built
    graphene subclass (e.g. ``GenericPaginationField``) would subclass a FRESH
    graphene module while a sibling test imports a different one, breaking
    ``issubclass`` (the #1611 / B5 harness-fragility trap).
    """
    saved = {
        name: mod
        for name, mod in list(sys.modules.items())
        if name == "graphene" or name.startswith("graphene.")
    }
    for name in saved:
        del sys.modules[name]
    return saved


def _arg_sdl(arg) -> str:
    """Render a single ``GraphQLArgument`` to its SDL fragment.

    Wraps the arg in a throwaway query field and extracts the parenthesised
    arg fragment so the comparison is purely the arg type + default rendering.
    """
    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        print_schema,
    )

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {"probe": GraphQLField(GraphQLString, args={"a": arg})},
        )
    )
    sdl = print_schema(schema)
    # the line "  probe(a: <TYPE...>): String"
    for line in sdl.splitlines():
        if "probe(" in line:
            return line.strip()
    raise AssertionError(f"probe field not found in SDL:\n{sdl}")


# --------------------------------------------------------------------------- #
# (a) NATIVE ARG API — Mutation class args via native GraphQLArgument           #
# --------------------------------------------------------------------------- #
def test_mutation_native_arg_compiles_on_field():
    """A native ``GraphQLArgument`` declared in ``class args`` compiles onto the
    field — it is NOT silently dropped (the pre-S-args-8 bug)."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex import Mutation, field

    class _CreateThingNative(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, name):
            return _CreateThingNative(ok=True)

    gql_field = _CreateThingNative.Field()
    assert isinstance(gql_field, GraphQLField)
    assert "name" in gql_field.args, (
        "native GraphQLArgument in class args must compile onto the field, not be dropped"
    )
    garg = gql_field.args["name"]
    assert isinstance(garg, GraphQLArgument)
    assert isinstance(garg.type, GraphQLNonNull)
    assert garg.type.of_type is GraphQLString


def test_mutation_native_arg_sets_out_name_from_camel_key():
    """A native ``GraphQLArgument`` declared under a camelCase key gets an
    ``out_name`` of the snake_case Python kwarg (graphene-form parity)."""
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLString

    from django_graphex import Mutation, field

    class _CreateNamed(Mutation):
        class args:
            firstName = GraphQLArgument(GraphQLString)  # noqa: N815 - wire name

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _CreateNamed(ok=True)

    gql_field = _CreateNamed.Field()
    assert "firstName" in gql_field.args
    assert gql_field.args["firstName"].out_name == "first_name", (
        "out_name must be the snake_case form of the camelCase declared key"
    )


def test_mutation_bare_native_type_is_wrapped_as_argument():
    """A bare graphql-core type declared in ``class args`` is wrapped in a
    ``GraphQLArgument`` (ergonomic native form)."""
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLInt

    from django_graphex import Mutation, field

    class _CreateWithBare(Mutation):
        class args:
            age = GraphQLInt

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _CreateWithBare(ok=True)

    gql_field = _CreateWithBare.Field()
    assert "age" in gql_field.args
    assert isinstance(gql_field.args["age"], GraphQLArgument)
    assert gql_field.args["age"].type is GraphQLInt


# --------------------------------------------------------------------------- #
# (a') CLEAN BREAK — a graphene.Argument in class args FAILS LOUDLY (not dropped)#
# --------------------------------------------------------------------------- #
def test_non_native_arg_in_class_args_raises_typeerror():
    """A non-native value declared in a Mutation ``class args`` raises ``TypeError``
    — it is NOT silently dropped.

    Pre-FIX-1 ``_compile_args`` filtered ``isinstance(value, (GraphQLArgument,
    GraphQLType))`` and SKIPPED everything else, so a leftover non-native arg
    (historically a ``graphene.Argument``) vanished with no error (the mutation
    lost its arg, and the advertised CLEAN BREAK = TypeError was unreachable). The
    native API now fails loudly, pointing to the native ``GraphQLArgument`` form.

    v2.0: graphene is gone, so the offending value is a generic non-native arg
    sentinel — the loud-fail contract is the same.
    """
    from graphql import GraphQLBoolean

    from django_graphex import Mutation, field

    class _NotANativeArg:
        """Stand-in for any non-graphql-core arg value (e.g. the legacy
        ``graphene.Argument`` that v2.0 no longer accepts)."""

    class _CreateWithBadArg(Mutation):
        class args:
            name = _NotANativeArg()

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _CreateWithBadArg(ok=True)

    with pytest.raises(TypeError) as exc:
        _CreateWithBadArg.Field()

    msg = str(exc.value)
    assert "name" in msg, f"TypeError must name the offending attribute: {msg!r}"
    assert "GraphQLArgument" in msg, (
        f"TypeError must point to the native GraphQLArgument form: {msg!r}"
    )


def test_helper_constant_in_class_args_still_ignored():
    """A trivial helper attribute on ``class args`` (the graphene-parity skip) is
    still IGNORED, not an error — only non-native ARG values fail loudly.

    ``props()`` strips dunders/underscore helpers; a plain non-arg public helper
    that the graphene path tolerated must remain tolerated so the loud-fail only
    targets genuine arg declarations.
    """
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString

    from django_graphex import Mutation, field
    from django_graphex.native.mutation import _compile_args

    class args:  # noqa: N801 - mimics a Mutation inner ``class args``
        name = GraphQLArgument(GraphQLNonNull(GraphQLString))
        _private_helper = "ignored by props()"  # underscore → stripped by props()

    compiled = _compile_args(args)
    assert set(compiled) == {"name"}, compiled
    assert isinstance(compiled["name"], GraphQLArgument)

    # Sanity: a Mutation that ONLY declares the native arg still compiles.
    class _CreateOk(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _CreateOk(ok=True)

    assert "name" in _CreateOk.Field().args


# --------------------------------------------------------------------------- #
# (d) SDL PARITY — native arg SDL byte-identical to graphene.Argument form      #
# --------------------------------------------------------------------------- #
def test_native_arg_sdl_renders_required_string():
    """The native ``GraphQLArgument`` declaration renders the expected arg SDL.

    S-del-backend-11: the graphene-bridge comparison was dropped (the graphene
    backend is deleted). The native ``GraphQLNonNull(GraphQLString)`` arg renders
    as ``a: String!`` — the byte-stable shape the graphene form used to produce.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    native_arg = GraphQLArgument(GraphQLNonNull(GraphQLString), out_name="a")
    assert _arg_sdl(native_arg) == "probe(a: String!): String"


def test_native_arg_with_default_sdl_renders_default():
    """Default-value rendering for a native ``GraphQLArgument`` is byte-stable."""
    from graphql import GraphQLArgument, GraphQLString

    native_arg = GraphQLArgument(GraphQLString, default_value="hello", out_name="a")
    assert _arg_sdl(native_arg) == 'probe(a: String = "hello"): String'


def test_full_mutation_field_arg_sdl_renders_expected_shape():
    """A whole mutation field's arg SDL — declared via the NATIVE arg form —
    renders the expected byte-stable shape.

    S-del-backend-11: the graphene-bridge baseline was dropped (the graphene
    backend is deleted). The native ``class args`` declaration is compiled by
    ``Mutation.Field()`` (graphene-free); its arg SDL is asserted directly against
    the expected ``name: String!, note: String`` shape the graphene form produced.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        print_schema,
    )

    from django_graphex import Mutation, field

    class _NativeArgsMutation(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))
            note = GraphQLArgument(GraphQLString)

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _NativeArgsMutation(ok=True)

    def _args_sdl(args_dict, wire_name):
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query", {wire_name: GraphQLField(GraphQLString, args=args_dict)}
            )
        )
        sdl = print_schema(schema)
        for line in sdl.splitlines():
            if wire_name + "(" in line:
                return line.strip().split("(", 1)[1]
        raise AssertionError(f"{wire_name} field not found:\n{sdl}")

    native_field = _NativeArgsMutation.Field()
    assert _args_sdl(native_field.args, "doThing") == "name: String!, note: String): String", (
        "native arg declaration must render the expected byte-stable arg SDL"
    )


# --------------------------------------------------------------------------- #
# (c) native arg builder is graphene-free on the native path                    #
# --------------------------------------------------------------------------- #
def test_compile_args_source_has_no_graphene_import():
    """``native/mutation.py``'s ``_compile_args`` no longer imports graphene.

    CLEAN BREAK: the transitional ``from graphene import Argument`` is gone — the
    native arg path accepts graphql-core ``GraphQLArgument`` verbatim.
    """
    import inspect

    from django_graphex.native import mutation as mut_mod

    src = inspect.getsource(mut_mod._compile_args)
    assert "import graphene" not in src and "from graphene" not in src, (
        "_compile_args must not import graphene (CLEAN BREAK, S-args-8):\n" + src
    )


def test_mutation_module_has_no_graphene_anywhere():
    """No graphene import survives anywhere in ``native/mutation.py`` source."""
    import inspect

    from django_graphex.native import mutation as mut_mod

    src = inspect.getsource(mut_mod)
    assert "import graphene" not in src, (
        "native/mutation.py must be fully graphene-free after S-args-8"
    )
    assert "from graphene" not in src


# --------------------------------------------------------------------------- #
# (b) IMPORT-REMOVAL — graphene blocked via sys.meta_path                        #
# --------------------------------------------------------------------------- #
def test_native_mutation_args_build_with_graphene_blocked():
    """Compile a Mutation with native args while graphene is blocked at meta_path.

    The strongest import-removal proof for the arg path: purge graphene, install
    the blocker, then declare + compile a Mutation whose ``class args`` uses the
    native ``GraphQLArgument`` form. Must NOT raise — proving the arg compile path
    imports no graphene.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex import Mutation, field

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:
        class _BlockedArgsMutation(Mutation):
            class args:
                name = GraphQLArgument(GraphQLNonNull(GraphQLString))

            ok = field(GraphQLBoolean)

            @staticmethod
            def mutate(root, info, **kw):
                return _BlockedArgsMutation(ok=True)

        gql_field = _BlockedArgsMutation.Field()
        assert "name" in gql_field.args
        assert isinstance(gql_field.args["name"], GraphQLArgument)
        assert "graphene" not in sys.modules, (
            "compiling native mutation args must not import graphene"
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)


def test_native_declared_field_args_build_with_graphene_blocked():
    """Compile a declared scalar field carrying native args, graphene blocked.

    The declared-field arg path (``field(..., args={...})`` →
    ``_build_scalar_field`` → arg converter) must accept native ``GraphQLArgument``
    verbatim without importing graphene.
    """
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex import field
    from django_graphex.native.schema_compiler import _build_scalar_field

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:
        declared = field(
            GraphQLString, args={"q": GraphQLArgument(GraphQLString)}
        )
        compiled = _build_scalar_field(declared, source_cls=None, field_name="thing")
        assert "q" in compiled.args
        assert isinstance(compiled.args["q"], GraphQLArgument)
        assert "graphene" not in sys.modules, (
            "compiling declared field args must not import graphene"
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)


def test_args_converter_native_passthrough_no_graphene():
    """The arg converter accepts a native ``GraphQLArgument`` verbatim and imports
    no graphene while doing so."""
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    from django_graphex.native._args import to_graphql_argument

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:
        native = GraphQLArgument(GraphQLNonNull(GraphQLString))
        result = to_graphql_argument(native, name="firstName")
        assert isinstance(result, GraphQLArgument)
        assert isinstance(result.type, GraphQLNonNull)
        assert result.type.of_type is GraphQLString
        assert result.out_name == "first_name"
        assert "graphene" not in sys.modules, (
            "native arg passthrough must not import graphene"
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)
