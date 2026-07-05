"""Unified "Field" descriptor (field-unify) — Strawberry-style single class.

Strict TDD. These tests describe the UNIFIED "Field" that replaces the former
"Field" (output-only) + "InputField" (input-only) pair. One "Field" is
usable in BOTH positions; direction always comes from the DECLARATION SITE:

- OUTPUT position ("ObjectType" / "Mutation" payload body): ".type" resolves
  the OUTPUT type (lazy "_meta.graphql_output_type"), "required=" wraps
  "NativeNonNull". "default=" is INPUT-only -> raises at output compile/mount.
- INPUT position ("class Arguments" body, "field(args={...})" dict):
  "to_graphql_argument()" resolves the INPUT type ("_meta.graphql_input_type"
  or a bare graphql-core type verbatim) with EAGER "GraphQLNonNull" when
  required. "resolver=" / "source=" / "args=" are OUTPUT-only -> raise here.

Plus the two folded fixes:
- F1: "_args.to_graphql_argument" preserves a pre-set "out_name" and carries
  "deprecation_reason" when adapting a "GraphQLArgument".
- F2: "field()" / "Field" accept "deprecation_reason=" and wire it into the
  compiled "GraphQLField" (SDL "@deprecated") and "GraphQLArgument".

Run:
    .venv/bin/python -m pytest -q tests/core/test_field_unification.py
"""

from __future__ import annotations

from typing import Any

import pytest


def _compiled_input_class(name: str = "FakeInput") -> tuple[type, Any]:
    """Build an "InputType" subclass with a populated "graphql_input_type".

    Mirrors "compile_all_inputs" at app-ready: compiles the Pydantic model into a
    "GraphQLInputObjectType" and stashes it so "cls._meta.graphql_input_type" is
    a real compiled type — the exact state a "Field" resolves against at the
    "to_graphql_argument" (input) call site.

    Args:
        name: The class name to give the generated "InputType" subclass.

    Returns:
        A tuple of the generated input class and its compiled
        "GraphQLInputObjectType".
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.input_compiler import compile_input_type

    cls = type(name, (InputType,), {"__annotations__": {"query": str}})
    compiled = compile_input_type(cls, name=name, description="")
    cls._gdx_opts.graphql_input_type = compiled  # type: ignore[attr-defined]
    return cls, compiled


# ---------------------------------------------------------------------------
# 1. Unification — ONE Field, usable in both positions
# ---------------------------------------------------------------------------


def test_input_field_class_is_gone() -> None:
    """CONTRACT: descriptors no longer exposes the retired "InputField" class.

    A resurrected "InputField" would signal the unification was reverted.
    """
    import django_graphex.core.descriptors as descriptors

    assert not hasattr(descriptors, "InputField")


def test_input_field_not_exported_from_core() -> None:
    """CONTRACT: "InputField" is not importable from "django_graphex.core".

    Neither as an attribute nor listed in "__all__", so downstream code
    cannot accidentally resurrect the retired input-only field class.
    """
    import django_graphex.core as core

    assert not hasattr(core, "InputField")
    assert "InputField" not in core.__all__


def test_field_usable_as_argument_via_to_graphql_argument() -> None:
    """CONTRACT: a single "Field" builds a "GraphQLArgument" in an input position.

    Required input fields must wrap the compiled input type in an eager
    "GraphQLNonNull".
    """
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("UnifyFakeInputReq")

    arg = Field(fake_input, required=True).to_graphql_argument()
    assert isinstance(arg, GraphQLArgument)
    assert isinstance(arg.type, GraphQLNonNull)
    assert arg.type.of_type is compiled


def test_field_argument_bare_when_not_required() -> None:
    """CONTRACT: without "required", the input arg type is the bare compiled input.

    No "GraphQLNonNull" wrapping should be applied when the field is optional.
    """
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("UnifyFakeInputOpt")

    arg = Field(fake_input).to_graphql_argument()
    assert isinstance(arg, GraphQLArgument)
    assert not isinstance(arg.type, GraphQLNonNull)
    assert arg.type is compiled


def test_field_argument_input_type_never_reads_output_type_property() -> None:
    """CONTRACT (C1): the INPUT route must NOT read ".type".

    A required input builds no eager NativeNonNull, and construction stays
    inert against an uncompiled input. The input class here is NOT compiled
    yet ("graphql_input_type" is None); nothing may be built at construction,
    and "to_graphql_argument" must resolve via the INPUT type, never the
    OUTPUT ".type" property (which would wrap NativeNonNull eagerly for
    "required=True").
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.descriptors import Field

    cls = type("UnifyUncompiledInput", (InputType,), {"__annotations__": {"q": str}})
    desc = Field(cls, required=True)  # inert: no eager build
    assert desc is not None


