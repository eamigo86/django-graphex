"""S-rel-4 — native flat-GFK + GenericRelation OUTPUT off graphene.

This is the LAST relation slice. After it, all six relation emitters
(``convert_field_to_id`` PK / ``convert_field_to_djangomodel`` FK + forward-O2O /
``convert_onetoone_field_to_djangomodel`` reverse-O2O / forward-M2M / reverse FK
+ reverse M2M via ``convert_many_rel_to_djangomodel`` / the FLAT GFK +
GenericRelation list here) are graphene-free on the native OUTPUT path.

What S-rel-4 migrates (OUTPUT path only — INPUT stays graphene until S-input-5)
------------------------------------------------------------------------------
* FLAT GenericForeignKey (``convert_generic_foreign_key_to_object``): the flat
  ``GenericForeignKeyType`` output Dynamic becomes a graphene-free
  ``NativeRelationField`` marker. SCOPE BOUNDARY: the Track-2 GFK-UNION path
  (``registry.get_gfk_union`` -> ``_g().Field(union_cls)``) is UNTOUCHED — it
  feeds the already-native union injector (``types._compile_gfk_union_output_fields``)
  and a converter-level test asserts it still returns a graphene ``Field`` to the
  union. So the marker is emitted ONLY when there is NO declared gfk_union (the
  flat path).
* forward ``GenericRelation`` list (``convert_generic_relation_to_object_list``):
  the list Dynamic becomes a ``NativeRelationField`` marker. The native compiler
  renders the ``<Model>ListType`` container directly from ``model._meta``
  (``_is_many_relation`` matches ``GenericRelation``), so the Dynamic is dead.
* reverse ``GenericRel`` arm of ``convert_many_rel_to_djangomodel``: the S-rel-3
  ``not isinstance(field, GenericRel)`` exclusion is FLIPPED so a reverse
  ``GenericRel`` ALSO returns a marker on the native OUTPUT path. A reverse
  GenericRel is NOT rendered by the native compiler at all
  (``_is_many_relation`` is False for ``GenericRel``), so its Dynamic is dead —
  pure import-removal, SDL-neutral.

Why this is IMPORT-REMOVAL and SDL-NEUTRAL
------------------------------------------
The flat GFK output is compiled by ``output_compiler._compile_generic_foreign_key``
(reads ``model._meta``, never the converter Dynamic); the forward GenericRelation
is compiled as a ``<Model>ListType`` container by
``types._compile_relation_list_fields`` (reads ``model._meta``); a reverse
GenericRel is not rendered at all. The converter's ``_g().Dynamic(...)`` for these
is built-then-DISCARDED on native — building it only PINS graphene. Replacing it
with a graphene-free marker stops the import without changing the SDL.

Test groups
-----------
* (a) IMPORT-REMOVAL — building the OUTPUT for a model with a flat GFK + forward
  GenericRelation + reverse GenericRel does NOT call ``converter._g()``.
* (b) GFK-UNION STILL WORKS — a Track-2 GFK-union owner still renders its typed
  union output (the union path is UNTOUCHED).
* (c) reverse-GenericRel BACKFILL — the reverse ``GenericRel`` arm returns a
  ``NativeRelationField`` on native OUTPUT (the coverage gap S-rel-3 noted).
* (d) PART B — ``_graphene_descriptor_markers`` is STILL reached during a
  comprehensive native build (the choices converter still emits a graphene
  ``Enum`` descriptor), so the ``_yank_fields`` graphene-marker branch is NOT
  dead → Part B is DEFERRED. This test PROVES the branch is still live so the
  branch is NOT removed.
* (e) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to the HEAD
  baseline.
"""
from __future__ import annotations

import hashlib

import pytest
from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRel,
    GenericRelation,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models

from django_graphex.native.descriptors import NativeMountedField, NativeRelationField
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# The HEAD native seed-schema SDL fingerprint (same as S-rel-2 / S-rel-3 — the #
# relation slices are SDL-neutral). S-rel-4 must keep it byte-identical.       #
# --------------------------------------------------------------------------- #
_HEAD_SEED_SDL_SHA256 = (
    "b3165b721f46e256f698b634b80eb1e027f8f50f0623ba7803a418b9485ce478"
)
_HEAD_SEED_SDL_LEN = 4659


