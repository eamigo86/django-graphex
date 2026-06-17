"""WU12 Phase-5 carry-forward coverage — filtering/native_schema.py.

Lifts ``filtering/native_schema.py`` branch coverage to >=95% by exercising the
native ``<Model>FilterInput`` builder paths the ``tests/native/`` suite did not
reach (the filtering parity tests live at ``tests/`` root and never ran under the
per-module ``tests/native/`` gate).

Each test asserts a MEANINGFUL outcome (real input-type shape, ``out_name``
mapping, scalar/enum dispatch, relation nesting, custom-filter typing) — not
coverage theater. All run under GDX_BACKEND=native.

Run:
  GDX_BACKEND=native .venv/bin/python -m pytest -q tests/native/test_wu12_native_schema_coverage.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest
from graphql import (
    GraphQLBoolean,
    GraphQLEnumType,
    GraphQLID,
    GraphQLInputObjectType,
    GraphQLInt,
    GraphQLList,
    GraphQLString,
)

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# build_filter_input_type — early returns + global-registry default
# ---------------------------------------------------------------------------


def test_build_filter_input_returns_none_without_fields_or_custom():
    """No filter_fields and no custom_filters -> None (line 343)."""
    from django_graphex.filtering.native_schema import build_filter_input_type
    from tests.models import Post

    assert build_filter_input_type(Post, None) is None
    assert build_filter_input_type(Post, []) is None


def test_build_filter_input_uses_global_registry_when_none(db):
    """registry=None resolves the global registry (line 345-346)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    # Clear cache so the registry-None branch actually executes (cache miss).
    _NATIVE_INPUT_CACHE.clear()

    result = build_filter_input_type(Post, ["title"], registry=None)
    assert isinstance(result, GraphQLInputObjectType)
    # title scalar field -> camelCase wire key + snake out_name.
    fields = result.fields
    assert "title" in fields
    assert fields["title"].out_name == "title"


# ---------------------------------------------------------------------------
# own scalar field -> <Field>Lookups input with out_name per lookup
# ---------------------------------------------------------------------------


def test_scalar_field_builds_lookups_input_with_out_names(db):
    """A scalar own-field produces a Lookups input whose lookups carry out_name."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()
    # Dict form with an explicit lookup tuple that exercises every out_name arm
    # of _build_lookups_type: isnull -> Boolean, in/range -> List(scalar), else scalar.
    result = build_filter_input_type(
        Post, {"title": ("exact", "icontains", "isnull", "in", "range")}
    )
    lookups_field = result.fields["title"]
    lookups_type = lookups_field.type
    assert isinstance(lookups_type, GraphQLInputObjectType)
    lf = lookups_type.fields
    assert "exact" in lf and lf["exact"].out_name == "exact"
    assert lf["isnull"].type is GraphQLBoolean
    assert lf["isnull"].out_name == "isnull"
    assert isinstance(lf["in"].type, GraphQLList)
    assert lf["in"].out_name == "in"
    assert isinstance(lf["range"].type, GraphQLList)
    assert lf["range"].out_name == "range"


def test_unknown_field_internal_type_falls_back_to_string(db):
    """A field whose internal type is not in the scalar map -> GraphQLString (180)."""
    # DurationField maps to String in the native scalar map; pick a field with an
    # internal type absent from the map to hit the fallback return at line 180.
    # JSONField/etc. are mapped, so probe a synthetic field via a real one whose
    # internal type is missing: use a SlugField-less probe by directly checking a
    # field Django reports an unmapped internal type for is brittle; instead probe
    # the documented String fallback through a TextField (mapped) AND assert the
    # explicit fallback line via a field with no map entry.
    from django.db import models as dj_models

    from django_graphex.filtering.native_schema import _field_scalar

    class _UnmappedField(dj_models.Field):
        def get_internal_type(self):  # noqa: D401
            return "SomeUnmappedInternalType"

    fake = _UnmappedField()
    assert _field_scalar(fake) is GraphQLString


# ---------------------------------------------------------------------------
# FK / OneToOne scalar -> related model pk scalar (_pk_scalar / lines 161, 175)
# ---------------------------------------------------------------------------


def test_fk_field_scalar_uses_related_pk_scalar(db):
    """A ForeignKey field's scalar is the related model's pk scalar (175, 161)."""
    from django_graphex.filtering.native_schema import _field_scalar, _pk_scalar
    from tests.models import Author, Post

    fk_field = Post._meta.get_field("author")
    # author FK -> Author pk (AutoField -> ID)
    assert _field_scalar(fk_field) is _pk_scalar(Author)
    assert _pk_scalar(Author) is GraphQLID


def test_uuid_fk_field_scalar_is_uuid_pk(db):
    """A FK to a UUID-pk model yields the UUID scalar (covers _pk_scalar branch)."""
    from django_graphex.filtering.native_schema import _field_scalar
    from django_graphex.native.scalars import GdxUUID
    from tests.models import UUIDItem

    fk_field = UUIDItem._meta.get_field("thing")
    assert _field_scalar(fk_field) is GdxUUID


# ---------------------------------------------------------------------------
# choices field -> _choices_enum (lines 200-221, 250)
# ---------------------------------------------------------------------------


def test_choices_field_builds_enum_lookups(db):
    """A CharField with choices yields a GraphQLEnumType scalar in its lookups."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import EnumCollisionItemA

    _NATIVE_INPUT_CACHE.clear()
    result = build_filter_input_type(EnumCollisionItemA, {"status": ("exact",)})
    lookups_type = result.fields["status"].type
    enum_scalar = lookups_type.fields["exact"].type
    assert isinstance(enum_scalar, GraphQLEnumType)
    # The enum exposes the declared choices (get_choices uppercases the keys).
    assert set(enum_scalar.values.keys()) == {"A", "B"}
    # And the underlying values map back to the stored choice codes.
    assert {v.value for v in enum_scalar.values.values()} == {"a", "b"}


