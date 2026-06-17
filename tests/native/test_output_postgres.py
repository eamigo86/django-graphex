"""Audit rank 7 — native OUTPUT rendering for PostgreSQL ArrayField / RangeField.

v1.x graphene rendered ``django.contrib.postgres.fields.ArrayField`` as a
``GraphQLList`` and a ``RangeField`` as a composite object. The native OUTPUT
compiler had NO entry for either, so the MRO walk over ``DJANGO_TO_GQL`` found
nothing and the field was silently DROPPED from the SDL (a v1→v2 regression).
These tests prove both field families are now PRESENT in the compiled output
type with the expected GraphQL shapes:

    * ArrayField(CharField)            → [String]
    * ArrayField(IntegerField)         → [Int]
    * ArrayField(ArrayField(CharField))→ [[String]]
    * ArrayField(CharField(choices=…)) → [Enum]
    * IntegerRangeField                → { lower: Int,  upper: Int }
    * DateTimeRangeField               → { lower: DateTime, upper: DateTime }

This is a COMPILER-level (build-time SDL) test — it constructs the model/fields
and compiles the output type. It does NOT need a live PostgreSQL connection.

Detection in the compiler is keyed on ``field.get_internal_type()`` (not on
``isinstance`` against the real Django classes), because importing
``django.contrib.postgres.fields`` pulls in the psycopg adapter chain, which is
NOT installed in this test venv. The stand-in fields below therefore subclass
plain ``models.Field`` and report the real internal-type strings, mirroring how
the production classes identify themselves.

Run: .venv/bin/python -m pytest -q tests/native/test_output_postgres.py
"""
from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

# Imports below are intentionally after ``django.setup()`` (the established
# pattern in tests/native/test_output_compiler.py): the native compiler modules
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

from django_graphex.native.output_compiler import (  # noqa: E402
    _to_graphql_field,
    compile_output_fields,
)
from django_graphex.native.scalars import GdxDateTime  # noqa: E402

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
    """Stand-in for ``django.contrib.postgres.fields.ArrayField``."""

    def __init__(self, base_field: models.Field, **kwargs):
        self.base_field = base_field
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self) -> str:
        return "ArrayField"

    def contribute_to_class(self, cls, name, **kwargs):  # noqa: ANN001
        super().contribute_to_class(cls, name, **kwargs)
        # Mirror real ArrayField: bind the base field to the owning model/name
        # so a choices base field can derive its canonical enum name.
        self.base_field.model = cls
        self.base_field.set_attributes_from_name(name)

    def deconstruct(self):
        # Django's ``Field.clone()`` (used when building migration ModelState
        # for the test DB) rebuilds via ``self.__class__(*args, **kwargs)`` from
        # ``deconstruct()``. ``base_field`` is a required positional arg, so it
        # MUST appear in the returned args — otherwise clone() raises and any
        # later test that migrates the ``tests`` app errors out. Mirrors real
        # ArrayField.deconstruct(), which also re-emits its base field.
        name, path, args, kwargs = super().deconstruct()
        return name, path, [self.base_field.clone(), *args], kwargs


class _FakeRangeField(models.Field):
    """Base stand-in for ``django.contrib.postgres.fields.RangeField``."""

    _internal = "RangeField"

    def __init__(self, **kwargs):
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self) -> str:
        return self._internal


class FakeIntegerRangeField(_FakeRangeField):
    _internal = "IntegerRangeField"


class FakeDateTimeRangeField(_FakeRangeField):
    _internal = "DateTimeRangeField"


# ---------------------------------------------------------------------------
# Test models (pure-python, app_label="tests"; never migrated — build-time only)
# ---------------------------------------------------------------------------

_GENRE_CHOICES = [("rock", "Rock"), ("jazz", "Jazz"), ("folk", "Folk")]


