# -*- coding: utf-8 -*-
"""Edge cases for the ``filtering/`` v2 package (schema build, translate, backend).

These cover the branches the end-to-end ``test_native_filtering`` suite does not:
unknown-type scalar fallback, choices-enum-missing fallback, plain-pk relation
lookups with isnull/in, non-relation ``__`` paths, the ``_relation_model`` /
``_relation_target`` exception guards, and the backend no-op paths.
"""

import graphene
import pytest
from django.db import models
from graphql import GraphQLError, Undefined

from django_graphex.filtering import schema as fschema
from django_graphex.filtering.backend import (
    NativeFilterBackend,
    resolve_filter_backend,
)
from django_graphex.filtering.schema import (
    _choices_enum,
    _field_scalar,
    _relation_model,
    build_filter_input_type,
)
from django_graphex.filtering.translate import (
    _is_pk_lookups,
    _is_to_many,
    _relation_target,
    to_q,
)
from django_graphex.registry import Registry

from .models import Author


class FilterModel(models.Model):
    name = models.CharField(max_length=50)
    rating = models.IntegerField(default=0)
    author = models.ForeignKey(
        Author, related_name="filtermodels", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"


# --------------------------------------------------------------------------- #
# schema.py                                                                    #
# --------------------------------------------------------------------------- #
def test_field_scalar_unknown_internal_type_degrades_to_string():
    # DurationField -> String per the scalar map; an unmapped one also -> String.
    class _Weird(models.Field):
        def get_internal_type(self):
            return "TotallyUnknownField"

    assert _field_scalar(_Weird()) is graphene.String


def test_choices_enum_missing_falls_back_to_string():
    # No enum registered for this field name -> graphene.String fallback.
    field = FilterModel._meta.get_field("name")
    assert _choices_enum(field, Registry()) is graphene.String


def test_build_filter_input_type_returns_none_without_fields():
    assert build_filter_input_type(FilterModel, None) is None
    assert build_filter_input_type(FilterModel, []) is None


def test_build_filter_input_type_default_registry():
    # registry=None path resolves the global registry without error.
    built = build_filter_input_type(FilterModel, ["name"], registry=None)
    assert built is not None
    assert "name" in built._meta.fields


def test_pk_relation_lookups_input_includes_isnull_and_in():
    R = Registry()
    built = build_filter_input_type(
        FilterModel,
        {"author": ("exact", "in", "isnull")},
        registry=R,
    )
    author_input = built._meta.fields["author"].type
    fields = set(author_input._meta.fields)
    assert {"exact", "in", "isnull"} <= fields
    # `in` is a List, `isnull` a Boolean, `exact` the pk scalar.
    assert isinstance(author_input._meta.fields["in"].type, graphene.List)


def test_relation_direct_list_form_uses_default_pk_lookups():
    # List-form (no explicit lookups) relation -> `_pk_lookups_input_type` with
    # `lookups=None` resolves the related pk default lookup set.
    R = Registry()
    built = build_filter_input_type(FilterModel, ["author"], registry=R)
    author_input = built._meta.fields["author"].type
    assert "exact" in author_input._meta.fields


def test_non_relation_double_underscore_path_falls_back_to_leaf():
    # `name__weird` where `name` is not a relation: the whole path is kept as a
    # leaf on the model (the `own[path] = lookups` fallback branch).
    R = Registry()
    built = build_filter_input_type(FilterModel, ["rating"], registry=R)
    # The fallback path: get_field("name__bad") raises -> field is skipped.
    built2 = build_filter_input_type(FilterModel, {"name__bad": ("exact",)}, registry=R)
    assert built is not None
    assert built2 is not None
    # `name__bad` is not a real field so it is dropped from the namespace.
    assert "name__bad" not in built2._meta.fields


def test_relation_model_returns_none_for_scalar_and_missing():
    assert _relation_model(FilterModel, "name") is None
    assert _relation_model(FilterModel, "does_not_exist") is None
    assert _relation_model(FilterModel, "author") is Author


def test_lookups_input_choices_field_uses_enum(db):
    # A choices field declared in filter_fields routes through `_choices_enum`.
    class ChoiceModel(models.Model):
        STATUS = (("a", "A"), ("b", "B"))
        status = models.CharField(max_length=1, choices=STATUS)

        class Meta:
            app_label = "tests"

    R = Registry()
    built = build_filter_input_type(ChoiceModel, {"status": ("exact",)}, registry=R)
    assert "status" in built._meta.fields


def test_filter_fields_dict_with_none_value_raises_improperly_configured():
    # filter_fields={"field": None} must now raise ImproperlyConfigured with a
    # helpful message pointing to @filter_field (not crash with TypeError).
    from django.core.exceptions import ImproperlyConfigured

    R = Registry()
    with pytest.raises(ImproperlyConfigured, match="filter_field"):
        build_filter_input_type(FilterModel, {"name": None}, registry=R)


def test_filter_fields_list_with_none_uses_default_lookups():
    # The LIST form (not dict) still works and uses default lookups.
    R = Registry()
    built_list = build_filter_input_type(FilterModel, ["name"], registry=R)
    assert built_list is not None
    assert "name" in built_list._meta.fields


# --------------------------------------------------------------------------- #
# translate.py guards                                                          #
# --------------------------------------------------------------------------- #
def test_relation_target_missing_field_returns_none():
    assert _relation_target(FilterModel, "nope") is None
    assert _relation_target(FilterModel, "name") is None
    assert _relation_target(FilterModel, "author") is Author


def test_is_to_many_missing_field_is_false():
    assert _is_to_many(FilterModel, "nope") is False
    assert _is_to_many(FilterModel, "author") is False
    assert _is_to_many(Author, "filtermodels") is True


def test_is_pk_lookups_non_mapping_is_false():
    assert _is_pk_lookups(5) is False
    assert _is_pk_lookups({"exact": 1}) is True
    assert _is_pk_lookups({"name": {"exact": 1}}) is False


def test_to_q_none_node_is_empty():
    q, many = to_q(None, FilterModel)
    assert q == models.Q()
    assert many is False
    q2, _ = to_q(Undefined, FilterModel)
    assert q2 == models.Q()


def test_to_q_skips_unset_values():
    q, _ = to_q({"name": {"exact": Undefined}}, FilterModel)
    assert q == models.Q()


def test_to_q_range_requires_two_elements():
    with pytest.raises(GraphQLError):
        to_q({"rating": {"range": [1, 2, 3]}}, FilterModel)


# --------------------------------------------------------------------------- #
# backend.py                                                                   #
# --------------------------------------------------------------------------- #
def test_backend_apply_empty_value_is_noop(db):
    Author.objects.create(name="x")
    backend = NativeFilterBackend()
    qs = Author.objects.all()
    assert backend.apply(qs, None) is qs
    assert backend.apply(qs, {}) is qs


def test_backend_apply_empty_q_returns_same_queryset(db):
    # A node whose only key is unset translates to an empty Q -> queryset unchanged.
    backend = NativeFilterBackend()
    qs = FilterModel.objects.all()
    result = backend.apply(qs, {"name": {"exact": Undefined}})
    assert result is qs


def test_resolve_filter_backend_returns_native():
    assert isinstance(resolve_filter_backend(), NativeFilterBackend)


def test_input_cache_reuses_built_type():
    R = Registry()
    fschema._INPUT_CACHE.clear()
    first = build_filter_input_type(FilterModel, ["name"], registry=R)
    second = build_filter_input_type(FilterModel, ["name"], registry=R)
    assert first is second
