"""django-graphex v2 reference implementation of the benchmark operation contract.

This is the CANONICAL implementation the other three libraries are compared
against. It uses django-graphex idiomatically:

  * ``DjangoObjectType`` with ``only_fields`` + ``filter_fields`` for the leaf
    types. ``only_fields`` matches the other libraries' explicit field lists and
    is a security boundary: a projected column is unreadable, unorderable and
    unfilterable through the type.
  * ``DjangoListObjectType`` + ``LimitOffsetGraphqlPagination`` for the
    ``results {} / totalCount`` list wrapper (used by flat_list, nested,
    filtered).
  * ``DjangoListObjectField`` / ``DjangoObjectField`` on the Query root.
  * A ``DjangoModelMutation`` for ``create_comment``.
  * ``GraphQLView`` from ``django_graphex.views``.

The module exports the three symbols the shared contract requires:
``graphql_view``, ``OPERATIONS``, ``LIB_VERSIONS`` (plus ``schema`` for tooling).

Import notes (v2 current API): types/descriptors come from ``django_graphex.core``;
mutation arguments live on ``class Arguments``; the unified ``Field`` doubles as an
argument descriptor. This file mirrors examples/playground/blog/schema.py.
"""

from importlib.metadata import PackageNotFoundError, version

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.mutation import DjangoModelMutation
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView

from benchapp.models import Author, Comment, Post

# --------------------------------------------------------------------------- #
# Object types                                                                #
#                                                                             #
# ``only_fields`` mirrors the explicit field lists graphene-django and         #
# strawberry declare in their own bench schemas, so the four libraries compile #
# the SAME surface and the schema-build number compares like for like. Without #
# it graphex auto-exposed every column plus ``tags`` and ``category``, building #
# the widest schema of the four — and ``category`` was dropped with a WARNING  #
# at import time, inside the region the harness times, because ``Category`` has #
# no registered type.                                                          #
#                                                                             #
# It is also a security boundary, not just a shape: a projected-away column is #
# unreadable, unorderable and unfilterable through the type. ``PostType``      #
# filters on ``author``, a relation-direct lookup, which is admitted only      #
# because ``AuthorType`` below publishes the author's key.                     #
# --------------------------------------------------------------------------- #
class CommentType(DjangoObjectType):
    class Meta:
        model = Comment
        only_fields = ("id", "author_name", "text", "is_approved", "created_at")
        filter_fields = {"id": ("exact",), "text": ("icontains",)}


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        only_fields = (
            "id",
            "title",
            "body",
            "status",
            "views_count",
            "created_at",
            "author",
            "comments",
        )
        filter_fields = {
            "id": ("exact",),
            "title": ("icontains",),
            "status": ("exact",),
            "author": ("exact",),
        }


class CommentListType(DjangoListObjectType):
    class Meta:
        model = Comment
        pagination = LimitOffsetGraphqlPagination(default_limit=5, ordering="id")


class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="id")


class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        only_fields = ("id", "name", "email", "bio", "posts")
        filter_fields = {"id": ("exact",), "name": ("icontains",)}


class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        pagination = LimitOffsetGraphqlPagination(default_limit=20, ordering="id")


# --------------------------------------------------------------------------- #
# Mutation: create_comment                                                    #
# --------------------------------------------------------------------------- #
class CommentMutation(DjangoModelMutation):
    class Meta:
        model = Comment
        model_operations = ("create",)


# --------------------------------------------------------------------------- #
# Query root                                                                  #
# --------------------------------------------------------------------------- #
class Query(ObjectType):
    # single object by id
    post = DjangoObjectField(PostType)
    # paginated + filterable list wrappers (results {} / totalCount)
    posts = DjangoListObjectField(PostListType)
    authors = DjangoListObjectField(AuthorListType)


# Compile inputs/outputs before the mutation Field descriptors resolve.
from django_graphex.core.base import compile_all_inputs  # noqa: E402
from django_graphex.core.registry_compiler import compile_all_outputs  # noqa: E402