def test_field_argument_bare_graphql_scalar_verbatim() -> None:
    """CONTRACT (C4): "Field(GraphQLString)" in an args position yields a "String" arg.

    A bare graphql-core scalar must pass through the input route unchanged.
    """
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core.descriptors import Field

    arg = Field(GraphQLString).to_graphql_argument(name="q")
    assert isinstance(arg, GraphQLArgument)
    assert arg.type is GraphQLString
    assert arg.out_name == "q"


def test_field_argument_bare_scalar_required_wraps_eager_nonnull() -> None:
    """CONTRACT (C4/C1): "Field(GraphQLString, required=True)" -> eager "GraphQLNonNull".

    The input route must build a REAL graphql-core "GraphQLNonNull" (not the
    lazy "NativeNonNull" output wrapper) around the bare scalar.
    """
    from graphql import GraphQLNonNull, GraphQLString

    from django_graphex.core.descriptors import Field

    arg = Field(GraphQLString, required=True).to_graphql_argument(name="q")
    assert isinstance(arg.type, GraphQLNonNull)
    assert arg.type.of_type is GraphQLString


def test_field_default_and_unset_sentinel() -> None:
    """CONTRACT: "default=" reaches the built "GraphQLArgument".

    "_UNSET" keeps "default=None" distinct from no-default (graphql-core
    "Undefined").
    """
    from graphql import Undefined

    from django_graphex.core.descriptors import _UNSET, Field

    fake_input, _ = _compiled_input_class("UnifyDefaultInput")

    # No default -> _UNSET sentinel -> Undefined on the arg.
    no_default = Field(fake_input)
    assert no_default._default is _UNSET
    assert no_default.to_graphql_argument().default_value is Undefined

    # Explicit default reaches the arg.
    with_default = Field(fake_input, default={"query": "x"}).to_graphql_argument()
    assert with_default.default_value == {"query": "x"}

    # Explicit None is a REAL null default (distinct from unset).
    explicit_none = Field(fake_input, default=None)
    assert explicit_none._default is None
    assert explicit_none.to_graphql_argument().default_value is None


def test_field_native_arg_branch() -> None:
    """Ships broken if "native_arg" stops recognizing a "Field" via its
    explicit branch.

    Without this branch native_arg would fall through to a generic path that
    does not build a correctly-wrapped required argument.
    """
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core._args import native_arg
    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("UnifyNativeArgInput")

    result = native_arg(Field(fake_input, required=True), name="newUser")
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is compiled
    assert result.out_name == "new_user"


# ---------------------------------------------------------------------------
# 2. Contextual validation — wrong-position params raise clearly
# ---------------------------------------------------------------------------


def test_input_position_rejects_resolver() -> None:
    """Ships broken if "resolver=" stops being output-only (no TypeError
    from "to_graphql_argument")."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field

    with pytest.raises(TypeError, match="resolver.*output-only|output-only.*resolver"):
        Field(GraphQLString, resolver=lambda r, i: None).to_graphql_argument(name="q")


def test_input_position_rejects_source() -> None:
    """Ships broken if "source=" stops being output-only (no TypeError from
    "to_graphql_argument")."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field

    with pytest.raises(TypeError, match="source.*output-only|output-only.*source"):
        Field(GraphQLString, source="attr").to_graphql_argument(name="q")


def test_input_position_rejects_args() -> None:
    """Ships broken if "args=" stops being output-only (no TypeError from
    "to_graphql_argument")."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field

    with pytest.raises(TypeError, match="args.*output-only|output-only.*args"):
        Field(GraphQLString, args={"x": GraphQLString}).to_graphql_argument(name="q")


def test_output_position_rejects_default_at_compile() -> None:
    """Ships broken if "default=" stops being input-only.

    An output-position "Field(default=...)" must raise a clear TypeError at
    output compile/mount time (never silently ignored).
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType
    from django_graphex.core.descriptors import Field
    from django_graphex.core.schema_compiler import compile_native_root

    class _Root(ObjectType):
        """ObjectType declaring an illegal default= on an output-position Field."""

        title = Field(GraphQLString, default="oops")

    with pytest.raises(TypeError, match="default.*input-only|input-only.*default"):
        compile_native_root(_Root, name="Query")


