"""Implement the shared benchmark contract with Graphene-Django.

The adapter returns the same rows and fields as the Graphex reference while
using Graphene-Django's idiomatic query shape. DjangoObjectType exposes each
model, Relay connections provide list access, django-filter powers the filtered
operation, a raw database identifier selects a single post, and a plain
Graphene mutation creates comments.

The nested workload deliberately relies on default resolvers. Graphene-Django
does not include automatic query optimization, so its expected N+1 behavior is
part of the fair out-of-the-box comparison. The module exports graphql_view,
OPERATIONS, LIB_VERSIONS, and schema for the benchmark harness and tooling.
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
    """Expose benchmark comments as Relay nodes.

    The field set matches the shared response contract.
    """

    class Meta:
        """Map the comment model and fields to Relay.

        The benchmark uses the default Graphene-Django mapping behavior.
        """

        model = Comment
        fields = ("id", "author_name", "text", "is_approved", "created_at")
        interfaces = (relay.Node,)


class PostType(DjangoObjectType):
    """Expose benchmark posts and their relations as Relay nodes.

    The type supports every list and single-post benchmark operation.
    """

    class Meta:
        """Map the post model, relations, and supported filters.

        Filtering remains limited to fields exercised by the workload.
        """

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
    """Expose authors and their posts as Relay nodes.

    Nested benchmark queries traverse the declared posts relation.
    """

    class Meta:
        """Map the author model and fields to Relay.

        The benchmark keeps Graphene-Django's default relation resolvers.
        """

        model = Author
        fields = ("id", "name", "email", "bio", "posts")
        interfaces = (relay.Node,)


# --------------------------------------------------------------------------- #
# Mutation: create_comment (plain graphene Mutation — the simplest doc form)   #
# --------------------------------------------------------------------------- #
class CreateComment(graphene.Mutation):
    """Create a comment through the shared mutation workload.

    The mutation returns the created comment and a success indicator.
    """

    class Arguments:
        """Declare inputs required by the comment mutation.

        Each input mirrors the variables in the shared operation contract.
        """

        post_id = graphene.ID(required=True)
        author_name = graphene.String(required=True)
        text = graphene.String(required=True)

    ok = graphene.Boolean()
    comment = graphene.Field(CommentType)

    def mutate(
        self,
        info: object,
        post_id: int | str,
        author_name: str,
        text: str,
    ) -> "CreateComment":
        """Persist a comment and return the mutation payload.

        Args:
            info: Resolver context supplied by Graphene.
            post_id: Database identifier of the parent post.
            author_name: Name attached to the new comment.
            text: Comment body used by the workload.

        Returns:
            The payload containing the created comment and success state.
        """
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
    """Expose the benchmark read operations through Graphene.

    Relay connections serve list workloads and post serves raw identifiers.
    """

    # single object by raw database pk (equivalent to the reference's post(id:))
    post = graphene.Field(PostType, id=graphene.ID(required=True))

    # list access via Relay connections (graphene-django's documented default).
    # ``posts`` is a filtered connection (django-filter) used by both flat_list
    # and filtered; ``authors`` is a plain connection used by nested.
    posts = DjangoFilterConnectionField(PostType)
    authors = DjangoConnectionField(AuthorType)

    def resolve_post(self, info: object, id: int | str) -> Post | None:
        """Resolve one post from its database identifier.

        Args:
            info: Resolver context supplied by Graphene.
            id: Database identifier requested by the operation.

        Returns:
            The matching post, or None when it does not exist.
        """
        return Post.objects.filter(pk=id).first()


class Mutation(graphene.ObjectType):
    """Expose the benchmark mutation entry point.

    The field delegates comment creation to CreateComment.
    """

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
