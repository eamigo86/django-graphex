"""Audit rank 7 — native OUTPUT rendering for PostgreSQL ArrayField / RangeField.

v1.x graphene rendered "django.contrib.postgres.fields.ArrayField" as a
"GraphQLList" and a "RangeField" as a composite object. The native OUTPUT
compiler had NO entry for either, so the MRO walk over "DJANGO_TO_GQL" found
nothing and the field was silently DROPPED from the SDL (a v1 to v2
regression). These tests prove both field families are now PRESENT in the
compiled output type with the expected GraphQL shapes:

    * ArrayField(CharField)             -> [String]
    * ArrayField(IntegerField)          -> [Int]
    * ArrayField(ArrayField(CharField)) -> [[String]]
    * ArrayField(CharField(choices=...))-> [Enum]
    * IntegerRangeField                 -> { lower: Int,  upper: Int }
    * DateTimeRangeField                -> { lower: DateTime, upper: DateTime }

This is a COMPILER-level (build-time SDL) test — it constructs the model/fields
and compiles the output type. It does NOT need a live PostgreSQL connection.

Detection in the compiler is keyed on "field.get_internal_type()" (not on
isinstance against the real Django classes), because importing
"django.contrib.postgres.fields" pulls in the psycopg adapter chain, which is
NOT installed in this test venv. The stand-in fields below therefore subclass
plain "models.Field" and report the real internal-type strings, mirroring how
the production classes identify themselves.

Run: .venv/bin/python -m pytest -q tests/core/test_output_postgres.py
"""

from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

# Imports below are intentionally after ``django.setup()`` (the established
# pattern in tests/core/test_output_compiler.py): the native compiler modules
# touch Django model machinery on import, so settings must be configured first.
from django.db import models  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLEnumType,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLString,
)

from django_graphex.core.output_compiler import (  # noqa: E402
    _to_graphql_field,
    compile_output_fields,
)
from django_graphex.core.scalars import GdxDateTime  # noqa: E402

# ---------------------------------------------------------------------------
# psycopg-free stand-ins for the PostgreSQL fields.
#
# The real classes cannot be imported in this venv (no psycopg). These mirror
# the only two attributes the OUTPUT compiler reads: ``get_internal_type()`` and
# (for arrays) ``base_field`` — and they bind the base field to the owning model
# on ``contribute_to_class`` exactly like Django's real ``ArrayField`` does, so
# a base field with ``choices`` can resolve its canonical enum name.
# ---------------------------------------------------------------------------


class FakeArrayField(models.Field):
    """Stand-in for "django.contrib.postgres.fields.ArrayField".

    Reports "ArrayField" as its internal type without requiring the psycopg
    adapter chain that the real class pulls in.
    """

    def __init__(self, base_field: models.Field, **kwargs: object) -> None:
        """Store the element field and default the column to nullable.

        Args:
            base_field: The Django field describing each array element.
            **kwargs: Extra field options forwarded to "models.Field".
        """
        self.base_field = base_field
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self) -> str:
        """Report the internal type string the output compiler keys on.

        Returns:
            internal_type: The literal string "ArrayField".
        """
        return "ArrayField"

    def contribute_to_class(
        self, cls: type[models.Model], name: str, **kwargs: object
    ) -> None:
        """Bind the base field to the owning model, mirroring real ArrayField.

        Args:
            cls: The model class this field is being attached to.
            name: The attribute name the field is bound to on "cls".
            **kwargs: Extra options forwarded to the base implementation.
        """
        super().contribute_to_class(cls, name, **kwargs)
        # Mirror real ArrayField: bind the base field to the owning model/name
        # so a choices base field can derive its canonical enum name.
        self.base_field.model = cls
        self.base_field.set_attributes_from_name(name)

    def deconstruct(self) -> tuple[str, str, list[object], dict[str, object]]:
        """Re-emit the base field as a positional arg, mirroring real ArrayField.

        Django's "Field.clone()" (used when building migration ModelState for
        the test DB) rebuilds via "self.__class__(*args, **kwargs)" from
        "deconstruct()". "base_field" is a required positional arg, so it MUST
        appear in the returned args — otherwise clone() raises and any later
        test that migrates the "tests" app errors out.

        Returns:
            deconstructed: The (name, path, args, kwargs) tuple with the
                cloned base field prepended to args.
        """
        name, path, args, kwargs = super().deconstruct()
        return name, path, [self.base_field.clone(), *args], kwargs


class _FakeRangeField(models.Field):
    """Base stand-in for "django.contrib.postgres.fields.RangeField"."""

    _internal = "RangeField"

    def __init__(self, **kwargs: object) -> None:
        """Default the column to nullable, mirroring real range fields.

        Args:
            **kwargs: Extra field options forwarded to "models.Field".
        """
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self) -> str:
        """Report the internal type string the output compiler keys on.

        Returns:
            internal_type: The subclass-specific range type name.
        """
        return self._internal


