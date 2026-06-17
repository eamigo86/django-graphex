"""S-rel-3 — native to-MANY relation OUTPUT container off graphene.

The native OUTPUT type for a model gets its to-MANY relations as the related
model's ``<Model>ListType`` results/totalCount CONTAINER (NOT a bare ``[Node]``
list). That container is built ENTIRELY natively by
``types._compile_relation_list_fields`` — which reads ``model._meta.get_fields()``
directly, resolves / auto-creates the related ``DjangoListObjectType`` via
``_nested_list_object_field`` -> ``get_or_create_list_object_type`` (reusing the
already-registered base node, so NO ``construct_fields`` -> NO graphene), and
emits the final ``GraphQLField`` via ``schema_compiler._build_list_object_field``.

The converter ALSO historically emitted a graphene ``Dynamic`` for every to-MANY
relation:

* forward ManyToMany ......... ``converter.convert_field_to_list_or_connection``;
* reverse FK (ManyToOneRel) .. ``converter.convert_many_rel_to_djangomodel``;
* reverse M2M (ManyToManyRel)  ``converter.convert_many_rel_to_djangomodel``.

That ``Dynamic`` is built at CLASS-DEFINITION time (``construct_fields``) and is
NEVER read on the native output path (the container is compiled from
``model._meta`` as above) — yet BUILDING it imports graphene (``converter._g()``),
pinning graphene for the process lifetime (ground truth #1607).

S-rel-3 makes the native OUTPUT path graphene-free for to-MANY relations: the
forward-M2M / reverse-FK / reverse-M2M converters return a graphene-free
``NativeRelationField`` presence/ordering marker on the native OUTPUT path
(kept by ``_yank_fields`` in its native-currency branch, carrying the SAME
``creation_counter`` so SDL field order is preserved) — NEVER ``None`` / the
dead-scalar sentinel (the silent-drop trap). The container itself is unchanged
(it was already native), so the SDL is byte-identical.

SCOPE (carefully bounded):
* The forward ``GenericRelation`` list (``convert_generic_relation_to_object_list``)
  and the reverse ``GenericRel`` arm of ``convert_many_rel_to_djangomodel`` stay
  on graphene ``Dynamic`` — they retire in S-rel-4 (GFK flat + GenericRelation
  list). This slice touches ONLY M2M / reverse-FK / reverse-M2M.
* The INPUT path is unchanged (it stays on graphene until S-input-5): the marker
  is OUTPUT-only.

Test groups:
* (a) IMPORT-REMOVAL — building the OUTPUT type for a model with forward M2M +
  reverse FK + reverse M2M does NOT call ``converter._g()`` (monkeypatched to
  raise); the nested-list / list-type registry/factory path likewise never calls
  ``_g()`` for an already-registered node.
* (b) CONTAINER SHAPE — each to-MANY field is the related ``<Model>ListType``
  results/totalCount CONTAINER (a native ``GraphQLObjectType`` keyed in the
  registry), NOT a bare ``[Node]`` list.
* (c) SILENT-DROP GUARD — every to-MANY field (tags / coAuthors / comments /
  posts / coauthoredPosts) is PRESENT in the compiled output type.
* (d) SDL-NEUTRAL — the full seed schema's native SDL is byte-identical to the
  HEAD (pre-S-rel-3) baseline.
"""
from __future__ import annotations

import hashlib

import pytest
from graphql import GraphQLObjectType

from django_graphex import DjangoObjectType
from django_graphex.native.descriptors import NativeMountedField, NativeRelationField
from django_graphex.registry import Registry
from tests.models import Author, Comment, Post, Tag

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# The HEAD (pre-S-rel-3) native seed-schema SDL fingerprint. Captured via      #
# ``render_native_sdl`` BEFORE the import-removal change (identical to the     #
# S-rel-2 baseline — both slices are SDL-neutral). S-rel-3 must keep the SDL   #
# byte-identical, so this golden hash is the byte-level SDL-neutral guard.     #
# --------------------------------------------------------------------------- #
_HEAD_SEED_SDL_SHA256 = (
    "b3165b721f46e256f698b634b80eb1e027f8f50f0623ba7803a418b9485ce478"
)
_HEAD_SEED_SDL_LEN = 4659


