"""S-ROOTS-a RED — native field descriptor (``NativeField``) + ``field()`` helper.

S-ROOTS-a establishes the NATIVE field-descriptor currency the duck-typed
compiler consumes for declared / root fields, replacing the graphene
``UnmountedType`` / ``MountedType`` instances on the LIVE-consumed surface.

The paramount risk is the SILENT FIELD DROP: the compiler reads
``field.type`` / ``field.args`` / ``field.name`` / ``field.description`` /
``field.wrap_resolve(...)`` via ``getattr`` with no ``isinstance(graphene.Field)``
guard. A descriptor whose shape it does NOT recognise vanishes from the compiled
SDL with NO error. These tests PROVE a ``field(...)``-declared field compiles to
the correct graphql-core field through the EXISTING compiler entry points
(``compile_declared_field`` and ``compile_native_root``) — no special-casing
added to the compiler.

Run: .venv/bin/python -m pytest \
    tests/native/test_s_roots_a_descriptors.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect

import pytest

# ---------------------------------------------------------------------------
# Import-safety: descriptors.py must NOT import graphene at module top level
# ---------------------------------------------------------------------------


def test_descriptors_module_has_no_top_level_graphene_import() -> None:
    """``native.descriptors`` is the native currency — zero top-level graphene.

    The module is part of the import path of ``django_graphex`` under BOTH
    backends, so a top-level ``import graphene`` would break import-safety when
    graphene is uninstalled (S8). Enforce it via AST so a regression is caught
    even if graphene happens to be installed.
    """
    from django_graphex.native import descriptors

    source = inspect.getsource(descriptors)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.split(".")[0] == "graphene", (
                    f"descriptors.py must NOT import graphene at module top level "
                    f"(found `import {alias.name}`)."
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "graphene", (
                f"descriptors.py must NOT import graphene at module top level "
                f"(found `from {node.module} import ...`)."
            )


# ---------------------------------------------------------------------------
# NativeField read-contract: the compiler reads .type/.args/.name/.description/
# .wrap_resolve — the descriptor must expose each precisely.
# ---------------------------------------------------------------------------


def test_native_field_exposes_compiler_read_contract() -> None:
    """``NativeField`` exposes EXACTLY the attrs/methods the compiler reads."""
    from graphql import GraphQLString

    from django_graphex.native.descriptors import NativeField

    f = NativeField(GraphQLString, description="a server time")
    assert f.type is GraphQLString
    assert f.args is None
    assert f.name is None
    assert f.description == "a server time"
    # wrap_resolve mirrors graphene Field: own resolver wins, else parent.
    sentinel_parent = object()
    assert f.wrap_resolve(sentinel_parent) is sentinel_parent


def test_native_field_wrap_resolve_prefers_own_resolver() -> None:
    """``wrap_resolve`` returns the field's own resolver over the parent."""
    from graphql import GraphQLString

    from django_graphex.native.descriptors import NativeField

    def my_resolver(root, info):  # pragma: no cover - identity only
        return "x"

    f = NativeField(GraphQLString, resolver=my_resolver)
    parent = object()
    assert f.wrap_resolve(parent) is my_resolver


def test_native_field_explicit_name_and_args() -> None:
    """``NativeField`` carries an explicit wire ``name`` and an ``args`` dict."""
    from graphql import GraphQLArgument, GraphQLInt, GraphQLString

    from django_graphex.native.descriptors import NativeField

    args = {"limit": GraphQLArgument(GraphQLInt)}
    f = NativeField(GraphQLString, name="serverTime", args=args)
    assert f.name == "serverTime"
    assert f.args == args


# ---------------------------------------------------------------------------
# field() helper: the public API (decision #1554).
# ---------------------------------------------------------------------------


def test_field_helper_produces_native_field() -> None:
    """``field(type, ...)`` returns a ``NativeField`` with the given attrs."""
    from graphql import GraphQLString

    from django_graphex.native.descriptors import NativeField, field

    f = field(GraphQLString, description="hello")
    assert isinstance(f, NativeField)
    assert f.type is GraphQLString
    assert f.description == "hello"


def test_field_helper_resolves_django_object_ref_lazily() -> None:
    """``field(DjangoObjectType)`` resolves ``.type`` to the compiled gql type."""
    from graphql import GraphQLObjectType

    from django_graphex.native.descriptors import field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _FieldRefCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    f = field(_FieldRefCatType)
    resolved = f.type
    assert isinstance(resolved, GraphQLObjectType)
    assert resolved is _FieldRefCatType._meta.graphql_output_type


# ---------------------------------------------------------------------------
# SILENT-DROP GUARD: a field(...)-declared field compiles to the correct
# graphql-core field through the EXISTING compiler entry points.
# ---------------------------------------------------------------------------