class FakeIntegerRangeField(_FakeRangeField):
    """Stand-in for "django.contrib.postgres.fields.IntegerRangeField".

    Reports "IntegerRangeField" as its internal type.
    """

    _internal = "IntegerRangeField"


class FakeDateTimeRangeField(_FakeRangeField):
    """Stand-in for "django.contrib.postgres.fields.DateTimeRangeField".

    Reports "DateTimeRangeField" as its internal type.
    """

    _internal = "DateTimeRangeField"


# ---------------------------------------------------------------------------
# Test models (pure-python, app_label="tests"; never migrated — build-time only)
# ---------------------------------------------------------------------------

_GENRE_CHOICES = [("rock", "Rock"), ("jazz", "Jazz"), ("folk", "Folk")]


class PgArrayModel(models.Model):
    """Model exercising every ArrayField shape + a RangeField.

    Registered under the "tests" app label; never migrated since this is a
    build-time-only (SDL compilation) fixture.
    """

    tags = FakeArrayField(models.CharField(max_length=50))
    scores = FakeArrayField(models.IntegerField())
    matrix = FakeArrayField(FakeArrayField(models.CharField(max_length=50)))
    genres = FakeArrayField(models.CharField(max_length=10, choices=_GENRE_CHOICES))
    age_range = FakeIntegerRangeField()
    active_period = FakeDateTimeRangeField()

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


# ---------------------------------------------------------------------------
# Minimal registry + graphene-registry stubs
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry for the output compiler.

    Only "get_compiled" is used by the code paths exercised in this file.
    """

    def __init__(self) -> None:
        self._compiled: dict = {}

    def get_compiled(self, model_cls: type) -> object | None:
        """Return the compiled GraphQL type registered for a model class.

        Args:
            model_cls: The Django model class to look up.

        Returns:
            compiled: The registered compiled type, or None if unregistered.
        """
        return self._compiled.get(model_cls)


class StubGrapheneRegistry:
    """Minimal enum slot registry shared by output + filter-input paths.

    Backs the "graphene_registry" parameter accepted by the output compiler
    so a choices field can resolve or register its shared enum type.
    """

    def __init__(self) -> None:
        self._enums: dict = {}

    def get_type_for_enum(self, key: str) -> object | None:
        """Return the shared enum type registered under a canonical key.

        Args:
            key: The canonical enum name to look up.

        Returns:
            enum_type: The registered enum type, or None if unregistered.
        """
        return self._enums.get(key)

    def register_enum(self, key: str, enum_type: object) -> None:
        """Register a shared enum type under its canonical key.

        Args:
            key: The canonical enum name.
            enum_type: The GraphQL enum type to associate with it.
        """
        self._enums[key] = enum_type


def _unwrap_nonnull(gql_type: object) -> object:
    """Strip a GraphQLNonNull wrapper, returning the inner type unchanged otherwise.

    Args:
        gql_type: The GraphQL type to unwrap.

    Returns:
        inner: The wrapped type's "of_type" if non-null, else "gql_type" as-is.
    """
    return gql_type.of_type if isinstance(gql_type, GraphQLNonNull) else gql_type


# ---------------------------------------------------------------------------
# ArrayField → GraphQLList(<inner>)
# ---------------------------------------------------------------------------


def test_array_of_char_renders_list_of_string() -> None:
    """ArrayField(CharField) must render [String], PRESENT on the output type.

    Contract: ArrayField output rendering ships broken (regressed to v1's
    silent drop) if a CharField-backed array no longer compiles to a List.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("tags"), registry)

    assert "tags" in field_map, "ArrayField(CharField) must NOT be dropped"
    gql_type = _unwrap_nonnull(field_map["tags"].type)
    assert isinstance(gql_type, GraphQLList), f"expected a List, got {gql_type!r}"
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLString


def test_array_of_int_renders_list_of_int() -> None:
    """ArrayField(IntegerField) must render [Int].

    Contract: ArrayField output rendering ships broken if an IntegerField-
    backed array no longer compiles to a List of Int.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("scores"), registry)

    assert "scores" in field_map
    gql_type = _unwrap_nonnull(field_map["scores"].type)
    assert isinstance(gql_type, GraphQLList)
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLInt


def test_nested_array_renders_list_of_list() -> None:
    """ArrayField(ArrayField(CharField)) must render [[String]].

    Contract: nested ArrayField rendering ships broken if the compiler
    stops recursing through a doubly-nested array shape.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("matrix"), registry)

    assert "matrix" in field_map
    outer = _unwrap_nonnull(field_map["matrix"].type)
    assert isinstance(outer, GraphQLList), f"outer must be a List, got {outer!r}"
    inner = _unwrap_nonnull(outer.of_type)
    assert isinstance(inner, GraphQLList), f"inner must be a List, got {inner!r}"
    assert _unwrap_nonnull(inner.of_type) is GraphQLString