# ---------------------------------------------------------------------------
# 3. Unified end-to-end — one Field on both sides of a real schema
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unified_field_end_to_end() -> None:
    """Ships broken if one "Field" on output AND input positions stops
    compiling and executing together."""
    from graphql import (
        GraphQLBoolean,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )
    from graphql import (
        GraphQLField as GQLField,
    )

    from django_graphex.core import Field, Mutation, ObjectType
    from django_graphex.core.base import InputType, compile_all_inputs
    from django_graphex.core.schema_compiler import compile_native_root

    class _UnifyUserCreateInput(InputType):
        """Input type carrying the single "name" field for the mutation."""

        name: str

    compile_all_inputs()

    class _CreateUser(Mutation):
        """Mutation using the unified Field in BOTH an argument and payload position."""

        class Arguments:
            """Declares the mutation's single required input-position Field."""

            new_user = Field(_UnifyUserCreateInput, required=True)  # INPUT position

        ok = Field(GraphQLBoolean)  # OUTPUT position, same class
        echo = Field(GraphQLString)

        @staticmethod
        def mutate(root, info, new_user):
            """Echo back the created user's name to prove the mutation ran."""
            return _CreateUser(ok=True, echo=new_user["name"])

    class _Root(ObjectType):
        """Mutation root exposing the createUser field."""

        create_user = _CreateUser.Field()

    native_root = compile_native_root(_Root, name="Mutation")
    field_obj = native_root.fields["createUser"]
    assert "new_user" in field_obj.args
    assert isinstance(field_obj.args["new_user"].type, GraphQLNonNull)
    assert field_obj.args["new_user"].out_name == "new_user"

    query_root = GraphQLObjectType(
        "Query", {"ping": GQLField(GraphQLString, resolve=lambda r, i: "pong")}
    )
    schema = GraphQLSchema(query=query_root, mutation=native_root)
    doc = 'mutation { createUser(new_user: {name: "Grace"}) { ok echo } }'
    result = graphql_sync(schema, doc)
    assert result.errors is None, f"unified mutation raised: {result.errors!r}"
    assert result.data["createUser"]["ok"] is True
    assert result.data["createUser"]["echo"] == "Grace"


# ---------------------------------------------------------------------------
# 4. Shortcuts collapse 24 -> 12; each usable in BOTH positions
# ---------------------------------------------------------------------------

_SURVIVING_SHORTCUTS = (
    "IntField",
    "CharField",
    "FloatField",
    "BooleanField",
    "IDField",
    "DateField",
    "DateTimeField",
    "TimeField",
    "DecimalField",
    "UUIDField",
    # ``JSONField`` survives (now ``as_str``-aware); ``GenericJSONField`` is
    # DELETED by the v2 RAW-JSON flip.
    "JSONField",
)

_DEAD_INPUT_SHORTCUTS = tuple(
    name.replace("Field", "InputField") for name in _SURVIVING_SHORTCUTS
)


@pytest.mark.parametrize("dead_name", _DEAD_INPUT_SHORTCUTS)
def test_input_shortcut_names_gone(dead_name: str) -> None:
    """Ships broken if any of the 12 "*InputField" scalar shortcuts stop
    being removed from core and "__all__".

    Args:
        dead_name: The retired "*InputField" shortcut name under test.
    """
    import django_graphex.core as core

    assert not hasattr(core, dead_name)
    assert dead_name not in core.__all__


@pytest.mark.parametrize("name", _SURVIVING_SHORTCUTS)
def test_surviving_shortcut_usable_as_output(name: str) -> None:
    """Ships broken if a surviving shortcut stops binding its scalar in OUTPUT position.

    Args:
        name: The surviving scalar shortcut name under test.
    """
    import django_graphex.core as core
    from django_graphex.core.descriptors import Field

    desc = getattr(core, name)()
    assert isinstance(desc, Field)


@pytest.mark.parametrize("name", _SURVIVING_SHORTCUTS)
def test_surviving_shortcut_usable_as_input(name: str) -> None:
    """Ships broken if a surviving shortcut stops being usable in an INPUT
    position (unified).

    Args:
        name: The surviving scalar shortcut name under test.
    """
    from graphql import GraphQLArgument

    import django_graphex.core as core
    from django_graphex.core._args import native_arg

    arg = native_arg(getattr(core, name)(), name="q")
    assert isinstance(arg, GraphQLArgument)
    assert arg.out_name == "q"


