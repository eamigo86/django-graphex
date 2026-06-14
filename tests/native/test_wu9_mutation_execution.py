"""WU9: native mutation SCHEMA assembly + end-to-end execution.

Phase 5 / WU9 closes the native mutation seam: under ``GDX_BACKEND=native`` a
``DjangoModelMutation`` field built by ``CreateField``/``UpdateField`` resolves to
a native ``GraphQLObjectType`` for the MUTATION PAYLOAD (the ``ok`` / ``errors`` +
output-field result type — NOT the bare model node type), with camelCase wire
argument names (``out_name`` snake) so a real GraphQL document EXECUTES.

These are the cardinal WU9 checks (execution, not just SDL/build):
- a native CREATE mutation creates a real row and returns the typed payload;
- a native UPDATE mutation updates a real row and returns the typed payload;
- the mutation field's output type carries the payload fields (``ok``/``errors``/
  output) with ``extensions['gdx']`` (D8) — distinct from the node type.

The schema entry point is ``DjangoGraphQLSchema`` (the native seam, D3/WU2), NOT a
bare ``graphene.Schema``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


def _build_post_mutation_schema():
    """Build a native DjangoGraphQLSchema with a Post create+update mutation."""
    import graphene

    from django_graphex import DjangoModelMutation, DjangoObjectType
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from tests.models import Author, Post, Tag

    class _W9Author(DjangoObjectType):
        class Meta:
            model = Author

    class _W9Tag(DjangoObjectType):
        class Meta:
            model = Tag

    class _W9Post(DjangoObjectType):
        class Meta:
            model = Post

    class _W9PostMutation(DjangoModelMutation):
        class Meta:
            model = Post

    compile_all_outputs()

    class _W9Query(graphene.ObjectType):
        hello = graphene.String()

    class _W9Mutation(graphene.ObjectType):
        post_create = _W9PostMutation.CreateField()
        post_update = _W9PostMutation.UpdateField()

    schema = DjangoGraphQLSchema(query=_W9Query, mutation=_W9Mutation)
    return schema, _W9PostMutation


@pytest.mark.django_db
def test_native_mutation_field_output_is_payload_type_not_node():
    """The native mutation field's output type is the PAYLOAD type (ok/errors +
    output field), NOT the bare model node type.

    Anti-tautology: a freshly built native CreateField must NOT carry the node
    DjangoObjectType (which has no ``ok``/``errors``) as its output type — that is
    the bug WU9 fixes (graphene path used ``cls._meta.output`` = the payload;
    native path used the node type, so ``ok``/``errors``/output were unqueryable).
    """
    from graphql import GraphQLNonNull, GraphQLObjectType

    schema, mut_cls = _build_post_mutation_schema()
    mutation_type = schema.graphql_schema.mutation_type
    assert mutation_type is not None
    field = mutation_type.fields["postCreate"]

    out = field.type
    if isinstance(out, GraphQLNonNull):
        out = out.of_type
    assert isinstance(out, GraphQLObjectType)

    # The payload type carries ok/errors + the output field (camelCased) — NOT
    # the node type whose fields are only the model's own columns.
    field_names = set(out.fields.keys())
    assert "ok" in field_names, (
        f"Mutation payload type must expose 'ok'; got fields {sorted(field_names)}"
    )
    assert "errors" in field_names, (
        f"Mutation payload type must expose 'errors'; got fields {sorted(field_names)}"
    )
    output_field_name = mut_cls._meta.output_field_name  # 'post'
    assert output_field_name in field_names, (
        f"Mutation payload type must expose the output field "
        f"{output_field_name!r}; got fields {sorted(field_names)}"
    )
    # D8: the payload type carries extensions['gdx'].
    assert "gdx" in (out.extensions or {}), (
        f"Mutation payload type {out.name!r} must carry extensions['gdx']"
    )


@pytest.mark.django_db
def test_native_mutation_field_arg_is_camelcase_wire_name():
    """The native mutation field's input argument uses the camelCase WIRE name
    (``newPost``) with ``out_name`` set to the snake Python kwarg (``new_post``).

    graphql-core does NOT auto-camelCase argument names, so without this the SDL
    arg would be ``new_post`` and a ``newPost: {...}`` document would be rejected.
    """
    schema, _ = _build_post_mutation_schema()
    field = schema.graphql_schema.mutation_type.fields["postCreate"]
    arg_names = set(field.args.keys())
    assert "newPost" in arg_names, (
        f"Mutation arg wire name must be camelCase 'newPost'; got {sorted(arg_names)}"
    )
    assert field.args["newPost"].out_name == "new_post", (
        "Mutation arg out_name must be the snake Python kwarg 'new_post'; got "
        f"{field.args['newPost'].out_name!r}"
    )


@pytest.mark.django_db
def test_native_create_mutation_executes_and_creates_row():
    """CARDINAL: a native CREATE mutation EXECUTES via graphql_sync, creates a
    real DB row, and returns the typed payload with the correct nested fields."""
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_mutation_schema()
    author = Author.objects.create(name="Ada")
    assert Post.objects.count() == 0

    # Selects the payload (ok/errors), a scalar (title), and a nested FK object
    # (author { name }) — proving the native mutation resolver runs AND the
    # payload's output field resolves through a relation. The auto-derived
    # to-many ``tags`` nested-list NODE shape is a separate node-relation slice
    # (tracked debt), not WU9 mutation-schema assembly.
    document = (
        'mutation { postCreate(newPost: {title: "X", body: "y", author: %d}) '
        "{ post { title author { name } } ok errors { field messages } } }"
        % author.id
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(
        schema.graphql_schema, document, context_value=request
    )

    assert result.errors is None, f"native create mutation raised: {result.errors!r}"
    data = result.data["postCreate"]
    assert data["ok"] is True, data["errors"]
    assert data["post"]["title"] == "X"
    assert data["post"]["author"]["name"] == "Ada"
    # The row really landed in the DB (not a faked payload).
    assert Post.objects.filter(title="X").exists()
    assert Post.objects.count() == 1


@pytest.mark.django_db
def test_native_update_mutation_executes_and_updates_row():
    """CARDINAL: a native UPDATE mutation EXECUTES via graphql_sync, mutates a
    real DB row, and returns the typed payload reflecting the change."""
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_mutation_schema()
    author = Author.objects.create(name="Ada")
    post = Post.objects.create(title="Old", body="b", author=author)

    document = (
        "mutation { postUpdate(newPost: {id: %d, title: \"New\", body: \"b\", "
        "author: %d}) { post { title } ok errors { field messages } } }"
        % (post.id, author.id)
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(
        schema.graphql_schema, document, context_value=request
    )

    assert result.errors is None, f"native update mutation raised: {result.errors!r}"
    data = result.data["postUpdate"]
    assert data["ok"] is True, data["errors"]
    assert data["post"]["title"] == "New"
    # The DB row really changed.
    post.refresh_from_db()
    assert post.title == "New"