def _build_post_graph(reg: Registry) -> tuple[type, type, type, type]:
    """Define the Author/Tag/Comment/Post output types in *reg*.

    Post carries forward M2M (``tags`` -> Tag, ``co_authors`` -> Author),
    reverse FK (``comments`` <- Comment), and is the target of reverse M2M
    (``Tag.posts`` / ``Author.coauthored_posts``). Returns the four types.
    """

    class RelManyAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg
            name = "RelManyAuthor"

    class RelManyTag(DjangoObjectType):
        class Meta:
            model = Tag
            registry = reg
            name = "RelManyTag"

    class RelManyComment(DjangoObjectType):
        class Meta:
            model = Comment
            registry = reg
            name = "RelManyComment"

    class RelManyPost(DjangoObjectType):
        class Meta:
            model = Post
            registry = reg
            name = "RelManyPost"

    return RelManyAuthor, RelManyTag, RelManyComment, RelManyPost


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — the to-MANY relation OUTPUT converters never call _g(). #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_to_many_output_converters_do_not_import_graphene(monkeypatch):
    """The to-MANY relation OUTPUT converters (forward M2M + reverse FK + reverse
    M2M) must NOT fire ``converter._g()`` (i.e. must not import graphene).

    Exercised DIRECTLY on the converters (not via a full class build) so the
    assertion is precise. The forward ``GenericRelation`` / reverse ``GenericRel``
    arms are OUT of S-rel-3 scope (S-rel-4), so they are not exercised here.
    """
    import django_graphex.converter as converter_mod
    from django_graphex.converter import (
        convert_field_to_list_or_connection,
        convert_many_rel_to_djangomodel,
    )

    def _boom(*_a, **_k):
        raise AssertionError(
            "converter._g() was called from a to-MANY relation OUTPUT converter "
            "— that path must be graphene-free in S-rel-3"
        )

    monkeypatch.setattr(converter_mod, "_g", _boom)

    reg = Registry()

    # forward M2M: Post.tags -> Tag, Post.co_authors -> Author.
    convert_field_to_list_or_connection(
        Post._meta.get_field("tags"), reg, input_flag=None
    )
    convert_field_to_list_or_connection(
        Post._meta.get_field("co_authors"), reg, input_flag=None
    )

    # reverse FK (ManyToOneRel): Post.comments <- Comment, Author.posts <- Post.
    rev_fk = next(
        f for f in Post._meta.get_fields() if getattr(f, "name", None) == "comments"
    )
    convert_many_rel_to_djangomodel(rev_fk, reg, input_flag=None)
    author_rev_fk = next(
        f for f in Author._meta.get_fields() if getattr(f, "name", None) == "posts"
    )
    convert_many_rel_to_djangomodel(author_rev_fk, reg, input_flag=None)

    # reverse M2M (ManyToManyRel): Tag.posts <- Post, Author.coauthored_posts.
    tag_rev_m2m = next(
        f for f in Tag._meta.get_fields() if getattr(f, "name", None) == "posts"
    )
    convert_many_rel_to_djangomodel(tag_rev_m2m, reg, input_flag=None)
    author_rev_m2m = next(
        f
        for f in Author._meta.get_fields()
        if getattr(f, "name", None) == "coauthored_posts"
    )
    convert_many_rel_to_djangomodel(author_rev_m2m, reg, input_flag=None)

    # Reaching here without AssertionError proves every to-MANY relation OUTPUT
    # converter (forward M2M / reverse FK / reverse M2M) is graphene-free.


@pytest.mark.django_db
def test_to_many_converters_return_native_marker_on_output():
    """Forward-M2M / reverse-FK / reverse-M2M converters return a
    ``NativeRelationField`` on the native OUTPUT path (never None / dead-scalar)."""
    from django_graphex.converter import (
        _DEAD_SCALAR,
        convert_field_to_list_or_connection,
        convert_many_rel_to_djangomodel,
    )

    reg = Registry()

    m2m = convert_field_to_list_or_connection(
        Post._meta.get_field("tags"), reg, input_flag=None
    )
    rev_fk_field = next(
        f for f in Post._meta.get_fields() if getattr(f, "name", None) == "comments"
    )
    rev_fk = convert_many_rel_to_djangomodel(rev_fk_field, reg, input_flag=None)
    rev_m2m_field = next(
        f for f in Tag._meta.get_fields() if getattr(f, "name", None) == "posts"
    )
    rev_m2m = convert_many_rel_to_djangomodel(rev_m2m_field, reg, input_flag=None)

    for label, marker in (
        ("forward-M2M", m2m),
        ("reverse-FK", rev_fk),
        ("reverse-M2M", rev_m2m),
    ):
        assert isinstance(marker, NativeRelationField), (
            f"{label} OUTPUT must return a NativeRelationField, got {marker!r}"
        )
        assert marker is not _DEAD_SCALAR and marker is not None, (
            f"{label} OUTPUT must NEVER be None / dead-scalar (silent-drop trap)"
        )


