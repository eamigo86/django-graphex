"""S-ROOTS-a RED — native field descriptor ("NativeField") + "field()" helper.

S-ROOTS-a establishes the NATIVE field-descriptor currency the duck-typed
compiler consumes for declared / root fields, replacing the graphene
"UnmountedType" / "MountedType" instances on the LIVE-consumed surface.

The paramount risk is the SILENT FIELD DROP: the compiler reads
"field.type" / "field.args" / "field.name" / "field.description" /
"field.wrap_resolve(...)" via "getattr" with no "isinstance(graphene.Field)"
guard. A descriptor whose shape it does NOT recognise vanishes from the compiled
SDL with NO error. These tests PROVE a "field(...)"-declared field compiles to
the correct graphql-core field through the EXISTING compiler entry points
("compile_declared_field" and "compile_native_root") — no special-casing
added to the compiler.

Run: .venv/bin/python -m pytest \
    tests/core/test_s_roots_a_descriptors.py -q -o addopts=""
"""

from __future__ import annotations

import ast
import inspect

import pytest

# ---------------------------------------------------------------------------
# Import-safety: descriptors.py must NOT import graphene at module top level
# ---------------------------------------------------------------------------


def test_descriptors_module_has_no_top_level_graphene_import() -> None:
    """The "native.descriptors" module is the native currency — zero top-level graphene.

    The module is part of the import path of "django_graphex" under BOTH
    backends, so a top-level "import graphene" would break import-safety when
    graphene is uninstalled (S8). Enforce it via AST so a regression is caught
    even if graphene happens to be installed.
    """
    from django_graphex.core import descriptors

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
    """Assert that "NativeField" exposes exactly the attrs the compiler reads.

    Ships broken if the descriptor stops carrying "type"/"args"/"name"/
    "description"/"wrap_resolve" with the exact shape the duck-typed compiler
    reads via getattr.
    """
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField

    f = NativeField(GraphQLString, description="a server time")
    assert f.type is GraphQLString
    assert f.args is None
    assert f.name is None
    assert f.description == "a server time"
    # wrap_resolve mirrors graphene Field: own resolver wins, else parent.
    sentinel_parent = object()
    assert f.wrap_resolve(sentinel_parent) is sentinel_parent


def test_native_field_wrap_resolve_prefers_own_resolver() -> None:
    """Assert that "wrap_resolve" returns the field's own resolver over the parent.

    Ships broken if a field carrying an explicit resolver stops taking
    priority over the parent resolver passed into "wrap_resolve".
    """
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField

    def my_resolver(root, info):  # pragma: no cover - identity only
        return "x"

    f = NativeField(GraphQLString, resolver=my_resolver)
    parent = object()
    assert f.wrap_resolve(parent) is my_resolver


def test_native_field_explicit_name_and_args() -> None:
    """Assert that "NativeField" carries an explicit wire "name" and "args" dict.

    Ships broken if an explicitly passed "name" or "args" mapping stops being
    stored verbatim on the descriptor.
    """
    from graphql import GraphQLArgument, GraphQLInt, GraphQLString

    from django_graphex.core.descriptors import NativeField

    args = {"limit": GraphQLArgument(GraphQLInt)}
    f = NativeField(GraphQLString, name="serverTime", args=args)
    assert f.name == "serverTime"
    assert f.args == args


# ---------------------------------------------------------------------------
# field() helper: the public API (decision #1554).
# ---------------------------------------------------------------------------


def test_field_helper_produces_native_field() -> None:
    """Assert that "field(type, ...)" returns a "NativeField" with the given attrs.

    Ships broken if the public "field" helper stops producing a "NativeField"
    instance or drops the "type"/"description" it was called with.
    """
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField, field

    f = field(GraphQLString, description="hello")
    assert isinstance(f, NativeField)
    assert f.type is GraphQLString
    assert f.description == "hello"