compile_all_inputs()
compile_all_outputs()


class Mutation(ObjectType):
    comment_create = CommentMutation.CreateField()


schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)

# GraphQLView reads the schema from settings by default; pass it explicitly so
# this module is self-contained and does not depend on DJANGO_GRAPHEX["SCHEMA"].
graphql_view = GraphQLView.as_view(schema=schema, graphiql=False)


# --------------------------------------------------------------------------- #
# Operation contract                                                          #
# --------------------------------------------------------------------------- #
# A seeded mid-range post pk. Fresh DB => pks are 1..10000 contiguous.
SINGLE_POST_ID = 5000


def _validate_flat_list(resp):
    assert "errors" not in resp, resp.get("errors")
    items = resp["data"]["posts"]["results"]
    assert len(items) == 50, f"expected 50 posts, got {len(items)}"
    first = items[0]
    assert {"id", "title", "status", "viewsCount"} <= set(first), first


def _validate_nested(resp):
    assert "errors" not in resp, resp.get("errors")
    authors = resp["data"]["authors"]["results"]
    assert len(authors) == 20, f"expected 20 authors, got {len(authors)}"
    posts = authors[0]["posts"]["results"]
    assert len(posts) >= 1, "expected nested posts on the first author"
    comments = posts[0]["comments"]["results"]
    assert len(comments) >= 1, "expected nested comments on the first post"
    assert "text" in comments[0], comments[0]


def _validate_single(resp):
    assert "errors" not in resp, resp.get("errors")
    post = resp["data"]["post"]
    assert post is not None, "post not found"
    assert post["title"], "post title is empty"
    assert post["author"]["name"], "author name is empty"


def _validate_filtered(resp):
    assert "errors" not in resp, resp.get("errors")
    items = resp["data"]["posts"]["results"]
    assert len(items) >= 1, "expected at least one filtered post"


def _validate_create_comment(resp):
    assert "errors" not in resp, resp.get("errors")
    payload = resp["data"]["commentCreate"]
    assert payload["ok"], payload
    assert payload["comment"]["id"], "created comment has no id"


OPERATIONS = {
    "flat_list": {
        "query": """
            query {
              posts {
                results(limit: 50, ordering: "id") { id title status viewsCount }
              }
            }
        """,
        "variables": None,
        "validate": _validate_flat_list,
    },
    "nested": {
        "query": """
            query {
              authors {
                results(limit: 20, ordering: "id") {
                  id
                  name
                  posts {
                    results(limit: 10, ordering: "id") {
                      id
                      title
                      comments {
                        results(limit: 5, ordering: "id") { id text }
                      }
                    }
                  }
                }
              }
            }
        """,
        "variables": None,
        "validate": _validate_nested,
    },
    "single": {
        "query": """
            query ($id: ID!) {
              post(id: $id) {
                id
                title
                author { name }
              }
            }
        """,
        "variables": {"id": SINGLE_POST_ID},
        "validate": _validate_single,
    },
    "filtered": {
        "query": """
            query {
              posts(filter: { title: { icontains: "post 42" } }) {
                results(limit: 50, ordering: "id") { id title }
              }
            }
        """,
        "variables": None,
        "validate": _validate_filtered,
    },
    "create_comment": {
        "query": """
            mutation ($input: CommentCreateGenericType!) {
              commentCreate(newComment: $input) {
                ok
                comment { id }
              }
            }
        """,
        "variables": {
            "input": {
                "post": SINGLE_POST_ID,
                "authorName": "Bench Bot",
                "text": "Benchmark generated comment.",
            }
        },
        "validate": _validate_create_comment,
    },
}


def _installed_versions():
    out = {}
    for pkg in ("django-graphex", "django", "graphql-core"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    return out


LIB_VERSIONS = _installed_versions()
