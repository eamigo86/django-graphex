"""Define the Strawberry benchmark schema and shared operations.

The adapter uses Strawberry Django's native pagination, filtering, ordering,
mutation, and optimizer support while preserving the shared workload and result
surface. It exposes the compiled schema, view, operations, and library versions
used by benchmark tooling.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Optional

import strawberry
import strawberry_django
from benchapp.models import Author, Comment, Post
from contract import validate_response
from strawberry.django.views import GraphQLView
from strawberry_django.optimizer import DjangoOptimizerExtension


# --------------------------------------------------------------------------- #
# Ordering (deterministic id ordering — parity with the graphex reference)     #
# --------------------------------------------------------------------------- #
@strawberry_django.order(Comment)
class CommentOrder:
    """Define deterministic comment ordering for benchmark queries.

    The shared workload orders comments by their primary key.
    """

    id: strawberry.auto


@strawberry_django.order(Post)
class PostOrder:
    """Define deterministic post ordering for benchmark queries.

    The shared workload orders posts by their primary key.
    """

    id: strawberry.auto


@strawberry_django.order(Author)
class AuthorOrder:
    """Define deterministic author ordering for benchmark queries.

    The shared workload orders authors by their primary key.
    """

    id: strawberry.auto


# --------------------------------------------------------------------------- #
# Filters (filtered list: title icontains "post 42")                           #
# --------------------------------------------------------------------------- #
@strawberry_django.filter_type(Post, lookups=True)
class PostFilter:
    """Expose the post filters required by benchmark operations.

    The selected fields support the shared filtered-list workload.
    """

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
    """Expose the projected comment fields used by benchmark operations.

    The declared surface matches the other benchmark adapters.
    """

    id: strawberry.auto
    author_name: strawberry.auto
    text: strawberry.auto
    is_approved: strawberry.auto
    created_at: strawberry.auto


@strawberry_django.type(Post, filters=PostFilter, order=PostOrder, pagination=True)
class PostType:
    """Expose the projected post fields used by benchmark operations.

    Pagination, filters, and relations support the shared workloads.
    """

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
    """Expose the projected author fields used by nested operations.

    The posts relation provides the shared nested benchmark path.
    """

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
    """Expose the read fields required by benchmark operations.

    The root supports single-post, post-list, and author-list workloads.
    """

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
    """Describe the input accepted by the create-comment workload.

    The fields match the shared mutation variables.
    """

    post: strawberry.auto
    author_name: strawberry.auto
    text: strawberry.auto


@strawberry.type
class Mutation:
    """Expose the write field required by the benchmark contract.

    The root provides the canonical create-comment operation.
    """

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
    validate_response("strawberry", "flat_list", resp)


def _validate_nested(resp):
    validate_response("strawberry", "nested", resp)


def _validate_single(resp):
    validate_response("strawberry", "single", resp)


def _validate_filtered(resp):
    validate_response("strawberry", "filtered", resp)


def _validate_create_comment(resp):
    validate_response("strawberry", "create_comment", resp)


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
