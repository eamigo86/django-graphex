"""Tests for list-typed input fields and field defaults in "compile_input_type".

Covers two defects in "core/input_compiler.py" (base "model_fields" loop):

1. LIST HANDLING — a "list[T]" / "typing.List[T]" / "Optional[list[T]]"
   annotation must compile to a GraphQL list type, not the scalar "String"
   fallback. Required lists render "[Inner!]!" (list NonNull, inner NonNull,
   mirroring the relation-list inner-NonNull precedent at :503-504); an
   "Optional"/defaulted list renders "[Inner!]" (nullable list); a
   nested-optional inner ("list[T | None]") renders "[Inner]" (nullable
   element).

2. DEFAULTS — the Pydantic v2 field default must reach "GraphQLInputField
   .default_value" so the SDL renders "= <value>": a concrete default ("1"),
   "False" ("= false"), explicit "None" ("= null"), and a
   "default_factory" (evaluated ONCE at compile time). A field with no default
   renders with no "= ..." marker (graphql-core "Undefined").

These are SDL-level ("print_type") + behavior-level (executing a GraphQL
argument through "graphql_sync") tests. No Django settings required — the
input models are model-free Pydantic "BaseModel" subclasses.

Run with:
    .venv/bin/python -m pytest tests/core/test_input_compiler_lists_defaults.py -x -v
"""

from __future__ import annotations

from typing import List, Optional

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_type,
)
from pydantic import BaseModel, Field

from django_graphex.core.input_compiler import compile_input_type

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sdl(
    model: type[BaseModel], *, name: str, emit_defaults: bool | None = None
) -> str:
    """Compile ``model`` and return the rendered input-type SDL.

    ``emit_defaults=True`` simulates the hand-authored ``InputType`` population
    (which surfaces user-declared defaults into the SDL); the default (``None``)
    auto-detects and, for a plain ``BaseModel``, does NOT emit defaults —
    mirroring the Django-model-derived mutation path.
    """
    return print_type(compile_input_type(model, name=name, emit_defaults=emit_defaults))


def _exec_arg(
    model: type[BaseModel],
    *,
    name: str,
    query: str,
    emit_defaults: bool | None = None,
) -> tuple:
    """Build a one-field Query whose arg is ``model`` and run ``query``.

    Returns ``(errors, captured_dict)`` where ``captured_dict`` is the coerced
    argument value graphql-core delivered to the resolver (snake ``out_name``
    keys, defaults already filled in when ``emit_defaults`` surfaces them).
    """
    inp = compile_input_type(model, name=name, emit_defaults=emit_defaults)
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
    result = graphql_sync(GraphQLSchema(query=query_type), query)
    return result.errors, captured


# ---------------------------------------------------------------------------
# LIST HANDLING — SDL-level
# ---------------------------------------------------------------------------


def test_required_list_str_renders_nonnull_list_of_nonnull() -> None:
    """Protect required-list rendering: "names: list[str]" -> "[String!]!".

    If this regresses, a required list field would compile to a nullable
    list, or fall back to the "String" scalar, letting clients send a bare
    string or omit the field entirely.
    """

    class M(BaseModel):
        names: list[str]

    sdl = _sdl(M, name="ReqListInput")
    assert "names: [String!]!" in sdl, sdl


def test_typing_list_alias_renders_list() -> None:
    """Protect that "typing.List[str]" compiles identically to "list[str]".

    If this regresses, models still using the "typing.List" alias would
    silently degrade to the scalar fallback instead of a proper list type.
    """

    class M(BaseModel):
        names: List[str]  # noqa: UP006 — deliberately exercise the typing alias

    sdl = _sdl(M, name="TypingListInput")
    assert "names: [String!]!" in sdl, sdl


def test_optional_list_renders_nullable_list_with_null_default() -> None:
    """Protect nullable-list rendering with an explicit null default.

    If this regresses, "tags: list[str] | None = None" would either compile
    as a required list (rejecting an omitted value) or lose its "= null" SDL
    default marker.
    """

    class M(BaseModel):
        tags: list[str] | None = None

    sdl = _sdl(M, name="OptListInput", emit_defaults=True)
    assert "tags: [String!] = null" in sdl, sdl


