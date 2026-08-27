"""strawberry-graphql-django implementation of the benchmark operation contract.

This is the strawberry-graphql-django counterpart to the django-graphex reference
(libs/graphex/bench_schema.py). It is written in strawberry-django's own idiomatic,
documented, recommended-for-production style:

  * ``@strawberry_django.type(Model)`` with ``auto`` fields mapped straight from
    the Django models.
  * ``@strawberry_django.filter_type`` for the filtered list (title icontains).
  * ``@strawberry_django.order`` for deterministic ``id`` ordering (parity with the
    graphex reference, which orders every list by ``id``).
  * ``pagination=True`` fields exposing strawberry-django's ``OffsetPaginationInput``
    (``{ offset, limit }``) — the library's documented offset/limit idiom.
  * ``strawberry_django.mutations.create`` for ``create_comment``.
  * ``strawberry.django.views.GraphQLView`` (the SYNC view) for WSGI test-client
    parity with the harness (which POSTs via ``django.test.Client``).

RECOMMENDED PRODUCTION SETUP — the query optimizer:
  ``strawberry_django.optimizer.DjangoOptimizerExtension`` is enabled on the schema.
  This is strawberry-django's OWN documented, recommended default for production: it
  inspects each GraphQL query and automatically applies ``select_related`` /
  ``prefetch_related`` / ``only`` so nested selections do not trigger N+1 queries.
  It is the direct analogue of the graphex reference's list/prefetch handling, so
  enabling it keeps the benchmark fair (each library gets its own documented
  optimizer). It is a stock extension, not a hand-tuned exotic optimization.

The module exports the three symbols the shared contract requires:
``graphql_view``, ``OPERATIONS``, ``LIB_VERSIONS`` (plus ``schema`` for tooling).

Semantic equivalence with the graphex reference (see benchmarks/README.md) is
preserved: same rows touched, same fields returned. Only the query SHAPE differs
(``pagination: { limit }`` / ``order: { id: ASC }`` / ``filters: {...}`` instead of
graphex's ``results(limit:, offset:, ordering:)`` wrapper).
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Optional

import strawberry
import strawberry_django
from strawberry.django.views import GraphQLView
from strawberry_django.optimizer import DjangoOptimizerExtension

from benchapp.models import Author, Comment, Post


# --------------------------------------------------------------------------- #
# Ordering (deterministic id ordering — parity with the graphex reference)     #
# --------------------------------------------------------------------------- #
@strawberry_django.order(Comment)
class CommentOrder:
    id: strawberry.auto


@strawberry_django.order(Post)
class PostOrder:
    id: strawberry.auto


@strawberry_django.order(Author)
class AuthorOrder:
    id: strawberry.auto


# --------------------------------------------------------------------------- #
# Filters (filtered list: title icontains "post 42")                           #
# --------------------------------------------------------------------------- #
@strawberry_django.filter_type(Post, lookups=True)
class PostFilter:
    id: strawberry.auto
    title: strawberry.auto
    status: strawberry.auto


# --------------------------------------------------------------------------- #
# Object types (auto fields from the Django models)                            #
#                                                                              #
# The declared field lists are the SAME on all four libraries — the harness     #
# introspects them back out of the running schema and records them under        #
# ``surface`` in results/<lib>.json, so the fairness rule is checkable from the  #
# artifact rather than taken on trust. Fields the five operations never query   #
# (body, createdAt, email, bio, isApproved) are declared anyway, because the    #
# schema-build number is a comparison of how much surface each library compiles.#
# --------------------------------------------------------------------------- #
@strawberry_django.type(Comment, order=CommentOrder)
class CommentType:
    id: strawberry.auto
    author_name: strawberry.auto
    text: strawberry.auto
    is_approved: strawberry.auto
    created_at: strawberry.auto


@strawberry_django.type(Post, filters=PostFilter, order=PostOrder, pagination=True)
class PostType:
    id: strawberry.auto
    title: strawberry.auto
    body: strawberry.auto
    status: strawberry.auto
    views_count: strawberry.auto
    created_at: strawberry.auto
    author: "AuthorType"
    # Nested paginated + ordered comments (the N+1 stressor leaf).
    comments: list[CommentType] = strawberry_django.field(
        order=CommentOrder, pagination=True
    )


@strawberry_django.type(Author, order=AuthorOrder, pagination=True)
class AuthorType:
    id: strawberry.auto
    name: strawberry.auto
    email: strawberry.auto
    bio: strawberry.auto
    # Nested paginated + ordered posts.
    posts: list[PostType] = strawberry_django.field(
        order=PostOrder, pagination=True
    )


# --------------------------------------------------------------------------- #
# Query root                                                                   #
# --------------------------------------------------------------------------- #
@strawberry.type
class Query:
    # single object by pk (post(pk: 5000))
    post: Optional[PostType] = strawberry_django.field()
    # paginated + filterable + ordered list wrappers
    posts: list[PostType] = strawberry_django.field()
    authors: list[AuthorType] = strawberry_django.field()


# --------------------------------------------------------------------------- #
# Mutation: create_comment                                                     #
# --------------------------------------------------------------------------- #
@strawberry_django.input(Comment)
class CommentCreateInput:
    post: strawberry.auto
    author_name: strawberry.auto
    text: strawberry.auto


@strawberry.type
class Mutation:
    create_comment: CommentType = strawberry_django.mutations.create(
        CommentCreateInput
    )


# --------------------------------------------------------------------------- #
# Schema — with the RECOMMENDED production optimizer extension enabled.         #
# --------------------------------------------------------------------------- #
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        # strawberry-django's documented, recommended-for-production optimizer:
        # auto select_related / prefetch_related / only to eliminate N+1.
        DjangoOptimizerExtension(),
    ],
)

# The SYNC Django view for WSGI test-client parity with the harness.
# graphql_ide=None disables the GraphiQL IDE (production-shaped, matches the
# harness which only POSTs application/json).
graphql_view = GraphQLView.as_view(schema=schema, graphql_ide=None)


# --------------------------------------------------------------------------- #
# Operation contract                                                          #
# --------------------------------------------------------------------------- #
# A seeded mid-range post pk. Fresh DB => pks are 1..10000 contiguous.
SINGLE_POST_ID = 5000


def _validate_flat_list(resp):
    assert "errors" not in resp, resp.get("errors")
    items = resp["data"]["posts"]
    assert len(items) == 50, f"expected 50 posts, got {len(items)}"
    first = items[0]
    assert {"id", "title", "status", "viewsCount"} <= set(first), first


def _validate_nested(resp):
    assert "errors" not in resp, resp.get("errors")
    authors = resp["data"]["authors"]
    assert len(authors) == 20, f"expected 20 authors, got {len(authors)}"
    posts = authors[0]["posts"]
    assert len(posts) >= 1, "expected nested posts on the first author"
    comments = posts[0]["comments"]
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
    items = resp["data"]["posts"]
    assert len(items) >= 1, "expected at least one filtered post"


def _validate_create_comment(resp):
    assert "errors" not in resp, resp.get("errors")
    payload = resp["data"]["createComment"]
    assert payload["id"], "created comment has no id"


OPERATIONS = {
    "flat_list": {
        "query": """
            query {
              posts(pagination: { limit: 50 }, order: { id: ASC }) {
                id
                title
                status
                viewsCount
              }
            }
        """,
        "variables": None,
        "validate": _validate_flat_list,
    },
    "nested": {
        "query": """
            query {
              authors(pagination: { limit: 20 }, order: { id: ASC }) {
                id
                name
                posts(pagination: { limit: 10 }, order: { id: ASC }) {
                  id
                  title
                  comments(pagination: { limit: 5 }, order: { id: ASC }) {
                    id
                    text
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
            query ($pk: ID!) {
              post(pk: $pk) {
                id
                title
                author { name }
              }
            }
        """,
        "variables": {"pk": SINGLE_POST_ID},
        "validate": _validate_single,
    },
    "filtered": {
        "query": """
            query {
              posts(
                filters: { title: { iContains: "post 42" } }
                pagination: { limit: 50 }
                order: { id: ASC }
              ) {
                id
                title
              }
            }
        """,
        "variables": None,
        "validate": _validate_filtered,
    },
    "create_comment": {
        "query": """
            mutation ($input: CommentCreateInput!) {
              createComment(data: $input) {
                id
              }
            }
        """,
        "variables": {
            "input": {
                "post": {"set": SINGLE_POST_ID},
                "authorName": "Bench Bot",
                "text": "Benchmark generated comment.",
            }
        },
        "validate": _validate_create_comment,
    },
}


def _installed_versions():
    out = {}
    for pkg in ("strawberry-graphql-django", "django", "strawberry-graphql", "graphql-core"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    return out


LIB_VERSIONS = _installed_versions()
