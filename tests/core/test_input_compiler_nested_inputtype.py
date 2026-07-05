"""Tests for InputType-referencing-InputType resolution in "compile_input_type".

Covers a CONFIRMED, data-corrupting defect in "core/input_compiler.py": a
hand-authored input field whose annotation is ANOTHER input model (an
"InputType" subclass, or any "pydantic.BaseModel" subclass) silently
compiled to "GraphQLString" instead of the child's compiled
"GraphQLInputObjectType" -- with ZERO warnings.

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        inner: Inner          # -> "inner: String!"  (WRONG)
        items: list[Inner]    # -> "items: [String!]!" (WRONG)

Root cause: "_python_type_to_gql" (and the list-element path) had no branch
for a "BaseModel" subclass, so both fell through to the "GraphQLString"
fallback. A client's structured object was then coerced against "String" and
either rejected or flattened -- silent data corruption.

Contract asserted here:

1. SDL — "Outer" renders "inner: Inner!" and "items: [Inner!]!" (the child
   input type, NOT "String"); "Optional[Inner]" renders nullable "Inner".
2. COMPILE ORDER — "Inner" declared AFTER "Outer" in source order (and
   compiled after it via "compile_all_inputs" registration order) still
   resolves, because the field thunk defers resolution until schema assembly.
3. E2E — a mutation passing a nested structured object BOTH via "variables"
   AND as an inline literal reaches the resolver as parsed "dict" values
   (snake "out_name" keys), never a "String".
4. TRULY-UNKNOWN — a non-"BaseModel" class annotation still falls back to
   "GraphQLString" but now emits a LOUD warning (captured via
   "pytest.warns") instead of a silent String.

These are model-free Pydantic "BaseModel" tests -- no Django settings needed.

Run with:
    .venv/bin/python -m pytest tests/core/test_input_compiler_nested_inputtype.py -x -v
"""

from __future__ import annotations

from typing import Optional

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_type,
)
from pydantic import BaseModel

from django_graphex.core.input_compiler import compile_input_type

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _exec_outer(query: str, *, variable_values: dict | None = None) -> tuple:
    """Run ``query`` against a one-field Query whose arg is the ``Outer`` input.

    Returns ``(errors, captured_dict)`` where ``captured_dict`` is the coerced
    argument value graphql-core delivered to the resolver -- nested input
    objects arrive as plain ``dict`` values keyed by the child ``out_name``.
    """

    class Inner(BaseModel):
        first_val: int

    class Outer(BaseModel):
        inner: Inner
        items: list[Inner]

    inp = compile_input_type(Outer, name="ExecOuterInput")
    captured: dict = {}

    def _resolve(_root, _info, flt):  # noqa: ANN001
        captured.update(flt)
        return "ok"

    query_type = GraphQLObjectType(
        "Query",
        lambda: {
            "probe": GraphQLField(
                GraphQLString,
                args={"flt": GraphQLArgument(inp)},
                resolve=_resolve,
            )
        },
    )
    result = graphql_sync(
        GraphQLSchema(query=query_type), query, variable_values=variable_values
    )
    return result.errors, captured


# ---------------------------------------------------------------------------
# 1. SDL — nested single + list resolve to the child input type
# ---------------------------------------------------------------------------


def test_single_nested_input_renders_child_input_type() -> None:
    """Protect the core defect fix: "inner: Inner" -> "inner: Inner!", not String.

    If this regresses, a required nested-input field would silently degrade
    back to the GraphQLString fallback, corrupting any structured object a
    client submits for it.
    """

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        inner: Inner

    sdl = print_type(compile_input_type(Outer, name="SingleNestedOuter"))
    assert "inner: Inner!" in sdl, sdl
    assert "inner: String" not in sdl, sdl


def test_list_of_nested_input_renders_child_input_list() -> None:
    """Protect the list variant of the fix: "items: list[Inner]" -> "items: [Inner!]!".

    If this regresses, a list of nested-input objects would silently degrade
    back to "[String!]!", corrupting every structured object a client
    submits in the list.
    """

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        items: list[Inner]

    sdl = print_type(compile_input_type(Outer, name="ListNestedOuter"))
    assert "items: [Inner!]!" in sdl, sdl
    assert "items: [String!]!" not in sdl, sdl


def test_optional_nested_input_is_nullable() -> None:
    """Protect that "Optional[Inner]" renders as nullable "inner: Inner" (no outer NonNull).

    If this regresses, an Optional nested-input field could be wrapped in
    GraphQLNonNull, forcing clients to always supply a value the model
    treats as optional.
    """

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        inner: Optional[Inner] = None

    sdl = print_type(compile_input_type(Outer, name="OptNestedOuter"))
    assert "inner: Inner\n" in sdl or sdl.rstrip().endswith("inner: Inner"), sdl
    assert "inner: Inner!" not in sdl, sdl


def test_nested_child_input_carries_child_fields() -> None:
    """Protect that the resolved child input type exposes the child's own fields.

    If this regresses, the compiled child GraphQLInputObjectType could
    resolve as an empty or wrong-shaped type, even though its top-level name
    (e.g. "Inner!") renders correctly in the SDL.
    """

    class Inner(BaseModel):
        a: int
        b: str

    class Outer(BaseModel):
        inner: Inner

    outer = compile_input_type(Outer, name="ChildFieldsOuter")
    inner_field = outer.fields["inner"].type
    child = (
        inner_field.of_type if isinstance(inner_field, GraphQLNonNull) else inner_field
    )
    assert isinstance(child, GraphQLInputObjectType), child
    # Fields carry the camelCase alias but the a/b snake out_names.
    out_names = {f.out_name for f in child.fields.values()}
    assert {"a", "b"} <= out_names, out_names