# Module-scope models exercising a reverse ``GenericRel`` (a ``GenericRelation``
# declared with ``related_query_name`` creates a reverse ``GenericRel`` on the
# TARGET model — the only way to produce one in get_fields()). The existing seed
# / test models do NOT have one, which is the S-rel-3 coverage gap.
class GfkS4Tag(models.Model):
    name = models.CharField(max_length=50, default="")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        app_label = "tests"


class GfkS4Host(models.Model):
    title = models.CharField(max_length=50, default="")
    # related_query_name forces a reverse GenericRel onto GfkS4Tag.
    tags = GenericRelation(GfkS4Tag, related_query_name="hosts")

    class Meta:
        app_label = "tests"


def _flat_gfk_field(model):
    return next(
        f for f in model._meta.get_fields() if isinstance(f, GenericForeignKey)
    )


def _forward_generic_relation_field(model):
    return next(
        f for f in model._meta.get_fields() if isinstance(f, GenericRelation)
    )


def _reverse_generic_rel_field(model):
    return next(f for f in model._meta.get_fields() if isinstance(f, GenericRel))


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — flat GFK + forward GenericRelation + reverse GenericRel  #
#     OUTPUT converters never call _g().                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_flat_gfk_and_generic_relation_output_do_not_import_graphene(monkeypatch):
    """The flat-GFK + forward-GenericRelation + reverse-GenericRel OUTPUT
    converters must NOT fire ``converter._g()`` (i.e. must be graphene-free).

    Drives the converters DIRECTLY (a full DjangoObjectType build would also
    exercise the choices Enum, which still uses graphene — that is OUT of S-rel-4
    scope). A declared gfk_union is NOT registered here, so the flat path runs.
    """
    import django_graphex.converter as converter_mod
    from django_graphex.converter import (
        convert_generic_foreign_key_to_object,
        convert_generic_relation_to_object_list,
        convert_many_rel_to_djangomodel,
    )

    def _boom(*_a, **_k):
        raise AssertionError(
            "converter._g() was called from a flat-GFK / GenericRelation OUTPUT "
            "converter — that path must be graphene-free in S-rel-4"
        )

    monkeypatch.setattr(converter_mod, "_g", _boom)

    reg = Registry()

    # flat GFK (GfkS4Tag.content_object) — no gfk_union declared -> flat path.
    convert_generic_foreign_key_to_object(
        _flat_gfk_field(GfkS4Tag), reg, input_flag=None
    )
    # forward GenericRelation list (GfkS4Host.tags).
    convert_generic_relation_to_object_list(
        _forward_generic_relation_field(GfkS4Host), reg, input_flag=None
    )
    # reverse GenericRel arm (GfkS4Tag.hosts).
    convert_many_rel_to_djangomodel(
        _reverse_generic_rel_field(GfkS4Tag), reg, input_flag=None
    )
    # Reaching here without AssertionError proves all three OUTPUT paths are
    # graphene-free.


@pytest.mark.django_db
def test_flat_gfk_and_generic_relation_return_native_markers():
    """flat GFK / forward GenericRelation / reverse GenericRel OUTPUT converters
    return a ``NativeRelationField`` (never ``None`` / the dead-scalar sentinel)."""
    from django_graphex.converter import (
        _DEAD_SCALAR,
        convert_generic_foreign_key_to_object,
        convert_generic_relation_to_object_list,
        convert_many_rel_to_djangomodel,
    )

    reg = Registry()

    flat = convert_generic_foreign_key_to_object(
        _flat_gfk_field(GfkS4Tag), reg, input_flag=None
    )
    fwd = convert_generic_relation_to_object_list(
        _forward_generic_relation_field(GfkS4Host), reg, input_flag=None
    )
    rev = convert_many_rel_to_djangomodel(
        _reverse_generic_rel_field(GfkS4Tag), reg, input_flag=None
    )

    for label, marker in (
        ("flat-GFK", flat),
        ("forward-GenericRelation", fwd),
        ("reverse-GenericRel", rev),
    ):
        assert isinstance(marker, NativeRelationField), (
            f"{label} OUTPUT must return a NativeRelationField, got {marker!r}"
        )
        assert marker is not _DEAD_SCALAR and marker is not None, (
            f"{label} OUTPUT must NEVER be None / dead-scalar (silent-drop trap)"
        )


