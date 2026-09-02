"""Field Descriptor API (field-descriptor-api) — G1 core: the unified "Field".

Strict TDD. These tests describe the Django-style capitalized descriptor that
compiles byte-identical to its "field()" / "GraphQLArgument" substrate:

- "Field" — a SINGLE Strawberry-style descriptor (thin subclass of
  "NativeMountedField") usable in BOTH positions. As OUTPUT it carries
  "source=" / "required=" / "resolver=" (which "field()" / "NativeField"
  do NOT). As an ARGUMENT it is routed through "native_arg" (in a
  "class Arguments" body) or "to_graphql_argument" (inside "Field(args={...})"
  / "field(args={...})"); a "DjangoInputObjectType" CLASS passed as the type
  resolves lazily to its compiled "graphql_input_type" at compile time.
- Collision guard for "django.db.models.Field" instances at BOTH the
  ObjectType-body descriptor-collection site AND the "native_arg" site.
- Exports from "django_graphex.core.__all__"; root package stays lean.
- Regressions: the lambda-thunk arg idiom and "field()" keep working verbatim.

The 12 typed scalar shortcuts ("CharField", "IntField", ...) are the same
unified "Field" and work in BOTH positions too. The separate "InputField"
class and the 12 "*InputField" shortcuts no longer exist.

Run:
    .venv/bin/python -m pytest -q tests/core/test_descriptors.py --no-cov
"""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared helper: compile a minimal InputType so Field(InputClass) can
# resolve ``_meta.graphql_input_type`` at "compile time" (post compile_all_inputs).
# ---------------------------------------------------------------------------


