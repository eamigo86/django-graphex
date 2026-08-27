"""ariadne (latest) implementation of the benchmark operation contract.

ariadne is **schema-first**: you write the GraphQL SDL by hand, then bind plain
Python resolvers to it with ``make_executable_schema``. This module follows the
library's documented, recommended production shape:

  * The schema is one SDL string. Field and argument names are ``camelCase`` in
    the SDL (idiomatic GraphQL), and ``make_executable_schema(...,
    convert_names_case=True)`` maps them to the models' ``snake_case`` Python
    attributes automatically. In ariadne 1.x this is the recommended replacement
    for the old ``snake_case_fallback_resolvers`` — it is the library's own
    documented default-name integration, so we enable it (noted per the fairness
    rule: this is ariadne's recommended default, not a hand-rolled optimization).
  * ``QueryType`` / ``MutationType`` / ``ObjectType`` carry the resolvers.
  * Resolvers are plain, idiomatic Django ORM calls: queryset slicing for the
    limit/offset, ``icontains`` for the filter, ``.get()`` for a single object.
  * **Nested resolvers access the relation per parent object**
    (``author.posts.all()[:limit]``, ``post.comments.all()[:limit]``), exactly
    as ariadne's docs show relation resolvers. ariadne ships **no** ORM query
    optimizer and its DataLoader story is opt-in (not part of the recommended
    default schema), so the ``nested`` operation N+1s. That is the honest,
    idiomatic ariadne result and we deliberately do NOT hand-add a dataloader
    (that would be an exotic optimization the library does not apply by default).

Django integration: the official ``ariadne-django`` package installs and works
on the pinned Django, so we mount its ``GraphQLView`` — a standard Django
class-based view that runs ``graphql_sync`` (correct for Django + sqlite). No
hand-rolled view is needed.

Exports the three contract symbols: ``graphql_view``, ``OPERATIONS``,
``LIB_VERSIONS`` (plus ``schema`` for tooling).
"""

from importlib.metadata import PackageNotFoundError, version

from ariadne import MutationType, ObjectType, QueryType, make_executable_schema
from ariadne_django.views import GraphQLView

from benchapp.models import Comment, Post

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
def resolve_posts(_, __, *, limit, offset=None, title_contains=None):
    # convert_names_case=True lowercases the SDL arg `titleContains` -> `title_contains`.
    qs = Post.objects.order_by("id")
    if title_contains is not None:
        qs = qs.filter(title__icontains=title_contains)
    return _slice(qs, limit, offset)


@query.field("authors")
def resolve_authors(_, __, *, limit, offset=None):
    from benchapp.models import Author

    return _slice(Author.objects.order_by("id"), limit, offset)


@query.field("post")
def resolve_post(_, __, *, id):
    return Post.objects.filter(pk=id).first()


# ---- Nested relation resolvers (per-object access; honest N+1) ------------ #
@author_type.field("posts")
def resolve_author_posts(author, _, *, limit, offset=None):
    return _slice(author.posts.order_by("id"), limit, offset)


@post_type.field("comments")
def resolve_post_comments(post, _, *, limit, offset=None):
    return _slice(post.comments.order_by("id"), limit, offset)


@post_type.field("author")
def resolve_post_author(post, _):
    return post.author


# ---- Mutation ------------------------------------------------------------- #
@mutation.field("createComment")
def resolve_create_comment(_, __, *, input):
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
    assert payload["ok"], payload
    assert payload["comment"]["id"], "created comment has no id"


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