# ---------------------------------------------------------------------------
# 2. COMPILE ORDER — child declared / compiled AFTER the parent
# ---------------------------------------------------------------------------


def test_child_compiled_after_parent_still_resolves() -> None:
    """Protect that "Inner" compiled AFTER "Outer" still resolves to the child input type.

    Mirrors "compile_all_inputs" registration order: the parent may be
    compiled before the child. The parent's field thunk defers child resolution
    until schema assembly ("print_type" forces it), so order does not matter.
    If this regresses, a registration-order dependency would reappear,
    breaking any schema where a parent input type is compiled before its
    child.
    """

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        inner: Inner
        items: list[Inner]

    # Compile the PARENT first (child not yet compiled/registered).
    outer = compile_input_type(Outer, name="OrderOuter")
    # Now compile the child (simulating the second pass reaching it later).
    compile_input_type(Inner, name="OrderInner")

    # Forcing the parent's fields (schema-assembly time) must resolve to the
    # child input type regardless of the compile order above.
    sdl = print_type(outer)
    assert "inner: Inner!" in sdl, sdl
    assert "items: [Inner!]!" in sdl, sdl
    assert "String" not in sdl.split("input OrderOuter")[1].split("}")[0], sdl


# ---------------------------------------------------------------------------
# 3. E2E — structured object reaches the resolver as parsed dicts
# ---------------------------------------------------------------------------


def test_nested_object_via_variables_reaches_resolver_as_dicts() -> None:
    """Protect the E2E variables path: a nested structured object arrives as parsed dicts.

    If this regresses, a nested object passed through GraphQL "variables"
    could reach the resolver as a raw string or the wrong shape instead of a
    dict keyed by the child's snake out_name.
    """

    query = """
        query ($flt: ExecOuterInput!) {
          probe(flt: $flt)
        }
    """
    errors, captured = _exec_outer(
        query,
        variable_values={
            "flt": {
                "inner": {"firstVal": 3},
                "items": [{"firstVal": 1}, {"firstVal": 2}],
            }
        },
    )
    assert errors is None, errors
    # Nested single + list arrive as dicts keyed by the child snake out_name.
    assert captured["inner"] == {"first_val": 3}, captured
    assert captured["items"] == [{"first_val": 1}, {"first_val": 2}], captured


def test_nested_object_inline_literal_reaches_resolver_as_dicts() -> None:
    """Protect the E2E inline-literal path: a nested structured object arrives as dicts.

    If this regresses, a nested object passed as an inline GraphQL query
    literal could reach the resolver as a raw string or the wrong shape
    instead of a dict keyed by the child's snake out_name.
    """

    query = """
        query {
          probe(flt: {
            inner: { firstVal: 7 }
            items: [{ firstVal: 8 }, { firstVal: 9 }]
          })
        }
    """
    errors, captured = _exec_outer(query)
    assert errors is None, errors
    assert captured["inner"] == {"first_val": 7}, captured
    assert captured["items"] == [{"first_val": 8}, {"first_val": 9}], captured


# ---------------------------------------------------------------------------
# 4. TRULY-UNKNOWN — non-BaseModel class warns + String fallback
# ---------------------------------------------------------------------------


def test_unknown_class_warns_and_falls_back_to_string() -> None:
    """A truly-unknown (non-BaseModel) class annotation warns AND yields String.

    The unknown-type fallback is documented behavior: keep the schema buildable
    with "GraphQLString" BUT emit a loud warning instead of silently degrading
    a structured field to a string.
    """

    class NotAnInput:  # plain class, NOT a pydantic BaseModel
        pass

    class M(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        blob: NotAnInput

    with pytest.warns(UserWarning, match="NotAnInput"):
        result = compile_input_type(M, name="UnknownClassInput")
        # Force the field thunk so the warning fires at build time.
        field_type = result.fields["blob"].type

    inner = field_type.of_type if isinstance(field_type, GraphQLNonNull) else field_type
    assert inner is GraphQLString, inner
    assert isinstance(inner, GraphQLScalarType), inner


def test_list_of_unknown_class_warns_and_falls_back_to_string() -> None:
    """Protect that a list of a truly-unknown class warns AND yields a "[String!]" list.

    If this regresses, a list of an unrecognized class annotation could
    either silently degrade without warning or raise instead of falling
    back to the documented "[String!]" scalar list.
    """

    class NotAnInput:
        pass

    class M(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        blobs: list[NotAnInput]

    with pytest.warns(UserWarning, match="NotAnInput"):
        result = compile_input_type(M, name="UnknownListInput")
        field_type = result.fields["blobs"].type

    outer = field_type.of_type if isinstance(field_type, GraphQLNonNull) else field_type
    assert isinstance(outer, GraphQLList), outer
    element = outer.of_type
    element = element.of_type if isinstance(element, GraphQLNonNull) else element
    assert element is GraphQLString, element
