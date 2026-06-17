# -*- coding: utf-8 -*-
"""Converter branches for input flags and relation/generic/postgres fields.

The existing ``test_converter`` covers output scalar conversion; this drives the
``input_flag`` paths of the FK/O2O/M2M/reverse converters (the ``Dynamic``
closures), plus the GenericForeignKey, GenericRelation, ArrayField and
JSON/HStore converters that the scalar tests skip.

Phase 7 graphene-removal: the FK/O2O/M2M/reverse/GFK ``convert_django_field``
relation closures are KEPT on native (the native output thunk consumes them), so
those tests are unchanged. The graphene ``construct_fields`` SCALAR fields and the
JSON scalar descriptor are dead on native (the native output compiler derives them
from ``model._meta`` directly); the three formerly scalar-asserting tests were
CONVERTED to drive the native field builders — ``compile_output_fields`` (only/
exclude) and the native ``DjangoInputObjectType`` create-input compile (id-skip) —
plus ``_to_graphql_field`` for the JSON scalar, preserving the original coverage.
"""

from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models
from graphene import Dynamic

from django_graphex.converter import (
    construct_fields,
    convert_django_field,
)
from django_graphex.native.output_compiler import (
    _to_graphql_field,
    compile_output_fields,
)
from django_graphex.native.scalars import GdxJSONString
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType

from .models import Author, Post


class _StubRegistry:
    """Minimal registry for ``_to_graphql_field`` (scalars never touch it)."""

    def get_compiled(self, model_cls):
        return None


def _resolve(field, **kwargs):
    """Convert a model field then resolve its ``Dynamic`` closure (if any)."""
    converted = convert_django_field(field, **kwargs)
    if isinstance(converted, Dynamic):
        return converted.get_type()
    return converted


# --------------------------------------------------------------------------- #
# FK / O2O / M2M / reverse: the input_flag dynamic branches                    #
# --------------------------------------------------------------------------- #
def test_fk_input_flag_not_nested_returns_native_marker():
    # S-input-5: a to-ONE FK on the native INPUT path converts to a graphene-free
    # ``NativeRelationField`` presence/ordering marker. The actual ``id: ID``
    # input field is built by ``input_compiler.compile_input_type`` from a
    # ``RelationInputField`` spec (``types._resolve_native_relation_input_fields``
    # reads ``model._meta``), NOT from this descriptor.
    from django_graphex.native.descriptors import NativeRelationField

    registry = Registry()
    fk = Post._meta.get_field("author")
    out = convert_django_field(fk, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_m2m_input_flag_not_nested_returns_native_marker():
    # S-input-5: a forward M2M on the native INPUT path converts to a graphene-free
    # ``NativeRelationField`` marker. The actual ``[ID!]`` input list is built by
    # ``compile_input_type`` from the relation spec.
    from django_graphex.native.descriptors import NativeRelationField

    registry = Registry()
    m2m = Post._meta.get_field("tags")
    out = convert_django_field(m2m, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_reverse_relation_input_flag_not_nested_returns_native_marker():
    # S-input-5: a reverse FK on the native INPUT path converts to a graphene-free
    # ``NativeRelationField`` marker. The actual ``[ID!]`` list is built by
    # ``compile_input_type`` from the (injected) relation spec.
    from django_graphex.native.descriptors import NativeRelationField

    registry = Registry()
    reverse = Author._meta.get_field("posts")  # reverse FK (ManyToOneRel)
    out = convert_django_field(reverse, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_fk_output_returns_native_marker():
    # S-rel-2: a to-ONE FK on the native OUTPUT path converts to a graphene-free
    # ``NativeRelationField`` marker (registered-or-not). The actual output field
    # (and the drop-when-unregistered decision) is owned by the native compiler
    # (``output_compiler._to_graphql_field`` reads ``model._meta`` directly), not
    # by this descriptor. ``_resolve`` returns the marker verbatim (not a Dynamic).
    # On the graphene backend the legacy Dynamic closure is UNCHANGED.
    from django_graphex.converter import _NATIVE_BACKEND
    from django_graphex.native.descriptors import NativeRelationField

    fk = Post._meta.get_field("author")
    reg = Registry()

    class _AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg

    out_unregistered = _resolve(fk, registry=Registry())
    out_registered = _resolve(fk, registry=reg)

    if _NATIVE_BACKEND:
        assert isinstance(out_unregistered, NativeRelationField)
        assert isinstance(out_registered, NativeRelationField)
    else:
        # graphene: closure drops when unregistered, wraps the type otherwise.
        assert out_unregistered is None
        assert out_registered.type is _AuthorType


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
    # Native create-input construction: the compiled GraphQLInputObjectType drops
    # the auto pk (``id``) and keeps the editable model scalars (``name``). This
    # is the native equivalent of the graphene ``construct_fields(input_flag=
    # "create")`` id-skip (the graphene scalar descriptors are dead on native).
    class _AuthorCreateInput(DjangoInputObjectType):
        class Meta:
            model = Author
            input_for = "create"

    fields = _AuthorCreateInput._meta.graphql_input_type.fields
    assert "id" not in fields
    assert "name" in fields


def test_construct_fields_exclude_and_only():
    # Native OUTPUT field construction honors only/exclude over the model scalars
    # (the graphene ``construct_fields`` scalar descriptors are dead on native).
    registry = Registry()
    only = compile_output_fields(Author, registry, only_fields=["name"])
    assert "name" in only and "bio" not in only
    excluded = compile_output_fields(Author, registry, exclude_fields=["bio"])
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
    # Native scalar conversion: JSONField -> GdxJSONString (renders as the
    # ``JSONString`` scalar). The graphene ``convert_django_field`` JSON descriptor
    # is dead on native, so drive the live native scalar mapper instead.
    field = models.JSONField()
    field.name = "json_field"
    field_map = _to_graphql_field(field, _StubRegistry())
    out = next(iter(field_map.values())).type
    assert out is GdxJSONString
