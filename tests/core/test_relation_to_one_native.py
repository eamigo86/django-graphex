"""S-rel-2 — native to-ONE relation OUTPUT + PK scalar off graphene.

The native OUTPUT type for a model is compiled ENTIRELY from
"model._meta.get_fields()":

* FK / forward-O2O ......... "output_compiler._to_graphql_field" (to-ONE arm);
* reverse-O2O .............. "types._compile_reverse_o2o_fields";
* PK "id: ID!" ........... "output_compiler._to_graphql_field" (scalar arm,
                            "AutoField -> GraphQLID" + "GraphQLNonNull").

The converter historically ALSO emitted a graphene "Dynamic" for every to-ONE
relation ("convert_field_to_djangomodel" / "convert_onetoone_field_to_djangomodel")
and a graphene "ID" for the PK ("convert_field_to_id"). Those descriptors are
NEVER read on the native output path (built-then-discarded), yet BUILDING them
imports graphene ("converter._g()") — pinning graphene for the process lifetime.

S-rel-2 makes the native OUTPUT path graphene-free for to-ONE relations and the
PK scalar:

* the PK on OUTPUT returns the dead-scalar sentinel (omitted by
  "construct_fields"); the native compiler still emits "id: ID!";
* FK / forward-O2O / reverse-O2O on OUTPUT return a graphene-free
  "NativeRelationField" presence/ordering marker (kept by "_yank_fields" in
  its native-currency branch, carrying the SAME "creation_counter" so SDL
  field order is preserved) — NEVER "None" / the dead-scalar sentinel (the
  test_issue52 self-ref-O2O silent-drop trap).

This slice is IMPORT-REMOVAL and SDL-NEUTRAL: the native SDL is byte-identical
before and after. The INPUT path stays on graphene until S-input-5.

Test groups:
* (a) IMPORT-REMOVAL — building the OUTPUT type for FK + forward-O2O +
  reverse-O2O + self-ref-O2O does NOT call "converter._g()" (monkeypatched to
  raise); the PK OUTPUT path likewise never calls "_g()".
* (b) SILENT-DROP GUARD — the self-ref O2O ("spouse") and the reverse-O2O
  ("authorProfile") fields are PRESENT in the compiled output type's fields
  (the test_issue52 canary, reproduced).
* (c) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to the
  HEAD baseline (a golden SHA256 captured pre-change), and the per-aspect
  to-ONE relation shapes are unchanged.
* (d) "_yank_fields" keeps a "NativeRelationField" (does not drop it to the
  final "continue").
"""

from __future__ import annotations

import hashlib

import pytest
from graphql import GraphQLID, GraphQLNonNull

from django_graphex.core.descriptors import NativeMountedField, NativeRelationField
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType
from tests.models import Author, AuthorProfile, Category, PersonWithSpouse, Post

# --------------------------------------------------------------------------- #
# The native seed-schema SDL fingerprint. Originally captured from a clean      #
# ``git worktree HEAD`` checkout via ``render_native_sdl`` BEFORE the           #
# import-removal change (S-rel-2 byte-level SDL-neutral guard).                 #
#                                                                               #
# Audit rank 6 (intentional, NON-neutral): the old SDL emitted a silent         #
# ``GraphQLString`` for any to-ONE relation whose target was unregistered at    #
# thunk-eval time. That fallback masked two real renderings: ``Post.category``  #
# now resolves to ``PSCategory`` (its registered object type) and              #
# ``OptNote.content_type`` (FK to Django's unregistered ``ContentType``) is now #
# DROPPED with a logged warning instead of leaking as ``String``. The golden    #
# hash/len were re-baselined to the corrected SDL.                              #
# --------------------------------------------------------------------------- #
_HEAD_SEED_SDL_SHA256 = (
    "a41675776f746c960f75d841cad8c9b6c10cdc792ac29e901b1906c9e0c208e9"
)
_HEAD_SEED_SDL_LEN = 4618


