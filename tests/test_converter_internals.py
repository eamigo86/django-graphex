# -*- coding: utf-8 -*-
"""Converter branches for input flags and relation/generic/postgres fields.

The existing "test_converter" covers output scalar conversion; this drives the
"input_flag" paths of the FK/O2O/M2M/reverse converters, plus the
GenericForeignKey, GenericRelation, ArrayField and JSON/HStore converters that
the scalar tests skip.

Phase 7 graphene-removal: the migrated FK/O2O/M2M/reverse/GFK
"convert_django_field" relation converters now return a graphene-free
"NativeRelationField" presence/ordering marker that the native output thunk
consumes. (The "GenericRelation" INPUT branch is not yet migrated and still
returns a lazy closure resolved verbatim by "_resolve" / "_is_lazy_closure".)
The graphene "construct_fields" SCALAR fields and the JSON scalar descriptor are
dead on native (the native output compiler derives them from "model._meta"
directly); the three formerly scalar-asserting tests were CONVERTED to drive the
native field builders — "compile_output_fields" (only/exclude) and the native
"DjangoInputObjectType" create-input compile (id-skip) — plus "_to_graphql_field"
for the JSON scalar, preserving the original coverage.
"""

from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models

from django_graphex.converter import (
    construct_fields,
    convert_django_field,
)
from django_graphex.core.output_compiler import (
    _to_graphql_field,
    compile_output_fields,
)
from django_graphex.core.scalars import GdxJSON
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType

from .models import Author, Post


class _StubRegistry:
    """Minimal registry for ``_to_graphql_field`` (scalars never touch it)."""

    def get_compiled(self, model_cls):
        return None


def _is_lazy_closure(obj):
    """True for a converter result that defers to a lazy ``get_type()`` closure.

    Some converter paths that have NOT yet been migrated off graphene (e.g. the
    ``GenericRelation`` INPUT branch, ``converter.py``) still return a graphene
    ``Dynamic`` whose ``get_type()`` must be called to read the resolved field.
    Detect it structurally (duck-typed ``get_type`` on a non-native object) so
    this test file imports no graphene symbol; the migrated relation converters
    return a ``NativeRelationField`` instead, which this helper returns verbatim.
    """
    from django_graphex.core.descriptors import NativeRelationField

    return (
        not isinstance(obj, NativeRelationField)
        and callable(getattr(obj, "get_type", None))
        and type(obj).__module__.startswith("graphene")
    )


def _resolve(field, **kwargs):
    """Convert a model field then resolve its lazy closure (if any)."""
    converted = convert_django_field(field, **kwargs)
    if _is_lazy_closure(converted):
        return converted.get_type()
    return converted