def test_optional_list_is_nullable_regardless_of_defaults() -> None:
    """Protect that an Optional list stays nullable even without emit_defaults.

    If this regresses, the outer NonNull wrapping decision would incorrectly
    depend on emit_defaults instead of on the field's own optionality.
    """

    class M(BaseModel):
        tags: list[str] | None = None

    # Auto-detect (no defaults surfaced): the list is still nullable (no outer
    # NonNull); only the '= null' SDL marker is gated on emit_defaults.
    sdl = _sdl(M, name="OptListNoDefInput")
    assert "tags: [String!]" in sdl, sdl
    assert "tags: [String!]!" not in sdl, sdl


def test_typing_optional_list_renders_nullable_list() -> None:
    """Protect "Optional[list[str]]" (explicit None) rendering as nullable + "= null".

    If this regresses, the "typing.Optional" spelling of a nullable list
    would be treated differently from the "X | None" spelling, breaking
    models still using the older typing syntax.
    """

    class M(BaseModel):
        tags: Optional[list[str]] = Field(default=None)

    sdl = _sdl(M, name="TypingOptListInput", emit_defaults=True)
    # Optional + explicit None default -> nullable list rendered with '= null'.
    assert "tags: [String!] = null" in sdl, sdl


def test_list_of_optional_inner_renders_nullable_element() -> None:
    """Protect nullable-element rendering: "list[str | None]" -> "[String]".

    If this regresses, a list whose elements may individually be null would
    render its inner type as NonNull, rejecting a legitimate null element.
    """

    class M(BaseModel):
        maybe: list[str | None]

    sdl = _sdl(M, name="ListOptInnerInput")
    # Inner element nullable -> no '!' on the element; list required -> outer '!'.
    assert "maybe: [String]!" in sdl, sdl


def test_list_int_renders_int_list() -> None:
    """Protect the non-str inner scalar path: "list[int]" -> "[Int!]!".

    If this regresses, the list-handling branch could be str-specific and
    silently fall back to String for any other scalar element type.
    """

    class M(BaseModel):
        pages: list[int]

    sdl = _sdl(M, name="ListIntInput")
    assert "pages: [Int!]!" in sdl, sdl


# ---------------------------------------------------------------------------
# LIST HANDLING — behavior-level (graphql-core coercion)
# ---------------------------------------------------------------------------


def test_required_list_accepts_list_literal() -> None:
    """Protect end-to-end coercion of a "list[str]" field from a GraphQL literal.

    If this regresses, a client sending a proper list literal would be
    rejected with a scalar-coercion error instead of the list reaching the
    resolver.
    """

    class M(BaseModel):
        names: list[str]

    errors, captured = _exec_arg(
        M, name="ExecListInput", query='query { probe(flt: { names: ["a", "b"] }) }'
    )
    assert errors is None, errors
    assert captured["names"] == ["a", "b"], captured


# ---------------------------------------------------------------------------
# DEFAULTS — SDL-level
# ---------------------------------------------------------------------------


def test_int_default_renders_in_sdl() -> None:
    """Protect that a concrete int default reaches the SDL: "page: Int = 1".

    If this regresses, a field's declared default would be dropped from the
    compiled schema, forcing clients to always supply a value the server
    would otherwise default for them.
    """

    class M(BaseModel):
        page: int = 1

    sdl = _sdl(M, name="IntDefaultInput", emit_defaults=True)
    assert "page: Int = 1" in sdl, sdl


def test_bool_default_false_renders_false() -> None:
    """Protect that a False bool default renders lowercase: "flag: Boolean = false".

    If this regresses, a falsy default could be dropped entirely (mistaken
    for "no default") or rendered with the wrong GraphQL literal casing.
    """

    class M(BaseModel):
        flag: bool = False

    sdl = _sdl(M, name="BoolDefaultInput", emit_defaults=True)
    assert "flag: Boolean = false" in sdl, sdl


