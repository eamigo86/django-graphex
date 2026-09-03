"""Implement the shared benchmark contract with Ariadne.

The adapter defines the schema in GraphQL SDL and binds plain Python resolvers
with Ariadne's schema-first helpers. Automatic name conversion maps GraphQL
camel case fields to Django model attributes, while ordinary queryset slicing
and filters implement the workload without custom optimization.

Nested resolvers deliberately access each parent's relation independently.
Ariadne does not provide an automatic ORM optimizer, so the resulting N+1
behavior is part of the fair out-of-the-box comparison. The official Django
integration serves the executable schema. The module exports graphql_view,
OPERATIONS, LIB_VERSIONS, and schema for the benchmark harness and tooling.
"""

from importlib.metadata import PackageNotFoundError, version

from ariadne import MutationType, ObjectType, QueryType, make_executable_schema
from ariadne_django.views import GraphQLView
from benchapp.models import Comment, Post
from contract import validate_response

# --------------------------------------------------------------------------- #
# Schema definition language (SDL)                                            #
# --------------------------------------------------------------------------- #
# camelCase field/arg names; convert_names_case=True maps them to the model's
# snake_case attributes (viewsCount -> views_count, authorName -> author_name).
#
# The declared field lists are the SAME on all four libraries — the harness
# introspects them back out of the running schema and records them under
# ``surface`` in results/<lib>.json, so the fairness rule is checkable from the
# artifact rather than taken on trust. Fields the five operations never query
# (body, createdAt, email, bio, isApproved) are declared anyway, because the
# schema-build number is a comparison of how much surface each library compiles.
# ``DateTime`` is declared without a binding: no operation selects a datetime,
# so the default pass-through serializer is never exercised.
type_defs = """
    scalar DateTime

    type Query {
        posts(limit: Int!, offset: Int, titleContains: String): [Post!]!
        authors(limit: Int!, offset: Int): [Author!]!
        post(id: ID!): Post
    }

    type Mutation {
        createComment(input: CreateCommentInput!): CreateCommentPayload!
    }

    input CreateCommentInput {
        post: ID!
        authorName: String!
        text: String!
    }

    type CreateCommentPayload {
        ok: Boolean!
        comment: Comment
    }

    type Author {
        id: ID!
        name: String!
        email: String!
        bio: String!
        posts(limit: Int!, offset: Int): [Post!]!
    }

    type Post {
        id: ID!
        title: String!
        body: String!
        status: String!
        viewsCount: Int!
        createdAt: DateTime!
        author: Author!
        comments(limit: Int!, offset: Int): [Comment!]!
    }

    type Comment {
        id: ID!
        authorName: String!
        text: String!
        isApproved: Boolean!
        createdAt: DateTime!
    }
"""

# --------------------------------------------------------------------------- #
# Resolvers — plain, idiomatic Django ORM                                     #
# --------------------------------------------------------------------------- #
query = QueryType()
mutation = MutationType()
author_type = ObjectType("Author")
post_type = ObjectType("Post")


def _slice(qs, limit, offset):
    """Idiomatic queryset limit/offset via Python slicing (SQL LIMIT/OFFSET)."""
    offset = offset or 0
    return list(qs[offset : offset + limit])


# ---- Query root ----------------------------------------------------------- #
@query.field("posts")
def resolve_posts(
    _: object,
    __: object,
    *,
    limit: int,
    offset: int | None = None,
    title_contains: str | None = None,
) -> list[Post]:
    """Resolve the ordered post list for flat and filtered workloads.

    Args:
        _: Root query value supplied by Ariadne.
        __: Execution context supplied by Ariadne.
        limit: Maximum number of posts to return.
        offset: Number of posts to skip before collecting results.
        title_contains: Optional case-insensitive title fragment.

    Returns:
        The selected posts in database identifier order.
    """
    # convert_names_case=True lowercases the SDL arg `titleContains` -> `title_contains`.
    qs = Post.objects.order_by("id")
    if title_contains is not None:
        qs = qs.filter(title__icontains=title_contains)
    return _slice(qs, limit, offset)


@query.field("authors")
def resolve_authors(
    _: object,
    __: object,
    *,
    limit: int,
    offset: int | None = None,
) -> list["Author"]:
    """Resolve the ordered author list for the nested workload.

    Args:
        _: Root query value supplied by Ariadne.
        __: Execution context supplied by Ariadne.
        limit: Maximum number of authors to return.
        offset: Number of authors to skip before collecting results.

    Returns:
        The selected authors in database identifier order.
    """
    from benchapp.models import Author

    return _slice(Author.objects.order_by("id"), limit, offset)


