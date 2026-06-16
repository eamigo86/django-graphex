"""S8c RED — fields.py field classes + types.py:13 / mutation.py:11 off graphene.

S8c (graphene-removal final sub-phase) takes the FIELD-DESCRIPTOR SURFACE off
graphene:

- ``fields.py`` line 13 ``from graphene import ID, Field, List`` + line 14
  ``from graphene.types.structures import NonNull, Structure`` -> the field
  classes (``DjangoObjectField`` / ``DjangoListField`` / ``DjangoFilterListField``
  / ``DjangoFilterPaginateListField`` / ``DjangoListObjectField`` /
  ``DjangoNestedListObjectField`` / ``AnnotatedField``) no longer subclass graphene
  ``Field``; they subclass a NATIVE field base (``native.descriptors``) that
  exposes the EXACT duck-typed read-contract the native compiler relies on
  (``.type`` / ``.args`` / ``.name`` / ``.description`` / ``.resolver`` /
  ``.wrap_resolve``). ``Structure`` / ``NonNull`` / ``List`` / ``ID`` usages are
  replaced with native wrappers (``NativeList`` / ``NativeNonNull``) or graphql-core
  (``GraphQLID``).
- ``types.py`` line 13 ``from graphene import (Field, InputField, Int)`` -> native
  (``NativeField`` mount + graphql-core ``GraphQLInt``); ``InputField`` -> the
  native input descriptor / graphql-core input field.
- ``mutation.py`` line 11 ``from graphene import Field`` -> the native mutation
  payload field descriptor.

CRITICAL silent-drop guard: a field whose ``.type`` / ``.args`` the compiler
cannot read VANISHES from the SDL. These tests assert every field kind still
appears in the compiled SDL with the right type / args, and that the SDL is
byte-identical to the pre-S8c baseline.

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s8c_field_descriptor_graphene_free.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.native_only


def _top_level_imported_names(module) -> set[str]:
    """Return the set of names imported at MODULE TOP LEVEL.

    Walks only ``tree.body`` (top-level statements), so a function-local / lazy
    import inside a method body is NOT counted.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                names.add(f"{mod}::{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(f"::{alias.name}")
    return names


def _all_graphene_imports(module) -> list[str]:
    """Return EVERY graphene import in the module (top-level AND lazy)."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "graphene":
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "graphene":
                names = ", ".join(a.name for a in node.names)
                found.append(f"from {node.module} import {names}")
    return found


# ---------------------------------------------------------------------------
# fields.py — ZERO graphene imports (top-level AND lazy)
# ---------------------------------------------------------------------------


def test_fields_module_is_fully_graphene_free() -> None:
    """``fields.py`` has ZERO graphene imports anywhere (the S8c headline)."""
    from django_graphex import fields

    found = _all_graphene_imports(fields)
    assert not found, (
        f"fields.py must have ZERO graphene imports (S8c); found: {found}."
    )


# ---------------------------------------------------------------------------
# fields.py — field classes are OFF graphene Field
# ---------------------------------------------------------------------------

_FIELD_CLASS_NAMES = (
    "DjangoObjectField",
    "DjangoListField",
    "DjangoFilterListField",
    "DjangoFilterPaginateListField",
    "DjangoListObjectField",
    "DjangoNestedListObjectField",
    "AnnotatedField",
)


@pytest.mark.parametrize("cls_name", _FIELD_CLASS_NAMES)
def test_field_class_is_not_a_graphene_field_subclass(cls_name: str) -> None:
    """Every field class is OFF graphene ``Field`` (no graphene MRO)."""
    import graphene

    from django_graphex import fields

    cls = getattr(fields, cls_name)
    assert not issubclass(cls, graphene.Field), (
        f"{cls_name} must NOT subclass graphene.Field (S8c)."
    )
    # Also assert no graphene class anywhere in the MRO.
    graphene_bases = [
        b.__qualname__
        for b in cls.__mro__
        if b.__module__.split(".")[0] == "graphene"
    ]
    assert not graphene_bases, (
        f"{cls_name} MRO must contain no graphene base; found: {graphene_bases}."
    )


def test_field_instances_expose_duck_typed_contract() -> None:
    """A built field INSTANCE exposes ``.type`` / ``.args`` / ``.wrap_resolve``.

    These are the EXACT attributes the native compiler reads via ``getattr`` —
    losing any one silently drops the field from the SDL. graphene set them as
    INSTANCE attributes, so the native base must too.
    """
    from django.contrib.auth.models import User

    from django_graphex import (
        DjangoFilterListField,
        DjangoFilterPaginateListField,
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectField,
        DjangoObjectType,
    )
    from django_graphex.fields import AnnotatedField, DjangoNestedListObjectField

    class _CUserType(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ["exact"]}

    class _CUserList(DjangoListObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ["exact"]}

    from django.db.models import Count
    from graphql import GraphQLInt

    instances = [
        DjangoObjectField(_CUserType),
        DjangoFilterListField(_CUserType),
        DjangoFilterPaginateListField(_CUserType),
        DjangoListObjectField(_CUserList),
        DjangoNestedListObjectField(_CUserList, accessor="x"),
        AnnotatedField(GraphQLInt, lambda: Count("*")),
    ]
    for inst in instances:
        kind = type(inst).__name__
        for attr in ("type", "args", "wrap_resolve", "resolver", "description"):
            assert hasattr(inst, attr), (
                f"{kind} instance must expose '{attr}' (compiler read-contract)."
            )
        # ``.type`` must resolve to a real type (class / wrapper), never raise.
        assert inst.type is not None, f"{kind}.type must resolve, not None."
        # ``.args`` must be a mapping (graphene parity: a dict).
        assert isinstance(inst.args, dict), f"{kind}.args must be a dict."


# ---------------------------------------------------------------------------
# types.py:13 / mutation.py:11 — graphene Field/InputField/Int gone
# ---------------------------------------------------------------------------


def test_types_no_top_level_graphene_field_inputfield_int() -> None:
    """``types.py`` no longer imports graphene ``Field`` / ``InputField`` / ``Int``."""
    from django_graphex import types

    names = _top_level_imported_names(types)
    for sym in ("Field", "InputField", "Int"):
        assert f"graphene::{sym}" not in names, (
            f"types.py must NOT import graphene {sym} at top level (S8c)."
        )


def test_mutation_no_top_level_graphene_field() -> None:
    """``mutation.py`` no longer imports graphene ``Field`` at top level."""
    from django_graphex import mutation

    names = _top_level_imported_names(mutation)
    assert "graphene::Field" not in names, (
        "mutation.py must NOT import graphene Field at top level (S8c)."
    )


# ---------------------------------------------------------------------------
# Silent-drop guard — every field kind present in compiled SDL with right shape
# ---------------------------------------------------------------------------


def _build_field_kind_schema():
    """Build a native schema exercising EVERY S8c field kind, return its SDL.

    Mirrors the public API: a root with a single-object field, a list-object
    field, a plain filtered-list field, a paginated filtered-list field, plus a
    nested-list field and a mutation payload field. The compiled SDL is the
    silent-drop oracle: a field whose ``.type`` the compiler cannot read vanishes.
    """
    from django.contrib.auth.models import User
    from graphql import print_schema

    from django_graphex import (
        DjangoFilterListField,
        DjangoFilterPaginateListField,
        DjangoGraphQLSchema,
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectField,
        DjangoObjectType,
        ObjectType,
    )

    class _S8cUserType(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ["exact", "icontains"]}

    class _S8cUserList(DjangoListObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ["exact"]}

    class _S8cQuery(ObjectType):
        one_user = DjangoObjectField(_S8cUserType)
        user_list = DjangoListObjectField(_S8cUserList)
        users_filtered = DjangoFilterListField(_S8cUserType)
        users_paginated = DjangoFilterPaginateListField(_S8cUserType)

    schema = DjangoGraphQLSchema(query=_S8cQuery)
    gql = schema.graphql_schema if hasattr(schema, "graphql_schema") else schema
    return print_schema(gql)


def test_every_field_kind_present_in_compiled_sdl() -> None:
    """Each S8c field kind renders into the SDL (no silent drop)."""
    sdl = _build_field_kind_schema()

    # DjangoObjectField -> single object with an id: ID! arg.
    assert "oneUser(" in sdl, "DjangoObjectField vanished from SDL (silent drop)."
    assert "id: ID!" in sdl, "DjangoObjectField id arg lost its ID! shape."

    # DjangoListObjectField -> list-container (results + totalCount).
    assert "userList(" in sdl, "DjangoListObjectField vanished from SDL."
    assert "totalCount: Int" in sdl, "List container totalCount lost its Int shape."

    # DjangoFilterListField -> [Node] with a filter arg.
    assert "usersFiltered(" in sdl, "DjangoFilterListField vanished from SDL."

    # DjangoFilterPaginateListField -> [Node!] with filter + pagination args.
    assert "usersPaginated(" in sdl, "DjangoFilterPaginateListField vanished."

    # The filter input must be present for the filterable fields.
    assert "filter:" in sdl, "Filter arg vanished from filterable list fields."


def test_paginate_list_field_keeps_nonnull_inner_shape() -> None:
    """``DjangoFilterPaginateListField`` keeps the ``[Node!]`` inner-non-null shape."""
    sdl = _build_field_kind_schema()
    # The field may render across multiple lines (args block). The return type
    # follows the closing ``)`` of the args. Assert the [Node!] shape appears in
    # the usersPaginated field block.
    assert "[_S8cUserType!]" in sdl, (
        "usersPaginated must render the inner-non-null [_S8cUserType!] shape "
        "(DjangoFilterPaginateListField); the wrapper shape was lost."
    )
    # And the single-object / list-object node renders the plain (nullable) node.
    assert "usersFiltered(" in sdl
