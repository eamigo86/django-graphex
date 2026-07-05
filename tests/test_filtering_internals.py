# -*- coding: utf-8 -*-
"""Edge cases for the "filtering/" v2 package (schema build, translate, backend).

These cover the branches the end-to-end "test_native_filtering" suite does not:
unknown-type scalar fallback, choices-enum-missing fallback, plain-pk relation
lookups with isnull/in, non-relation "__" paths, the "_relation_model" /
"_relation_target" exception guards, and the backend no-op paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import models
from graphql import GraphQLError, Undefined

from django_graphex.filtering import native_schema as fschema
from django_graphex.filtering.backend import (
    NativeFilterBackend,
    resolve_filter_backend,
)
from django_graphex.filtering.native_schema import (
    _relation_model,
    build_filter_input_type,
)
from django_graphex.filtering.translate import (
    _is_pk_lookups,
    _is_to_many,
    _relation_target,
    to_q,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch
from django_graphex.registry import Registry

from .models import Author


class FilterModel(models.Model):
    """A model with a scalar, an integer, and a FK, used across this module's tests.

    Provides "name", "rating", and "author" fields for the filter-input and
    "to_q" scenarios covered below.
    """

    name = models.CharField(max_length=50)
    rating = models.IntegerField(default=0)
    author = models.ForeignKey(
        Author, related_name="filtermodels", on_delete=models.CASCADE
    )

    class Meta:
        """Register "FilterModel" under the "tests" app label.

        No other options are set.
        """

        app_label = "tests"


# --------------------------------------------------------------------------- #
# native_schema.py — the native ``<Model>Filterinput`` builder                 #
#                                                                              #
# S7 (graphene-removal): the graphene filter-input builder (``filtering/schema``)
# was deleted. These tests now exercise the NATIVE builder
# (``filtering/native_schema.build_filter_input_type``), which returns a
# graphql-core ``GraphQLInputObjectType`` whose field surface is ``.fields``
# (camelCase wire keys), NOT a graphene type with ``_meta.fields``. The
# graphene-only ``_field_scalar`` / ``_choices_enum`` unit tests are pruned (those
# helpers do not exist natively — the native builder derives scalars via
# ``_scalar_by_internal()`` and registry-keyed enums).
# --------------------------------------------------------------------------- #
def test_build_filter_input_type_returns_none_without_fields() -> None:
    """ "build_filter_input_type" must return None when no filter fields are given.

    Covers both the None and empty-list "filter_fields" shapes.
    """
    assert build_filter_input_type(FilterModel, None) is None
    assert build_filter_input_type(FilterModel, []) is None


def test_build_filter_input_type_default_registry() -> None:
    """ "build_filter_input_type" must resolve the global registry when "registry=None".

    Guards the default-registry fallback path so it does not error.
    """
    # registry=None path resolves the global registry without error.
    built = build_filter_input_type(FilterModel, ["name"], registry=None)
    assert built is not None
    assert "name" in built.fields


def test_pk_relation_lookups_input_includes_isnull_and_in() -> None:
    """A pk relation with explicit lookups must expose "exact"/"in"/"isnull" fields.

    "in" must compile to a "GraphQLList", not a bare scalar.
    """
    from graphql import GraphQLList

    R = Registry()
    built = build_filter_input_type(
        FilterModel,
        {"author": ("exact", "in", "isnull")},
        registry=R,
    )
    author_input = built.fields["author"].type
    fields = set(author_input.fields)
    assert {"exact", "in", "isnull"} <= fields
    # `in` is a List, `isnull` a Boolean, `exact` the pk scalar.
    assert isinstance(author_input.fields["in"].type, GraphQLList)


def test_relation_direct_list_form_uses_default_pk_lookups() -> None:
    """A list-form relation (no explicit lookups) must use the default pk lookup set.

    If this breaks, declaring a relation without explicit lookups would drop
    the default "exact" lookup.
    """
    # List-form (no explicit lookups) relation -> the related pk default lookup set.
    R = Registry()
    built = build_filter_input_type(FilterModel, ["author"], registry=R)
    author_input = built.fields["author"].type
    assert "exact" in author_input.fields


def test_non_relation_double_underscore_path_falls_back_to_leaf() -> None:
    """A "field__weird" path where "field" is not a relation must be dropped, not crash.

    Covers the "own[path] = lookups" fallback branch when "get_field" raises
    for the compound path.
    """
    # `name__weird` where `name` is not a relation: the whole path is kept as a
    # leaf on the model (the `own[path] = lookups` fallback branch).
    R = Registry()
    built = build_filter_input_type(FilterModel, ["rating"], registry=R)
    # The fallback path: get_field("name__bad") raises -> field is skipped.
    built2 = build_filter_input_type(FilterModel, {"name__bad": ("exact",)}, registry=R)
    assert built is not None
    assert built2 is not None
    # `name__bad` is not a real field so it is dropped from the namespace.
    assert "name__bad" not in built2.fields


def test_relation_model_returns_none_for_scalar_and_missing() -> None:
    """ "_relation_model" must return None for a scalar or missing field, the model for a relation.

    Covers all three cases in one assertion set.
    """
    assert _relation_model(FilterModel, "name") is None
    assert _relation_model(FilterModel, "does_not_exist") is None
    assert _relation_model(FilterModel, "author") is Author


def test_lookups_input_choices_field_uses_enum(db: None) -> None:
    """A choices field declared in filter_fields must compile into the input type.

    Args:
        db: The pytest-django fixture granting database access.
    """

    # A choices field declared in filter_fields compiles into the input type.
    class ChoiceModel(models.Model):
        STATUS = (("a", "A"), ("b", "B"))
        status = models.CharField(max_length=1, choices=STATUS)

        class Meta:
            app_label = "tests"

    R = Registry()
    built = build_filter_input_type(ChoiceModel, {"status": ("exact",)}, registry=R)
    assert "status" in built.fields


def test_filter_fields_dict_with_none_value_raises_improperly_configured() -> None:
    """filter_fields={"field": None} must raise ImproperlyConfigured, not TypeError.

    The error message must point to "@filter_field" as the intended
    replacement for a None lookup value.
    """
    # filter_fields={"field": None} must now raise ImproperlyConfigured with a
    # helpful message pointing to @filter_field (not crash with TypeError).
    from django.core.exceptions import ImproperlyConfigured

    R = Registry()
    with pytest.raises(ImproperlyConfigured, match="filter_field"):
        build_filter_input_type(FilterModel, {"name": None}, registry=R)


def test_filter_fields_list_with_none_uses_default_lookups() -> None:
    """The list form of filter_fields must still work and use default lookups.

    Complements the dict-form None-value rejection tested above.
    """
    # The LIST form (not dict) still works and uses default lookups.
    R = Registry()
    built_list = build_filter_input_type(FilterModel, ["name"], registry=R)
    assert built_list is not None
    assert "name" in built_list.fields


# --------------------------------------------------------------------------- #
# translate.py guards                                                          #
# --------------------------------------------------------------------------- #
def test_relation_target_missing_field_returns_none() -> None:
    """ "_relation_target" must return None for a missing or scalar field, the model for a relation.

    Covers all three cases in one assertion set.
    """
    assert _relation_target(FilterModel, "nope") is None
    assert _relation_target(FilterModel, "name") is None
    assert _relation_target(FilterModel, "author") is Author


def test_is_to_many_missing_field_is_false() -> None:
    """ "_is_to_many" must return False for a missing or to-one field, True for a to-many reverse relation.

    Covers all three cases in one assertion set.
    """
    assert _is_to_many(FilterModel, "nope") is False
    assert _is_to_many(FilterModel, "author") is False
    assert _is_to_many(Author, "filtermodels") is True


def test_is_pk_lookups_non_mapping_is_false() -> None:
    """ "_is_pk_lookups" must accept only a mapping of known lookup names, not a scalar or nested mapping.

    Covers all three cases in one assertion set.
    """
    assert _is_pk_lookups(5) is False
    assert _is_pk_lookups({"exact": 1}) is True
    assert _is_pk_lookups({"name": {"exact": 1}}) is False


def test_to_q_none_node_is_empty() -> None:
    """ "to_q" must return an empty Q for both a None node and the Undefined sentinel.

    Guards the two "no filter supplied" shapes.
    """
    q, many = to_q(None, FilterModel)
    assert q == models.Q()
    assert many is False
    q2, _ = to_q(Undefined, FilterModel)
    assert q2 == models.Q()


def test_to_q_skips_unset_values() -> None:
    """ "to_q" must skip a lookup whose value is the Undefined sentinel.

    If this breaks, an unset GraphQL argument would be translated into a
    spurious Q lookup.
    """
    q, _ = to_q({"name": {"exact": Undefined}}, FilterModel)
    assert q == models.Q()


def test_to_q_range_requires_two_elements() -> None:
    """ "to_q" must raise GraphQLError when a "range" lookup does not have exactly two elements.

    Guards against a malformed range value reaching the ORM as a raw
    ValueError.
    """
    with pytest.raises(GraphQLError):
        to_q({"rating": {"range": [1, 2, 3]}}, FilterModel)


# --------------------------------------------------------------------------- #
# backend.py                                                                   #
# --------------------------------------------------------------------------- #
def test_backend_apply_empty_value_is_noop(db: None) -> None:
    """ "NativeFilterBackend.apply" must return the same queryset for a None or empty filter value.

    Args:
        db: The pytest-django fixture granting database access.
    """
    Author.objects.create(name="x")
    backend = NativeFilterBackend()
    qs = Author.objects.all()
    assert backend.apply(qs, None) is qs
    assert backend.apply(qs, {}) is qs


def test_backend_apply_empty_q_returns_same_queryset(db: None) -> None:
    """ "NativeFilterBackend.apply" must return the same queryset when the filter node resolves to an empty Q.

    Args:
        db: The pytest-django fixture granting database access.
    """
    # A node whose only key is unset translates to an empty Q -> queryset unchanged.
    backend = NativeFilterBackend()
    qs = FilterModel.objects.all()
    result = backend.apply(qs, {"name": {"exact": Undefined}})
    assert result is qs


def test_resolve_filter_backend_returns_native() -> None:
    """ "resolve_filter_backend" must return a "NativeFilterBackend" instance.

    Guards the default backend selection, now that graphene support is gone.
    """
    assert isinstance(resolve_filter_backend(), NativeFilterBackend)


def test_input_cache_reuses_built_type() -> None:
    """The native filter-input cache must return the same compiled type for identical inputs.

    Native cache is "_NATIVE_INPUT_CACHE" (the graphene "_INPUT_CACHE" was
    deleted with "filtering/schema.py").
    """
    R = Registry()
    # Native cache is `_NATIVE_INPUT_CACHE` (the graphene `_INPUT_CACHE` was
    # deleted with `filtering/schema.py`).
    fschema._NATIVE_INPUT_CACHE.clear()
    first = build_filter_input_type(FilterModel, ["name"], registry=R)
    second = build_filter_input_type(FilterModel, ["name"], registry=R)
    assert first is second


# --------------------------------------------------------------------------- #
# WU3 — native FilterInput builder                                            #
# --------------------------------------------------------------------------- #
def test_native_build_filter_input_type_returns_graphql_input_object_type() -> None:
    """The native "build_filter_input_type" must return a "GraphQLInputObjectType".

    Baseline contract for the rest of the WU3 tests in this section.
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact", "icontains"), "rating": ("exact", "gt")},
        registry=R,
    )
    assert isinstance(built, GraphQLInputObjectType)


