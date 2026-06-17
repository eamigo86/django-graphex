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
* (d) PART B (re-evaluated in S-enum-2) — after the choices OUTPUT migration the
  OUTPUT build no longer reaches the ``_yank_fields`` graphene-marker branch, but
  a CREATE-INPUT build STILL emits graphene relation ``Dynamic`` descriptors that
  do (the INPUT path stays graphene until S-input-5). So the branch is NOT dead
  and Part B (retiring it) stays DEFERRED — the blocker MOVED from the choices
  OUTPUT path to the INPUT path. This test proves the new blocker.
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

    # S-del-backend-11: the converter has no ``_g()`` graphene accessor (the
    # graphene backend was deleted), so building these GFK / GenericRelation
    # DjangoObjectTypes is structurally graphene-free. Assert the OUTPUT types
    # compile (the relation paths emit native markers, never pin graphene).
    assert _TagT._meta.graphql_output_type is not None
    assert _HostT._meta.graphql_output_type is not None


# --------------------------------------------------------------------------- #
# (b) GFK-UNION STILL WORKS — the Track-2 typed-union path is UNTOUCHED.        #
# --------------------------------------------------------------------------- #
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
# (d) PART B — RETIRED in S-input-5. After the INPUT path went graphene-free     #
#     (relation Dynamics -> NativeRelationField, choices Enum -> shared native    #
#     GraphQLEnumType, PK ID -> dead scalar), NO graphene descriptor reaches      #
#     ``_yank_fields`` on ANY native build (OUTPUT or INPUT). The lazy            #
#     graphene-marker branch + ``_graphene_descriptor_markers`` are deleted.      #
#     This test (renamed/flipped from the S-enum-2 tripwire) PROVES the branch    #
#     is gone and a create-input build reaches ``_yank_fields`` graphene-free.    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_graphene_marker_branch_retired_input_now_graphene_free():
    """Part B retirement (S-input-5).

    The long-deferred Part B (#1609 / S-enum-2) is DONE: the INPUT path no longer
    emits graphene relation ``Dynamic`` / ``ID`` / choices ``Enum`` descriptors
    (they became ``NativeRelationField`` / dead-scalar / the shared native
    ``GraphQLEnumType``). So:

    * the lazy ``types._graphene_descriptor_markers`` helper is DELETED;
    * a CREATE-INPUT build (formerly the blocker — it emitted graphene relation
      ``Dynamic`` descriptors that reached the branch via ``_as.mounted``) now
      reaches ``_yank_fields`` with ZERO graphene descriptors;
    * the OUTPUT build likewise stays graphene-free at ``_yank_fields``.
    """
    import django_graphex.types as types_mod
    from django_graphex.converter import _DEAD_SCALAR
    from django_graphex.native.descriptors import NativeField, NativeMountedField
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoInputObjectType
    from tests.models import PersonWithSpouse

    # The graphene-marker branch helper is GONE.
    assert not hasattr(types_mod, "_graphene_descriptor_markers"), (
        "S-input-5 must retire types._graphene_descriptor_markers (the "
        "graphene-marker branch is dead on every native build)"
    )

    def _graphene_reached_during(thunk) -> dict[str, str]:
        reached: dict[str, str] = {}
        orig_yank = types_mod._yank_fields

        def _spy_yank(attrs, _as, sort=True):
            for name, value in attrs.items():
                if isinstance(value, (NativeMountedField, NativeField)):
                    continue
                if value is _DEAD_SCALAR:
                    continue
                mod = type(value).__module__
                if mod.startswith("graphene"):
                    reached[name] = mod + "." + type(value).__name__
            return orig_yank(attrs, _as, sort=sort)

        types_mod._yank_fields = _spy_yank
        try:
            thunk()
        finally:
            types_mod._yank_fields = orig_yank
        return reached

    # (1) OUTPUT build: graphene-free at _yank_fields.
    from tests.native._sdl_parity_seed import render_native_sdl

    output_reached = _graphene_reached_during(render_native_sdl)
    assert not output_reached, (
        "the OUTPUT build must reach _yank_fields with zero graphene descriptors; "
        f"still found {output_reached}"
    )

    # (2) CREATE-INPUT build: now ALSO graphene-free (the former Part B blocker).
    def _build_create_input() -> None:
        reg = Registry()

        class _PersonCreateInputTripwire(DjangoInputObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = reg
                input_for = "create"

    input_reached = _graphene_reached_during(_build_create_input)
    assert not input_reached, (
        "after S-input-5 a create-input build must reach _yank_fields with zero "
        f"graphene descriptors (the INPUT path is graphene-free); found {input_reached}"
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


# =========================================================================== #
# S-enum-2 — converter choices OUTPUT descriptor off graphene (#1609).         #
#                                                                              #
# These tests live in THIS module (alongside the S-rel-4 choices-gap          #
# deferral tripwire above) on purpose: the seed harness ``render_native_sdl``  #
# is NOT idempotent across modules (a pre-existing global-state leak in the    #
# shared output registry surfaces ``TagListType`` duplicate-name collisions    #
# when called from a NEW native test module). Co-locating with the existing    #
# ``render_native_sdl`` caller avoids introducing a new module that shifts     #
# collection order and trips that latent harness bug.                          #
#                                                                              #
# Background: S-enum-1 migrated the native output COMPILER (renders choices as  #
# a GraphQLEnumType from model._meta). But                                      #
# ``converter.convert_django_field_with_choices`` STILL called ``_g().Enum``    #
# at CLASS-DEFINITION time inside ``construct_fields`` — so defining a choices  #
# DjangoObjectType imported graphene AND the graphene Enum reached the          #
# ``_yank_fields`` graphene-marker branch (#1609). S-enum-2 Part 1 returns the  #
# dead-scalar sentinel on the native OUTPUT path so the graphene import never   #
# fires and the OUTPUT build is graphene-free at ``_yank_fields``. The INPUT    #
# choices path is UNCHANGED (graphene until S-input-5).                         #
# =========================================================================== #
@pytest.mark.django_db
def test_choices_define_object_type_does_not_import_graphene():
    """Defining a ``DjangoObjectType`` with a choices field (class-def time) and
    building its native OUTPUT type must NOT call ``converter._g()`` (#1609 gap).
    """
    from graphql import GraphQLEnumType

    from tests.models import EnumCollisionItemA

    reg = Registry()

    # S-del-backend-11: the choices converter has no ``_g().Enum`` to call (the
    # graphene backend was deleted), so defining a choices DjangoObjectType and
    # building its native OUTPUT type is structurally graphene-free. The per-class
    # native OUTPUT type is built at class-def time, so reaching the assertions
    # proves the choices OUTPUT path renders the native ``GraphQLEnumType``.
    class _ChoicesItemImport(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            name = "ChoicesItemImportRemovalS2"

    compiled = _ChoicesItemImport._meta.graphql_output_type
    assert compiled is not None
    assert isinstance(compiled.fields["status"].type, GraphQLEnumType)


@pytest.mark.django_db
def test_choices_output_converter_returns_dead_scalar():
    """``convert_django_field_with_choices`` on OUTPUT (input_flag is None) for a
    choices field returns the dead-scalar sentinel without calling ``_g()``."""
    from django_graphex.converter import (
        _DEAD_SCALAR,
        convert_django_field_with_choices,
    )
    from tests.models import EnumCollisionItemA

    field = EnumCollisionItemA._meta.get_field("status")
    out = convert_django_field_with_choices(field, Registry(), input_flag=None)
    assert out is _DEAD_SCALAR, (
        "a choices field on OUTPUT must return the dead-scalar sentinel (the "
        f"native compiler renders the enum from model._meta); got {out!r}"
    )


@pytest.mark.django_db
def test_choices_input_path_off_graphene():
    """S-input-5: the INPUT / mutation choices converter path is now graphene-free
    too — it returns the dead-scalar sentinel (the native input compiler renders
    the SHARED native ``GraphQLEnumType`` from ``model._meta``)."""
    from django_graphex.converter import _DEAD_SCALAR, convert_django_field_with_choices
    from tests.models import EnumCollisionItemA

    field = EnumCollisionItemA._meta.get_field("status")
    for input_flag in ("create", "update"):
        out = convert_django_field_with_choices(
            field, Registry(), input_flag=input_flag
        )
        assert out is _DEAD_SCALAR, (
            f"INPUT choices ({input_flag}) must return the dead-scalar sentinel; "
            f"got {out!r}"
        )


@pytest.mark.django_db
def test_choices_field_omitted_from_meta_fields_on_output():
    """A choices field on OUTPUT is OMITTED from ``_meta.fields`` (option A: the
    dead-scalar sentinel, dropped by ``construct_fields``) — the native compiler
    still renders the enum from ``model._meta``, so this is SDL-neutral."""
    from tests.models import EnumCollisionItemA

    reg = Registry()

    class _ChoicesItemMeta(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            name = "ChoicesItemMetaFieldsS2"

    assert "status" not in _ChoicesItemMeta._meta.fields, (
        "the choices field must be omitted from _meta.fields on OUTPUT (dead "
        f"scalar); got {list(_ChoicesItemMeta._meta.fields)}"
    )


@pytest.mark.django_db
def test_choices_output_build_clean_at_yank_fields():
    """A comprehensive native OUTPUT build reaches ``_yank_fields`` with ZERO
    graphene descriptors (the choices Enum was the last graphene OUTPUT descriptor
    after S-rel-2/3/4; S-enum-2 retired it). S-input-5 retired the graphene-marker
    branch entirely, so there is no longer a ``_graphene_descriptor_markers`` to
    spy — the graphene-free assertion is the OUTPUT regression guard."""
    import django_graphex.types as types_mod
    from django_graphex.converter import _DEAD_SCALAR
    from django_graphex.native.descriptors import NativeField, NativeMountedField

    graphene_reached: list[tuple[str, str]] = []
    orig_yank = types_mod._yank_fields

    def _spy_yank(attrs, _as, sort=True):
        for name, value in attrs.items():
            if isinstance(value, (NativeMountedField, NativeField)):
                continue
            if value is _DEAD_SCALAR:
                continue
            mod = type(value).__module__
            if mod.startswith("graphene"):
                graphene_reached.append((name, mod + "." + type(value).__name__))
        return orig_yank(attrs, _as, sort=sort)

    types_mod._yank_fields = _spy_yank
    try:
        from tests.native._sdl_parity_seed import render_native_sdl

        render_native_sdl()
    finally:
        types_mod._yank_fields = orig_yank

    assert not graphene_reached, (
        "graphene descriptors still reach _yank_fields on a native OUTPUT build: "
        f"{graphene_reached}"
    )


@pytest.mark.django_db
def test_choices_seed_sdl_byte_identical_and_enum_renders():
    """The seed native SDL is byte-identical to HEAD (S-enum-2 is SDL-NEUTRAL) and
    the choices field still renders as its enum (S-enum-1 output unchanged)."""
    from tests.native._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.native.conftest import normalize_sdl

    sdl = render_native_sdl()
    assert len(sdl) == _HEAD_SEED_SDL_LEN, (
        f"seed SDL length changed: {len(sdl)} != {_HEAD_SEED_SDL_LEN}"
    )
    digest = hashlib.sha256(sdl.encode()).hexdigest()
    assert digest == _HEAD_SEED_SDL_SHA256, (
        "seed SDL not byte-identical to HEAD — S-enum-2 must be SDL-neutral.\n"
        f"Got SHA256 {digest}, expected {_HEAD_SEED_SDL_SHA256}"
    )

    # Broad silent-drop guard: relations + choices all present in the seed SDL.
    author = normalize_sdl(extract_type_block(sdl, "PSAuthor"))
    post = normalize_sdl(extract_type_block(sdl, "PSPost"))
    person = normalize_sdl(extract_type_block(sdl, "PSPerson"))
    item = normalize_sdl(extract_type_block(sdl, "PSItem"))
    assert "authorProfile: PSAuthorProfile" in author  # reverse-O2O
    assert "author: PSAuthor" in post  # FK
    assert "category: PSCategory" in post  # FK
    assert "spouse: PSPerson" in person  # self-ref O2O
    # choices renders as its enum type (not String); graphene's to_camel_case
    # keeps the first char lowercase.
    assert "status: testsEnumcollisionitemaStatusEnum" in item