@pytest.mark.django_db
def test_nested_list_container_path_is_graphene_free(monkeypatch):
    """The list-container path (``_nested_list_object_field`` ->
    ``get_or_create_list_object_type`` -> ``factory_type`` ->
    ``_build_list_object_field``) does NOT fire ``_g()`` for an already-registered
    node — proving the to-MANY OUTPUT CONTAINER is built natively (no graphene
    Registry/factory firing)."""
    import django_graphex.converter as converter_mod

    reg = Registry()
    _build_post_graph(reg)  # registers Tag (and its node) in reg

    def _boom(*_a, **_k):
        raise AssertionError(
            "converter._g() fired in the native to-MANY container path "
            "(_nested_list_object_field / get_or_create_list_object_type / "
            "factory_type) — that path must be graphene-free in S-rel-3"
        )

    monkeypatch.setattr(converter_mod, "_g", _boom)

    from django_graphex.converter import _nested_list_object_field
    from django_graphex.types import get_or_create_list_object_type

    nested = _nested_list_object_field(
        Post._meta.get_field("tags"), Tag, reg, accessor="tags"
    )
    assert nested is not None, "nested list field must build for a registered node"

    list_type = get_or_create_list_object_type(Tag, reg)
    assert list_type is not None, "the <Model>ListType must resolve without graphene"


# --------------------------------------------------------------------------- #
# (b) CONTAINER SHAPE — each to-MANY field is the <Model>ListType container.   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_to_many_fields_are_list_containers_not_bare_lists():
    """Each to-MANY field is the related ``<Model>ListType`` results/totalCount
    CONTAINER (a native ``GraphQLObjectType``), NOT a bare ``[Node]`` list."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()
    _author, _tag, _comment, post_cls = _build_post_graph(reg)
    compile_all_outputs()

    post_compiled = post_cls._meta.graphql_output_type
    assert post_compiled is not None

    # The list-container name derives from the MODEL name (factory_type 'list':
    # ``<Model>_List_Type``), not the node type's ``Meta.name``.
    expected = {
        "tags": "TagListType",
        "coAuthors": "AuthorListType",
        "comments": "CommentListType",
    }
    for field_name, container_name in expected.items():
        assert field_name in post_compiled.fields, (
            f"{field_name} must be present in the compiled Post output type; "
            f"got {list(post_compiled.fields)}"
        )
        ftype = post_compiled.fields[field_name].type
        assert isinstance(ftype, GraphQLObjectType), (
            f"{field_name} must be a list CONTAINER (GraphQLObjectType), not a "
            f"bare [Node] list; got {ftype!r}"
        )
        assert ftype.name == container_name, (
            f"{field_name} container must be {container_name}; got {ftype.name}"
        )
        container_fields = set(ftype.fields)
        assert {"results", "totalCount"} <= container_fields, (
            f"{field_name} container must expose results/totalCount; got "
            f"{sorted(container_fields)}"
        )


@pytest.mark.django_db
def test_list_container_keyed_in_registry():
    """The to-MANY ``<Model>ListType`` container is a native GraphQLObjectType
    keyed in the output registry (resolved by the schema, not re-created)."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()
    _author, tag_cls, _comment, post_cls = _build_post_graph(reg)
    compile_all_outputs()

    # Force the Post output thunk to resolve so the nested to-MANY containers are
    # built (the ``<Model>ListType`` is auto-created + registered lazily when the
    # relation field type is resolved by ``_compile_relation_list_fields``).
    _ = post_cls._meta.graphql_output_type.fields["tags"].type

    tag_list_type = reg.get_list_type_for_model(Tag)
    assert tag_list_type is not None, (
        "the Tag <Model>ListType must be registered (so nested to-MANY references "
        "reuse it)"
    )
    compiled = tag_list_type._meta.graphql_output_type
    assert isinstance(compiled, GraphQLObjectType)
    assert compiled.name == "TagListType"


# --------------------------------------------------------------------------- #
# (c) SILENT-DROP GUARD — every to-MANY field present in the compiled output.  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_all_to_many_fields_present_in_compiled_output():
    """Every to-MANY field (forward M2M, reverse FK, reverse M2M) is PRESENT in
    its compiled output type — none is silently dropped."""
    from django_graphex.native.registry_compiler import compile_all_outputs

    reg = Registry()
    author_cls, tag_cls, _comment, post_cls = _build_post_graph(reg)
    compile_all_outputs()

    post_fields = set(post_cls._meta.graphql_output_type.fields)
    assert {"tags", "coAuthors", "comments"} <= post_fields, (
        f"Post to-MANY fields missing; got {sorted(post_fields)}"
    )

    tag_fields = set(tag_cls._meta.graphql_output_type.fields)
    assert "posts" in tag_fields, (  # reverse M2M
        f"Tag reverse-M2M 'posts' missing; got {sorted(tag_fields)}"
    )

    author_fields = set(author_cls._meta.graphql_output_type.fields)
    assert "posts" in author_fields, (  # reverse FK
        f"Author reverse-FK 'posts' missing; got {sorted(author_fields)}"
    )
    assert "coauthoredPosts" in author_fields, (  # reverse M2M
        f"Author reverse-M2M 'coauthoredPosts' missing; got {sorted(author_fields)}"
    )