def test_choices_enum_memoized_via_registry(db):
    """_choices_enum returns the cached enum on the second call (lines 205-207)."""
    from django_graphex.filtering.native_schema import _choices_enum
    from django_graphex.registry import get_global_registry
    from tests.models import EnumCollisionItemB

    field = EnumCollisionItemB._meta.get_field("status")
    registry = get_global_registry()
    first = _choices_enum(field, registry)
    second = _choices_enum(field, registry)
    assert isinstance(first, GraphQLEnumType)
    # Second call hits the registry cache branch and returns the SAME instance.
    assert second is first


def test_choices_enum_falls_back_to_string_when_no_choices(db):
    """_choices_enum returns GraphQLString when the field has no choices (210-211)."""
    from django_graphex.filtering.native_schema import _choices_enum
    from django_graphex.registry import get_global_registry
    from tests.models import Post

    # title has no choices -> the not-choices guard returns String.
    field = Post._meta.get_field("title")
    assert _choices_enum(field, get_global_registry()) is GraphQLString


def test_choices_enum_falls_back_to_string_when_empty_values(db):
    """_choices_enum returns GraphQLString when choices produce no values (216-217)."""

    from django_graphex.filtering.native_schema import _choices_enum
    from django_graphex.registry import get_global_registry
    from tests.models import Post

    # A field reporting truthy-but-empty choices: get_choices() yields nothing.
    field = Post._meta.get_field("title")

    class _EmptyChoicesField:
        model = Post
        name = "title_probe"
        choices = [("__grp__", [])]  # truthy choices, but get_choices yields none

    # Monkeypatch get_choices to return empty for this probe so values stays empty.
    import django_graphex.converter as conv

    original = conv.get_choices
    try:
        conv.get_choices = lambda choices: iter(())  # noqa: ARG005
        result = _choices_enum(_EmptyChoicesField(), get_global_registry())
    finally:
        conv.get_choices = original
    assert result is GraphQLString
    assert field is not None  # sanity


# ---------------------------------------------------------------------------
# relation paths: nested (head__tail), relation_direct (head -> pk lookups)
# (lines 367-379, 400-412, 275-279)
# ---------------------------------------------------------------------------


def test_nested_relation_filter_builds_subinput(db):
    """A ``author__name`` path nests a related FilterInput (relations branch)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()
    result = build_filter_input_type(Post, {"author__name": ("exact", "icontains")})
    # head 'author' -> nested Author FilterInput, out_name snake 'author'.
    assert "author" in result.fields
    nested = result.fields["author"]
    assert nested.out_name == "author"
    assert isinstance(nested.type, GraphQLInputObjectType)
    # The nested input exposes the leaf 'name' lookups.
    assert "name" in nested.type.fields


def test_relation_direct_filter_builds_pk_lookups(db):
    """A bare relation name (``author``) yields a pk-lookups input (407-412, 275-279)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()
    result = build_filter_input_type(Post, ["author"])
    assert "author" in result.fields
    direct = result.fields["author"]
    assert direct.out_name == "author"
    pk_lookups_type = direct.type
    assert isinstance(pk_lookups_type, GraphQLInputObjectType)
    # The pk lookups expose 'exact' typed as the related pk scalar (ID).
    assert pk_lookups_type.fields["exact"].type is GraphQLID