@query.field("post")
def resolve_post(_: object, __: object, *, id: int | str) -> Post | None:
    """Resolve one post from its database identifier.

    Args:
        _: Root query value supplied by Ariadne.
        __: Execution context supplied by Ariadne.
        id: Database identifier requested by the operation.

    Returns:
        The matching post, or None when it does not exist.
    """
    return Post.objects.filter(pk=id).first()


# ---- Nested relation resolvers (per-object access; honest N+1) ------------ #
@author_type.field("posts")
def resolve_author_posts(
    author: "Author",
    _: object,
    *,
    limit: int,
    offset: int | None = None,
) -> list[Post]:
    """Resolve one author's ordered posts for the nested workload.

    Args:
        author: Parent author selected by the query.
        _: Execution context supplied by Ariadne.
        limit: Maximum number of posts to return.
        offset: Number of posts to skip before collecting results.

    Returns:
        The selected posts in database identifier order.
    """
    return _slice(author.posts.order_by("id"), limit, offset)


@post_type.field("comments")
def resolve_post_comments(
    post: Post,
    _: object,
    *,
    limit: int,
    offset: int | None = None,
) -> list[Comment]:
    """Resolve one post's ordered comments for the nested workload.

    Args:
        post: Parent post selected by the query.
        _: Execution context supplied by Ariadne.
        limit: Maximum number of comments to return.
        offset: Number of comments to skip before collecting results.

    Returns:
        The selected comments in database identifier order.
    """
    return _slice(post.comments.order_by("id"), limit, offset)


@post_type.field("author")
def resolve_post_author(post: Post, _: object) -> "Author":
    """Resolve the author related to a post.

    Args:
        post: Parent post selected by the query.
        _: Execution context supplied by Ariadne.

    Returns:
        The author associated with the post.
    """
    return post.author


# ---- Mutation ------------------------------------------------------------- #
@mutation.field("createComment")
def resolve_create_comment(
    _: object,
    __: object,
    *,
    input: dict[str, int | str],
) -> dict[str, bool | Comment]:
    """Create a comment for the mutation workload.

    Args:
        _: Root mutation value supplied by Ariadne.
        __: Execution context supplied by Ariadne.
        input: Validated mutation fields after name conversion.

    Returns:
        The created comment and successful mutation state.
    """
    # convert_names_case=True converts input field keys too: authorName -> author_name.
    comment = Comment.objects.create(
        post_id=input["post"],
        author_name=input["author_name"],
        text=input["text"],
    )
    return {"ok": True, "comment": comment}


schema = make_executable_schema(
    type_defs,
    query,
    mutation,
    author_type,
    post_type,
    convert_names_case=True,
)

# Official ariadne-django Django view (class-based, runs graphql_sync, csrf-exempt).
graphql_view = GraphQLView.as_view(schema=schema)


# --------------------------------------------------------------------------- #
# Operation contract                                                          #
# --------------------------------------------------------------------------- #
# A seeded mid-range post pk. Fresh DB => pks are 1..10000 contiguous.
SINGLE_POST_ID = 5000


def _validate_flat_list(resp):
    validate_response("ariadne", "flat_list", resp)


def _validate_nested(resp):
    validate_response("ariadne", "nested", resp)


def _validate_single(resp):
    validate_response("ariadne", "single", resp)


def _validate_filtered(resp):
    validate_response("ariadne", "filtered", resp)


def _validate_create_comment(resp):
    validate_response("ariadne", "create_comment", resp)


OPERATIONS = {
    "flat_list": {
        "query": """
            query {
              posts(limit: 50) { id title status viewsCount }
            }
        """,
        "variables": None,
        "validate": _validate_flat_list,
    },
    "nested": {
        "query": """
            query {
              authors(limit: 20) {
                id
                name
                posts(limit: 10) {
                  id
                  title
                  comments(limit: 5) { id text }
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
              posts(limit: 50, titleContains: "post 42") { id title }
            }
        """,
        "variables": None,
        "validate": _validate_filtered,
    },
    "create_comment": {
        "query": """
            mutation ($input: CreateCommentInput!) {
              createComment(input: $input) {
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
    for pkg in ("ariadne", "ariadne-django", "django", "graphql-core"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    return out


LIB_VERSIONS = _installed_versions()
