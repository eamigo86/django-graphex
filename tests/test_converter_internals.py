# -*- coding: utf-8 -*-
"""Converter branches for input flags and relation/generic/postgres fields.

The existing ``test_converter`` covers output scalar conversion; this drives the
``input_flag`` paths of the FK/O2O/M2M/reverse converters (the ``Dynamic``
closures), plus the GenericForeignKey, GenericRelation, ArrayField and
JSON/HStore converters that the scalar tests skip.
"""

from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models
from graphene import ID, Dynamic

from django_graphex.converter import (
    construct_fields,
    convert_django_field,
)
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType

from .models import Author, Post


def _resolve(field, **kwargs):
    """Convert a model field then resolve its ``Dynamic`` closure (if any)."""
    converted = convert_django_field(field, **kwargs)
    if isinstance(converted, Dynamic):
        return converted.get_type()
    return converted


# --------------------------------------------------------------------------- #
# FK / O2O / M2M / reverse: the input_flag dynamic branches                    #
# --------------------------------------------------------------------------- #
def test_fk_input_flag_not_nested_is_id():
    registry = Registry()
    fk = Post._meta.get_field("author")
    out = _resolve(fk, registry=registry, input_flag="create")
    assert isinstance(out, ID)


def test_m2m_input_flag_not_nested_is_list_of_id():
    registry = Registry()
    m2m = Post._meta.get_field("tags")
    out = _resolve(m2m, registry=registry, input_flag="create")
    # DjangoListField wrapping ID.
    assert out is not None


def test_reverse_relation_input_flag_not_nested_is_list_of_id():
    registry = Registry()
    reverse = Author._meta.get_field("posts")  # reverse FK (ManyToOneRel)
    out = _resolve(reverse, registry=registry, input_flag="create")
    assert out is not None


def test_fk_output_unregistered_model_returns_none():
    # No type registered for the related model -> the closure returns None.
    registry = Registry()
    fk = Post._meta.get_field("author")
    assert _resolve(fk, registry=registry) is None


def test_fk_output_registered_model_returns_field():
    reg = Registry()

    class _AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg

    fk = Post._meta.get_field("author")
    out = _resolve(fk, registry=reg)
    assert out is not None  # a Field wrapping the registered type


def test_m2m_nested_input_registered_returns_list():
    reg = Registry()
    tag_model = Post._meta.get_field("tags").related_model

    class _TagInput(DjangoInputObjectType):
        class Meta:
            model = tag_model
            registry = reg

    m2m = Post._meta.get_field("tags")
    out = _resolve(m2m, registry=reg, input_flag="create", nested_field=True)
    assert out is not None


# --------------------------------------------------------------------------- #
# construct_fields: delete flag keeps only id; create skips id                 #
# --------------------------------------------------------------------------- #
def test_construct_fields_delete_flag_keeps_only_id():
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None, input_flag="delete")
    assert set(fields) == {"id"}


def test_construct_fields_create_flag_skips_id():
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None, input_flag="create")
    assert "id" not in fields
    assert "name" in fields


def test_construct_fields_exclude_and_only():
    registry = Registry()
    only = construct_fields(Author, registry, ["name"], None, None)
    assert "name" in only and "bio" not in only
    excluded = construct_fields(Author, registry, None, None, ["bio"])
    assert "bio" not in excluded and "name" in excluded


# --------------------------------------------------------------------------- #
# GenericForeignKey / GenericRelation                                          #
# --------------------------------------------------------------------------- #
class TaggedItem(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        app_label = "tests"


class GfkHost(models.Model):
    name = models.CharField(max_length=50)
    items = GenericRelation(TaggedItem)

    class Meta:
        app_label = "tests"


def test_generic_foreign_key_output_returns_field():
    registry = Registry()
    gfk = next(
        f for f in TaggedItem._meta.get_fields() if isinstance(f, GenericForeignKey)
    )
    out = _resolve(gfk, registry=registry)
    assert out is not None


def test_generic_foreign_key_input_returns_input_type():
    registry = Registry()
    gfk = next(
        f for f in TaggedItem._meta.get_fields() if isinstance(f, GenericForeignKey)
    )
    out = _resolve(gfk, registry=registry, input_flag="create")
    assert out is not None


def test_generic_relation_input_flag_returns_none():
    registry = Registry()
    rel = next(f for f in GfkHost._meta.get_fields() if isinstance(f, GenericRelation))
    # The input branch of a GenericRelation produces no input field.
    assert _resolve(rel, registry=registry, input_flag="create") is None


# --------------------------------------------------------------------------- #
# Postgres ArrayField / JSON / HStore (string-typed, no postgres import)       #
# --------------------------------------------------------------------------- #
def test_json_field_converts_to_string_scalar():
    field = models.JSONField()
    out = convert_django_field(field)
    assert out is not None