@pytest.mark.django_db
def test_to_many_marker_present_in_meta_fields():
    """The AUTO-DERIVED to-MANY relation stays in ``_meta.fields`` as a
    ``NativeRelationField`` marker (presence/ordering), kept by ``_yank_fields``."""
    reg = Registry()
    _author, _tag, _comment, post_cls = _build_post_graph(reg)

    fields = post_cls._meta.fields
    for name in ("tags", "co_authors", "comments"):
        assert name in fields, (
            f"to-MANY '{name}' must stay in _meta.fields (presence); "
            f"got {list(fields)}"
        )
        assert isinstance(fields[name], NativeRelationField), (
            f"to-MANY '{name}' must be carried as a NativeRelationField marker; "
            f"got {fields[name]!r}"
        )


# --------------------------------------------------------------------------- #
# (d) SDL-NEUTRAL — the seed schema's native SDL is byte-identical to HEAD.    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_seed_native_sdl_byte_identical_to_head_baseline():
    """The full seed schema's native SDL must be byte-identical to the HEAD
    (pre-S-rel-3) baseline — S-rel-3 is SDL-NEUTRAL."""
    from tests.native._sdl_parity_seed import render_native_sdl

    sdl = render_native_sdl()
    assert len(sdl) == _HEAD_SEED_SDL_LEN, (
        f"seed SDL length changed: {len(sdl)} != {_HEAD_SEED_SDL_LEN} "
        "(S-rel-3 must be SDL-neutral)"
    )
    digest = hashlib.sha256(sdl.encode()).hexdigest()
    assert digest == _HEAD_SEED_SDL_SHA256, (
        "seed SDL changed (not byte-identical to the HEAD baseline) — S-rel-3 "
        f"must be SDL-neutral.\nGot SHA256 {digest}, expected {_HEAD_SEED_SDL_SHA256}"
    )


@pytest.mark.django_db
def test_to_many_relation_shapes_unchanged_in_seed_sdl():
    """The to-MANY relation field shapes are unchanged in the seed SDL."""
    from tests.native._sdl_parity_seed import extract_type_block, render_native_sdl
    from tests.native.conftest import normalize_sdl

    sdl = render_native_sdl()
    post = normalize_sdl(extract_type_block(sdl, "PSPost"))
    assert "tags: TagListType" in post  # forward M2M container
    assert "coAuthors: AuthorListType" in post  # forward M2M (self-ref Author)
    assert "comments: CommentListType" in post  # reverse FK container

    tag = normalize_sdl(extract_type_block(sdl, "PSTag"))
    assert "posts: PostListType" in tag  # reverse M2M container

    author = normalize_sdl(extract_type_block(sdl, "PSAuthor"))
    assert "coauthoredPosts: PostListType" in author  # reverse M2M container


# --------------------------------------------------------------------------- #
# (e) GenericRel / GenericRelation stay on graphene (S-rel-4 scope guard).     #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_generic_relation_list_still_graphene_dynamic():
    """The forward ``GenericRelation`` list converter stays on graphene Dynamic in
    S-rel-3 (it retires in S-rel-4). This pins the slice boundary."""
    import graphene

    from django_graphex.converter import convert_generic_relation_to_object_list
    from tests.test_optimizer_coverage import Profile

    reg = Registry()
    notes_field = Profile._meta.get_field("notes")  # GenericRelation
    out = convert_generic_relation_to_object_list(notes_field, reg, input_flag=None)
    assert isinstance(out, graphene.Dynamic), (
        "forward GenericRelation list must STILL be a graphene Dynamic in S-rel-3 "
        f"(retires in S-rel-4); got {out!r}"
    )


# --------------------------------------------------------------------------- #
# (f) _yank_fields keeps a to-MANY NativeRelationField (not dropped).          #
# --------------------------------------------------------------------------- #
def test_yank_fields_keeps_to_many_native_relation_field():
    """``_yank_fields`` keeps a to-MANY ``NativeRelationField`` AS-IS in its
    native-currency branch (it subclasses ``NativeMountedField``)."""
    from django_graphex.types import _yank_fields

    marker = NativeRelationField(related_model=Tag)
    assert isinstance(marker, NativeMountedField)

    out = _yank_fields({"tags": marker}, _as=NativeMountedField)
    assert "tags" in out, "_yank_fields dropped the to-MANY NativeRelationField"
    assert out["tags"] is marker, "the marker must be kept AS-IS (not re-mounted)"