def test_array_of_choices_renders_list_of_enum() -> None:
    """ArrayField(CharField(choices=...)) must render [Enum], reusing the enum builder.

    Contract: choices-array rendering ships broken if the choices base
    field stops resolving through the shared choices-enum builder.
    """
    registry = StubRegistry()
    graphene_registry = StubGrapheneRegistry()
    field_map = _to_graphql_field(
        PgArrayModel._meta.get_field("genres"), registry, graphene_registry
    )

    assert "genres" in field_map
    gql_type = _unwrap_nonnull(field_map["genres"].type)
    assert isinstance(gql_type, GraphQLList)
    inner = _unwrap_nonnull(gql_type.of_type)
    assert isinstance(inner, GraphQLEnumType), (
        f"a choices base field must render [Enum], got {inner!r}"
    )
    assert set(inner.values.keys()) == {"ROCK", "JAZZ", "FOLK"}


def test_array_of_choices_without_graphene_registry_falls_back_to_string() -> None:
    """Without a shared enum registry, a choices base field falls back to [String].

    Contract: the no-shared-registry fallback ships broken if it crashes or
    still tries to render an enum instead of the plain scalar.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("genres"), registry)

    assert "genres" in field_map
    gql_type = _unwrap_nonnull(field_map["genres"].type)
    assert isinstance(gql_type, GraphQLList)
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLString


# ---------------------------------------------------------------------------
# RangeField → composite { lower, upper }
# ---------------------------------------------------------------------------


def test_integer_range_renders_composite_int_bounds() -> None:
    """IntegerRangeField must render { lower: Int, upper: Int } composite object.

    Contract: RangeField output rendering ships broken (regressed to v1's
    silent drop) if an IntegerRangeField no longer compiles to a composite.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("age_range"), registry)

    assert "ageRange" in field_map, "RangeField must NOT be dropped"
    composite = _unwrap_nonnull(field_map["ageRange"].type)
    assert isinstance(composite, GraphQLObjectType), (
        f"RangeField must render a composite object, got {composite!r}"
    )
    fields = composite.fields
    assert set(fields) == {"lower", "upper"}
    assert _unwrap_nonnull(fields["lower"].type) is GraphQLInt
    assert _unwrap_nonnull(fields["upper"].type) is GraphQLInt


def test_datetime_range_renders_composite_datetime_bounds() -> None:
    """DateTimeRangeField must render { lower: DateTime, upper: DateTime } composite.

    Contract: RangeField output rendering ships broken if a
    DateTimeRangeField stops binding its composite's bounds to GdxDateTime.
    """
    registry = StubRegistry()
    field_map = _to_graphql_field(
        PgArrayModel._meta.get_field("active_period"), registry
    )

    assert "activePeriod" in field_map
    composite = _unwrap_nonnull(field_map["activePeriod"].type)
    assert isinstance(composite, GraphQLObjectType)
    fields = composite.fields
    assert set(fields) == {"lower", "upper"}
    assert _unwrap_nonnull(fields["lower"].type) is GdxDateTime
    assert _unwrap_nonnull(fields["upper"].type) is GdxDateTime


def test_distinct_range_bound_types_get_distinct_composites() -> None:
    """Int-bound and DateTime-bound ranges must NOT share one composite type.

    Contract: per-bound-scalar memoization ships broken if two Range fields
    with different bound scalars collapse onto the same composite type.
    """
    registry = StubRegistry()
    int_field = _to_graphql_field(PgArrayModel._meta.get_field("age_range"), registry)
    dt_field = _to_graphql_field(
        PgArrayModel._meta.get_field("active_period"), registry
    )
    int_composite = _unwrap_nonnull(int_field["ageRange"].type)
    dt_composite = _unwrap_nonnull(dt_field["activePeriod"].type)
    assert int_composite is not dt_composite


# ---------------------------------------------------------------------------
# Full-model compile: every field PRESENT (the regression is closed)
# ---------------------------------------------------------------------------


def test_full_compile_includes_all_postgres_fields() -> None:
    """compile_output_fields must render every Array/Range field (none dropped).

    Contract: the full-model compile path ships broken if any PostgreSQL
    Array/Range field is silently dropped from the compiled output type.
    """
    registry = StubRegistry()
    graphene_registry = StubGrapheneRegistry()
    fields = compile_output_fields(
        PgArrayModel, registry, graphene_registry=graphene_registry
    )

    for camel in ("tags", "scores", "matrix", "genres", "ageRange", "activePeriod"):
        assert camel in fields, f"{camel!r} must be present in the compiled output"
        assert isinstance(fields[camel], GraphQLField)

    # Spot-check the shapes survive the full compile path too.
    assert isinstance(_unwrap_nonnull(fields["tags"].type), GraphQLList)
    assert isinstance(_unwrap_nonnull(fields["ageRange"].type), GraphQLObjectType)
