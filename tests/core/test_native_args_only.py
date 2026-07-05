"""S-args-8 — native arg-declaration API; the graphene.Argument bridge stripped.

Decision #1603 (CLEAN BREAK): v2.0 removes graphene entirely. The transitional
"graphene.Argument" form for a "Mutation.args" (and a declared field's
"args={...}") is replaced by the NATIVE arg API: graphql-core "GraphQLArgument"
(or a bare graphql-core type), accepted VERBATIM by the mutation + field compile
paths WITHOUT importing graphene.

This file is the S-args-8 contract:

(a) NATIVE ARG API — a "Mutation" declaring "class Arguments" ONLY via the native
    "GraphQLArgument" form compiles correctly; the compiled arg SDL is
    byte-identical to the "graphene.Argument" form it replaces.
(b) IMPORT-REMOVAL — with graphene blocked via "sys.meta_path", compiling a
    mutation + a declared field with args + a full schema imports NO graphene via
    "core/_args.py" / "core/mutation.py" (the arg seams). (The schema_compiler
    plain-object / scalar graphene FALLBACK that still fires for graphene.ObjectType
    ROOTS is open-Q#3, deferred — these tests use NATIVE roots only.)
(c) "core/mutation.py"'s arg builder no longer references graphene on the
    native arg path (no "from graphene import Argument").
(d) SDL PARITY — the arg SDL of the native declaration is byte-identical to the
    graphene.Argument declaration it replaces.

Run:
    .venv/bin/python -m pytest -q tests/core/test_native_args_only.py
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
# (a) NATIVE ARG API — Mutation class Arguments via native GraphQLArgument      #
# --------------------------------------------------------------------------- #
def test_mutation_native_arg_compiles_on_field() -> None:
    """Assert that a native "GraphQLArgument" in "class Arguments" compiles onto the field.

    It is NOT silently dropped (the pre-S-args-8 bug).

    If this fails, a mutation's declared native argument would vanish from
    the compiled GraphQLField instead of appearing in its args.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex.core import Mutation, field

    class _CreateThingNative(Mutation):
        class Arguments:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, name):
            return _CreateThingNative(ok=True)

    gql_field = _CreateThingNative.Field()
    assert isinstance(gql_field, GraphQLField)
    assert "name" in gql_field.args, (
        "native GraphQLArgument in class Arguments must compile onto the field, not be dropped"
    )
    garg = gql_field.args["name"]
    assert isinstance(garg, GraphQLArgument)
    assert isinstance(garg.type, GraphQLNonNull)
    assert garg.type.of_type is GraphQLString


def test_mutation_native_arg_sets_out_name_from_camel_key() -> None:
    """Assert that a camelCase-keyed native argument gets a snake_case out_name.

    Matches graphene-form parity: the compiled out_name is the snake_case
    Python kwarg name.

    If this fails, resolvers would receive the argument under its
    camelCase wire key instead of the expected snake_case kwarg.
    """
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLString

    from django_graphex.core import Mutation, field

    class _CreateNamed(Mutation):
        class Arguments:
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


def test_mutation_bare_native_type_is_wrapped_as_argument() -> None:
    """Assert that a bare graphql-core type in "class Arguments" is wrapped in a GraphQLArgument.

    This is the ergonomic native form that lets callers skip the explicit
    GraphQLArgument wrapper.

    If this fails, declaring a bare scalar type as an argument would raise
    or fail to compile instead of being auto-wrapped.
    """
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLInt

    from django_graphex.core import Mutation, field

    class _CreateWithBare(Mutation):
        class Arguments:
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
# (a') CLEAN BREAK — a graphene.Argument in class Arguments FAILS LOUDLY (not dropped)#
# --------------------------------------------------------------------------- #
def test_non_native_arg_in_class_args_raises_typeerror() -> None:
    """Assert that a non-native value in "class Arguments" raises TypeError, not a silent drop.

    Pre-FIX-1 "_compile_args" filtered "isinstance(value, (GraphQLArgument,
    GraphQLType))" and SKIPPED everything else, so a leftover non-native arg
    (historically a "graphene.Argument") vanished with no error (the
    mutation lost its arg, and the advertised CLEAN BREAK = TypeError was
    unreachable). The native API now fails loudly, pointing to the native
    "GraphQLArgument" form.

    v2.0: graphene is gone, so the offending value is a generic non-native
    arg sentinel — the loud-fail contract is the same.

    Raises:
        TypeError: Propagated from "Field()" when a non-native value is
            declared as an argument; this test asserts it is raised and
            names the offending attribute.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import Mutation, field

    class _NotANativeArg:
        """Stand-in for any non-graphql-core arg value (e.g. the legacy
        "graphene.Argument" that v2.0 no longer accepts)."""

    class _CreateWithBadArg(Mutation):
        class Arguments:
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


def test_helper_constant_in_class_args_still_ignored() -> None:
    """Assert that a trivial helper attribute on "class Arguments" is still ignored.

    Only non-native ARG values fail loudly; a plain non-arg helper (the
    graphene-parity skip) must not.

    "props()" strips dunders/underscore helpers; a plain non-arg public
    helper that the graphene path tolerated must remain tolerated so the
    loud-fail only targets genuine arg declarations.

    If this fails, a benign helper attribute would either error out the
    build or leak into the compiled arguments.
    """
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString

    from django_graphex.core import Mutation, field
    from django_graphex.core.mutation import _compile_args

    class Arguments:  # noqa: N801 - mimics a Mutation inner ``class Arguments``
        name = GraphQLArgument(GraphQLNonNull(GraphQLString))
        _private_helper = "ignored by props()"  # underscore → stripped by props()

    compiled = _compile_args(Arguments)
    assert set(compiled) == {"name"}, compiled
    assert isinstance(compiled["name"], GraphQLArgument)

    # Sanity: a Mutation that ONLY declares the native arg still compiles.
    class _CreateOk(Mutation):
        class Arguments:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)

        @staticmethod
        def mutate(root, info, **kw):
            return _CreateOk(ok=True)

    assert "name" in _CreateOk.Field().args


# --------------------------------------------------------------------------- #
# (d) SDL PARITY — native arg SDL byte-identical to graphene.Argument form      #
# --------------------------------------------------------------------------- #
def test_native_arg_sdl_renders_required_string() -> None:
    """Assert that a native "GraphQLArgument" declaration renders the expected arg SDL.

    S-del-backend-11: the graphene-bridge comparison was dropped (the
    graphene backend is deleted). The native "GraphQLNonNull(GraphQLString)"
    arg renders as "a: String!" — the byte-stable shape the graphene form
    used to produce.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    native_arg = GraphQLArgument(GraphQLNonNull(GraphQLString), out_name="a")
    assert _arg_sdl(native_arg) == "probe(a: String!): String"