class PgArrayModel(models.Model):
    """Model exercising every ArrayField shape + a RangeField."""

    tags = FakeArrayField(models.CharField(max_length=50))
    scores = FakeArrayField(models.IntegerField())
    matrix = FakeArrayField(FakeArrayField(models.CharField(max_length=50)))
    genres = FakeArrayField(models.CharField(max_length=10, choices=_GENRE_CHOICES))
    age_range = FakeIntegerRangeField()
    active_period = FakeDateTimeRangeField()

    class Meta:
        app_label = "tests"


# ---------------------------------------------------------------------------
# Minimal registry + graphene-registry stubs
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry for the output compiler (only get_compiled is used)."""

    def __init__(self):
        self._compiled: dict = {}

    def get_compiled(self, model_cls):
        return self._compiled.get(model_cls)


class StubGrapheneRegistry:
    """Minimal enum slot registry shared by output + filter-input paths."""

    def __init__(self):
        self._enums: dict = {}

    def get_type_for_enum(self, key):
        return self._enums.get(key)

    def register_enum(self, key, enum_type):
        self._enums[key] = enum_type


def _unwrap_nonnull(gql_type):
    return gql_type.of_type if isinstance(gql_type, GraphQLNonNull) else gql_type


# ---------------------------------------------------------------------------
# ArrayField → GraphQLList(<inner>)
# ---------------------------------------------------------------------------


def test_array_of_char_renders_list_of_string():
    """ArrayField(CharField) → [String], PRESENT on the output type."""
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("tags"), registry)

    assert "tags" in field_map, "ArrayField(CharField) must NOT be dropped"
    gql_type = _unwrap_nonnull(field_map["tags"].type)
    assert isinstance(gql_type, GraphQLList), f"expected a List, got {gql_type!r}"
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLString


def test_array_of_int_renders_list_of_int():
    """ArrayField(IntegerField) → [Int]."""
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("scores"), registry)

    assert "scores" in field_map
    gql_type = _unwrap_nonnull(field_map["scores"].type)
    assert isinstance(gql_type, GraphQLList)
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLInt


def test_nested_array_renders_list_of_list():
    """ArrayField(ArrayField(CharField)) → [[String]]."""
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("matrix"), registry)

    assert "matrix" in field_map
    outer = _unwrap_nonnull(field_map["matrix"].type)
    assert isinstance(outer, GraphQLList), f"outer must be a List, got {outer!r}"
    inner = _unwrap_nonnull(outer.of_type)
    assert isinstance(inner, GraphQLList), f"inner must be a List, got {inner!r}"
    assert _unwrap_nonnull(inner.of_type) is GraphQLString


def test_array_of_choices_renders_list_of_enum():
    """ArrayField(CharField(choices=…)) → [Enum] reusing the choices-enum builder."""
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


def test_array_of_choices_without_graphene_registry_falls_back_to_string():
    """Without a shared enum registry, a choices base field falls back to [String]."""
    registry = StubRegistry()
    field_map = _to_graphql_field(PgArrayModel._meta.get_field("genres"), registry)

    assert "genres" in field_map
    gql_type = _unwrap_nonnull(field_map["genres"].type)
    assert isinstance(gql_type, GraphQLList)
    assert _unwrap_nonnull(gql_type.of_type) is GraphQLString


# ---------------------------------------------------------------------------
# RangeField → composite { lower, upper }
# ---------------------------------------------------------------------------


def test_integer_range_renders_composite_int_bounds():
    """IntegerRangeField → { lower: Int, upper: Int } composite object."""
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


def test_datetime_range_renders_composite_datetime_bounds():
    """DateTimeRangeField → { lower: DateTime, upper: DateTime } composite object."""
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


def test_distinct_range_bound_types_get_distinct_composites():
    """Int-bound and DateTime-bound ranges must NOT share one composite type."""
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


def test_full_compile_includes_all_postgres_fields():
    """compile_output_fields renders every Array/Range field (none dropped)."""
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