def _compiled_input_class(name: str = "FakeInput"):
    """Build an "InputType" subclass with a populated "graphql_input_type".

    Mirrors what "compile_all_inputs" does at app-ready: compiles the Pydantic
    model into a "GraphQLInputObjectType" and stashes it on "_gdx_opts" so
    "cls._meta.graphql_input_type" is a real compiled type — the exact state a
    "Field" (in an argument position) resolves against at "Field()" /
    compile time.

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
# 1.1 Field — mirrors field() surface, adds source=/required= via NativeMountedField
# ---------------------------------------------------------------------------


def test_field_is_native_mounted_field_subclass() -> None:
    """Ships broken if "Field" stops being a THIN subclass of "NativeMountedField"
    (design decision #1)."""
    from django_graphex.core.descriptors import Field, NativeMountedField

    assert issubclass(Field, NativeMountedField)


def test_field_mirrors_field_surface_type_description_name() -> None:
    """Ships broken if "Field(type, description=, name=)" diverges from the
    same read-contract as "field()"."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field, field

    desc = Field(GraphQLString, description="d", name="t")
    substrate = field(GraphQLString, description="d", name="t")

    # Byte-identical read-contract the compiler consumes.
    assert desc.type is GraphQLString
    assert desc.type is substrate.type
    assert desc.description == substrate.description == "d"
    assert desc.name == substrate.name == "t"


def test_field_required_wraps_native_nonnull_at_type_read() -> None:
    """Ships broken if "Field(required=True).type" stops being a "NativeNonNull"
    around the type."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field, NativeNonNull

    desc = Field(GraphQLString, required=True)
    assert isinstance(desc.type, NativeNonNull)
    assert desc.type.of_type is GraphQLString


def test_field_not_required_is_bare_type() -> None:
    """Ships broken if the type is wrapped when "required=" is absent
    (triangulation against the required=True case above)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field, NativeNonNull

    desc = Field(GraphQLString)
    assert desc.type is GraphQLString
    assert not isinstance(desc.type, NativeNonNull)


def test_field_source_routes_to_resolver() -> None:
    """Ships broken if "Field(source="attr")" stops resolving by reading
    "attr" off the root."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field

    desc = Field(GraphQLString, source="user_email")
    resolver = desc.wrap_resolve(None)
    assert resolver is not None

    class _Root:
        """Stand-in resolver root exposing the source attribute to read."""

        user_email = "a@b.com"

    assert resolver(_Root(), None) == "a@b.com"


def test_field_explicit_resolver_wins_over_source() -> None:
    """Ships broken if an explicit resolver stops winning over "source"
    (triangulation)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import Field

    def my_resolver(root, info):
        """Return a fixed marker string identifying the explicit resolver ran."""
        return "explicit"

    desc = Field(GraphQLString, source="user_email", resolver=my_resolver)
    assert desc.wrap_resolve(None) is my_resolver


# ---------------------------------------------------------------------------
# 1.3 Field as an argument — lazy .type + to_graphql_argument, no eager NonNull, _UNSET
# ---------------------------------------------------------------------------


def test_field_to_graphql_argument_wraps_nonnull_when_required() -> None:
    """Ships broken if "Field(FakeInput, required=True).to_graphql_argument()"
    stops equaling "NonNull(compiled)"."""
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("FakeInputReq")

    arg = Field(fake_input, required=True).to_graphql_argument()
    assert isinstance(arg, GraphQLArgument)
    assert isinstance(arg.type, GraphQLNonNull)
    assert arg.type.of_type is compiled


def test_field_to_graphql_argument_bare_when_not_required() -> None:
    """Ships broken if the arg type is wrapped when "required" is absent
    (triangulation)."""
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("FakeInputOpt")

    arg = Field(fake_input).to_graphql_argument()
    assert isinstance(arg, GraphQLArgument)
    assert not isinstance(arg.type, GraphQLNonNull)
    assert arg.type is compiled


def test_field_output_type_property_is_lazy_native_wrapper() -> None:
    """Ships broken if the OUTPUT ".type" of a unified "Field" stops being the
    lazy "NativeNonNull" wrapper.

    Unlike the deleted "InputField", the unified "Field" does NOT eagerly
    resolve the compiled input type on its ".type" property. ".type" is the
    OUTPUT read-contract: "required=True" yields a lazy "NativeNonNull" around
    the DECLARED type (here the input CLASS itself), resolved only at the compile
    boundary. The INPUT route deliberately bypasses ".type" and resolves the
    compiled "graphql_input_type" through "to_graphql_argument" instead — see
    "test_field_to_graphql_argument_wraps_nonnull_when_required".
    """
    from django_graphex.core.descriptors import Field, NativeNonNull

    fake_input, _compiled = _compiled_input_class("FakeInputTypeProp")

    required = Field(fake_input, required=True)
    assert isinstance(required.type, NativeNonNull)
    assert required.type.of_type is fake_input

    optional = Field(fake_input)
    assert optional.type is fake_input


def test_field_required_builds_no_eager_nonnull_at_construction() -> None:
    """Ships broken if "required=True" builds a GraphQLArgument/NonNull at
    construction time.

    The input class is NOT compiled yet ("graphql_input_type" is None), so if
    anything were built eagerly it would crash. Construction must be inert.
    """
    from django_graphex.core.base import InputType
    from django_graphex.core.descriptors import Field

    cls = type("UncompiledInput", (InputType,), {"__annotations__": {"q": str}})
    # graphql_input_type is None here — construction must not touch it.
    desc = Field(cls, required=True)
    assert desc is not None  # no error raised at construction


def test_field_unset_sentinel_distinguishes_default_none() -> None:
    """Ships broken if the "_UNSET" sentinel stops distinguishing
    "default=None" from no-default."""
    from django_graphex.core.descriptors import _UNSET, Field

    no_default = Field(_compiled_input_class("FakeInputND")[0])
    assert no_default._default is _UNSET

    explicit_none = Field(_compiled_input_class("FakeInputEN")[0], default=None)
    assert explicit_none._default is None


def test_field_default_flows_to_graphql_argument() -> None:
    """Ships broken if an explicit "default" stops reaching the built
    "GraphQLArgument.default_value"."""
    from graphql import Undefined

    from django_graphex.core.descriptors import Field

    fake_input, _ = _compiled_input_class("FakeInputDefault")

    with_default = Field(fake_input, default={"query": "x"}).to_graphql_argument()
    assert with_default.default_value == {"query": "x"}

    # No default -> graphql-core Undefined (not None).
    no_default = Field(fake_input).to_graphql_argument()
    assert no_default.default_value is Undefined


# ---------------------------------------------------------------------------
# 1.5 Field as an argument end-to-end: replaces the lambda thunk in Arguments;
#      usable inside Field(args=...) / field(args=...)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_field_argument_replaces_lambda_thunk_end_to_end() -> None:
    """Ships broken if "Field(UserCreateInput, required=True)" stops compiling
    and executing in a real Mutation."""
    from graphql import (
        GraphQLBoolean,
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )

    from django_graphex.core import Field, Mutation, ObjectType, field
    from django_graphex.core.base import InputType, compile_all_inputs
    from django_graphex.core.schema_compiler import compile_native_root

    class _UserCreateInput(InputType):
        """Input type carrying the single "name" field for the mutation."""

        name: str

    compile_all_inputs()

    class _CreateUser(Mutation):
        """Mutation whose Arguments body declares the Field-based input."""

        class Arguments:
            """Declares the mutation's single required input-position Field."""

            new_user = Field(_UserCreateInput, required=True)

        ok = field(GraphQLBoolean)
        echo = field(GraphQLString)

        @staticmethod
        def mutate(root, info, new_user):
            """Echo back the created user's name to prove the mutation ran."""
            return _CreateUser(ok=True, echo=new_user["name"])

    class _Root(ObjectType):
        """Mutation root exposing the createUser field."""

        create_user = _CreateUser.Field()

    native_root = compile_native_root(_Root, name="Mutation")
    field_obj = native_root.fields["createUser"]
    # The arg exists and is NonNull-wrapped (required=True). Arg wire keys are NOT
    # camelCased by the compiler — the declared attr name (``new_user``) is the
    # wire name; ``out_name`` is its snake_case form (identity here).
    from graphql import GraphQLNonNull

    assert "new_user" in field_obj.args
    assert isinstance(field_obj.args["new_user"].type, GraphQLNonNull)
    assert field_obj.args["new_user"].out_name == "new_user"

    query_root = GraphQLObjectType(
        "Query", {"ping": GraphQLField(GraphQLString, resolve=lambda r, i: "pong")}
    )
    schema = GraphQLSchema(query=query_root, mutation=native_root)

    doc = 'mutation { createUser(new_user: {name: "Grace"}) { ok echo } }'
    result = graphql_sync(schema, doc)
    assert result.errors is None, f"native mutation raised: {result.errors!r}"
    assert result.data["createUser"]["ok"] is True
    assert result.data["createUser"]["echo"] == "Grace"


def test_field_usable_inside_field_args() -> None:
    """Ships broken if "Field(GraphQLString, args={"data": Field(SearchInput)})"
    stops yielding a valid arg."""
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core._args import to_graphql_argument
    from django_graphex.core.descriptors import Field

    search_input, compiled = _compiled_input_class("SearchInputArgs")

    desc = Field(GraphQLString, args={"data": Field(search_input)})
    # The field(args=...) route reads Field.type via to_graphql_argument.
    raw_arg = desc.args["data"]
    built = to_graphql_argument(raw_arg, name="data")
    assert isinstance(built, GraphQLArgument)
    assert built.type is compiled


def test_field_in_native_arg_direct() -> None:
    """Ships broken if "native_arg" stops recognizing a "Field" (argument
    position) via its explicit branch."""
    from graphql import GraphQLArgument, GraphQLNonNull

    from django_graphex.core._args import native_arg
    from django_graphex.core.descriptors import Field

    fake_input, compiled = _compiled_input_class("NativeArgInput")

    result = native_arg(Field(fake_input, required=True), name="newUser")
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is compiled
    # out_name is the snake_case form of the declared key.
    assert result.out_name == "new_user"


# ---------------------------------------------------------------------------
# 1.7 Collision guard — django.db.models.Field at BOTH sites (two distinct raises)
# ---------------------------------------------------------------------------


def test_collision_guard_model_field_in_native_arg() -> None:
    """Ships broken if "models.IntegerField()" in a "class Arguments" stops
    raising via "native_arg"."""
    from django.db import models

    from django_graphex.core._args import native_arg

    with pytest.raises(TypeError, match="django.db.models"):
        native_arg(models.IntegerField(), name="x")


def test_collision_guard_model_field_on_objecttype_body() -> None:
    """Ships broken if "models.CharField(max_length=10)" on an ObjectType
    body stops raising "TypeError"."""
    from django.db import models

    from django_graphex.core import ObjectType

    with pytest.raises(TypeError, match="django.db.models"):

        class _Bad(ObjectType):
            """ObjectType wrongly declaring a raw Django model field."""

            name = models.CharField(max_length=10)


# ---------------------------------------------------------------------------
# 1.9 A stray argument-style Field on an ObjectType body is ignored by Pydantic
# ---------------------------------------------------------------------------


def test_stray_input_field_on_objecttype_body_is_ignored_by_pydantic() -> None:
    """Ships broken if a stray argument-style "Field" on an ObjectType body
    starts crashing creation.

    "_FIELD_DESCRIPTOR_TYPES" (which contains "NativeMountedField", the base of
    the unified "Field") is wired into "ignored_types", so Pydantic does NOT
    try to infer it as a model field (which would raise a cryptic
    "PydanticUserError" 'non-annotated attribute'). It is collected into
    "_meta.fields" instead.
    """
    from graphql import GraphQLString

    from django_graphex.core import Field, ObjectType, field

    fake_input, _ = _compiled_input_class("StrayBodyInput")

    class _Weird(ObjectType):
        """ObjectType mixing a normal output field with a stray input-style Field."""

        real = field(GraphQLString)
        stray = Field(fake_input)

    assert "stray" in _Weird._meta.fields


# ---------------------------------------------------------------------------
# 1.11 Exports — Field importable from core; root stays lean
# ---------------------------------------------------------------------------


def test_field_importable_from_core() -> None:
    """Ships broken if "from django_graphex.core import Field" stops succeeding.

    This is the public import path downstream consumers rely on.
    """
    from django_graphex.core import Field

    assert Field is not None


def test_field_in_core_all() -> None:
    """Ships broken if "Field" stops being listed in "django_graphex.core.__all__".

    "__all__" membership is what "from django_graphex.core import *" honors.
    """
    import django_graphex.core as core

    assert "Field" in core.__all__


def test_input_field_class_no_longer_exists() -> None:
    """Ships broken if the separate "InputField" class comes back — not
    exported, not importable."""
    import django_graphex.core as core

    assert "InputField" not in core.__all__
    assert not hasattr(core, "InputField")

    with pytest.raises(ImportError):
        from django_graphex.core.descriptors import InputField  # noqa: F401


def test_root_package_all_stays_lean() -> None:
    """Ships broken if "django_graphex.__all__" stops exporting ONLY
    "__version__"."""
    import django_graphex

    assert django_graphex.__all__ == ("__version__",)


# ---------------------------------------------------------------------------
# 1.12 Regression — lambda-thunk idiom + field() remain byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lambda_thunk_arg_idiom_still_works() -> None:
    """Ships broken if the legacy
    "lambda: GraphQLArgument(GraphQLNonNull(Input._meta...))" thunk stops compiling."""
    from graphql import (
        GraphQLArgument,
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
        graphql_sync,
    )

    from django_graphex.core import Mutation, ObjectType, field
    from django_graphex.core.base import InputType, compile_all_inputs
    from django_graphex.core.schema_compiler import compile_native_root

    class _LegacyInput(InputType):
        """Input type carrying the single "name" field for the legacy mutation."""

        name: str

    compile_all_inputs()

    class _LegacyMutation(Mutation):
        """Mutation whose Arguments body uses the legacy lambda-thunk idiom."""

        class Arguments:
            """Declares the mutation's single argument via a lambda thunk."""

            data = lambda: GraphQLArgument(  # noqa: E731
                GraphQLNonNull(_LegacyInput._meta.graphql_input_type)
            )

        ok = field(GraphQLBoolean)
        echo = field(GraphQLString)

        @staticmethod
        def mutate(root, info, data):
            """Echo back the created user's name to prove the mutation ran."""
            return _LegacyMutation(ok=True, echo=data["name"])

    class _LegacyRoot(ObjectType):
        """Mutation root exposing the doLegacy field."""

        do_legacy = _LegacyMutation.Field()

    native_root = compile_native_root(_LegacyRoot, name="Mutation")
    assert isinstance(native_root.fields["doLegacy"].args["data"].type, GraphQLNonNull)

    query_root = GraphQLObjectType(
        "Query", {"ping": GraphQLField(GraphQLString, resolve=lambda r, i: "pong")}
    )
    schema = GraphQLSchema(query=query_root, mutation=native_root)
    result = graphql_sync(
        schema, 'mutation { doLegacy(data: {name: "Ada"}) { ok echo } }'
    )
    assert result.errors is None, result.errors
    assert result.data["doLegacy"]["echo"] == "Ada"


def test_field_helper_regression_unchanged() -> None:
    """Ships broken if "field(GraphQLString, description="d")" output changes
    (substrate intact)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField, field

    f = field(GraphQLString, description="d")
    assert isinstance(f, NativeField)
    assert f.type is GraphQLString
    assert f.description == "d"


def test_field_descriptor_sdl_byte_identical_to_field_helper() -> None:
    """Ships broken if a "Field(...)" and the equivalent "field(...)" compile
    to different SDL."""
    from graphql import GraphQLSchema, GraphQLString, print_schema

    from django_graphex.core import ObjectType, field
    from django_graphex.core.descriptors import Field
    from django_graphex.core.schema_compiler import compile_native_root

    class _RootA(ObjectType):
        """ObjectType declaring the field via the lowercase field() helper."""

        title = field(GraphQLString, description="d")

    class _RootB(ObjectType):
        """ObjectType declaring the equivalent field via the Field class."""

        title = Field(GraphQLString, description="d")

    root_a = compile_native_root(_RootA, name="Query")
    root_b = compile_native_root(_RootB, name="Query")

    schema_a = GraphQLSchema(query=root_a)
    schema_b = GraphQLSchema(query=root_b)
    assert print_schema(schema_a) == print_schema(schema_b)


# ===========================================================================
# G2: Typed scalar shortcuts — the same unified Field, usable in BOTH positions
# ===========================================================================
#
# The 12-name scalar inventory (name -> bound singleton). This is the SINGLE
# source of truth every parametrized test reads: each shortcut MUST bind the
# correct scalar SINGLETON (identity) as OUTPUT, and — routed through
# ``native_arg`` in an argument position — MUST produce a ``GraphQLArgument``
# byte-identical to the bare-scalar result.


def _output_shortcut_inventory():
    """Return "[(shortcut_name, bound_scalar_singleton), ...]" for the 12 shortcuts.

    Returns:
        A list of (shortcut_name, scalar_singleton) pairs covering every
        surviving typed scalar shortcut.
    """
    from graphql import (
        GraphQLBoolean,
        GraphQLFloat,
        GraphQLID,
        GraphQLInt,
        GraphQLString,
    )

    from django_graphex.core.scalars import (
        GdxDate,
        GdxDateTime,
        GdxDecimal,
        GdxJSON,
        GdxTime,
        GdxUUID,
    )

    # ``JSONField`` (default ``as_str=False``) binds the RAW ``JSON`` scalar
    # (``GdxJSON``); the old ``GenericJSONField`` shortcut is DELETED (v2 flip).
    return [
        ("IntField", GraphQLInt),
        ("CharField", GraphQLString),
        ("FloatField", GraphQLFloat),
        ("BooleanField", GraphQLBoolean),
        ("IDField", GraphQLID),
        ("DateField", GdxDate),
        ("DateTimeField", GdxDateTime),
        ("TimeField", GdxTime),
        ("DecimalField", GdxDecimal),
        ("UUIDField", GdxUUID),
        ("JSONField", GdxJSON),
    ]


# ---------------------------------------------------------------------------
# 2.1 Output scalar shortcuts — each binds the correct scalar singleton
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shortcut_name,scalar", _output_shortcut_inventory())
def test_output_shortcut_binds_correct_scalar_singleton(
    shortcut_name: str, scalar: Any
) -> None:
    """Ships broken if an output shortcut stops binding its scalar SINGLETON
    by identity ("is").

    Args:
        shortcut_name: The scalar shortcut class name under test.
        scalar: The graphql-core scalar singleton the shortcut must bind.
    """
    import django_graphex.core as core
    from django_graphex.core.descriptors import Field

    shortcut = getattr(core, shortcut_name)
    desc = shortcut()
    assert isinstance(desc, Field)
    # The bare (non-required) type is the scalar singleton itself.
    assert desc.type is scalar


@pytest.mark.parametrize("shortcut_name,scalar", _output_shortcut_inventory())
def test_output_shortcut_importable_from_core(shortcut_name: str, scalar: Any) -> None:
    """Ships broken if an output shortcut stops being importable from
    "django_graphex.core" and listed in "__all__".

    Args:
        shortcut_name: The scalar shortcut class name under test.
        scalar: The graphql-core scalar singleton the shortcut must bind
            (unused here beyond parametrization symmetry with the sibling test).
    """
    import django_graphex.core as core

    assert hasattr(core, shortcut_name)
    assert shortcut_name in core.__all__


def test_output_shortcut_required_wraps_nonnull() -> None:
    """Ships broken if "IntField(required=True).type" stops being "Int!"
    (a NativeNonNull around Int)."""
    from graphql import GraphQLInt

    from django_graphex.core import IntField
    from django_graphex.core.descriptors import NativeNonNull

    desc = IntField(required=True)
    assert isinstance(desc.type, NativeNonNull)
    assert desc.type.of_type is GraphQLInt


def test_output_shortcut_source_reads_off_root() -> None:
    """Ships broken if "CharField(source="user_email")" stops resolving by
    reading it off the root."""
    from django_graphex.core import CharField

    desc = CharField(source="user_email")
    resolver = desc.wrap_resolve(None)

    class _Root:
        """Stand-in resolver root exposing the source attribute to read."""

        user_email = "a@b.com"

    assert resolver(_Root(), None) == "a@b.com"


def test_output_shortcut_description_and_name_forwarded() -> None:
    """Ships broken if "CharField(description=, name=)" stops forwarding to
    the underlying "Field"."""
    from graphql import GraphQLString

    from django_graphex.core import CharField

    desc = CharField(description="d", name="t")
    assert desc.type is GraphQLString
    assert desc.description == "d"
    assert desc.name == "t"


def test_output_shortcut_resolver_wins() -> None:
    """Ships broken if an explicit resolver on an output shortcut stops
    winning over "source" (triangulation)."""
    from django_graphex.core import CharField

    def my_resolver(root, info):
        """Return a fixed marker string identifying the explicit resolver ran."""
        return "explicit"

    desc = CharField(source="user_email", resolver=my_resolver)
    assert desc.wrap_resolve(None) is my_resolver


# ---------------------------------------------------------------------------
# 2.3 The SAME shortcuts in an argument position — byte-identical to bare-scalar
# native_arg. The 12 unified shortcuts double as input arguments; there is no
# separate ``*InputField`` family anymore.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shortcut_name,scalar", _output_shortcut_inventory())
def test_shortcut_as_input_matches_bare_scalar_native_arg(
    shortcut_name: str, scalar: Any
) -> None:
    """Ships broken if a shortcut, routed through "native_arg", diverges from
    the bare scalar.

    Args:
        shortcut_name: The scalar shortcut class name under test.
        scalar: The graphql-core scalar singleton the shortcut must bind.
    """
    import django_graphex.core as core
    from django_graphex.core._args import native_arg

    shortcut = getattr(core, shortcut_name)
    # native_arg over the shortcut vs native_arg over the bare scalar — identical.
    via_shortcut = native_arg(shortcut(), name="q")
    via_bare = native_arg(scalar, name="q")

    assert via_shortcut.type is via_bare.type
    assert via_shortcut.type is scalar
    assert via_shortcut.out_name == via_bare.out_name == "q"


def test_shortcut_as_input_required_and_default() -> None:
    """Ships broken if "CharField(required=True, default="x")" stops
    producing "GraphQLArgument(NonNull(String), "x")"."""
    from graphql import GraphQLNonNull, GraphQLString

    from django_graphex.core import CharField
    from django_graphex.core._args import native_arg

    arg = native_arg(CharField(required=True, default="x"), name="q")
    assert isinstance(arg.type, GraphQLNonNull)
    assert arg.type.of_type is GraphQLString
    assert arg.default_value == "x"


def test_shortcut_as_input_no_default_is_undefined() -> None:
    """Ships broken if a shortcut argument with no default stops yielding
    graphql-core "Undefined" (not None)."""
    from graphql import Undefined

    from django_graphex.core import IntField
    from django_graphex.core._args import native_arg

    arg = native_arg(IntField(), name="count")
    assert arg.default_value is Undefined


def test_shortcut_as_input_explicit_none_default_distinct_from_unset() -> None:
    """Ships broken if "default=None" on a shortcut argument stops being an
    EXPLICIT null default (not Undefined)."""
    from graphql import Undefined

    from django_graphex.core import CharField
    from django_graphex.core._args import native_arg

    arg = native_arg(CharField(default=None), name="q")
    assert arg.default_value is None
    assert arg.default_value is not Undefined


def test_shortcut_as_input_description_forwarded() -> None:
    """Ships broken if "CharField(description=...)" stops forwarding to the
    built "GraphQLArgument"."""
    from django_graphex.core import CharField
    from django_graphex.core._args import native_arg

    arg = native_arg(CharField(description="the query"), name="q")
    assert arg.description == "the query"


# ---------------------------------------------------------------------------
# 2.x COLLISION (mandated) — importing CharField from django.db.models by
#     mistake fires the loud guard at BOTH the ObjectType-body AND the
#     Mutation-Arguments sites (hinting the import mistake).
# ---------------------------------------------------------------------------


def test_shortcut_collision_wrong_charfield_on_objecttype_body() -> None:
    """Ships broken if a "django.db.models.CharField" on an ObjectType body
    stops raising the loud guard.

    This is the exact mistake the shortcut names invite: "CharField" exists in
    BOTH "django.db.models" and "django_graphex.core". Passing the WRONG one
    to an ObjectType body must fire the named guard.
    """
    from django.db.models import CharField as DjangoCharField

    from django_graphex.core import CharField as GraphexCharField  # noqa: F401
    from django_graphex.core import ObjectType

    with pytest.raises(TypeError, match="django.db.models"):

        class _Bad(ObjectType):
            """ObjectType wrongly declaring the Django (not graphex) CharField."""

            name = DjangoCharField(max_length=10)


def test_shortcut_collision_wrong_charfield_in_mutation_arguments() -> None:
    """Ships broken if a "django.db.models.CharField" in a Mutation
    "Arguments" stops raising via "native_arg".

    Same import mistake, the OTHER site: passing the Django model "CharField" to
    a mutation argument must fire the named guard hinting the import mistake.
    """
    from django.db.models import CharField as DjangoCharField

    from django_graphex.core import CharField as GraphexCharField  # noqa: F401
    from django_graphex.core._args import native_arg

    with pytest.raises(TypeError, match="django.db.models"):
        native_arg(DjangoCharField(max_length=10), name="name")


# ---------------------------------------------------------------------------
# 2.x END-TO-END (mandated) — an ObjectType + Mutation built ENTIRELY with
#     shortcuts compiles into a schema and EXECUTES.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_end_to_end_object_type_and_mutation_built_with_shortcuts() -> None:
    """Ships broken if a full ObjectType + Mutation using ONLY shortcuts stops
    compiling and executing.

    - Output type uses "CharField(source=...)" and "IntField(required=True)".
    - Mutation "Arguments" uses the SAME shortcuts as arguments:
      "CharField(required=True)" and "IntField(default=10)".
    - SDL asserted, resolver runs, defaults honoured.
    """
    from graphql import (
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
        graphql_sync,
        print_schema,
    )

    from django_graphex.core import (
        BooleanField,
        CharField,
        IntField,
        Mutation,
        ObjectType,
        field,
    )
    from django_graphex.core.schema_compiler import compile_native_root

    # OUTPUT ObjectType built ENTIRELY with shortcuts:
    #   - CharField(source=...) reads off root
    #   - IntField(required=True) -> Int!
    class _Profile(ObjectType):
        """Output ObjectType built entirely with typed scalar shortcuts."""

        name = CharField(source="username")
        count = IntField(required=True)

    profile_root = compile_native_root(_Profile, name="Profile")
    assert isinstance(profile_root.fields["count"].type, GraphQLNonNull)  # Int!

    # SDL reflects the shortcut-declared fields (source= is invisible in SDL —
    # the field renders under its declared name).
    profile_schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Q", {"profile": __import__("graphql").GraphQLField(profile_root)}
        )
    )
    sdl = print_schema(profile_schema)
    assert "count: Int!" in sdl
    assert "name: String" in sdl

    # Query root built with a shortcut, resolving a real root object so
    # CharField(source=...) is exercised end-to-end.
    class _Query(ObjectType):
        """Query root resolving a Profile through a real root object."""

        profile = field(_Profile)

        def resolve_profile(root, info):
            """Return a fake root object so CharField(source=...) is exercised."""

            class _Obj:
                """Fake resolver root carrying the username and count attributes."""

                username = "grace"
                count = 7

            return _Obj()

    query_root = compile_native_root(_Query, name="Query")

    # Mutation whose Arguments are built ENTIRELY with the SAME shortcuts, now as
    # arguments:
    #   - CharField(required=True) -> String!
    #   - IntField(default=10)     -> default honoured
    class _MakeProfile(Mutation):
        """Mutation whose Arguments are built entirely with typed scalar shortcuts."""

        class Arguments:
            """Declares the mutation's required username and defaulted limit."""

            username = CharField(required=True)
            limit = IntField(default=10)

        ok = BooleanField()
        echo = CharField()

        @staticmethod
        def mutate(root, info, username, limit):
            """Echo back "username:limit" to prove the default was honoured."""
            return _MakeProfile(ok=True, echo=f"{username}:{limit}")

    class _MutationRoot(ObjectType):
        """Mutation root exposing the makeProfile field."""

        make_profile = _MakeProfile.Field()

    mutation_root = compile_native_root(_MutationRoot, name="Mutation")
    make_field = mutation_root.fields["makeProfile"]
    assert isinstance(make_field.args["username"].type, GraphQLNonNull)  # required=True
    assert make_field.args["limit"].default_value == 10  # default honoured
    assert make_field.args["username"].out_name == "username"

    schema = GraphQLSchema(query=query_root, mutation=mutation_root)

    # (1) Resolver runs and CharField(source=) reads off the root.
    q_result = graphql_sync(schema, "{ profile { name count } }")
    assert q_result.errors is None, f"shortcut query raised: {q_result.errors!r}"
    assert q_result.data["profile"]["name"] == "grace"
    assert q_result.data["profile"]["count"] == 7

    # (2) Mutation with required arg + honoured default executes.
    m_result = graphql_sync(
        schema, 'mutation { makeProfile(username: "grace") { ok echo } }'
    )
    assert m_result.errors is None, f"shortcut mutation raised: {m_result.errors!r}"
    assert m_result.data["makeProfile"]["ok"] is True
    assert (
        m_result.data["makeProfile"]["echo"] == "grace:10"
    )  # default limit=10 honoured


# --------------------------------------------------------------------------- #
# W1 fix (verify-report 1879): a Field's default=/description= must survive    #
# the ``field(args={...})`` route (to_graphql_argument), not only Arguments.   #
# --------------------------------------------------------------------------- #
class TestFieldArgsRouteCarriesDefaultAndDescription:
    """Regression suite for W1: the args= route must carry default/description.

    Covers "to_graphql_argument(Field(...))" so a Field's "default=" and
    "description=" reach the compiled "GraphQLArgument" the same way they do
    when the Field is declared inside a Mutation's "class Arguments" body.
    """

    def test_default_and_description_survive_args_route(self) -> None:
        """Ships broken if "to_graphql_argument(Field(...))" stops carrying
        default + description."""
        from graphql import GraphQLString

        from django_graphex.core import Field
        from django_graphex.core._args import to_graphql_argument

        arg = to_graphql_argument(
            Field(GraphQLString, default=10, description="how many"),
            name="q",
        )
        assert arg.default_value == 10
        assert arg.description == "how many"

    def test_explicit_none_default_is_a_null_default(self) -> None:
        """Ships broken if "default=None" stops being a REAL null default
        (distinct from no-default)."""
        from graphql import GraphQLString, Undefined

        from django_graphex.core import Field
        from django_graphex.core._args import to_graphql_argument

        arg = to_graphql_argument(Field(GraphQLString, default=None))
        assert arg.default_value is None
        assert arg.default_value is not Undefined

    def test_no_default_is_undefined_not_null(self) -> None:
        """Ships broken if omitting "default=" stops yielding "Undefined"
        (i.e. it wrongly becomes "= null")."""
        from graphql import GraphQLString, Undefined

        from django_graphex.core import Field
        from django_graphex.core._args import to_graphql_argument

        arg = to_graphql_argument(Field(GraphQLString))
        assert arg.default_value is Undefined

    def test_bare_type_has_no_default_regression(self) -> None:
        """Ships broken if a bare graphql-core type via the args route stops
        getting "Undefined" (no "= null" SDL leak), matching an argument with
        no declared default."""
        from graphql import GraphQLString, Undefined

        from django_graphex.core._args import to_graphql_argument

        arg = to_graphql_argument(GraphQLString, name="x")
        assert arg.default_value is Undefined


# --------------------------------------------------------------------------- #
# DjangoModelType `class Arguments` must accept the unified Field / typed       #
# scalar shortcuts — the THIRD arg call-site (types._build_native_mutation_field),#
# which consumed raw values without normalizing through to_graphql_argument.    #
# Runs in a SUBPROCESS: registering a DjangoModelType over auth.Group in the    #
# shared test process would pollute the global output registry.                 #
# --------------------------------------------------------------------------- #
_MODELTYPE_ARGS_SNIPPET = """
import django
from django.conf import settings
settings.configure(
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", "django_graphex"],
    DJANGO_GRAPHEX={},
)
django.setup()

from django.contrib.auth.models import Group
from graphql import GraphQLArgument, GraphQLBoolean
from django_graphex.core import BooleanField, IntField
from django_graphex.types import DjangoModelType


class GroupModelType(DjangoModelType):
    class Arguments:
        dry_run = BooleanField(description="Validate only; do not save")
        retries = IntField(default=3)
        raw_flag = GraphQLArgument(GraphQLBoolean)  # raw args keep working

    class Meta:
        model = Group


fld = GroupModelType.CreateField()
names = sorted(fld.args)
assert names == ["dryRun", "newGroup", "rawFlag", "retries"], names
assert fld.args["dryRun"].description == "Validate only; do not save"
assert fld.args["dryRun"].out_name == "dry_run"
assert fld.args["retries"].default_value == 3
upd = GroupModelType.UpdateField()
assert "dryRun" in upd.args and "retries" in upd.args
print("OK")
"""


def test_modeltype_arguments_accept_input_field_descriptors() -> None:
    """Ships broken if DjangoModelType.Arguments members declared with the
    unified "Field" / typed scalar shortcuts stop compiling into the
    generated CRUD mutation fields (camelCased wire name, snake out_name,
    description + default preserved), alongside raw GraphQLArgument values."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _MODELTYPE_ARGS_SNIPPET],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    assert "OK" in result.stdout