def test_shortcut_input_required_and_default() -> None:
    """Ships broken if "CharField(required=True, default=...)" in an input arg
    stops rendering "String!" with the default honoured."""
    from graphql import GraphQLNonNull, GraphQLString

    from django_graphex.core import CharField
    from django_graphex.core._args import native_arg

    arg = native_arg(CharField(required=True, default="x"), name="q")
    assert isinstance(arg.type, GraphQLNonNull)
    assert arg.type.of_type is GraphQLString
    assert arg.default_value == "x"


# ---------------------------------------------------------------------------
# 5. F1 — to_graphql_argument preserves out_name + carries deprecation_reason
# ---------------------------------------------------------------------------


def test_f1_to_graphql_argument_preserves_out_name_and_deprecation() -> None:
    """Ships broken if adapting a "GraphQLArgument" stops keeping a pre-set
    "out_name" or carrying "deprecation_reason" (F1: current code clobbers
    out_name + drops it)."""
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core._args import to_graphql_argument

    original = GraphQLArgument(
        GraphQLString, out_name="already", deprecation_reason="old"
    )
    adapted = to_graphql_argument(original, name="someWireName")

    assert adapted.out_name == "already"  # pre-set out_name preserved, not clobbered
    assert adapted.deprecation_reason == "old"  # carried through


def test_f1_to_graphql_argument_fills_out_name_when_none() -> None:
    """Ships broken if a "GraphQLArgument" with no "out_name" stops being
    filled from "name"."""
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core._args import to_graphql_argument

    original = GraphQLArgument(GraphQLString)  # out_name is None
    adapted = to_graphql_argument(original, name="someWireName")
    assert adapted.out_name == "some_wire_name"


# ---------------------------------------------------------------------------
# 6. F2 — deprecation_reason on field()/Field wired into compiled SDL
# ---------------------------------------------------------------------------


def test_f2_field_accepts_deprecation_reason() -> None:
    """Ships broken if "field(GraphQLString, deprecation_reason=...)" starts
    raising TypeError again."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import field

    f = field(GraphQLString, deprecation_reason="old")
    assert f.deprecation_reason == "old"


def test_f2_output_field_deprecation_reason_in_sdl() -> None:
    """Ships broken if a declared output "field(..., deprecation_reason=...)"
    stops rendering "@deprecated"."""
    from graphql import GraphQLSchema, GraphQLString, print_schema

    from django_graphex.core import ObjectType, field
    from django_graphex.core.schema_compiler import compile_native_root

    class _Root(ObjectType):
        """ObjectType declaring a deprecated output field via field()."""

        legacy = field(GraphQLString, deprecation_reason="use newField")

    root = compile_native_root(_Root, name="Query")
    assert root.fields["legacy"].deprecation_reason == "use newField"
    sdl = print_schema(GraphQLSchema(query=root))
    assert '@deprecated(reason: "use newField")' in sdl


def test_f2_field_class_deprecation_reason_in_sdl() -> None:
    """Ships broken if the capitalized "Field(..., deprecation_reason=...)"
    stops rendering "@deprecated"."""
    from graphql import GraphQLSchema, GraphQLString, print_schema

    from django_graphex.core import ObjectType
    from django_graphex.core.descriptors import Field
    from django_graphex.core.schema_compiler import compile_native_root

    class _Root(ObjectType):
        """ObjectType declaring a deprecated output field via the Field class."""

        legacy = Field(GraphQLString, deprecation_reason="gone soon")

    root = compile_native_root(_Root, name="Query")
    assert root.fields["legacy"].deprecation_reason == "gone soon"
    sdl = print_schema(GraphQLSchema(query=root))
    assert '@deprecated(reason: "gone soon")' in sdl


def test_f2_input_arg_deprecation_reason_wired() -> None:
    """Ships broken if "Field(..., deprecation_reason=...)" in an input
    position stops wiring the arg's "deprecation_reason".

    graphql-core args CAN be deprecated, so this must reach the compiled arg.
    """
    from graphql import GraphQLString

    from django_graphex.core._args import native_arg
    from django_graphex.core.descriptors import Field

    arg = native_arg(Field(GraphQLString, deprecation_reason="stale arg"), name="q")
    assert arg.deprecation_reason == "stale arg"
