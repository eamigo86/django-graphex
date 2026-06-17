"""WU9 (fix): native DjangoModelType mutation SCHEMA assembly + execution.

This closes the SECOND native mutation path — ``DjangoModelType`` (the
serializer-style CRUD type, e.g. ``BasicSerializerType``) — to parity with both
graphene and the already-fixed ``DjangoModelMutation`` path (see
tests/native/test_wu9_mutation_execution.py and bugfix #1506).

Graphene's ``DjangoModelType`` mutation field mounts ``cls._meta.mutation_output``
(= the type itself) as the field type, so the SDL is::

    postCreate(newPost: <Input>!): <ThisType>

where ``<ThisType>`` is the PAYLOAD wrapper carrying ``ok`` / ``errors`` + the
output field (the model node). The native path now MATCHES this:

- ``_build_native_mutation_field`` compiles ``cls`` (the wrapper) via
  ``_compile_plain_object_type`` → the payload GraphQLObjectType (NOT the bare
  node), with camelCase wire arg keys (``out_name`` snake);
- it REGISTERS the field in ``_NATIVE_FIELD_REGISTRY[(model, op, "native")]`` so
  the native root compiler's ``_collect_root_attrs`` (gated on registry
  membership) mounts it onto the native Mutation root.

These are the cardinal checks (execution + registration + parity), assembled via
``DjangoGraphQLSchema`` (the native seam, D3/WU2), NOT a bare ``graphene.Schema``.
"""
from __future__ import annotations

import pytest


def _build_post_modeltype_schema():
    """Build a native DjangoGraphQLSchema with a DjangoModelType Post mutation."""
    from graphql import GraphQLString

    from django_graphex import DjangoObjectType, ObjectType, field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType
    from tests.models import Author, Post, Tag

    class _W9MtAuthor(DjangoObjectType):
        class Meta:
            model = Author

    class _W9MtTag(DjangoObjectType):
        class Meta:
            model = Tag

    class _W9MtPost(DjangoObjectType):
        class Meta:
            model = Post

    class _W9MtPostType(DjangoModelType):
        class Meta:
            model = Post

    compile_all_outputs()

    class _W9MtQuery(ObjectType):
        hello = field(GraphQLString)

    class _W9MtMutation(ObjectType):
        # MutationFields() returns (create, delete, update).
        post_create, post_delete, post_update = _W9MtPostType.MutationFields()

    schema = DjangoGraphQLSchema(query=_W9MtQuery, mutation=_W9MtMutation)
    return schema, _W9MtPostType


@pytest.mark.django_db
def test_modeltype_mutation_field_registered_and_mounted():
    """REGISTRATION: the DjangoModelType mutation field is in
    ``_NATIVE_FIELD_REGISTRY`` AND mounted on the native Mutation root.

    Anti-tautology: no manual ``_NATIVE_FIELD_REGISTRY`` injection — the
    ``DjangoModelType.*Field()`` builder must register itself, otherwise
    ``_collect_root_attrs`` (gated on registry membership) would drop the field
    and the native Mutation root would be missing it (KeyError on assembly).
    """
    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY
    from tests.models import Post

    schema, mut_cls = _build_post_modeltype_schema()

    # The builder registered each operation under (model, op, "native").
    for op in ("create", "delete", "update"):
        assert (Post, op, "native") in _NATIVE_FIELD_REGISTRY, (
            f"DjangoModelType {op} field not self-registered in "
            "_NATIVE_FIELD_REGISTRY — _collect_root_attrs would drop it."
        )

    # The native Mutation root carries the (camelCased) mounted fields.
    mutation_type = schema.graphql_schema.mutation_type
    assert mutation_type is not None
    for wire_name in ("postCreate", "postDelete", "postUpdate"):
        assert wire_name in mutation_type.fields, (
            f"native Mutation root missing {wire_name!r} — registration/collection "
            f"failed; got {sorted(mutation_type.fields)}"
        )

    # The mounted field IS the registered instance (identity, no rebuild).
    assert (
        mutation_type.fields["postCreate"]
        is _NATIVE_FIELD_REGISTRY[(Post, "create", "native")]
    )


@pytest.mark.django_db
def test_modeltype_mutation_field_output_is_payload_not_node():
    """PARITY: the field output type is the PAYLOAD wrapper (ok/errors + output
    field), matching graphene's ``...: <ThisType>`` — NOT the bare model node."""
    from graphql import GraphQLNonNull, GraphQLObjectType

    schema, mut_cls = _build_post_modeltype_schema()
    field = schema.graphql_schema.mutation_type.fields["postCreate"]

    out = field.type
    if isinstance(out, GraphQLNonNull):
        out = out.of_type
    assert isinstance(out, GraphQLObjectType)

    field_names = set(out.fields.keys())
    assert "ok" in field_names, sorted(field_names)
    assert "errors" in field_names, sorted(field_names)
    assert mut_cls._meta.output_field_name in field_names, sorted(field_names)
    # D8: the payload type carries extensions['gdx'].
    assert "gdx" in (out.extensions or {})


@pytest.mark.django_db
def test_modeltype_mutation_field_arg_is_camelcase_wire_name():
    """PARITY: the create input arg uses the camelCase WIRE name (``newPost``)
    with ``out_name`` set to the snake Python kwarg (``new_post``)."""
    schema, _ = _build_post_modeltype_schema()
    field = schema.graphql_schema.mutation_type.fields["postCreate"]
    arg_names = set(field.args.keys())
    assert "newPost" in arg_names, sorted(arg_names)
    assert field.args["newPost"].out_name == "new_post"


@pytest.mark.django_db
def test_modeltype_create_mutation_executes_and_creates_row():
    """CARDINAL: a native DjangoModelType CREATE EXECUTES via graphql_sync,
    creates a real DB row, and returns the graphene-matching payload."""
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_modeltype_schema()
    author = Author.objects.create(name="Ada")
    assert Post.objects.count() == 0

    document = (
        'mutation { postCreate(newPost: {title: "X", body: "y", author: %d}) '
        "{ post { title author { name } } ok errors { field messages } } }"
        % author.id
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(schema.graphql_schema, document, context_value=request)

    assert result.errors is None, f"native create raised: {result.errors!r}"
    data = result.data["postCreate"]
    assert data["ok"] is True, data["errors"]
    assert data["post"]["title"] == "X"
    assert data["post"]["author"]["name"] == "Ada"
    # The row really landed in the DB (not a faked payload).
    assert Post.objects.filter(title="X").exists()
    assert Post.objects.count() == 1


@pytest.mark.django_db
def test_modeltype_update_mutation_executes_and_updates_row():
    """CARDINAL: a native DjangoModelType UPDATE EXECUTES via graphql_sync,
    mutates a real DB row, and returns the typed payload reflecting the change."""
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_modeltype_schema()
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(title="Old", body="b", author=author)

    document = (
        'mutation { postUpdate(newPost: {id: %d, title: "New", body: "b", '
        'author: %d}) { post { title } ok errors { field messages } } }'
        % (post.id, author.id)
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(schema.graphql_schema, document, context_value=request)

    assert result.errors is None, f"native update raised: {result.errors!r}"
    data = result.data["postUpdate"]
    assert data["ok"] is True, data["errors"]
    assert data["post"]["title"] == "New"
    # The DB row really changed.
    post.refresh_from_db()
    assert post.title == "New"
