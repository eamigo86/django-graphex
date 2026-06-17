"""S-ROOTS-b RED — native ``ErrorType`` + native-marker on ``_is_plain_object_type``.

S-ROOTS-b is the SILENT-DROP EPICENTER of the descriptor-surface conversion
(#1553). Two coupled changes are proven here:

1. ``ErrorType`` (the mutation error payload ``{field, messages}``) becomes a
   NATIVE ``ObjectType`` (``django_graphex.native.base.ObjectType`` subclass,
   metaclass ``pydantic.ModelMetaclass``) — NO ``graphene.ObjectType`` base, NO
   ``import graphene`` in ``errors.py``. The value-object constructor
   ``ErrorType(field=..., messages=...)`` MUST still round-trip because it is
   instantiated at runtime by ``nested.py`` / ``utils.py`` / ``native/backend.py``.

2. ``schema_compiler._is_plain_object_type`` gains a NATIVE-MARKER branch that
   recognises a native ``ObjectType`` (like ErrorType) BEFORE the transitional
   ``issubclass(graphene.ObjectType)`` fallback, so it routes to the object arm
   (``_compile_plain_object_type``) — NOT the scalar arm where
   ``_unwrap_graphene_type`` would KeyError, dropping the field silently.

PARAMOUNT GUARD: the compiler is duck-typed; a mis-classified native ErrorType
would either KeyError in the scalar arm OR vanish from the compiled SDL. The
final test compiles a payload carrying ``errors = List(ErrorType)`` and asserts
the ``errors`` field IS present with element type = the ErrorType
``GraphQLObjectType`` (field + messages). It FAILS if ErrorType is mis-routed.

Run: .venv/bin/python -m pytest \
    tests/native/test_s_roots_b_native_errortype.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect

import pytest

# ---------------------------------------------------------------------------
# ErrorType is NATIVE (pydantic ModelMetaclass, NOT a graphene.ObjectType)
# ---------------------------------------------------------------------------


def test_errortype_metaclass_is_pydantic_model_metaclass() -> None:
    """``type(ErrorType) is pydantic ModelMetaclass`` (the native-base identity)."""
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.errors import ErrorType

    assert type(ErrorType) is ModelMetaclass


def test_errortype_is_native_objecttype_subclass() -> None:
    """``ErrorType`` subclasses the native ``ObjectType`` base, not graphene's."""
    from django_graphex.errors import ErrorType
    from django_graphex.native.base import ObjectType as NativeObjectType

    assert issubclass(ErrorType, NativeObjectType)


def test_errortype_is_not_graphene_objecttype() -> None:
    """``ErrorType`` is NOT a graphene class (it left graphene).

    Asserted via MRO ``__module__`` strings so the gate never imports graphene —
    it must hold with graphene ABSENT (v2.0).
    """
    from django_graphex.errors import ErrorType

    graphene_bases = [
        b.__qualname__
        for b in ErrorType.__mro__
        if b.__module__.split(".")[0] == "graphene"
    ]
    assert not graphene_bases, (
        f"ErrorType MRO must contain no graphene base; found: {graphene_bases}."
    )


# ---------------------------------------------------------------------------
# errors.py is graphene-free (import-safety under both backends + after S8)
# ---------------------------------------------------------------------------


