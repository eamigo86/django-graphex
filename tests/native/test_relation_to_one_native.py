"""S-rel-2 — native to-ONE relation OUTPUT + PK scalar off graphene.

The native OUTPUT type for a model is compiled ENTIRELY from
``model._meta.get_fields()``:

* FK / forward-O2O ......... ``output_compiler._to_graphql_field`` (to-ONE arm);
* reverse-O2O .............. ``types._compile_reverse_o2o_fields``;
* PK ``id: ID!`` ........... ``output_compiler._to_graphql_field`` (scalar arm,
                            ``AutoField -> GraphQLID`` + ``GraphQLNonNull``).

The converter historically ALSO emitted a graphene ``Dynamic`` for every to-ONE
relation (``convert_field_to_djangomodel`` / ``convert_onetoone_field_to_djangomodel``)
and a graphene ``ID`` for the PK (``convert_field_to_id``). Those descriptors are
NEVER read on the native output path (built-then-discarded), yet BUILDING them
imports graphene (``converter._g()``) — pinning graphene for the process lifetime.

S-rel-2 makes the native OUTPUT path graphene-free for to-ONE relations and the
PK scalar:

* the PK on OUTPUT returns the dead-scalar sentinel (omitted by
  ``construct_fields``); the native compiler still emits ``id: ID!``;
* FK / forward-O2O / reverse-O2O on OUTPUT return a graphene-free
  ``NativeRelationField`` presence/ordering marker (kept by ``_yank_fields`` in
  its native-currency branch, carrying the SAME ``creation_counter`` so SDL
  field order is preserved) — NEVER ``None`` / the dead-scalar sentinel (the
  test_issue52 self-ref-O2O silent-drop trap).

This slice is IMPORT-REMOVAL and SDL-NEUTRAL: the native SDL is byte-identical
before and after. The INPUT path stays on graphene until S-input-5.

Test groups:
* (a) IMPORT-REMOVAL — building the OUTPUT type for FK + forward-O2O +
  reverse-O2O + self-ref-O2O does NOT call ``converter._g()`` (monkeypatched to
  raise); the PK OUTPUT path likewise never calls ``_g()``.
* (b) SILENT-DROP GUARD — the self-ref O2O (``spouse``) and the reverse-O2O
  (``authorProfile``) fields are PRESENT in the compiled output type's fields
  (the test_issue52 canary, reproduced).
* (c) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to the
  HEAD baseline (a golden SHA256 captured pre-change), and the per-aspect
  to-ONE relation shapes are unchanged.
* (d) ``_yank_fields`` keeps a ``NativeRelationField`` (does not drop it to the
  final ``continue``).
"""
from __future__ import annotations

import hashlib

import pytest
from graphql import GraphQLID, GraphQLNonNull

from django_graphex import DjangoObjectType
from django_graphex.native.descriptors import NativeMountedField, NativeRelationField
from django_graphex.registry import Registry
from tests.models import Author, AuthorProfile, Category, PersonWithSpouse, Post

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# The HEAD (pre-S-rel-2) native seed-schema SDL fingerprint. Captured from a   #
# clean ``git worktree HEAD`` checkout via ``render_native_sdl`` BEFORE the    #
# import-removal change. S-rel-2 must keep the native SDL byte-identical, so   #
# this golden hash is the byte-level SDL-neutral guard.                        #
# --------------------------------------------------------------------------- #
_HEAD_SEED_SDL_SHA256 = (
    "b3165b721f46e256f698b634b80eb1e027f8f50f0623ba7803a418b9485ce478"
)
_HEAD_SEED_SDL_LEN = 4659