def test_explicit_none_default_renders_null() -> None:
    """Protect that an explicit None default renders as "note: String = null".

    If this regresses, an explicitly-nullable default could be dropped from
    the SDL, making it indistinguishable from a field with no default at
    all.
    """

    class M(BaseModel):
        note: str | None = None

    sdl = _sdl(M, name="NoneDefaultInput", emit_defaults=True)
    assert "note: String = null" in sdl, sdl


def test_no_default_renders_without_marker() -> None:
    """Protect that a field with NO default renders without an "= ..." marker.

    If this regresses, an omitted-vs-null distinction would be lost: a field
    the caller never set a default for could start rendering "= null",
    breaking the omit-vs-null contract mutations rely on.
    """

    class M(BaseModel):
        # optional (nullable) but explicitly NO default -> Undefined, not null.
        note: Optional[str]

    # Even with defaults surfaced, a field with NO default must render markerless
    # (PydanticUndefined -> graphql-core Undefined), distinct from an explicit None.
    sdl = _sdl(M, name="NoDefaultInput", emit_defaults=True)
    # Line is 'note: String' with no default marker.
    assert "note: String\n" in sdl or sdl.rstrip().endswith("note: String"), sdl
    assert "note: String =" not in sdl, sdl


def test_default_factory_evaluated_once_and_present() -> None:
    """Protect single-evaluation of a default_factory list default.

    If this regresses, a default_factory could be invoked repeatedly (once
    per SDL print or schema access) instead of exactly once at compile time,
    which would break factories with side effects or non-idempotent output.
    """

    calls = {"n": 0}

    def _factory() -> list[str]:
        calls["n"] += 1
        return ["seed"]

    class M(BaseModel):
        tags: list[str] = Field(default_factory=_factory)

    result = compile_input_type(M, name="FactoryDefaultInput", emit_defaults=True)
    # Force the thunk to build fields (defaults are read at build time).
    sdl = print_type(result)
    assert 'tags: [String!] = ["seed"]' in sdl, sdl
    # Single-evaluation constraint: the factory ran exactly once at compile time.
    assert calls["n"] == 1, f"default_factory must be evaluated ONCE, ran {calls['n']}x"


def test_default_factory_list_default_is_nullable_list() -> None:
    """Protect that a default_factory list field is nullable (it has a default).

    If this regresses, a field with a default_factory would be wrapped in
    GraphQLNonNull, forcing clients to always supply a value the factory
    would otherwise provide.
    """

    class M(BaseModel):
        tags: list[str] = Field(default_factory=list)

    result = compile_input_type(M, name="FactoryEmptyInput", emit_defaults=True)
    field_type = result.fields["tags"].type
    # A field WITH a default is nullable -> NOT wrapped in the outer NonNull.
    assert not isinstance(field_type, GraphQLNonNull), field_type
    assert isinstance(field_type, GraphQLList), field_type


# ---------------------------------------------------------------------------
# DEFAULTS — behavior-level (defaults reach the resolver)
# ---------------------------------------------------------------------------


def test_scalar_defaults_fill_in_when_omitted() -> None:
    """Protect that omitted defaulted scalars ("page=1", "size=25") reach the resolver.

    If this regresses, a client omitting a defaulted argument would have the
    resolver receive it as missing/None instead of the declared default
    value.
    """

    class M(BaseModel):
        names: list[str]
        page: int = 1
        size: int = 25

    errors, captured = _exec_arg(
        M,
        name="DefaultsExecInput",
        query='query { probe(flt: { names: ["x"] }) }',
        emit_defaults=True,
    )
    assert errors is None, errors
    assert captured.get("page") == 1, captured
    assert captured.get("size") == 25, captured


# ---------------------------------------------------------------------------
# Combined regression — the exact confirmed reproduction from the ticket
# ---------------------------------------------------------------------------