def test_errors_module_has_no_graphene_import() -> None:
    """``errors.py`` must NOT import graphene at module top level (AST check).

    The module imports cleanly under BOTH backends and after graphene is
    uninstalled (S8). Enforced via AST so a regression is caught even with
    graphene installed.
    """
    from django_graphex import errors

    source = inspect.getsource(errors)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "graphene", (
                    f"errors.py must NOT import graphene (found `import {alias.name}`)."
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "graphene", (
                f"errors.py must NOT import graphene "
                f"(found `from {node.module} import ...`)."
            )


# ---------------------------------------------------------------------------
# Value-object constructor round-trip — the runtime contract callers depend on
# ---------------------------------------------------------------------------


def test_errortype_value_object_ctor_roundtrip() -> None:
    """``ErrorType(field=, messages=)`` round-trips via attribute access.

    nested.py:360 reads ``error.messages``; nested.py:358 reads ``error.field``
    via getattr. native/backend.py:29 / utils.py:136 construct it. The native
    container ``__init__`` (S6a/S6c) must stash these as plain instance attrs.
    """
    from django_graphex.errors import ErrorType

    e = ErrorType(field="title", messages=["This field is required.", "too long"])
    assert e.field == "title"
    assert e.messages == ["This field is required.", "too long"]


def test_errortype_field_in_meta_fields() -> None:
    """The native ErrorType exposes ``field`` + ``messages`` in ``_meta.fields``.

    ``_compile_plain_object_type`` iterates ``_meta.fields`` to build the
    GraphQLObjectType — both wire fields must be present or the compiled
    ErrorType would be missing a field.
    """
    from django_graphex.errors import ErrorType

    field_names = set(ErrorType._meta.fields)
    assert "field" in field_names
    assert "messages" in field_names


# ---------------------------------------------------------------------------
# Native-marker branch on _is_plain_object_type — the silent-drop epicenter
# ---------------------------------------------------------------------------


def test_is_plain_object_type_recognises_native_errortype() -> None:
    """``_is_plain_object_type(ErrorType)`` is True via the NATIVE marker.

    Before S-ROOTS-b this relied on ``issubclass(graphene.ObjectType)``; a native
    ErrorType is NOT a graphene class, so without the native-marker branch this
    returns False and the field routes to the scalar arm → KeyError / silent drop.
    """
    from django_graphex.errors import ErrorType
    from django_graphex.native.schema_compiler import _is_plain_object_type

    assert _is_plain_object_type(ErrorType) is True


def test_is_plain_object_type_excludes_native_input_type() -> None:
    """A native ``InputType`` must NOT be classified as a plain OUTPUT object.

    InputType subclasses the same native base; the native marker must exclude it
    so an input never mis-routes into the output-object arm.
    """
    from django_graphex.native.base import InputType
    from django_graphex.native.schema_compiler import _is_plain_object_type

    class _SomeInput(InputType):
        x: int = 0

    assert _is_plain_object_type(_SomeInput) is False


def test_is_plain_object_type_excludes_non_class() -> None:
    """Non-class field types (wrappers / scalars) are not plain objects."""
    from graphql import GraphQLString

    from django_graphex.native.schema_compiler import _is_plain_object_type

    assert _is_plain_object_type(GraphQLString) is False


# ---------------------------------------------------------------------------
# SILENT-DROP GUARD: errors = List(ErrorType) compiles to correct SDL
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_errortype_compiles_to_object_type_with_both_fields() -> None:
    """A ``NativeList(ErrorType)`` field compiles to a list of the ErrorType object.

    Routes through the EXISTING ``_compile_wrapped_field_type`` (the
    ``errors: [ErrorType]`` mutation-payload path). Asserts the inner element is a
    ``GraphQLObjectType`` named ``ErrorType`` carrying BOTH ``field`` and
    ``messages`` — proving the native ErrorType lands in the object arm, NOT the
    scalar arm (which would KeyError) and does NOT silently vanish.

    S-del-backend-11: the graphene ``List(ErrorType)`` wrapper was replaced with
    the native ``NativeList(ErrorType)`` wrapper (the graphene-root/wrapper compile
    capability was removed; the native ``errors = field(NativeList(ErrorType))``
    idiom is how the payload declares it now).
    """
    from graphql import GraphQLList, GraphQLObjectType

    from django_graphex.errors import ErrorType
    from django_graphex.native.descriptors import NativeList
    from django_graphex.native.schema_compiler import _compile_wrapped_field_type

    wrapped = NativeList(ErrorType)
    compiled = _compile_wrapped_field_type(wrapped)

    assert isinstance(compiled, GraphQLList), "List wrapper shape lost"
    element = compiled.of_type
    assert isinstance(element, GraphQLObjectType), (
        "ErrorType mis-routed: inner element is not a GraphQLObjectType "
        "(would mean it fell into the scalar arm / silently dropped)."
    )
    assert element.name == "ErrorType"
    assert "field" in element.fields, "ErrorType.field DROPPED"
    assert "messages" in element.fields, "ErrorType.messages DROPPED"


@pytest.mark.django_db
def test_modeltype_errors_field_present_in_compiled_payload() -> None:
    """A real mutation payload's ``errors`` field survives native compilation.

    Declares a ``DjangoModelType`` (which carries ``errors = List(ErrorType)``)
    and compiles its declared fields. The compiled ``errors`` field MUST be
    present with element type = the ErrorType GraphQLObjectType. This is the
    end-to-end silent-drop guard at a real mutation-payload site.
    """
    from graphql import GraphQLList, GraphQLObjectType

    from django_graphex.native.schema_compiler import compile_declared_field
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _RootsBCatModelType(DjangoModelType):
        class Meta:
            model = Category

    # The `errors` descriptor is mounted into _meta.fields by the native base.
    errors_field = _RootsBCatModelType._meta.fields["errors"]
    compiled = compile_declared_field(_RootsBCatModelType, "errors", errors_field)

    assert isinstance(compiled.type, GraphQLList), "errors lost its List wrapper"
    element = compiled.type.of_type
    assert isinstance(element, GraphQLObjectType), "errors element mis-routed"
    assert element.name == "ErrorType"
    assert "field" in element.fields
    assert "messages" in element.fields
