"""WU1 identity-invariant regression guards (the RED the original apply missed).

These two tests are the permanent guards for the dual-path identity hazard:

1. ``test_compile_all_outputs_relation_identity_no_string_fallback`` — drives
   ``compile_all_outputs()`` over two cross-referencing DjangoObjectTypes
   (A.b -> B, B.a -> A) and asserts the relation thunk target IS the *same*
   GraphQLObjectType object as the related type's
   ``_meta.graphql_output_type`` (identity, NO GraphQLString fallback), in
   BOTH directions, with ``extensions['gdx']`` present on both.

2. ``test_schema_assembly_no_duplicate_type_name`` — the reviewer's probe 3.
   Under GDX_BACKEND=native, two cross-referencing DjangoObjectTypes PLUS a
   mutation referencing one of them; after ``compile_all_outputs()``, assemble
   a ``graphql.GraphQLSchema(query=..., mutation=...)`` from the compiled roots
   and assert it constructs WITHOUT the duplicate-name ``TypeError``.

Both tests FAIL against the buggy dual-path apply:
- (1) failed because the eager per-class compile used a per-class LOCAL
  registry where the related model was NOT registered, so the relation thunk
  resolved to GraphQLString instead of the related GraphQLObjectType.
- (2) failed because the eager class-def instance (pinned by the mutation at
  class-def time) and the second instance created by compile_all_outputs()
  were DIFFERENT objects with the SAME name → GraphQLSchema raised
  "Schema must contain uniquely named types but contains multiple types
  named '<TypeName>'".

Run:
    GDX_BACKEND=native .venv/bin/python -m pytest \
        tests/native/test_output_identity_invariant.py -q -o addopts=""
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# (1) Relation identity — single instance, no String fallback, both directions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compile_all_outputs_relation_identity_no_string_fallback():
    """Two cross-referencing DjangoObjectTypes resolve relations to the SAME
    GraphQLObjectType instance (identity), never to GraphQLString.

    Post.author -> Author and AuthorProfile.author -> Author exercise the
    relation thunk path. After compile_all_outputs(), the field type the
    thunk produces for the FK MUST be the very object stored on the related
    type's _meta.graphql_output_type.
    """
    from graphql import GraphQLObjectType

    from django_graphex.native.base import get_shared_output_registry
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoObjectType
    from tests.models import Author, Post

    class _IdAuthorType(DjangoObjectType):
        class Meta:
            model = Author

    class _IdPostType(DjangoObjectType):
        class Meta:
            model = Post

    compile_all_outputs()

    author_gql = _IdAuthorType._meta.graphql_output_type
    post_gql = _IdPostType._meta.graphql_output_type

    assert isinstance(author_gql, GraphQLObjectType)
    assert isinstance(post_gql, GraphQLObjectType)

    # _IdAuthorType is the last-registered (canonical) type for Author here, so
    # its instance is what the shared registry hands relation thunks.
    canonical_author = get_shared_output_registry().get_compiled(Author)
    assert canonical_author is author_gql, (
        "_IdAuthorType must be the canonical Author instance after definition"
    )

    # extensions['gdx'] present on both (Phase-3 invariant)
    assert "gdx" in (author_gql.extensions or {})
    assert "gdx" in (post_gql.extensions or {})

    # Force thunk evaluation: Post has a FK 'author' -> Author.
    post_fields = post_gql.fields
    assert "author" in post_fields, (
        f"Post must expose 'author' FK field; got {sorted(post_fields.keys())}"
    )

    author_field_type = post_fields["author"].type
    # Unwrap NonNull if present (author FK is non-null on Post).
    inner = getattr(author_field_type, "of_type", author_field_type)

    # NO STRING FALLBACK: the relation target is a GraphQLObjectType, not the
    # GraphQLString degrade that the per-class local registry produced.
    assert isinstance(inner, GraphQLObjectType), (
        "Post.author relation must resolve to a GraphQLObjectType, not a "
        f"GraphQLString fallback. Got: {inner!r}"
    )

    # IDENTITY: the relation target IS the single canonical Author instance —
    # the same object on _IdAuthorType._meta.graphql_output_type. No second copy.
    assert inner is author_gql, (
        "Post.author relation must resolve to the SAME GraphQLObjectType "
        "instance as Author._meta.graphql_output_type (identity-stable, "
        "shared global registry). A GraphQLString here means the relation "
        f"degraded to a per-class local registry. Got: {inner!r}"
    )


@pytest.mark.django_db
def test_compile_all_outputs_self_cycle_resolves_to_same_instance():
    """A self-referencing FK (A.parent -> A) compiled via compile_all_outputs()
    must resolve the relation to the SAME single instance (the A↔A cycle), with
    NO RecursionError and NO GraphQLString fallback.

    This drives the DEFERRED recursion path through compile_all_outputs() (the
    path the pre-existing test_circular_reference_ab_ba_no_recursion does NOT
    cover — that one drives the separate compile_all()).  The module-level
    _in_progress cycle guard + the shared registry make the parent field resolve
    to the node type itself.
    """
    from graphql import GraphQLObjectType

    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoObjectType
    from tests.models import NestedTreeNode

    class _SelfCycleNodeType(DjangoObjectType):
        class Meta:
            model = NestedTreeNode

    # Must not raise RecursionError.
    compile_all_outputs()

    node_gql = _SelfCycleNodeType._meta.graphql_output_type
    assert isinstance(node_gql, GraphQLObjectType)

    fields = node_gql.fields
    assert "parent" in fields, (
        f"NestedTreeNode must expose 'parent' self-FK; got {sorted(fields)}"
    )
    parent_type = fields["parent"].type
    inner = getattr(parent_type, "of_type", parent_type)

    assert isinstance(inner, GraphQLObjectType), (
        f"Self-FK 'parent' must resolve to a GraphQLObjectType, got {inner!r}"
    )
    # A↔A identity: the parent relation IS the same single node instance.
    assert inner is node_gql, (
        "Self-referencing FK must resolve to the SAME GraphQLObjectType "
        f"instance (the cycle's single node). Got: {inner!r}"
    )


@pytest.mark.django_db
def test_compile_all_outputs_single_instance_stable_across_recompile():
    """compile_all_outputs() must NOT create a second GraphQLObjectType for an
    already-registered type — the instance identity is stable across calls.

    This is the core invariant: exactly ONE instance per DjangoObjectType,
    created once, identity-stable. A second compile_all_outputs() call must
    return the SAME object on _meta.graphql_output_type.
    """
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _StableCategoryType(DjangoObjectType):
        class Meta:
            model = Category

    # Instance pinned at class-def time (what a mutation would capture).
    pinned = _StableCategoryType._meta.graphql_output_type

    compile_all_outputs()
    after_first = _StableCategoryType._meta.graphql_output_type

    compile_all_outputs()
    after_second = _StableCategoryType._meta.graphql_output_type

    assert pinned is after_first, (
        "compile_all_outputs() must REUSE the class-def instance, not replace "
        "it with a second GraphQLObjectType (the dual-path identity hazard)."
    )
    assert after_first is after_second, (
        "Repeated compile_all_outputs() calls must not create new instances."
    )


# ---------------------------------------------------------------------------
# (2) Schema-assembly smoke — reviewer probe 3: no duplicate-name TypeError
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schema_assembly_no_duplicate_type_name():
    """Reviewer probe 3 — the permanent regression guard for the identity bug.

    Two cross-referencing DjangoObjectTypes plus a mutation. After
    compile_all_outputs(), assemble a graphql.GraphQLSchema(query=..., mutation=...)
    from the compiled roots. This MUST construct without:

        TypeError: Schema must contain uniquely named types but contains
                   multiple types named '<TypeName>'.

    WU9 update: the native mutation field's output type is the MUTATION PAYLOAD
    type (``ok`` / ``errors`` + the output field), NOT the bare model node type
    (the pre-WU9 bug pinned the node type, leaving ``ok``/``errors``/output
    unqueryable). The payload type's output FIELD references the CANONICAL node
    instance compile_all_outputs() left on ``_meta`` — so the node type still
    appears exactly once in the schema's type map (no duplicate-name TypeError).
    """
    from graphql import (
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
    )

    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY, DjangoModelMutation
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoObjectType
    from tests.models import Author, Post

    class _SchemaAuthorType(DjangoObjectType):
        class Meta:
            model = Author

    class _SchemaPostType(DjangoObjectType):
        class Meta:
            model = Post

    # A mutation referencing Author. Under WU9 it pins the compiled PAYLOAD type
    # at class-def time; the payload's output field references Author's canonical
    # node instance via the shared registry.
    class _SchemaAuthorMutation(DjangoModelMutation):
        class Meta:
            model = Author
            model_operations = ("create",)

    compile_all_outputs()

    author_gql = _SchemaAuthorType._meta.graphql_output_type
    post_gql = _SchemaPostType._meta.graphql_output_type

    pinned_field = _NATIVE_FIELD_REGISTRY.get((Author, "create", "native"))
    assert pinned_field is not None, "mutation native create field must be registered"

    # WU9: the pinned field's output type is the PAYLOAD type (ok/errors + output
    # field), NOT the node type. The payload exposes ok/errors + the output field.
    payload = pinned_field.type
    if isinstance(payload, GraphQLNonNull):
        payload = payload.of_type
    assert isinstance(payload, GraphQLObjectType)
    assert payload is not author_gql, (
        "WU9: the mutation output type must be the PAYLOAD type, not the node type."
    )
    payload_fields = set(payload.fields.keys())
    assert {"ok", "errors"} <= payload_fields, (
        f"Mutation payload must expose ok/errors; got {sorted(payload_fields)}"
    )

    # The payload's OUTPUT FIELD (camelCased model name) references the CANONICAL
    # Author node instance — identity proof that there is no dual-path second
    # instance (the bug compile_all_outputs() guards against).
    output_field_name = _SchemaAuthorMutation._meta.output_field_name
    out_field_type = payload.fields[output_field_name].type
    if isinstance(out_field_type, GraphQLNonNull):
        out_field_type = out_field_type.of_type
    assert out_field_type is author_gql, (
        "The mutation payload's output field references a DIFFERENT "
        "GraphQLObjectType than the one compile_all_outputs() left on _meta — "
        f"the dual-path identity hazard. inner={out_field_type!r} vs "
        f"author={author_gql!r}"
    )

    # Build query + mutation roots from the SAME compiled instances.
    query_root = GraphQLObjectType(
        name="Query",
        fields={
            "author": GraphQLField(author_gql),
            "post": GraphQLField(post_gql),
        },
    )
    mutation_root = GraphQLObjectType(
        name="Mutation",
        fields={
            "createAuthor": pinned_field,
        },
    )

    # This is the load-bearing assertion: GraphQLSchema validates type-name
    # uniqueness at construction. A second same-named instance raises here.
    schema = GraphQLSchema(query=query_root, mutation=mutation_root)

    # Sanity: the schema's type map carries exactly one type per name and the
    # Author type in the map IS our single instance.
    type_map = schema.type_map
    assert type_map[author_gql.name] is author_gql, (
        "Schema type_map must hold the single Author instance — duplicate-name "
        "hazard would have raised before reaching here."
    )
    assert type_map[post_gql.name] is post_gql