def test_native_arg_with_default_sdl_renders_default() -> None:
    """Assert that default-value rendering for a native "GraphQLArgument" is byte-stable.

    If this fails, the SDL rendering of a default-valued argument would
    drift from the expected quoted-default shape.
    """
    from graphql import GraphQLArgument, GraphQLString

    native_arg = GraphQLArgument(GraphQLString, default_value="hello", out_name="a")
    assert _arg_sdl(native_arg) == 'probe(a: String = "hello"): String'


def test_full_mutation_field_arg_sdl_renders_expected_shape() -> None:
    """Assert that a whole mutation field's arg SDL renders the expected byte-stable shape.

    S-del-backend-11: the graphene-bridge baseline was dropped (the
    graphene backend is deleted). The native "class Arguments" declaration
    is compiled by "Mutation.Field()" (graphene-free); its arg SDL is
    asserted directly against the expected "name: String!, note: String"
    shape the graphene form produced.

    Raises:
        AssertionError: Propagated from the local "_args_sdl" helper when
            the expected field line is absent from the printed schema.
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

    from django_graphex.core import Mutation, field

    class _NativeArgsMutation(Mutation):
        class Arguments:
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
    assert (
        _args_sdl(native_field.args, "doThing")
        == "name: String!, note: String): String"
    ), "native arg declaration must render the expected byte-stable arg SDL"


# --------------------------------------------------------------------------- #
# (c) native arg builder is graphene-free on the native path                    #
# --------------------------------------------------------------------------- #
def test_compile_args_source_has_no_graphene_import() -> None:
    """Assert that "core/mutation.py"'s "_compile_args" no longer imports graphene.

    CLEAN BREAK: the transitional "from graphene import Argument" is
    gone — the native arg path accepts graphql-core "GraphQLArgument"
    verbatim.
    """
    import inspect

    from django_graphex.core import mutation as mut_mod

    src = inspect.getsource(mut_mod._compile_args)
    assert "import graphene" not in src and "from graphene" not in src, (
        "_compile_args must not import graphene (CLEAN BREAK, S-args-8):\n" + src
    )


def test_mutation_module_has_no_graphene_anywhere() -> None:
    """Assert that no graphene import survives anywhere in "core/mutation.py" source.

    If this fails, a leftover graphene import would linger in the module
    source, contradicting the clean-break goal even if unused at runtime.
    """
    import inspect

    from django_graphex.core import mutation as mut_mod

    src = inspect.getsource(mut_mod)
    assert "import graphene" not in src, (
        "core/mutation.py must be fully graphene-free after S-args-8"
    )
    assert "from graphene" not in src


# --------------------------------------------------------------------------- #
# (b) IMPORT-REMOVAL — graphene blocked via sys.meta_path                        #
# --------------------------------------------------------------------------- #
def test_native_mutation_args_build_with_graphene_blocked() -> None:
    """Assert that compiling a Mutation's native args succeeds with graphene blocked.

    The strongest import-removal proof for the arg path: purge graphene,
    install the blocker, then declare and compile a Mutation whose
    "class Arguments" uses the native "GraphQLArgument" form. Must NOT
    raise — proving the arg compile path imports no graphene.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex.core import Mutation, field

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:

        class _BlockedArgsMutation(Mutation):
            class Arguments:
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


def test_native_declared_field_args_build_with_graphene_blocked() -> None:
    """Assert that compiling a declared scalar field's native args succeeds with graphene blocked.

    The declared-field arg path ("field(..., args={...})" ->
    "_build_scalar_field" -> arg converter) must accept native
    "GraphQLArgument" verbatim without importing graphene.
    """
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core import field
    from django_graphex.core.schema_compiler import _build_scalar_field

    saved = _purge_graphene_modules()
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:
        declared = field(GraphQLString, args={"q": GraphQLArgument(GraphQLString)})
        compiled = _build_scalar_field(declared, source_cls=None, field_name="thing")
        assert "q" in compiled.args
        assert isinstance(compiled.args["q"], GraphQLArgument)
        assert "graphene" not in sys.modules, (
            "compiling declared field args must not import graphene"
        )
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)


def test_args_converter_native_passthrough_no_graphene() -> None:
    """Assert that the arg converter passes a native "GraphQLArgument" through with no graphene import.

    If this fails, the arg converter would either transform the native
    argument unexpectedly or trigger a graphene import as a side effect.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    from django_graphex.core._args import to_graphql_argument

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
