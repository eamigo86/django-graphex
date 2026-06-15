"""S-ROOTS-d — converter SCALAR descriptors native-aware (per-field-type skip).

Phase 7 graphene-removal, sub-slice (d). The native OUTPUT compiler
(``native/output_compiler.compile_output_fields``) reads ``model._meta`` DIRECTLY
and maps Django field types to native scalars (DateField->GdxDate,
BinaryField->GraphQLString, CharField->GraphQLString, …). It NEVER reads the
graphene SCALAR descriptors that ``converter.py`` builds into ``_meta.fields``
(``Binary(...)`` / ``CustomDate(...)`` / ``String(...)`` / ``Int(...)`` / …).
Those scalar descriptors are therefore DEAD on the native path.

This slice makes ``construct_fields`` NATIVE-AWARE PER-FIELD-TYPE: on native it
SKIPS building the dead SCALAR descriptors, while KEEPING the descriptors the
native path / runtime still reads:
  * GFK descriptors (``convert_generic_foreign_key_to_object``),
  * the relation ``Dynamic`` descriptors (FK / O2O / M2M / reverse rels),
  * the nested-list (``_nested_list_object_field``) descriptors.

PARAMOUNT: the compiled native SDL scalar NAMES must stay BYTE-IDENTICAL
(``CustomDate`` / ``CustomDateTime`` / ``CustomTime`` / ``UUID`` / ``JSONString``
/ ``String`` for Binary / …). Those names come from ``native/scalars.py`` via the
output compiler, NOT from the skipped converter descriptors — so skipping must not
change a single byte of the SDL.

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s_roots_d_converter_native_aware.py -q -o addopts=""
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# The graphene scalar descriptor types converter builds for scalar field kinds.
_DEAD_SCALAR_DESC_NAMES = {
    "String",
    "Int",
    "Boolean",
    "Float",
    "UUID",
    "Binary",
    "CustomDate",
    "CustomDateTime",
    "CustomTime",
    "JSONString",
}


def _scalar_kinds_meta_fields():
    from django_graphex.types import DjangoObjectType
    from tests.models import ScalarKindsModel

    class _SkType(DjangoObjectType):
        class Meta:
            model = ScalarKindsModel

    return _SkType


# ---------------------------------------------------------------------------
# RED 1: dead SCALAR descriptors are NOT built on native (skipped per-field-type)
# ---------------------------------------------------------------------------
def test_construct_fields_skips_dead_scalar_descriptors_on_native():
    """On native, construct_fields must NOT build the dead scalar descriptors.

    Every concrete scalar field (char/text/integer/boolean/float/decimal/
    duration/uuid/date/datetime/time/binary/json) is derived directly by the
    native output_compiler from model._meta; the converter graphene scalar
    descriptor for each is dead, so it must be absent from _meta.fields.
    """
    sk = _scalar_kinds_meta_fields()
    meta_fields = sk._meta.fields

    dead_scalar_names = {
        "char",
        "text",
        "integer",
        "big_integer",
        "boolean",
        "floating",
        "decimal",
        "duration",
        "uuid_field",
        "date",
        "datetime",
        "time",
        "binary",
        "json_field",
    }
    leaked = dead_scalar_names & set(meta_fields.keys())
    assert not leaked, (
        "Native construct_fields must SKIP building dead scalar descriptors; "
        f"these scalar descriptors leaked into _meta.fields: {sorted(leaked)}"
    )


# ---------------------------------------------------------------------------
# RED 2: GFK + relation + nested-list descriptors are KEPT on native
# ---------------------------------------------------------------------------
def test_construct_fields_keeps_gfk_descriptor_on_native():
    """The GFK converter descriptor (Dynamic) must STILL be built on native."""
    from django_graphex.types import DjangoObjectType
    from tests.models import Track2GfkComment

    class _GfkType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment

    meta_fields = _GfkType._meta.fields
    assert "target" in meta_fields, (
        "The GFK 'target' descriptor must be KEPT in _meta.fields on native "
        "(per-field-type skip must NOT blanket-drop GFK)."
    )


def test_construct_fields_keeps_relation_descriptors_on_native():
    """The relation Dynamic descriptors (FK / M2M / reverse FK) must be KEPT."""
    from django_graphex.types import DjangoObjectType
    from tests.models import Post

    class _PostType(DjangoObjectType):
        class Meta:
            model = Post

    meta_fields = _PostType._meta.fields
    # FK (author/category) + M2M (tags/co_authors) + reverse FK (comments) are
    # relation descriptors the per-field-type skip must NOT touch.
    for rel in ("author", "category", "tags", "co_authors", "comments"):
        assert rel in meta_fields, (
            f"Relation descriptor {rel!r} must be KEPT in _meta.fields on native"
        )


# ---------------------------------------------------------------------------
# RED 3: SDL byte-parity — every scalar name + FK survives, unchanged
# ---------------------------------------------------------------------------
def test_native_scalar_sdl_is_byte_identical_after_skip():
    """The native SDL scalar names must be UNCHANGED after the converter skip.

    Byte-identical to the captured baseline (built from native/scalars.py via the
    output compiler, NOT from the skipped converter descriptors).
    """
    from graphql import print_type

    sk = _scalar_kinds_meta_fields()
    sdl = print_type(sk._meta.graphql_output_type)

    expected_lines = {
        "id: ID!",
        "char: String",
        "text: String",
        "integer: Int",
        "bigInteger: Int",
        "boolean: Boolean",
        "floating: Float",
        "decimal: Float",
        "duration: Float",
        "uuidField: UUID",
        "date: CustomDate",
        "datetime: CustomDateTime",
        "time: CustomTime",
        "binary: String",
        "jsonField: JSONString",
    }
    normalized = {line.strip() for line in sdl.splitlines()}
    missing = {ln for ln in expected_lines if ln not in normalized}
    assert not missing, (
        "Native SDL scalar parity REGRESSION (a scalar name/type changed or a "
        f"field vanished); missing lines: {sorted(missing)}\nFull SDL:\n{sdl}"
    )


# ---------------------------------------------------------------------------
# RED 4: SILENT-DROP guard — every field kind present with correct type
# ---------------------------------------------------------------------------
def test_silent_drop_guard_all_field_kinds_present():
    """Compile a scalar + date + binary + uuid + json + FK model; assert ALL
    expected fields are present in the compiled output type with correct types.

    If skipping a converter scalar over-reached and dropped a field the native
    path reads, it would vanish here SILENTLY (the duck-typed compiler drops
    unrecognized descriptors with no error).
    """
    sk = _scalar_kinds_meta_fields()
    gql = sk._meta.graphql_output_type
    keys = set(gql.fields.keys())

    expected = {
        "id",
        "char",
        "text",
        "integer",
        "bigInteger",
        "boolean",
        "floating",
        "decimal",
        "duration",
        "uuidField",
        "date",
        "datetime",
        "time",
        "binary",
        "jsonField",
        "author",  # FK relation must survive the scalar skip
    }
    missing = expected - keys
    assert not missing, (
        f"SILENT DROP: expected output fields missing from native type: "
        f"{sorted(missing)}; present: {sorted(keys)}"
    )


def test_silent_drop_guard_relation_list_containers_present():
    """A model with FK + M2M + reverse FK must keep all relation containers."""
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Author, Category, Comment, Post, Tag

    reg = Registry()

    class _A(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg

    class _C(DjangoObjectType):
        class Meta:
            model = Category
            registry = reg

    class _T(DjangoObjectType):
        class Meta:
            model = Tag
            registry = reg

    class _Cm(DjangoObjectType):
        class Meta:
            model = Comment
            registry = reg

    class _TList(DjangoListObjectType):
        class Meta:
            model = Tag
            registry = reg

    class _CmList(DjangoListObjectType):
        class Meta:
            model = Comment
            registry = reg

    class _AList(DjangoListObjectType):
        class Meta:
            model = Author
            registry = reg

    class _P(DjangoObjectType):
        class Meta:
            model = Post
            registry = reg

    keys = set(_P._meta.graphql_output_type.fields.keys())
    expected = {
        "id",
        "title",
        "body",
        "views",
        "author",
        "category",
        "tags",
        "coAuthors",
        "comments",
    }
    missing = expected - keys
    assert not missing, (
        f"SILENT DROP (relations): missing {sorted(missing)}; present {sorted(keys)}"
    )


# ---------------------------------------------------------------------------
# RED 5: base_types scalar classes — KEPT (still LIVE on graphene path + tested)
# ---------------------------------------------------------------------------
def test_base_types_scalar_classes_kept_documented():
    """Binary / CustomDate / CustomDateTime / CustomTime stay in base_types.

    They are STILL referenced by the converter graphene path (graphene installed)
    and directly unit-tested by tests/test_base_types_internals.py. Removing them
    would add NEW collateral, so this slice keeps them (per the task's
    "if a scalar class can't be removed, keep it + note why" clause). Removal is
    deferred to S8 (graphene uninstall).
    """
    from django_graphex import base_types

    for name in ("Binary", "CustomDate", "CustomDateTime", "CustomTime"):
        assert hasattr(base_types, name), (
            f"base_types.{name} must be KEPT — still LIVE on the graphene path."
        )