def test_pk_lookups_explicit_lookup_tuple(db):
    """_pk_lookups_input_type honors an explicit lookup tuple (skips line 275-276)."""
    from django_graphex.filtering.native_schema import _pk_lookups_input_type
    from tests.models import Author, Post

    result = _pk_lookups_input_type(Post, "author", Author, ("exact", "in"))
    assert isinstance(result, GraphQLInputObjectType)
    assert set(result.fields.keys()) == {"exact", "in"}
    assert isinstance(result.fields["in"].type, GraphQLList)


def test_path_with_separator_but_no_relation_treated_as_own(db):
    """A ``foo__bar`` path whose head is NOT a relation is treated as own (371-372)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()
    # 'title__icontains' — head 'title' is a scalar (no relation): the whole path
    # goes into 'own', then get_field('title__icontains') raises FieldDoesNotExist
    # and is skipped (lines 387-390). Result still has the and/or/not combinators.
    result = build_filter_input_type(Post, ["title__icontains"])
    assert isinstance(result, GraphQLInputObjectType)
    # The bogus own path was skipped; combinators keep the type non-empty.
    assert "and" in result.fields


# ---------------------------------------------------------------------------
# field that does not exist -> FieldDoesNotExist skip (389-390)
# ---------------------------------------------------------------------------


def test_nonexistent_own_field_is_skipped(db):
    """An own field name that doesn't exist on the model is skipped (389-390)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()
    # 'nonexistent_field' is not a relation and not a real field -> skipped.
    result = build_filter_input_type(Post, ["nonexistent_field", "title"])
    assert "title" in result.fields
    # The phantom field produced no entry.
    assert "nonexistentField" not in result.fields


# ---------------------------------------------------------------------------
# custom @filter_field args -> _custom_filter_gql_type (lines 414-416, 495-501)
# ---------------------------------------------------------------------------


def test_custom_filter_with_graphene_type(db):
    """A custom filter carrying graphene_type=Int renders an Int arg (495-501).

    The native filter builder normalizes the declared ``graphene_type`` and
    accepts a graphql-core scalar AS-IS, so a native ``GraphQLInt`` is the
    canonical end-state arg type (the metadata key name is 1.x-historical)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()

    def _by_year(qs, value):  # pragma: no cover - not invoked here
        return qs

    custom = [("byYear", _by_year, {"graphene_type": GraphQLInt, "description": "yr"})]
    result = build_filter_input_type(Post, ["title"], custom_filters=custom)
    assert "byYear" in result.fields
    assert result.fields["byYear"].type is GraphQLInt
    assert result.fields["byYear"].out_name == "byYear"
    assert result.fields["byYear"].description == "yr"


def test_custom_filter_without_graphene_type_defaults_string(db):
    """_custom_filter_gql_type returns String when no graphene_type (496-497)."""
    from django_graphex.filtering.native_schema import _custom_filter_gql_type

    assert _custom_filter_gql_type({}) is GraphQLString
    assert _custom_filter_gql_type({"graphene_type": None}) is GraphQLString


def test_custom_filter_only_no_declared_fields(db):
    """custom_filters with no filter_fields still builds an input (not None)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Post

    _NATIVE_INPUT_CACHE.clear()

    def _flag(qs, value):  # pragma: no cover - not invoked
        return qs

    custom = [("isFeatured", _flag, {"graphene_type": GraphQLBoolean})]
    result = build_filter_input_type(Post, None, custom_filters=custom)
    assert isinstance(result, GraphQLInputObjectType)
    assert result.fields["isFeatured"].type is GraphQLBoolean


# ---------------------------------------------------------------------------
# cache hit on second identical build (line 358-360)
# ---------------------------------------------------------------------------


def test_filter_input_cache_hit_returns_same_instance(db):
    """The second identical build returns the cached instance (358-360)."""
    from django_graphex.filtering.native_schema import (
        _NATIVE_INPUT_CACHE,
        build_filter_input_type,
    )
    from tests.models import Comment

    _NATIVE_INPUT_CACHE.clear()
    first = build_filter_input_type(Comment, ["body"])
    second = build_filter_input_type(Comment, ["body"])
    assert first is second


# ---------------------------------------------------------------------------
# _assert_filter_type_complete — the empty-fields footgun guard
# ---------------------------------------------------------------------------


def test_assert_filter_type_complete_raises_on_empty():
    """_assert_filter_type_complete raises AssertionError on empty .fields."""
    from graphql import GraphQLInputObjectType

    from django_graphex.filtering.native_schema import _assert_filter_type_complete

    empty = GraphQLInputObjectType(name="EmptyFilterinput", fields=lambda: {})
    with pytest.raises(AssertionError):
        _assert_filter_type_complete(empty)