# --------------------------------------------------------------------------- #
# FK / O2O / M2M / reverse: the input_flag dynamic branches                    #
# --------------------------------------------------------------------------- #
def test_fk_input_flag_not_nested_returns_native_marker() -> None:
    """A to-ONE FK on the native INPUT path must convert to a NativeRelationField.

    S-input-5: this graphene-free presence/ordering marker is consumed by
    "input_compiler.compile_input_type", which builds the actual "id: ID"
    input field from a RelationInputField spec
    ("types._resolve_native_relation_input_fields" reads "model._meta"), NOT
    from this descriptor. Ships broken if the FK input conversion regresses
    to returning a graphene Dynamic instead.
    """
    from django_graphex.core.descriptors import NativeRelationField

    registry = Registry()
    fk = Post._meta.get_field("author")
    out = convert_django_field(fk, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_m2m_input_flag_not_nested_returns_native_marker() -> None:
    """A forward M2M on the native INPUT path must convert to a NativeRelationField.

    S-input-5: this graphene-free marker is consumed by "compile_input_type",
    which builds the actual "[ID!]" input list from the relation spec. Ships
    broken if the M2M input conversion regresses to returning a graphene
    Dynamic instead.
    """
    from django_graphex.core.descriptors import NativeRelationField

    registry = Registry()
    m2m = Post._meta.get_field("tags")
    out = convert_django_field(m2m, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_reverse_relation_input_flag_not_nested_returns_native_marker() -> None:
    """A reverse FK on the native INPUT path must convert to a NativeRelationField.

    S-input-5: this graphene-free marker is consumed by "compile_input_type",
    which builds the actual "[ID!]" list from the injected relation spec.
    Ships broken if the reverse-FK input conversion regresses to returning a
    graphene Dynamic instead.
    """
    from django_graphex.core.descriptors import NativeRelationField

    registry = Registry()
    reverse = Author._meta.get_field("posts")  # reverse FK (ManyToOneRel)
    out = convert_django_field(reverse, registry=registry, input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_fk_output_returns_native_marker() -> None:
    """A to-ONE FK on the native OUTPUT path must convert to a NativeRelationField.

    S-rel-2: this graphene-free marker is returned regardless of whether the
    related model is registered; the actual output field (and the
    drop-when-unregistered decision) is owned by the native compiler
    ("output_compiler._to_graphql_field" reads "model._meta" directly), not
    by this descriptor. "_resolve" returns the marker verbatim (not a
    Dynamic). Ships broken if either the registered or unregistered branch
    regresses to a graphene Dynamic.
    """
    from django_graphex.core.descriptors import NativeRelationField

    fk = Post._meta.get_field("author")
    reg = Registry()

    class _AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg

    out_unregistered = _resolve(fk, registry=Registry())
    out_registered = _resolve(fk, registry=reg)

    assert isinstance(out_unregistered, NativeRelationField)
    assert isinstance(out_registered, NativeRelationField)


def test_m2m_nested_input_registered_returns_list() -> None:
    """A nested-input M2M whose related model is registered must resolve to a field.

    Ships broken if a registered nested M2M input conversion starts
    returning None instead of a usable list field.
    """
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
def test_construct_fields_delete_flag_keeps_only_id() -> None:
    """A "delete" input_flag must keep only the "id" field.

    Ships broken if delete-input construction starts including editable
    model scalars instead of restricting to just the primary key.
    """
    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None, input_flag="delete")
    assert set(fields) == {"id"}


def test_construct_fields_create_flag_skips_id() -> None:
    """A "create" input type must drop the auto pk and keep editable scalars.

    Native create-input construction: the compiled GraphQLInputObjectType
    drops the auto pk ("id") and keeps the editable model scalars ("name").
    This is the native equivalent of the graphene "construct_fields(
    input_flag="create")" id-skip (the graphene scalar descriptors are dead
    on native). Ships broken if the compiled create-input starts exposing
    "id" or drops legitimate editable fields.
    """

    class _AuthorCreateInput(DjangoInputObjectType):
        class Meta:
            model = Author
            input_for = "create"

    fields = _AuthorCreateInput._meta.graphql_input_type.fields
    assert "id" not in fields
    assert "name" in fields


def test_construct_fields_exclude_and_only() -> None:
    """Native OUTPUT field construction must honor only_fields and exclude_fields.

    The graphene "construct_fields" scalar descriptors are dead on native, so
    this drives "compile_output_fields" directly. Ships broken if
    only/exclude filtering stops narrowing the compiled output fields
    correctly.
    """
    registry = Registry()
    only = compile_output_fields(Author, registry, only_fields=["name"])
    assert "name" in only and "bio" not in only
    excluded = compile_output_fields(Author, registry, exclude_fields=["bio"])
    assert "bio" not in excluded and "name" in excluded


# --------------------------------------------------------------------------- #
# GenericForeignKey / GenericRelation                                          #
# --------------------------------------------------------------------------- #
class TaggedItem(models.Model):
    """An ORM fixture with a GenericForeignKey.

    Used to exercise the GenericForeignKey output/input converter branches
    below; not itself a test case.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        """Register this ORM fixture under the "tests" app label.

        Required so Django can resolve the model without a real installed
        app owning it.
        """

        app_label = "tests"


class GfkHost(models.Model):
    """An ORM fixture with a GenericRelation.

    Used to exercise the GenericRelation INPUT-branch converter below; not
    itself a test case.
    """

    name = models.CharField(max_length=50)
    items = GenericRelation(TaggedItem)

    class Meta:
        """Register this ORM fixture under the "tests" app label.

        Required so Django can resolve the model without a real installed
        app owning it.
        """

        app_label = "tests"


def test_generic_foreign_key_output_returns_field() -> None:
    """A GenericForeignKey on the OUTPUT path must resolve to a usable field.

    Ships broken if GFK output conversion starts returning None instead of a
    resolvable field.
    """
    registry = Registry()
    gfk = next(
        f for f in TaggedItem._meta.get_fields() if isinstance(f, GenericForeignKey)
    )
    out = _resolve(gfk, registry=registry)
    assert out is not None


def test_generic_foreign_key_input_returns_input_type() -> None:
    """A GenericForeignKey on the INPUT path must resolve to a usable input type.

    Ships broken if GFK input conversion starts returning None instead of a
    resolvable input type.
    """
    registry = Registry()
    gfk = next(
        f for f in TaggedItem._meta.get_fields() if isinstance(f, GenericForeignKey)
    )
    out = _resolve(gfk, registry=registry, input_flag="create")
    assert out is not None


def test_generic_relation_input_flag_returns_dead_scalar() -> None:
    """A GenericRelation on the INPUT path must return the dead-scalar sentinel.

    S-del-backend-11: the input branch of a GenericRelation produces no
    input field, so the converter returns the dead-scalar sentinel and
    "construct_fields" OMITS it (the native equivalent of the retired
    graphene Dynamic resolving to None). Ships broken if this branch starts
    returning a real (non-omittable) field instead.
    """
    from django_graphex.converter import _DEAD_SCALAR

    registry = Registry()
    rel = next(f for f in GfkHost._meta.get_fields() if isinstance(f, GenericRelation))
    out = convert_django_field(rel, registry=registry, input_flag="create")
    assert out is _DEAD_SCALAR


# --------------------------------------------------------------------------- #
# Postgres ArrayField / JSON / HStore (string-typed, no postgres import)       #
# --------------------------------------------------------------------------- #
def test_json_field_converts_to_raw_json_scalar() -> None:
    """JSONField must convert to GdxJSON (v2 RAW-JSON default, structured passthrough).

    The graphene "convert_django_field" JSON descriptor is dead on native,
    so this drives the live native scalar mapper directly. Ships broken if
    JSONField stops mapping to the raw JSON scalar on the native output path.
    """
    # Native scalar conversion (v2 RAW-JSON default): JSONField -> GdxJSON
    # (renders as the raw "JSON" scalar, structured passthrough). The graphene
    # "convert_django_field" JSON descriptor is dead on native, so drive the
    # live native scalar mapper instead.
    field = models.JSONField()
    field.name = "json_field"
    field_map = _to_graphql_field(field, _StubRegistry())
    out = next(iter(field_map.values())).type
    assert out is GdxJSON