# NOTE: ``DjangoObjectType`` uses a pydantic metaclass that requires a
# class-statement ``Meta`` (a dynamically attached ``type(...)`` namespace lacks
# ``__module__`` and trips pydantic's ``inspect_namespace``). The seed schema
# documents the same constraint. So each test defines its types with explicit
# ``class`` statements.


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — the to-ONE relation + PK OUTPUT paths never call _g().  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_to_one_output_converters_do_not_import_graphene(monkeypatch):
    """The to-ONE relation OUTPUT converters (FK + forward-O2O + self-ref-O2O +
    reverse-O2O) and the PK OUTPUT converter must NOT fire converter._g() (i.e.
    must not import graphene).

    NOTE: this exercises the to-ONE relation + PK converters DIRECTLY rather than
    building a full ``DjangoObjectType``, because the to-MANY relations on these
    models (reverse-FK / M2M / reverse-M2M) STILL emit graphene ``Dynamic``s —
    that is S-rel-3's scope, not S-rel-2. S-rel-2 retires graphene only on the
    to-ONE relation + PK OUTPUT paths.
    """
    import django_graphex.converter as converter_mod
    from django_graphex.converter import (
        convert_field_to_djangomodel,
        convert_field_to_id,
        convert_onetoone_field_to_djangomodel,
    )

    def _boom(*_a, **_k):
        raise AssertionError(
            "converter._g() was called from a to-ONE relation / PK OUTPUT "
            "converter — that path must be graphene-free in S-rel-2"
        )

    monkeypatch.setattr(converter_mod, "_g", _boom)

    reg = Registry()

    # FK (Post.author / Post.category), forward-O2O (AuthorProfile.author),
    # self-ref-O2O (PersonWithSpouse.spouse): convert_field_to_djangomodel.
    convert_field_to_djangomodel(Post._meta.get_field("author"), reg, input_flag=None)
    convert_field_to_djangomodel(Post._meta.get_field("category"), reg, input_flag=None)
    convert_field_to_djangomodel(
        AuthorProfile._meta.get_field("author"), reg, input_flag=None
    )
    convert_field_to_djangomodel(
        PersonWithSpouse._meta.get_field("spouse"), reg, input_flag=None
    )

    # reverse-O2O (Author.author_profile): convert_onetoone_field_to_djangomodel.
    rev_o2o_field = next(
        f
        for f in Author._meta.get_fields()
        if getattr(f, "name", None) == "author_profile"
    )
    convert_onetoone_field_to_djangomodel(rev_o2o_field, reg, input_flag=None)

    # PK OUTPUT (Author.id / Post.id): convert_field_to_id.
    convert_field_to_id(Author._meta.get_field("id"), reg, input_flag=None)
    convert_field_to_id(Post._meta.get_field("id"), reg, input_flag=None)

    # Reaching here without AssertionError proves the to-ONE relation OUTPUT path
    # (FK / forward-O2O / reverse-O2O / self-ref-O2O) and the PK OUTPUT path are
    # graphene-free.


@pytest.mark.django_db
def test_pk_output_path_does_not_import_graphene(monkeypatch):
    """``convert_field_to_id`` on OUTPUT (input_flag is None) must not call _g()."""
    import django_graphex.converter as converter_mod
    from django_graphex.converter import _DEAD_SCALAR, convert_field_to_id

    def _boom(*_a, **_k):
        raise AssertionError("PK OUTPUT path called _g() — must be graphene-free")

    monkeypatch.setattr(converter_mod, "_g", _boom)

    pk_field = Post._meta.get_field("id")
    out = convert_field_to_id(pk_field, Registry(), input_flag=None)
    assert out is _DEAD_SCALAR, (
        "the PK on OUTPUT must return the dead-scalar sentinel (the native "
        f"compiler emits id: ID! from model._meta); got {out!r}"
    )