def test_compile_declared_field_for_native_scalar_field() -> None:
    """``compile_declared_field`` compiles ``field(GraphQLString)`` correctly.

    This is the duck-typed seam (schema_compiler.py:369/404): no graphene
    isinstance — the descriptor must drop straight in.
    """
    from graphql import GraphQLField, GraphQLString

    from django_graphex.native.descriptors import field
    from django_graphex.native.schema_compiler import compile_declared_field

    nf = field(GraphQLString, description="server time")

    class _Src:
        pass

    gql_field = compile_declared_field(_Src, "server_time", nf)
    assert isinstance(gql_field, GraphQLField)
    assert gql_field.type is GraphQLString
    assert gql_field.description == "server time"


def test_compile_declared_field_for_native_list_field() -> None:
    """``compile_declared_field`` preserves a ``GraphQLList`` wrapper shape."""
    from graphql import GraphQLField, GraphQLList, GraphQLString

    from django_graphex.native.descriptors import field
    from django_graphex.native.schema_compiler import compile_declared_field

    nf = field(GraphQLList(GraphQLString))

    class _Src:
        pass

    gql_field = compile_declared_field(_Src, "tags", nf)
    assert isinstance(gql_field, GraphQLField)
    assert isinstance(gql_field.type, GraphQLList)
    assert gql_field.type.of_type is GraphQLString


@pytest.mark.django_db
def test_native_root_compiles_field_declared_object_and_scalar_and_list() -> None:
    """SILENT-DROP GUARD: a root carrying field(...) descriptors compiles fully.

    Declares a throwaway ``graphene.ObjectType`` root and injects three
    ``field(...)`` descriptors into its ``_meta.fields`` (the dict the compiler
    iterates). Compiles it through the EXISTING ``compile_native_root`` and
    asserts every declared field lands in the compiled SDL with the right type —
    proving the descriptor matches the compiler's read-contract and does NOT
    silently vanish.
    """
    import graphene
    from graphql import (
        GraphQLList,
        GraphQLObjectType,
        GraphQLString,
    )

    from django_graphex.native.descriptors import field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _RootsACatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _RootsAQuery(graphene.ObjectType):
        pass

    # Inject the native descriptors into the graphene root's _meta.fields — the
    # exact dict compile_native_root iterates. (S-ROOTS-f will mount these from
    # a native ObjectType body; here we drive the compiler directly so the
    # read-contract is proven in isolation.)
    _RootsAQuery._meta.fields["server_time"] = field(
        GraphQLString, description="now"
    )
    _RootsAQuery._meta.fields["me"] = field(_RootsACatType)
    _RootsAQuery._meta.fields["tags"] = field(GraphQLList(GraphQLString))

    native_root = compile_native_root(_RootsAQuery, name="Query")
    assert isinstance(native_root, GraphQLObjectType)

    # NONE of the three may have silently dropped.
    assert "serverTime" in native_root.fields, "scalar field(...) was DROPPED"
    assert "me" in native_root.fields, "object field(...) was DROPPED"
    assert "tags" in native_root.fields, "list field(...) was DROPPED"

    # Types are correct.
    assert native_root.fields["serverTime"].type is GraphQLString
    me_type = native_root.fields["me"].type
    assert isinstance(me_type, GraphQLObjectType)
    assert me_type is _RootsACatType._meta.graphql_output_type
    tags_type = native_root.fields["tags"].type
    assert isinstance(tags_type, GraphQLList)
    assert tags_type.of_type is GraphQLString


# ---------------------------------------------------------------------------
# _args._unwrap_graphene_type generalization: native graphql-core types pass
# through as-is; graphene path stays as a fallback.
# ---------------------------------------------------------------------------


def test_unwrap_passes_through_native_scalar() -> None:
    """``_unwrap_graphene_type`` returns a graphql-core scalar unchanged."""
    from graphql import GraphQLString

    from django_graphex.native._args import _unwrap_graphene_type

    assert _unwrap_graphene_type(GraphQLString) is GraphQLString


def test_unwrap_passes_through_native_wrappers() -> None:
    """``_unwrap_graphene_type`` returns graphql-core List/NonNull unchanged."""
    from graphql import GraphQLList, GraphQLNonNull, GraphQLString

    from django_graphex.native._args import _unwrap_graphene_type

    wrapped = GraphQLNonNull(GraphQLList(GraphQLString))
    assert _unwrap_graphene_type(wrapped) is wrapped


def test_unwrap_rejects_graphene_scalar_clean_break() -> None:
    """The graphene leaf path is DELETED — a graphene scalar raises TypeError.

    S-del-backend-11: ``_unwrap_graphene_type`` no longer converts graphene types
    (the v2.0 CLEAN BREAK, decision #1603); it returns graphql-core types verbatim
    and rejects anything else. A leftover ``graphene.String`` raises ``TypeError``.
    """
    import graphene
    import pytest

    from django_graphex.native._args import _unwrap_graphene_type

    with pytest.raises(TypeError, match="Cannot convert"):
        _unwrap_graphene_type(graphene.String)