def test_field_helper_resolves_django_object_ref_lazily() -> None:
    """Assert that "field(DjangoObjectType)" resolves ".type" to the compiled type.

    Ships broken if a "field(...)" descriptor built from a "DjangoObjectType"
    reference stops resolving its ".type" attribute to the compiled
    GraphQLObjectType once compilation has run.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core.descriptors import field
    from django_graphex.core.registry_compiler import compile_all_outputs
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
    """Assert that "compile_declared_field" compiles "field(GraphQLString)" correctly.

    This is the duck-typed seam (schema_compiler.py:369/404): no graphene
    isinstance — the descriptor must drop straight in.
    """
    from graphql import GraphQLField, GraphQLString

    from django_graphex.core.descriptors import field
    from django_graphex.core.schema_compiler import compile_declared_field

    nf = field(GraphQLString, description="server time")

    class _Src:
        pass

    gql_field = compile_declared_field(_Src, "server_time", nf)
    assert isinstance(gql_field, GraphQLField)
    assert gql_field.type is GraphQLString
    assert gql_field.description == "server time"


def test_compile_declared_field_for_native_list_field() -> None:
    """Assert that "compile_declared_field" preserves a "GraphQLList" wrapper shape.

    Ships broken if compiling a "field(GraphQLList(...))" descriptor stops
    wrapping the compiled field type in a "GraphQLList".
    """
    from graphql import GraphQLField, GraphQLList, GraphQLString

    from django_graphex.core.descriptors import field
    from django_graphex.core.schema_compiler import compile_declared_field

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

    Declares a native "ObjectType" root with three "field(...)" descriptors in
    its class body. Compiles it through the EXISTING "compile_native_root" and
    asserts every declared field lands in the compiled SDL with the right type —
    proving the descriptor matches the compiler's read-contract and does NOT
    silently vanish.

    v2.0: the root is a native "django_graphex.ObjectType" (the graphene-root
    compile capability was removed, decision #1603).
    """
    from graphql import (
        GraphQLList,
        GraphQLObjectType,
        GraphQLString,
    )

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.descriptors import field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _RootsACatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _RootsAQuery(_NativeRoot):
        server_time = field(GraphQLString, description="now")
        me = field(_RootsACatType)
        tags = field(GraphQLList(GraphQLString))

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
# _args._unwrap_graphql_type generalization: native graphql-core types pass
# through as-is; graphene path stays as a fallback.
# ---------------------------------------------------------------------------


def test_unwrap_passes_through_native_scalar() -> None:
    """Assert that "_unwrap_graphql_type" returns a graphql-core scalar unchanged.

    Ships broken if a native graphql-core scalar stops passing through
    "_unwrap_graphql_type" as-is (identity preserved).
    """
    from graphql import GraphQLString

    from django_graphex.core._args import _unwrap_graphql_type

    assert _unwrap_graphql_type(GraphQLString) is GraphQLString


def test_unwrap_passes_through_native_wrappers() -> None:
    """Assert that "_unwrap_graphql_type" returns graphql-core List/NonNull unchanged.

    Ships broken if a wrapped native type ("GraphQLNonNull(GraphQLList(...))")
    stops passing through "_unwrap_graphql_type" with its identity preserved.
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLString

    from django_graphex.core._args import _unwrap_graphql_type

    wrapped = GraphQLNonNull(GraphQLList(GraphQLString))
    assert _unwrap_graphql_type(wrapped) is wrapped


def test_unwrap_rejects_non_native_type_clean_break() -> None:
    """The graphene leaf path is DELETED — a non-native type raises TypeError.

    S-del-backend-11: "_unwrap_graphql_type" no longer converts graphene types
    (the v2.0 CLEAN BREAK, decision #1603); it returns graphql-core types verbatim
    and rejects anything else. graphene is gone, so a generic non-native value
    (the stand-in for the legacy "graphene.String") raises "TypeError".
    """
    import pytest

    from django_graphex.core._args import _unwrap_graphql_type

    class _NotAGraphQLType:
        """No graphql-core type identity."""

    with pytest.raises(TypeError, match="Cannot convert"):
        _unwrap_graphql_type(_NotAGraphQLType())