@pytest.mark.django_db
def test_to_one_converters_return_native_marker_on_output():
    """FK / forward-O2O / reverse-O2O converters return a NativeRelationField on
    the native OUTPUT path (never None / the dead-scalar sentinel)."""
    from django_graphex.converter import (
        _DEAD_SCALAR,
        convert_field_to_djangomodel,
        convert_onetoone_field_to_djangomodel,
    )

    registry = Registry()

    fk = convert_field_to_djangomodel(
        Post._meta.get_field("author"), registry, input_flag=None
    )
    fwd_o2o = convert_field_to_djangomodel(
        AuthorProfile._meta.get_field("author"), registry, input_flag=None
    )
    self_o2o = convert_field_to_djangomodel(
        PersonWithSpouse._meta.get_field("spouse"), registry, input_flag=None
    )
    rev_o2o_field = next(
        f
        for f in Author._meta.get_fields()
        if getattr(f, "name", None) == "author_profile"
    )
    rev_o2o = convert_onetoone_field_to_djangomodel(
        rev_o2o_field, registry, input_flag=None
    )

    for label, marker in (
        ("FK", fk),
        ("forward-O2O", fwd_o2o),
        ("self-ref-O2O", self_o2o),
        ("reverse-O2O", rev_o2o),
    ):
        assert isinstance(marker, NativeRelationField), (
            f"{label} OUTPUT must return a NativeRelationField, got {marker!r}"
        )
        assert marker is not _DEAD_SCALAR and marker is not None, (
            f"{label} OUTPUT must NEVER be None / dead-scalar (silent-drop trap)"
        )


