"""graphene-django implementation of the benchmark operation contract.

Semantically equivalent to the graphex reference (see benchmarks/README.md):
same rows, same fields. Only the query SHAPE differs — this module uses
graphene-django's documented, idiomatic building blocks:

  * ``DjangoObjectType`` per model, exposing scalar + relation fields.
  * Relay ``Node`` + ``DjangoConnectionField`` / ``DjangoFilterConnectionField``
    for list access. Relay connections are graphene-django's recommended list
    idiom (the docs' primary pattern), so ``first: N`` is how a graphene client
    limits a list, and nested relations are traversed as nested connections.
  * ``django-filter`` via ``DjangoFilterConnectionField`` + ``filterset_fields``
    for the ``filtered`` operation. django-filter is graphene-django's
    documented, recommended filtering integration — installing it is part of the
    library's idiomatic setup, not an exotic optimization.
  * A plain ``graphene.Field`` taking a raw database ``id`` for ``single``.
    (Relay's ``Node.Field`` would demand an opaque global id, which is not what
    the shared contract passes; a by-pk field is the honest equivalent of the
    reference's ``post(id: 5000)``.)
  * A ``graphene.Mutation`` (``relay.ClientIDMutation`` is optional; a plain
    Mutation is the simplest documented form) for ``create_comment``.

FAIRNESS NOTE — no hand-tuning: the nested operation traverses relations with
graphene-django's default resolvers. graphene-django does NOT ship an automatic
query optimizer by default (that lives in a separate optional package,
``graphene-django-optimizer``, which is NOT installed here because it is not the
library's own documented default). So ``nested`` will N+1 — that is the honest,
out-of-the-box behavior of graphene-django and is exactly what the benchmark is
meant to measure.

Exports the three contract symbols: ``graphql_view``, ``OPERATIONS``,
``LIB_VERSIONS`` (plus ``schema`` for tooling).
"""

from importlib.metadata import PackageNotFoundError, version

import graphene
from benchapp.models import Author, Comment, Post
from contract import validate_response
from graphene import relay
from graphene_django import DjangoConnectionField, DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField
from graphene_django.views import GraphQLView


# --------------------------------------------------------------------------- #
# Object types (Relay nodes — the graphene-django documented default)         #
# --------------------------------------------------------------------------- #
class CommentType(DjangoObjectType):
    class Meta:
        model = Comment
        fields = ("id", "author_name", "text", "is_approved", "created_at")
        interfaces = (relay.Node,)


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        fields = (
            "id",
            "title",
            "body",
            "status",
            "views_count",
            "created_at",
            "author",
            "comments",
        )
        # django-filter integration: the documented, recommended way to filter a
        # graphene-django list. ``filtered`` uses title__icontains through this.
        filter_fields = {"title": ["icontains"], "status": ["exact"]}
        interfaces = (relay.Node,)


class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        fields = ("id", "name", "email", "bio", "posts")
        interfaces = (relay.Node,)


# --------------------------------------------------------------------------- #
# Mutation: create_comment (plain graphene Mutation — the simplest doc form)   #
# --------------------------------------------------------------------------- #
class CreateComment(graphene.Mutation):
    class Arguments:
        post_id = graphene.ID(required=True)
        author_name = graphene.String(required=True)
        text = graphene.String(required=True)

    ok = graphene.Boolean()
    comment = graphene.Field(CommentType)

    def mutate(self, info, post_id, author_name, text):
        comment = Comment.objects.create(
            post_id=post_id,
            author_name=author_name,
            text=text,
        )
        return CreateComment(ok=True, comment=comment)


# --------------------------------------------------------------------------- #
# Query root                                                                  #
# --------------------------------------------------------------------------- #
class Query(graphene.ObjectType):
    # single object by raw database pk (equivalent to the reference's post(id:))
    post = graphene.Field(PostType, id=graphene.ID(required=True))

    # list access via Relay connections (graphene-django's documented default).
    # ``posts`` is a filtered connection (django-filter) used by both flat_list
    # and filtered; ``authors`` is a plain connection used by nested.
    posts = DjangoFilterConnectionField(PostType)
    authors = DjangoConnectionField(AuthorType)

    def resolve_post(self, info, id):
        return Post.objects.filter(pk=id).first()


class Mutation(graphene.ObjectType):
    create_comment = CreateComment.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)

graphql_view = GraphQLView.as_view(schema=schema, graphiql=False)


# --------------------------------------------------------------------------- #
# Operation contract                                                          #
# --------------------------------------------------------------------------- #
SINGLE_POST_ID = 5000


def _validate_flat_list(resp):
    validate_response("graphene", "flat_list", resp)


def _validate_nested(resp):
    validate_response("graphene", "nested", resp)


def _validate_single(resp):
    validate_response("graphene", "single", resp)


def _validate_filtered(resp):
    validate_response("graphene", "filtered", resp)


def _validate_create_comment(resp):
    validate_response("graphene", "create_comment", resp)


OPERATIONS = {
    "flat_list": {
        "query": """
            query {
              posts(first: 50) {
                edges { node { id title status viewsCount } }
              }
            }
        """,
        "variables": None,
        "validate": _validate_flat_list,
    },
    "nested": {
        "query": """
            query {
              authors(first: 20) {
                edges {
                  node {
                    id
                    name
                    posts(first: 10) {
                      edges {
                        node {
                          id
                          title
                          comments(first: 5) {
                            edges { node { id text } }
                          }
                        }
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
              posts(first: 50, title_Icontains: "post 42") {
                edges { node { id title } }
              }
            }
        """,
        "variables": None,
        "validate": _validate_filtered,
    },
    "create_comment": {
        "query": """
            mutation ($postId: ID!, $authorName: String!, $text: String!) {
              createComment(postId: $postId, authorName: $authorName, text: $text) {
                ok
                comment { id }
              }
            }
        """,
        "variables": {
            "postId": SINGLE_POST_ID,
            "authorName": "Bench Bot",
            "text": "Benchmark generated comment.",
        },
        "validate": _validate_create_comment,
    },
}


def _installed_versions():
    out = {}
    for pkg in ("graphene-django", "graphene", "django", "graphql-core", "django-filter"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    return out


LIB_VERSIONS = _installed_versions()