@pytest.mark.django_db
def test_full_gfk_object_type_build_does_not_import_graphene_for_relations():
    """Building a DjangoObjectType whose model carries a flat GFK + forward
    GenericRelation + reverse GenericRel does not raise from those relation
    paths (the choices Enum is out of scope; these models have no choices).
    """
    import django_graphex.converter as converter_mod

    real_g = converter_mod._g
    calls: list[str] = []

    def _tracking_g():
        calls.append("called")
        return real_g()

    converter_mod._g = _tracking_g
    try:
        reg = Registry()

        class _TagT(DjangoObjectType):
            class Meta:
                model = GfkS4Tag
                registry = reg
                name = "GfkS4TagFullT"

        class _HostT(DjangoObjectType):
            class Meta:
                model = GfkS4Host
                registry = reg
                name = "GfkS4HostFullT"
    finally:
        converter_mod._g = real_g

    # These models have NO scalar that needs graphene and NO choices, so building
    # them on the native OUTPUT path must not pin graphene via _g().
    assert calls == [], (
        "building a GFK / GenericRelation DjangoObjectType (no choices) called "
        f"converter._g() {len(calls)} time(s) — relations must be graphene-free"
    )


# --------------------------------------------------------------------------- #
# (b) GFK-UNION STILL WORKS — the Track-2 typed-union path is UNTOUCHED.        #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_gfk_union_converter_still_emits_graphene_field():
    """When the owner declares ``Meta.gfk_unions`` for a GFK, the converter STILL
    emits a graphene ``Field`` to the union (the union path is out of S-rel-4
    scope — it feeds the native union injector and stays graphene)."""
    import graphene

    from django_graphex.converter import convert_django_field
    from django_graphex.types import DjangoUnionType
    from tests.models import Track2Account, Track2GfkComment, Track2Invoice

    reg = Registry()

    class _AccountT(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class _InvoiceT(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    class _PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = (_AccountT, _InvoiceT)
            registry = reg

    class _GfkCommentT(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": _PaymentUnion}

    gfk = _flat_gfk_field(Track2GfkComment)
    converted = convert_django_field(gfk, registry=reg)
    # The union path stays a graphene Dynamic; resolving it yields a graphene
    # Field whose type is the declared union.
    assert isinstance(converted, graphene.Dynamic), (
        "the GFK-union path must STILL be a graphene Dynamic (untouched in "
        f"S-rel-4); got {converted!r}"
    )
    resolved = converted.get_type()
    assert isinstance(resolved, graphene.Field)
    assert resolved.type is _PaymentUnion, (
        "the GFK-union path must resolve to a graphene Field wrapping the union"
    )


@pytest.mark.django_db
def test_gfk_union_output_renders_typed_union_in_schema():
    """A Track-2 GFK-union owner renders a typed union output field in the
    compiled native schema (the native union injector reads model._meta +
    registry.get_gfk_union directly — independent of the converter descriptor)."""
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoUnionType
    from tests.models import Track2Account, Track2GfkComment, Track2Invoice

    reg = Registry()

    class _AccountT2(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg
            name = "GfkS4AccountT"

    class _InvoiceT2(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg
            name = "GfkS4InvoiceT"

    class _PaymentUnion2(DjangoUnionType):
        class Meta:
            gfk_types = (_AccountT2, _InvoiceT2)
            registry = reg
            name = "GfkS4PaymentUnion"

    class _GfkCommentT2(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            name = "GfkS4GfkCommentT"
            gfk_unions = {"target": _PaymentUnion2}

    compile_all_outputs()

    out = _GfkCommentT2._meta.graphql_output_type
    assert out is not None
    assert "target" in out.fields, (
        f"the GFK-union field 'target' must be present; got {list(out.fields)}"
    )
    target_type = out.fields["target"].type
    assert getattr(target_type, "name", None) == "GfkS4PaymentUnion", (
        "the 'target' field must render the typed GFK union, not the flat "
        f"GenericForeignKeyType; got {target_type!r}"
    )


# --------------------------------------------------------------------------- #
# (c) reverse-GenericRel BACKFILL (the S-rel-3 coverage gap).                   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_reverse_generic_rel_arm_returns_native_marker():
    """The reverse ``GenericRel`` arm of ``convert_many_rel_to_djangomodel``
    returns a ``NativeRelationField`` on the native OUTPUT path (the S-rel-3
    ``not isinstance(field, GenericRel)`` exclusion is flipped in S-rel-4)."""
    from django_graphex.converter import (
        _DEAD_SCALAR,
        convert_many_rel_to_djangomodel,
    )

    rev = _reverse_generic_rel_field(GfkS4Tag)
    assert isinstance(rev, GenericRel)

    out = convert_many_rel_to_djangomodel(rev, Registry(), input_flag=None)
    assert isinstance(out, NativeRelationField), (
        "reverse GenericRel OUTPUT must return a NativeRelationField in S-rel-4; "
        f"got {out!r}"
    )
    assert out is not _DEAD_SCALAR and out is not None, (
        "the reverse GenericRel marker must NEVER be None / dead-scalar"
    )


@pytest.mark.django_db
def test_reverse_generic_rel_not_rendered_in_native_output():
    """A reverse ``GenericRel`` is NOT rendered by the native output compiler
    (``_is_many_relation`` is False for ``GenericRel``), so swapping its dead
    Dynamic for a marker is SDL-neutral — the field never appears either way."""
    from django_graphex.native.output_compiler import _is_many_relation
    from django_graphex.native.registry_compiler import compile_all_outputs

    rev = _reverse_generic_rel_field(GfkS4Tag)
    assert _is_many_relation(rev) is False, (
        "a reverse GenericRel must not be classified as a to-many relation "
        "(it is not rendered as a native container)"
    )

    reg = Registry()

    class _TagOut(DjangoObjectType):
        class Meta:
            model = GfkS4Tag
            registry = reg
            name = "GfkS4TagOutT"

    compile_all_outputs()
    out = _TagOut._meta.graphql_output_type
    assert rev.name not in out.fields and "hosts" not in out.fields, (
        "the reverse GenericRel must not appear in the native output type; got "
        f"{list(out.fields)}"
    )


@pytest.mark.django_db
def test_forward_generic_relation_renders_native_list_container():
    """The forward ``GenericRelation`` renders a ``<Model>ListType`` container in
    the native output (its Dynamic is dead — the container is built from
    ``model._meta``)."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()

    class _TagC(DjangoObjectType):
        class Meta:
            model = GfkS4Tag
            registry = reg
            name = "GfkS4TagContainerT"

    class _HostC(DjangoObjectType):
        class Meta:
            model = GfkS4Host
            registry = reg
            name = "GfkS4HostContainerT"

    compile_all_outputs()
    host_out = _HostC._meta.graphql_output_type
    assert "tags" in host_out.fields, (
        f"forward GenericRelation 'tags' must render natively; got {list(host_out.fields)}"
    )


# --------------------------------------------------------------------------- #
# (d) PART B — the _yank_fields graphene-marker branch is STILL reached (the    #
#     choices converter still emits a graphene Enum descriptor). Part B is      #
#     DEFERRED: the branch is NOT removed because removing it would silently     #
#     drop the choices field from _meta.fields.                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_graphene_marker_branch_still_reached_by_choices_after_part_a():
    """STEP 0 / Part B proof: after the S-rel-4 relation migration, a graphene
    descriptor STILL flows into the ``_yank_fields`` graphene-marker branch — the
    choices field's graphene ``Enum`` (from ``convert_django_field_with_choices``,
    which retires in a LATER slice, not S-rel-4). So the branch is NOT dead and
    ``_graphene_descriptor_markers`` IS still called during a comprehensive native
    build. This documents WHY Part B (retiring the branch) is DEFERRED."""
    import django_graphex.types as types_mod
    from django_graphex.converter import _DEAD_SCALAR
    from django_graphex.native.descriptors import NativeField, NativeMountedField

    reached: list[tuple[str, str]] = []
    orig_yank = types_mod._yank_fields

    def _spy_yank(attrs, _as, sort=True):
        for name, value in attrs.items():
            if not isinstance(value, (NativeMountedField, NativeField)):
                if value is not _DEAD_SCALAR:
                    reached.append(
                        (name, type(value).__module__ + "." + type(value).__name__)
                    )
        return orig_yank(attrs, _as, sort=sort)

    types_mod._yank_fields = _spy_yank
    try:
        from tests.native._sdl_parity_seed import render_native_sdl

        render_native_sdl()
    finally:
        types_mod._yank_fields = orig_yank

    # After S-rel-4: the ONLY graphene descriptor reaching the branch is the
    # choices Enum (a graphene-module type). The relation Dynamics (content_object,
    # notes, target) are gone — they are now native markers.
    graphene_reached = {n: t for (n, t) in reached if t.startswith("graphene.")}
    assert graphene_reached, (
        "expected the choices Enum to still reach the graphene-marker branch "
        "(Part B prerequisite). If this is empty, the branch may be dead and "
        "Part B could proceed — re-evaluate."
    )
    # No relation Dynamic should remain — they were migrated in S-rel-2/3/4.
    relation_dynamics = {
        n: t for (n, t) in reached if t == "graphene.types.dynamic.Dynamic"
    }
    assert not relation_dynamics, (
        "no relation graphene Dynamic should reach the branch after S-rel-4; "
        f"found {relation_dynamics}"
    )
    # The choices Enum is the live blocker.
    assert any("enum" in t.lower() for t in graphene_reached.values()), (
        f"expected a graphene Enum descriptor; reached: {graphene_reached}"
    )


# --------------------------------------------------------------------------- #
# (e) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to HEAD.     #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_seed_native_sdl_byte_identical_to_head_baseline():
    """The full seed schema's native SDL must be byte-identical to the HEAD
    (pre-S-rel-4) baseline — S-rel-4 is SDL-NEUTRAL."""
    from tests.native._sdl_parity_seed import render_native_sdl

    sdl = render_native_sdl()
    assert len(sdl) == _HEAD_SEED_SDL_LEN, (
        f"seed SDL length changed: {len(sdl)} != {_HEAD_SEED_SDL_LEN} "
        "(S-rel-4 must be SDL-neutral)"
    )
    digest = hashlib.sha256(sdl.encode()).hexdigest()
    assert digest == _HEAD_SEED_SDL_SHA256, (
        "seed SDL changed (not byte-identical to the HEAD baseline) — S-rel-4 "
        f"must be SDL-neutral.\nGot SHA256 {digest}, expected {_HEAD_SEED_SDL_SHA256}"
    )


@pytest.mark.django_db
def test_flat_gfk_and_generic_relation_shapes_unchanged_in_seed_sdl():
    """The flat-GFK + GenericRelation field shapes are unchanged in the seed SDL."""
    from tests.native._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.native.conftest import normalize_sdl

    sdl = render_native_sdl()
    # flat GFK -> GenericForeignKeyType
    comment = normalize_sdl(extract_type_block(sdl, "PSGfkComment"))
    assert "target: GenericForeignKeyType" in comment
    note = normalize_sdl(extract_type_block(sdl, "PSNote"))
    assert "contentObject: GenericForeignKeyType" in note
    gfk = normalize_sdl(extract_type_block(sdl, "GenericForeignKeyType"))
    assert "appLabel: String" in gfk
    assert "id: ID" in gfk
    assert "modelName: String" in gfk
    # forward GenericRelation -> <Model>ListType container
    profile = normalize_sdl(extract_type_block(sdl, "PSProfile"))
    assert "notes: OptNoteListType" in profile


# --------------------------------------------------------------------------- #
# (f) _yank_fields keeps a NativeRelationField (not dropped to the continue).   #
# --------------------------------------------------------------------------- #
def test_yank_fields_keeps_gfk_native_relation_field():
    """``_yank_fields`` keeps a flat-GFK ``NativeRelationField`` AS-IS in its
    native-currency branch (it subclasses ``NativeMountedField``)."""
    from django_graphex.types import _yank_fields

    marker = NativeRelationField(related_model=GfkS4Tag)
    assert isinstance(marker, NativeMountedField)

    out = _yank_fields({"contentObject": marker}, _as=NativeMountedField)
    assert "contentObject" in out, "_yank_fields dropped the GFK NativeRelationField"
    assert out["contentObject"] is marker, "the marker must be kept AS-IS"