# NOTE: ``DjangoObjectType`` uses a pydantic metaclass that requires a
# class-statement ``Meta`` (a dynamically attached ``type(...)`` namespace lacks
# ``__module__`` and trips pydantic's ``inspect_namespace``). The seed schema
# documents the same constraint. So each test defines its types with explicit
# ``class`` statements.


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — the to-ONE relation + PK OUTPUT paths never call _g().  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_pk_output_path_returns_dead_scalar() -> None:
    """Ships broken if "convert_field_to_id" on OUTPUT (input_flag is None)
    stops returning the dead-scalar sentinel (graphene-free).

    S-del-backend-11: the converter no longer has a "_g()" graphene accessor to
    monkeypatch — the to-ONE relation + PK OUTPUT paths are structurally
    graphene-free (the whole graphene backend was deleted). This asserts the
    behavioral result: the PK OUTPUT converter returns "_DEAD_SCALAR" (the
    native compiler emits "id: ID!" from "model._meta").
    """
    from django_graphex.converter import _DEAD_SCALAR, convert_field_to_id

    pk_field = Post._meta.get_field("id")
    out = convert_field_to_id(pk_field, Registry(), input_flag=None)
    assert out is _DEAD_SCALAR, (
        "the PK on OUTPUT must return the dead-scalar sentinel (the native "
        f"compiler emits id: ID! from model._meta); got {out!r}"
    )


@pytest.mark.django_db
def test_to_one_converters_return_native_marker_on_output() -> None:
    """Ships broken if the FK, forward-O2O, or reverse-O2O converters stop
    returning a NativeRelationField on the native OUTPUT path and instead
    return None or the dead-scalar sentinel.
    """
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
def test_self_ref_o2o_field_present_in_meta_fields() -> None:
    """Ships broken if "PersonWithSpouse.spouse" (self-ref O2O) stops staying
    in "_meta.fields" (the test_issue52 canary) because its NativeRelationField
    marker got dropped.
    """
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
def test_reverse_o2o_field_present_in_compiled_output_type() -> None:
    """Ships broken if the reverse-O2O ("authorProfile") field is silently
    dropped from the compiled OUTPUT type.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs

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
def test_fk_and_self_ref_present_in_compiled_output_type() -> None:
    """Ships broken if the FK ("author") or self-ref-O2O ("spouse") field is
    silently dropped from the compiled OUTPUT type.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs

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
def test_seed_native_sdl_byte_identical_to_head_baseline() -> None:
    """Ships broken if the full seed schema's native SDL stops being
    byte-identical to the HEAD (pre-S-rel-2) baseline — S-rel-2 must be
    SDL-NEUTRAL.
    """
    from tests.core._sdl_parity_seed import render_native_sdl

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
def test_to_one_relation_shapes_unchanged_in_seed_sdl() -> None:
    """Ships broken if any to-ONE relation field shape changes in the seed
    SDL.
    """
    from tests.core._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.core.conftest import normalize_sdl

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
def test_pk_renders_id_nonnull_in_seed_sdl() -> None:
    """Ships broken if the PK stops rendering "id: ID!" natively (from
    model._meta, not the converter's now-dead graphene ID descriptor).
    """
    from tests.core._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.core.conftest import normalize_sdl

    sdl = render_native_sdl()
    author = normalize_sdl(extract_type_block(sdl, "PSAuthor"))
    assert "id: ID!" in author, "PK must still render id: ID! on the native output"


@pytest.mark.django_db
def test_pk_output_compiler_emits_id_nonnull() -> None:
    """Ships broken if the native output compiler stops emitting "id: ID!"
    directly from model._meta.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    pk_field = Post._meta.get_field("id")
    out = _to_graphql_field(pk_field, Registry())
    assert "id" in out
    gql_type = out["id"].type
    assert isinstance(gql_type, GraphQLNonNull)
    assert gql_type.of_type is GraphQLID


# --------------------------------------------------------------------------- #
# (d) _yank_fields keeps a NativeRelationField (not dropped to the continue).  #
# --------------------------------------------------------------------------- #
def test_yank_fields_keeps_native_relation_field() -> None:
    """Ships broken if "_yank_fields" stops keeping a "NativeRelationField"
    AS-IS in its native-currency branch (it subclasses "NativeMountedField").
    """
    from django_graphex.types import _yank_fields

    marker = NativeRelationField(related_model=Author)
    assert isinstance(marker, NativeMountedField)

    out = _yank_fields({"author": marker}, _as=NativeMountedField)
    assert "author" in out, "_yank_fields dropped the NativeRelationField"
    assert out["author"] is marker, "the marker must be kept AS-IS (not re-mounted)"


def test_native_relation_field_carries_creation_counter() -> None:
    """Ships broken if the marker stops carrying a monotonic
    "creation_counter", breaking SDL-order parity.
    """
    a = NativeRelationField(related_model=Author)
    b = NativeRelationField(related_model=Post)
    assert isinstance(a.creation_counter, int)
    assert b.creation_counter > a.creation_counter, (
        "creation counters must be monotonically increasing (declaration order)"
    )
    # explicit-counter path (re-mount parity)
    c = NativeRelationField(related_model=Author, _creation_counter=42)
    assert c.creation_counter == 42