# --------------------------------------------------------------------------- #
# (b) SILENT-DROP GUARD — reproduce test_issue52: spouse + reverse-O2O present #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_self_ref_o2o_field_present_in_meta_fields():
    """``PersonWithSpouse.spouse`` (self-ref O2O) stays in ``_meta.fields`` (the
    test_issue52 canary) — the NativeRelationField marker is not dropped."""
    reg = Registry()

    class RelPerson2(DjangoObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = reg
            name = "RelPerson2"

    person_type = RelPerson2
    field_names = list(person_type._meta.fields.keys())
    assert "spouse" in field_names, (
        f"'spouse' (self-ref O2O) must stay in _meta.fields; got {field_names}"
    )
    assert isinstance(person_type._meta.fields["spouse"], NativeRelationField), (
        "the self-ref O2O field must be carried as a NativeRelationField marker"
    )


@pytest.mark.django_db
def test_reverse_o2o_field_present_in_compiled_output_type():
    """The reverse-O2O (``authorProfile``) is PRESENT in the compiled OUTPUT type."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()

    class RelAuthor3(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg
            name = "RelAuthor3"

    class RelAuthorProfile3(DjangoObjectType):
        class Meta:
            model = AuthorProfile
            registry = reg
            name = "RelAuthorProfile3"

    compile_all_outputs()

    compiled = RelAuthor3._meta.graphql_output_type
    assert compiled is not None
    assert "authorProfile" in compiled.fields, (
        "reverse-O2O 'authorProfile' must be present in the compiled output "
        f"type; got {list(compiled.fields)}"
    )


@pytest.mark.django_db
def test_fk_and_self_ref_present_in_compiled_output_type():
    """FK (``author``) and self-ref-O2O (``spouse``) are PRESENT in compiled OUTPUT."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()

    class RelAuthor4(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg
            name = "RelAuthor4"

    class RelCategory4(DjangoObjectType):
        class Meta:
            model = Category
            registry = reg
            name = "RelCategory4"

    class RelPost4(DjangoObjectType):
        class Meta:
            model = Post
            registry = reg
            name = "RelPost4"

    class RelPerson4(DjangoObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = reg
            name = "RelPerson4"

    compile_all_outputs()

    post_compiled = RelPost4._meta.graphql_output_type
    person_compiled = RelPerson4._meta.graphql_output_type
    assert "author" in post_compiled.fields
    assert "category" in post_compiled.fields
    assert "spouse" in person_compiled.fields


# --------------------------------------------------------------------------- #
# (c) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to HEAD.    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_seed_native_sdl_byte_identical_to_head_baseline():
    """The full seed schema's native SDL must be byte-identical to the HEAD
    (pre-S-rel-2) baseline — S-rel-2 is SDL-NEUTRAL."""
    from tests.native._sdl_parity_seed import render_native_sdl

    sdl = render_native_sdl()
    assert len(sdl) == _HEAD_SEED_SDL_LEN, (
        f"seed SDL length changed: {len(sdl)} != {_HEAD_SEED_SDL_LEN} "
        "(S-rel-2 must be SDL-neutral)"
    )
    digest = hashlib.sha256(sdl.encode()).hexdigest()
    assert digest == _HEAD_SEED_SDL_SHA256, (
        "seed SDL changed (not byte-identical to the HEAD baseline) — S-rel-2 "
        f"must be SDL-neutral.\nGot SHA256 {digest}, expected {_HEAD_SEED_SDL_SHA256}"
    )


@pytest.mark.django_db
def test_to_one_relation_shapes_unchanged_in_seed_sdl():
    """The to-ONE relation field shapes are unchanged in the seed SDL."""
    from tests.native._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.native.conftest import normalize_sdl

    sdl = render_native_sdl()
    post = normalize_sdl(extract_type_block(sdl, "PSPost"))
    assert "author: PSAuthor" in post  # FK
    assert "category: PSCategory" in post  # FK

    profile = normalize_sdl(extract_type_block(sdl, "PSAuthorProfile"))
    assert "author: PSAuthor" in profile  # forward O2O

    person = normalize_sdl(extract_type_block(sdl, "PSPerson"))
    assert "spouse: PSPerson" in person  # self-ref O2O

    author = normalize_sdl(extract_type_block(sdl, "PSAuthor"))
    assert "authorProfile: PSAuthorProfile" in author  # reverse O2O


@pytest.mark.django_db
def test_pk_renders_id_nonnull_in_seed_sdl():
    """The PK still renders ``id: ID!`` natively (from model._meta, not the
    converter's now-dead graphene ID descriptor)."""
    from tests.native._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.native.conftest import normalize_sdl

    sdl = render_native_sdl()
    author = normalize_sdl(extract_type_block(sdl, "PSAuthor"))
    assert "id: ID!" in author, "PK must still render id: ID! on the native output"


@pytest.mark.django_db
def test_pk_output_compiler_emits_id_nonnull():
    """The native output compiler emits ``id: ID!`` directly from model._meta."""
    from django_graphex.native.output_compiler import _to_graphql_field

    pk_field = Post._meta.get_field("id")
    out = _to_graphql_field(pk_field, Registry())
    assert "id" in out
    gql_type = out["id"].type
    assert isinstance(gql_type, GraphQLNonNull)
    assert gql_type.of_type is GraphQLID


# --------------------------------------------------------------------------- #
# (d) _yank_fields keeps a NativeRelationField (not dropped to the continue).  #
# --------------------------------------------------------------------------- #
def test_yank_fields_keeps_native_relation_field():
    """``_yank_fields`` keeps a ``NativeRelationField`` AS-IS in its native-
    currency branch (it subclasses ``NativeMountedField``)."""
    from django_graphex.types import _yank_fields

    marker = NativeRelationField(related_model=Author)
    assert isinstance(marker, NativeMountedField)

    out = _yank_fields({"author": marker}, _as=NativeMountedField)
    assert "author" in out, "_yank_fields dropped the NativeRelationField"
    assert out["author"] is marker, "the marker must be kept AS-IS (not re-mounted)"


def test_native_relation_field_carries_creation_counter():
    """The marker carries a monotonic ``creation_counter`` (SDL-order parity)."""
    a = NativeRelationField(related_model=Author)
    b = NativeRelationField(related_model=Post)
    assert isinstance(a.creation_counter, int)
    assert b.creation_counter > a.creation_counter, (
        "creation counters must be monotonically increasing (declaration order)"
    )
    # explicit-counter path (re-mount parity)
    c = NativeRelationField(related_model=Author, _creation_counter=42)
    assert c.creation_counter == 42
