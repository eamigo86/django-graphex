"""item-b B5 — lazy-fork: two DjangoGraphQLSchema over the SAME model coexist.

THE CRUX (~70% of item-b's risk). Today there is EXACTLY ONE
``GraphQLObjectType`` per ``DjangoObjectType`` / ``DjangoListObjectType`` CLASS,
created at class-def and pinned on ``_meta.graphql_output_type``, with relation
thunks bound to the SINGLE process-global shared output registry. That 1:1
assumption means two schemas over the same model (e.g. two apps re-declaring an
``ArticleType`` in distinct registries) cannot coexist in one process: the global
last-wins slot makes two DISTINCT same-named instances reachable in one schema ->
graphql-core raises "Schema must contain uniquely named types".

B5 splits "create the per-class instance" from "register into a registry":
- the DEFAULT pair reuses the class-def instance VERBATIM (byte-identical SDL +
  behavior — the 1:1 invariant holds for the common single-schema case);
- a DISTINCT (non-default) ``SchemaRegistries`` pair runs
  ``compile_outputs_into(pair)`` to FORK pair-local ``GraphQLObjectType`` /
  list-container instances bound to THAT pair, so two schemas yield two distinct
  same-named instances with NO collision.

GATE (this file): build TWO ``DjangoGraphQLSchema`` over the SAME model with
DISTINCT registry-pairs in one process ->
1. BOTH build with NO "uniquely named types" error;
2. each schema's type for the model is a DISTINCT instance;
3. a query against each resolves correctly, including a relation field.

Run: .venv/bin/python -m pytest -q \
    tests/native/test_schema_lazy_fork.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest


@pytest.fixture(autouse=True)
def _isolate_global_registries():
    """Snapshot + restore the process-global output registries around each test.

    These tests intentionally declare THROWAWAY ``DjangoObjectType`` /
    ``DjangoListObjectType`` subclasses (in custom registries) to build forked
    schemas. A ``DjangoObjectType`` class-def writes its instance into the
    process-global shared output registry (last-wins) and appends to the global
    ``_gdx_output_registry`` app-ready compile list. Without cleanup these
    throwaway types would leak into LATER tests' default-pair schema builds and
    cause spurious cross-test duplicate-name collisions (the #1590 global
    contamination at full-suite scale). Snapshot the global state before the test
    and restore it after, so this file is a good cross-test citizen — it does NOT
    weaken any production guarantee, only its own test hygiene.
    """
    from django_graphex.native.base import (
        _gdx_output_registry,
        get_shared_output_registry,
    )

    shared = get_shared_output_registry()
    entries_before = list(_gdx_output_registry)
    compiled_before = dict(shared._compiled)

    try:
        yield
    finally:
        _gdx_output_registry[:] = entries_before
        shared._compiled.clear()
        shared._compiled.update(compiled_before)


# =========================================================================== #
# Helpers                                                                      #
# =========================================================================== #
def _build_schema_over_post(*, type_name_author: str, type_name_post: str):
    """Build a fresh (graphene Registry + forked SchemaRegistries) schema.

    Declares an ``Author`` + ``Post`` (Post has an FK ``author`` -> Author, a
    genuine relation field) in a brand-new graphene ``Registry`` AND a brand-new
    NON-default ``SchemaRegistries`` pair, then builds a ``DjangoGraphQLSchema``
    bound to that pair. Returns ``(schema, AuthorType, PostType, pair)``.

    The SAME ``type_name_*`` are used by BOTH callers, so the two schemas declare
    same-NAMED types over the same MODELS in distinct registries — exactly the
    cross-schema duplicate-name scenario B5 must make coexist.

    v2.0: the root is a native ``django_graphex.ObjectType`` (the graphene-root
    compile capability was removed, decision #1603).
    """
    from django_graphex import ObjectType as _NativeRoot
    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.base import SchemaRegistries
    from django_graphex.native.registry_compiler import NativeOutputRegistry
    from django_graphex.registry import Registry
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Author, Post

    reg = Registry()

    class AuthorType(DjangoObjectType):
        class Meta:
            name = type_name_author
            model = Author
            registry = reg

    class PostType(DjangoObjectType):
        class Meta:
            name = type_name_post
            model = Post
            registry = reg
            only_fields = ("id", "title", "author")

    # A DISTINCT, NON-default SchemaRegistries pair (fresh graphene Registry +
    # fresh NativeOutputRegistry + fresh compile caches). This is the seam B5's
    # lazy-fork rides on: a non-default pair forks pair-local instances.
    pair = SchemaRegistries(
        graphene=reg,
        output=NativeOutputRegistry(),
        plain_object_cache={},
        union_cache={},
        interface_cache={},
        filter_input_cache={},
    )

    class Query(_NativeRoot):
        post = DjangoObjectField(PostType)

    schema = DjangoGraphQLSchema(query=Query, registries=pair)
    return schema, AuthorType, PostType, pair


def _invalidate_relation_caches(schema) -> None:
    """Force every object type's lazy ``fields`` thunk to re-evaluate.

    graphql-core's ``GraphQLObjectType.fields`` is a ``@cached_property``; the
    native root compiler warms it at BUILD time, which masks the cross-schema
    relation leak (a thunk caches the CORRECT instance before a later schema
    overwrites the global slot). Dropping the cache forces the thunk to
    re-resolve relations NOW — surfacing the leak that #1590 hit at query time
    (thunks evaluate AFTER another module/schema overwrote the global registry).

    A forked schema (B5) must STILL resolve relations to its OWN pair after this
    invalidation; only the unforked global-registry architecture leaks.
    """
    for gql_type in list(schema.graphql_schema.type_map.values()):
        if hasattr(gql_type, "__dict__"):
            gql_type.__dict__.pop("fields", None)


# =========================================================================== #
# THE CRUX GATE                                                                #
# =========================================================================== #
@pytest.mark.django_db
def test_two_schemas_same_model_distinct_pairs_both_build_no_collision():
    """Two schemas over the SAME models (same type NAMES) build with NO collision.

    Each schema uses a DISTINCT non-default ``SchemaRegistries`` pair. Before B5,
    the second build (or the first query) raised "Schema must contain uniquely
    named types" because both schemas' relation thunks read the SINGLE global
    shared output registry (last-wins), making two distinct same-named instances
    reachable in one schema.

    TEETH: with the 1:1 class-def instance still global, building schema B then
    reading schema A's type map surfaces the duplicate-name collision.
    """
    schema_a, _author_a, _post_a, _pair_a = _build_schema_over_post(
        type_name_author="ForkAuthorType", type_name_post="ForkPostType"
    )
    schema_b, _author_b, _post_b, _pair_b = _build_schema_over_post(
        type_name_author="ForkAuthorType", type_name_post="ForkPostType"
    )

    # Force schema A's relation thunks to re-resolve NOW — AFTER schema B has
    # registered into the global slot. Without the fork this is exactly when
    # A's ``Post.author`` thunk reaches B's same-named ``Author`` instance,
    # making two distinct same-named types reachable in schema A (the #1590
    # collision). graphql-core's ``validate_schema`` then raises.
    _invalidate_relation_caches(schema_a)
    _invalidate_relation_caches(schema_b)

    from graphql import validate_schema

    # validate_schema raises (or returns errors) on duplicate-named types once
    # the graph is fully walked.
    errors_a = validate_schema(schema_a.graphql_schema)
    errors_b = validate_schema(schema_b.graphql_schema)
    assert not errors_a, errors_a
    assert not errors_b, errors_b

    type_map_a = schema_a.graphql_schema.type_map
    type_map_b = schema_b.graphql_schema.type_map
    assert "ForkPostType" in type_map_a
    assert "ForkAuthorType" in type_map_a
    assert "ForkPostType" in type_map_b
    assert "ForkAuthorType" in type_map_b


@pytest.mark.django_db
def test_two_schemas_yield_distinct_instances_per_model():
    """Each schema's GraphQLObjectType for the model is a DISTINCT instance.

    The whole point of the fork: schema A and schema B must NOT share the same
    ``GraphQLObjectType`` object for the same model — otherwise one schema's
    relation thunk could reach the other schema's instance (R1 leakage).

    TEETH: without forking, both schemas reuse the one class-def instance and the
    ``is not`` identity assertion fails.
    """
    schema_a, _author_a, _post_a, _pair_a = _build_schema_over_post(
        type_name_author="ForkAuthorType2", type_name_post="ForkPostType2"
    )
    schema_b, _author_b, _post_b, _pair_b = _build_schema_over_post(
        type_name_author="ForkAuthorType2", type_name_post="ForkPostType2"
    )

    post_type_a = schema_a.graphql_schema.type_map["ForkPostType2"]
    post_type_b = schema_b.graphql_schema.type_map["ForkPostType2"]
    author_type_a = schema_a.graphql_schema.type_map["ForkAuthorType2"]
    author_type_b = schema_b.graphql_schema.type_map["ForkAuthorType2"]

    assert post_type_a is not post_type_b, (
        "Both schemas reuse the SAME PostType instance — no fork happened."
    )
    assert author_type_a is not author_type_b, (
        "Both schemas reuse the SAME AuthorType instance — no fork happened."
    )

    # R1 leak guard: schema A's ``Post.author`` relation MUST resolve to schema
    # A's Author instance, NOT schema B's — EVEN after a forced re-evaluation
    # post-B-build (the #1590 deferred-thunk leak). The unforked architecture
    # resolves to B's instance here (global last-wins).
    _invalidate_relation_caches(schema_a)
    author_field_type_a = post_type_a.fields["author"].type
    assert author_field_type_a is author_type_a, (
        "R1 LEAK: schema A's Post.author resolved to the WRONG Author instance "
        "(cross-schema leakage from the global registry)."
    )


@pytest.mark.django_db
def test_each_forked_schema_relation_field_resolves_correctly():
    """A query against each forked schema resolves correctly, incl. a relation.

    Seeds a real DB row, runs a query selecting ``post { title author { name } }``
    against BOTH forked schemas, and asserts each returns REAL data with NO
    errors. The ``author`` subfield exercises the relation thunk: it MUST resolve
    to the SAME schema's Author instance (not the other schema's), proving the
    fork wired relation references against the schema's own pair.

    TEETH: a relation thunk that leaked to the other schema's instance, or a
    duplicate-name collision, makes ``result.errors`` non-empty.
    """
    from graphql import graphql_sync

    from tests.models import Author, Post

    author = Author.objects.create(name="Ada Lovelace")
    Post.objects.create(title="GraphQL intro", author=author)

    schema_a, _aa, _pa, _pra = _build_schema_over_post(
        type_name_author="ForkAuthorType3", type_name_post="ForkPostType3"
    )
    schema_b, _ab, _pb, _prb = _build_schema_over_post(
        type_name_author="ForkAuthorType3", type_name_post="ForkPostType3"
    )

    post = Post.objects.get(title="GraphQL intro")
    query = "{ post(id: %d) { title author { name } } }" % post.pk
    # Force re-resolution so a deferred relation thunk does not mask a leak.
    _invalidate_relation_caches(schema_a)
    _invalidate_relation_caches(schema_b)
    for schema in (schema_a, schema_b):
        result = graphql_sync(schema.graphql_schema, query)
        assert result.errors is None, result.errors
        assert result.data is not None
        assert result.data["post"]["title"] == "GraphQL intro"
        assert result.data["post"]["author"]["name"] == "Ada Lovelace"


@pytest.mark.django_db
def test_forked_instance_carries_gdx_meta_for_optimizer():
    """R4: each forked instance carries ``extensions['gdx']`` with the source class.

    The optimizer reads ``info.schema`` + the gdx bridge (``graphene_type``,
    ``model``) on each type. A forked instance MUST copy that gdx meta or the
    optimizer is silently inert on forked schemas.

    TEETH: a forked GraphQLObjectType built without copying gdx meta has no
    ``extensions['gdx']`` (or a ``graphene_type`` of ``None``), failing this.
    """
    schema, _author, post_cls, _pair = _build_schema_over_post(
        type_name_author="ForkAuthorType4", type_name_post="ForkPostType4"
    )

    post_type = schema.graphql_schema.type_map["ForkPostType4"]
    gdx = (post_type.extensions or {}).get("gdx")
    assert gdx is not None, "Forked instance is missing extensions['gdx']."
    # graphene_type back-reference recovers the source DjangoObjectType subclass.
    assert gdx._meta.graphene_type is post_cls
    assert gdx._meta.model is post_cls._meta.model


# =========================================================================== #
# R1 — build-invariant check detects cross-schema leakage                      #
# =========================================================================== #
@pytest.mark.django_db
def test_build_invariant_passes_on_clean_forked_schema():
    """The B5 build-invariant check passes for a correctly forked schema.

    After building a NON-default schema, ``assert_schema_pair_isolation`` walks
    the reachable object types and asserts every one belongs to THIS schema's
    pair (its forked instance), raising on cross-schema leakage. A clean fork
    must pass.

    TEETH: if the invariant check were never wired (or always raised), this call
    raises on a valid schema.
    """
    from django_graphex.native.registry_compiler import (
        assert_schema_pair_isolation,
    )

    schema, _author, _post, pair = _build_schema_over_post(
        type_name_author="ForkAuthorType5", type_name_post="ForkPostType5"
    )
    # Must not raise — the schema's object types all belong to this pair.
    assert_schema_pair_isolation(schema.graphql_schema, pair)


@pytest.mark.django_db
def test_build_invariant_raises_on_cross_schema_leak():
    """The invariant check RAISES when a type does not belong to the pair.

    Construct schema A and pair B (a DIFFERENT pair). Asserting schema A's graph
    against pair B must raise: A's forked instances are NOT in B's
    ``output_instances`` map, so the isolation check detects the mismatch — this
    is the detection mechanism for the crux's silent-wrong-instance risk (R1).

    TEETH: an invariant that does not actually compare instance identity against
    the pair would not raise here.
    """
    from django_graphex.native.registry_compiler import (
        BuildError,
        assert_schema_pair_isolation,
    )

    schema_a, _aa, _pa, _pair_a = _build_schema_over_post(
        type_name_author="ForkAuthorType6", type_name_post="ForkPostType6"
    )
    _schema_b, _ab, _pb, pair_b = _build_schema_over_post(
        type_name_author="ForkAuthorType6", type_name_post="ForkPostType6"
    )

    with pytest.raises(BuildError):
        assert_schema_pair_isolation(schema_a.graphql_schema, pair_b)


# =========================================================================== #
# Default-pair byte-identical guard (the NON-NEGOTIABLE)                        #
# =========================================================================== #
@pytest.mark.django_db
def test_default_pair_reuses_class_def_instance_verbatim():
    """The DEFAULT-pair schema reuses the class-def ``_meta`` instance VERBATIM.

    A schema built with NO ``registries=`` (the default pair) must NOT fork: its
    type for the model IS the canonical class-def ``_meta.graphql_output_type``
    instance — proving the single/default-schema path is byte-identical (no new
    instance created).

    TEETH: if B5 forked unconditionally (even for the default pair), the schema's
    type would be a NEW instance, not the class-def one, and this identity check
    fails — catching an accidental byte-identical regression.

    v2.0: the root is a native ``django_graphex.ObjectType``.
    """
    from django_graphex import ObjectType as _NativeRoot
    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _DefaultPairCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _DefaultPairQuery(_NativeRoot):
        category = DjangoObjectField(_DefaultPairCatType)

    schema = DjangoGraphQLSchema(query=_DefaultPairQuery)
    schema_type = schema.graphql_schema.type_map["_DefaultPairCatType"]
    canonical = _DefaultPairCatType._meta.graphql_output_type
    assert schema_type is canonical, (
        "Default-pair schema did NOT reuse the class-def instance — the "
        "byte-identical single-schema guarantee is broken."
    )