def test_ticket_reproduction_full_sdl() -> None:
    """Protect the confirmed ticket regression: list typing + defaults together in SDL.

    If this regresses, the exact combination that shipped broken (a list
    field alongside scalar defaults on the same input model) would return:
    the list would fall back to scalar String and/or the defaults would
    vanish from the SDL.
    """

    class TagFilterInput(BaseModel):
        names: list[str]
        page: int = 1
        size: int = 25

    # A hand-authored InputType surfaces its declared defaults (emit_defaults).
    sdl = _sdl(TagFilterInput, name="TagFilterInput", emit_defaults=True)
    assert "names: [String!]!" in sdl, sdl
    assert "page: Int = 1" in sdl, sdl
    assert "size: Int = 25" in sdl, sdl
    # The scalar-String regression must be gone.
    assert "names: String" not in sdl, sdl


def test_emit_defaults_autodetect_off_for_plain_basemodel() -> None:
    """AUTO-DETECT: a plain "BaseModel" (no "_gdx_opts") omits SDL defaults.

    This is the Django-mutation regression guard: "build_model_schema" stamps a
    synthetic "default=None" on every optional/partial field, and graphql-core
    injects that "default_value" into the coerced dict for OMITTED fields. If it
    were surfaced, the "save_object" "model_fields_set" omit-vs-null contract
    would break (omitted fields would be written as "None"). Auto-detect keeps
    the default OFF for a plain "BaseModel".
    """

    class M(BaseModel):
        page: int = 1
        note: str | None = None

    sdl = _sdl(M, name="AutoOffInput")  # emit_defaults=None -> auto-detect
    assert "page: Int = 1" not in sdl, sdl
    assert " = null" not in sdl, sdl


def test_emit_defaults_autodetect_on_for_gdx_input_type() -> None:
    """AUTO-DETECT: a model carrying "_gdx_opts" surfaces its declared defaults.

    Mirrors the hand-authored "InputType" population ("compile_all_inputs"
    compiles those; they carry "_gdx_opts"). The presence of the marker flips
    auto-detect ON without the caller passing "emit_defaults" explicitly.
    """

    class M(BaseModel):
        page: int = 1

    # Simulate the hand-authored InputType marker the compiler auto-detects on.
    M._gdx_opts = object()  # type: ignore[attr-defined]
    sdl = _sdl(M, name="AutoOnInput")  # emit_defaults=None -> auto-detect
    assert "page: Int = 1" in sdl, sdl


def test_omitted_field_not_injected_when_defaults_off() -> None:
    """AUTO-DETECT OFF: an omitted defaulted field is NOT injected into coerced data.

    Direct behavior-level proof of the mutation-path contract: with defaults off
    (plain "BaseModel"), omitting "page" leaves it ABSENT from the resolver's
    coerced dict (no synthetic "None"/default value materialized).
    """

    class M(BaseModel):
        names: list[str]
        page: int = 1

    errors, captured = _exec_arg(
        M,
        name="OmitAbsentInput",
        query='query { probe(flt: { names: ["x"] }) }',
    )  # emit_defaults=None -> auto-detect OFF for a plain BaseModel
    assert errors is None, errors
    assert "page" not in captured, (
        f"omitted defaulted field must stay absent (omit-vs-null), got {captured}"
    )


def test_unsupported_origin_falls_back_like_unknown_type() -> None:
    """Protect that a "dict[...]" origin is NOT mistakenly treated as a list.

    If this regresses, a dict-typed field could be misrouted into the list
    compilation branch instead of falling back to its documented scalar
    handling.
    """

    class M(BaseModel):
        mapping: dict[str, int]

    result = compile_input_type(M, name="DictOriginInput")
    field_type = result.fields["mapping"].type
    if isinstance(field_type, GraphQLNonNull):
        field_type = field_type.of_type
    # dict maps to the JSONString scalar via _native_scalar_map (existing
    # behavior) — the key point is it is NOT a GraphQLList.
    assert not isinstance(field_type, GraphQLList), field_type
    assert isinstance(field_type, GraphQLScalarType), field_type