def test_native_filter_input_fields_are_non_empty() -> None:
    """The compiled filter input's ".fields" must be non-empty and include every declared field.

    Forces thunk evaluation before asserting field membership.
    """
    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact", "icontains"), "rating": ("exact", "gt")},
        registry=R,
    )
    # Force thunk evaluation.
    assert dict(built.fields), "FilterInput .fields must be non-empty"
    assert "name" in built.fields
    assert "rating" in built.fields


def test_native_filter_input_carries_extensions_gdx() -> None:
    """The compiled filter input must carry a non-None "gdx" key under "extensions".

    Guards the metadata bridge other native compiler consumers rely on.
    """
    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(FilterModel, {"name": ("exact",)}, registry=R)
    assert built.extensions is not None
    assert "gdx" in built.extensions
    assert built.extensions["gdx"] is not None


def test_native_filter_every_field_carries_snake_out_name() -> None:
    """The cardinal footgun: EVERY field (top-level + nested lookups) must carry
    an "out_name" so the coerced dict uses snake ORM keys, never camelCase wire
    keys. A multi-word field ("published_date") proves wire(camel) != out(snake).
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    class MultiWordModel(models.Model):
        published_date = models.DateField(null=True)
        word_count = models.IntegerField(default=0)

        class Meta:
            app_label = "tests"

    R = Registry()
    built = native_build(
        MultiWordModel,
        {
            "published_date": ("exact", "isnull"),
            "word_count": ("exact", "gt"),
        },
        registry=R,
    )

    fields = dict(built.fields)
    # Wire key is camelCase; out_name is snake.
    assert "publishedDate" in fields
    assert fields["publishedDate"].out_name == "published_date"
    assert "wordCount" in fields
    assert fields["wordCount"].out_name == "word_count"

    # Every nested lookup field carries an out_name equal to its lookup name.
    for top_name, top_field in fields.items():
        if top_name in ("and", "or", "not"):
            continue
        lookups_type = top_field.type
        assert isinstance(lookups_type, GraphQLInputObjectType)
        for lookup_name, lookup_field in dict(lookups_type.fields).items():
            assert lookup_field.out_name == lookup_name, (
                f"lookup {lookup_name!r} on {top_name!r} missing/wrong out_name"
            )


def test_native_filter_isnull_field_out_name_is_isnull() -> None:
    """The "isnull" lookup field must carry "out_name" equal to "isnull".

    Guards the single-lookup case alongside the every-field sweep above.
    """
    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(FilterModel, {"rating": ("exact", "isnull")}, registry=R)
    rating_lookups = dict(built.fields)["rating"].type
    isnull_field = dict(rating_lookups.fields)["isnull"]
    assert isnull_field.out_name == "isnull"


def test_native_choices_field_produces_enum(db: None) -> None:
    """A choices field's "exact" lookup must compile to a "GraphQLEnumType".

    Args:
        db: The pytest-django fixture granting database access.
    """
    from graphql import GraphQLEnumType

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    class NativeChoiceModel(models.Model):
        STATUS = (("a", "A"), ("b", "B"))
        status = models.CharField(max_length=1, choices=STATUS)

        class Meta:
            app_label = "tests"

    R = Registry()
    built = native_build(NativeChoiceModel, {"status": ("exact", "in")}, registry=R)
    status_lookups = dict(built.fields)["status"].type
    exact_field = dict(status_lookups.fields)["exact"]
    assert isinstance(exact_field.type, GraphQLEnumType), (
        "choices field must produce a GraphQLEnumType, not a bare GraphQLString"
    )


def test_native_filter_to_q_round_trip_icontains_and_isnull(db: None) -> None:
    """End-to-end: coerce a wire payload through the native FilterInput, then
    translate to a Q. The coerced dict MUST use snake keys (via out_name) so
    "to_q" builds the correct lookup. Missing out_name -> empty/wrong Q.

    Args:
        db: The pytest-django fixture granting database access.
    """
    from graphql.utilities import coerce_input_value

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact", "icontains", "isnull"), "rating": ("exact", "gt")},
        registry=R,
    )

    # Wire payload uses camelCase top-level keys; lookups are snake.
    raw = {"name": {"icontains": "foo", "isnull": True}}
    coerced = coerce_input_value(raw, built)
    # out_name mapping: top-level snake key preserved (single-word here).
    assert coerced == {"name": {"icontains": "foo", "isnull": True}}

    q, touched = to_q(coerced, FilterModel)
    expected = models.Q(name__icontains="foo") & models.Q(name__isnull=True)
    assert q == expected
    assert touched is False


def test_native_filter_to_q_round_trip_multiword_field(db: None) -> None:
    """Multi-word field: wire camelCase -> out_name snake -> correct Q.
    This is the canonical out_name footgun guard.

    Args:
        db: The pytest-django fixture granting database access.
    """
    from graphql.utilities import coerce_input_value

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    class MWQModel(models.Model):
        published_date = models.DateField(null=True)

        class Meta:
            app_label = "tests"

    R = Registry()
    built = native_build(MWQModel, {"published_date": ("isnull",)}, registry=R)
    raw = {"publishedDate": {"isnull": True}}
    coerced = coerce_input_value(raw, built)
    # Without out_name this would be {'publishedDate': ...} and to_q would
    # silently produce an EMPTY Q (publishedDate is not a real field).
    assert coerced == {"published_date": {"isnull": True}}

    q, _ = to_q(coerced, MWQModel)
    assert q == models.Q(published_date__isnull=True)


def test_native_backend_build_input_type_returns_graphql_input_object_type() -> None:
    """ "NativeFilterBackend.build_input_type" must return a "GraphQLInputObjectType", or None with no fields.

    Covers both the populated and the empty "filter_fields" case.
    """
    from graphql import GraphQLInputObjectType

    R = Registry()
    backend = NativeFilterBackend()
    built = backend.build_input_type(FilterModel, {"name": ("exact",)}, registry=R)
    assert isinstance(built, GraphQLInputObjectType)
    # No filterable fields -> None on the native path too.
    assert backend.build_input_type(FilterModel, None, registry=R) is None


def test_native_custom_filter_field_uses_declared_graphql_type() -> None:
    """A custom "@filter_field(GraphQLInt)" arg must render as the matching
    graphql-core scalar ("GraphQLInt") under the native backend, NOT degrade
    to "GraphQLString". The 2.0 public form declares the native graphql-core
    type directly; a leftover graphene type raises "TypeError" via the unwrap
    bridge.
    """
    from graphql import GraphQLFloat, GraphQLInt, GraphQLString

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    custom_filters = [
        (
            "search_count",
            lambda qs, info, value: qs,
            {
                "graphql_type": GraphQLInt,
                "description": "Count search",
            },
        ),
        (
            "min_score",
            lambda qs, info, value: qs,
            {
                "graphql_type": GraphQLFloat,
                "description": None,
            },
        ),
        (
            "text_search",
            lambda qs, info, value: qs,
            {
                "graphql_type": GraphQLString,
                "description": None,
            },
        ),
    ]

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact",)},
        registry=R,
        custom_filters=custom_filters,
    )

    fields = dict(built.fields)
    # Wire keys are camelCase; out_name preserves the snake arg name.
    assert fields["searchCount"].type is GraphQLInt
    assert fields["searchCount"].out_name == "search_count"
    assert fields["minScore"].type is GraphQLFloat
    assert fields["minScore"].out_name == "min_score"
    assert fields["textSearch"].type is GraphQLString
    assert fields["textSearch"].out_name == "text_search"


def test_native_custom_filter_field_no_graphql_type_falls_back_to_string() -> None:
    """When no "graphql_type" is present, the custom arg falls back to
    "GraphQLString" (matches graphene's default).
    """
    from graphql import GraphQLString

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    custom_filters = [
        ("legacy", lambda qs, info, value: qs, {"description": None}),
    ]

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact",)},
        registry=R,
        custom_filters=custom_filters,
    )
    fields = dict(built.fields)
    assert fields["legacy"].type is GraphQLString
    assert fields["legacy"].out_name == "legacy"


# --------------------------------------------------------------------------- #
# WU4 — recursion (and/or/not), completeness assert, native translate enum     #
# --------------------------------------------------------------------------- #
def test_native_filter_input_has_and_or_not_combinators() -> None:
    """The native filter input MUST expose the recursive "and" / "or" /
    "not" combinators, mirroring the graphene builder for SDL parity.

    Shape (matches graphene "filtering/schema.py:334-336"):
        and: [<Self>]   or: [<Self>]   not: <Self>
    """
    from graphql import GraphQLInputObjectType, GraphQLList

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact", "icontains"), "rating": ("exact", "gt")},
        registry=R,
    )
    fields = dict(built.fields)

    assert "and" in fields, "filter input missing 'and' combinator"
    assert "or" in fields, "filter input missing 'or' combinator"
    assert "not" in fields, "filter input missing 'not' combinator"

    # and/or -> GraphQLList(<self>); not -> <self>. The element/inner type MUST
    # be the SAME cached input instance (recursion via cache-before-thunk).
    and_type = fields["and"].type
    or_type = fields["or"].type
    not_type = fields["not"].type
    assert isinstance(and_type, GraphQLList)
    assert isinstance(or_type, GraphQLList)
    assert and_type.of_type is built, "and: must be a list of the SAME filter input"
    assert or_type.of_type is built, "or: must be a list of the SAME filter input"
    assert not_type is built, "not: must be the SAME filter input (self-ref)"
    assert isinstance(built, GraphQLInputObjectType)

    # out_name carries the snake combinator name (== the wire key here).
    assert fields["and"].out_name == "and"
    assert fields["or"].out_name == "or"
    assert fields["not"].out_name == "not"


def test_native_filter_self_referential_recursion_resolves() -> None:
    """Category->parent->Category (self-relation FK): the nested relation filter
    input must resolve with NON-EMPTY ".fields" and no RecursionError, proving
    cache-before-thunk registration breaks the cycle.

    "NestedTreeNode" has "parent = FK("self")" — the canonical self-relation.
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    from .models import NestedTreeNode

    R = Registry()
    # Declare BOTH a self-relation-nested path AND the recursive combinators.
    built = native_build(
        NestedTreeNode,
        {"label": ("exact", "icontains"), "parent__label": ("exact",)},
        registry=R,
    )

    fields = dict(built.fields)
    # The nested relation filter input (parent -> NestedTreeNode) is present and
    # its own .fields are non-empty (forces the nested thunk to evaluate).
    assert "parent" in fields
    parent_input = fields["parent"].type
    assert isinstance(parent_input, GraphQLInputObjectType)
    parent_fields = dict(parent_input.fields)
    assert parent_fields, "nested self-relation filter input has EMPTY .fields"
    assert "label" in parent_fields

    # The nested input ALSO carries and/or/not (recursion all the way down).
    assert "and" in parent_fields
    assert "or" in parent_fields
    assert "not" in parent_fields

    # No RecursionError even though parent's filter input references itself via
    # and/or/not. Force the top-level thunk one more time for good measure.
    assert dict(built.fields)


def test_native_assert_filter_type_complete_passes_for_valid_type() -> None:
    """ "_assert_filter_type_complete" forces thunk eval and accepts a type with
    non-empty fields without raising.
    """
    from django_graphex.filtering.native_schema import (
        _assert_filter_type_complete,
    )
    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(FilterModel, {"name": ("exact",)}, registry=R)
    # Must NOT raise.
    _assert_filter_type_complete(built)


def test_native_assert_filter_input_out_names_passes_for_valid_type() -> None:
    """ "_assert_filter_input_out_names" accepts a normally-compiled filter input
    where every field carries a snake "out_name" (audit rank 19).
    """
    from django_graphex.filtering.native_schema import (
        _assert_filter_input_out_names,
    )
    from django_graphex.filtering.native_schema import (
        build_filter_input_type as native_build,
    )

    R = Registry()
    built = native_build(
        FilterModel,
        {"name": ("exact",), "rating": ("gt",), "author": ("exact",)},
        registry=R,
    )
    # Must NOT raise — the builder sets out_name on every field.
    _assert_filter_input_out_names(built)


def test_native_assert_filter_input_out_names_fires_when_out_name_missing() -> None:
    """A compiled filter input field WITHOUT "out_name" (e.g. a custom extension
    mutated the fields post-compile) must raise a clear error at build time —
    otherwise "to_q" silently receives the camelCase wire key and produces an
    EMPTY Q (audit rank 19, the cardinal out_name footgun).
    """
    from graphql import GraphQLInputField, GraphQLInputObjectType, GraphQLString

    from django_graphex.filtering.native_schema import (
        _assert_filter_input_out_names,
    )

    # A field that LOST its out_name (None) — exactly what a post-compile mutation
    # would leave behind for a multi-word field whose wire key is camelCase.
    broken = GraphQLInputObjectType(
        name="BrokenFilterInput",
        fields=lambda: {
            "publishedDate": GraphQLInputField(GraphQLString, out_name=None),
        },
    )
    with pytest.raises((AssertionError, GraphQLError)) as exc:
        _assert_filter_input_out_names(broken)
    assert "publishedDate" in str(exc.value) or "out_name" in str(exc.value)


def test_native_build_filter_input_type_wires_out_name_assert(
    monkeypatch: "MonkeyPatch",
) -> None:
    """ "build_filter_input_type" MUST wire "_assert_filter_input_out_names" so a
    missing out_name is caught at BUILD time (audit rank 19). Uses a UNIQUE model
    so the module cache is cold and the assert actually runs on a fresh build.

    Args:
        monkeypatch: The pytest fixture used to wrap
            "_assert_filter_input_out_names" and record whether it was
            invoked.
    """
    import django_graphex.filtering.native_schema as ns

    class OutNameWireModel(models.Model):
        headline = models.CharField(max_length=50)

        class Meta:
            app_label = "tests"

    R = Registry()
    calls = {"n": 0}
    real_assert = ns._assert_filter_input_out_names

    def _spy(t):
        calls["n"] += 1
        return real_assert(t)

    monkeypatch.setattr(ns, "_assert_filter_input_out_names", _spy)
    built = ns.build_filter_input_type(
        OutNameWireModel, {"headline": ("exact",)}, registry=R
    )
    assert built is not None
    assert calls["n"] >= 1, (
        "build_filter_input_type did NOT wire _assert_filter_input_out_names"
    )


def test_native_assert_filter_type_complete_raises_on_empty_fields() -> None:
    """ "_assert_filter_type_complete" raises AssertionError when a thunk
    evaluates to empty ".fields" (the silent-empty footgun A6 catches).
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.filtering.native_schema import (
        _assert_filter_type_complete,
    )

    empty = GraphQLInputObjectType(name="EmptyFilterinput", fields=lambda: {})
    with pytest.raises(AssertionError):
        _assert_filter_type_complete(empty)


def test_native_build_filter_input_type_wires_completeness_assert(
    monkeypatch: "MonkeyPatch",
) -> None:
    """ "build_filter_input_type" MUST wire "_assert_filter_type_complete" so a
    type that resolves to empty fields is caught at BUILD time, not silently
    shipped.

    Uses a UNIQUE model so the module-level "_NATIVE_INPUT_CACHE" is cold — a
    cache hit would (correctly) short-circuit before the assert, so the wiring
    can only be observed on a fresh build.

    Args:
        monkeypatch: The pytest fixture used to wrap
            "_assert_filter_type_complete" and record whether it was invoked.
    """
    import django_graphex.filtering.native_schema as ns

    class WireAssertModel(models.Model):
        headline = models.CharField(max_length=50)

        class Meta:
            app_label = "tests"

    R = Registry()
    # Patch the helper to record that it was called during build (proves wiring).
    calls = {"n": 0}
    real_assert = ns._assert_filter_type_complete

    def _spy(t):
        calls["n"] += 1
        return real_assert(t)

    monkeypatch.setattr(ns, "_assert_filter_type_complete", _spy)
    built = ns.build_filter_input_type(
        WireAssertModel, {"headline": ("exact",)}, registry=R
    )
    assert built is not None
    assert calls["n"] >= 1, (
        "build_filter_input_type did NOT wire _assert_filter_type_complete"
    )


def test_translate_to_q_enum_lookup_native(db: None) -> None:
    """ "to_q" builds the correct Q for an enum lookup. Native graphql-core
    delivers the raw value straight through into the Q (no graphene Enum unwrap).

    S7: the graphene-era "_unwrap_enum" helper and its two contract tests
    ("test_native_translate_skips_unwrap_enum" / the dual-backend
    "test_translate_unwrap_enum_kept_for_graphene_path") were removed alongside
    the helper — this native "to_q" exercise is the surviving coverage.

    Args:
        db: The pytest-django fixture granting database access.
    """
    from django_graphex.filtering.translate import to_q

    q, _ = to_q({"rating": {"in": [1, 2]}}, FilterModel)
    assert q == models.Q(rating__in=[1, 2])


# --------------------------------------------------------------------------- #
# Audit rank 16: unknown field names inside and/or/not combinators must FAIL  #
# LOUD instead of being silently skipped (which masks a typo as an empty Q).  #
# Custom @filter_field args ride ONLY at the TOP level (apply_custom_filters   #
# never recurses into combinators), so a key that is not a model field /       #
# relation / nested combinator inside a combinator is ALWAYS a genuine error.  #
# --------------------------------------------------------------------------- #
def test_to_q_unknown_field_in_or_raises_graphql_error() -> None:
    """An unknown field name inside "or: [...]" raises GraphQLError naming the
    field and the combinator — not a silent empty Q that masks the typo.
    """
    with pytest.raises(GraphQLError) as exc:
        to_q({"or": [{"nmae": {"exact": "x"}}]}, FilterModel)
    message = str(exc.value)
    assert "nmae" in message
    assert "or" in message


def test_to_q_unknown_field_in_and_raises_graphql_error() -> None:
    """An unknown field name inside "and: [...]" raises GraphQLError.

    Mirrors the "or" combinator case above for the "and" combinator.
    """
    with pytest.raises(GraphQLError) as exc:
        to_q({"and": [{"raitng": {"gt": 3}}]}, FilterModel)
    message = str(exc.value)
    assert "raitng" in message
    assert "and" in message


def test_to_q_unknown_field_in_not_raises_graphql_error() -> None:
    """An unknown field name inside "not: {...}" raises GraphQLError.

    Mirrors the "or"/"and" combinator cases above for the "not" combinator.
    """
    with pytest.raises(GraphQLError) as exc:
        to_q({"not": {"bogus": {"exact": 1}}}, FilterModel)
    message = str(exc.value)
    assert "bogus" in message
    assert "not" in message


def test_to_q_valid_fields_in_combinators_still_filter() -> None:
    """A combinator over VALID model fields keeps building the correct Q —
    the fail-loud guard must not break legitimate combinator filters.
    """
    q_or, _ = to_q(
        {"or": [{"name": {"exact": "a"}}, {"rating": {"gt": 3}}]}, FilterModel
    )
    assert q_or == (models.Q(name__exact="a") | models.Q(rating__gt=3))

    q_and, _ = to_q(
        {"and": [{"name": {"exact": "a"}}, {"rating": {"gt": 3}}]}, FilterModel
    )
    assert q_and == (models.Q(name__exact="a") & models.Q(rating__gt=3))

    q_not, _ = to_q({"not": {"name": {"exact": "a"}}}, FilterModel)
    assert q_not == ~models.Q(name__exact="a")


def test_to_q_relation_field_in_combinator_still_filters() -> None:
    """A relation field inside a combinator (e.g. "author") recurses correctly
    and is NOT mistaken for an unknown field.
    """
    q, _ = to_q({"or": [{"author": {"name": {"exact": "x"}}}]}, FilterModel)
    assert q == models.Q(author__name__exact="x")


def test_to_q_top_level_custom_filter_arg_still_skipped() -> None:
    """A top-level custom "@filter_field" arg (not a model field) is STILL
    skipped — only combinator children fail loud. "apply_custom_filters"
    handles the custom arg separately, so to_q must leave it alone.
    """
    q, _ = to_q({"search": "hello", "name": {"exact": "a"}}, FilterModel)
    # 'search' is skipped; only 'name' contributes.
    assert q == models.Q(name__exact="a")
