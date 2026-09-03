"""Define the canonical django-graphex benchmark schema and operations.

The projected fields, pagination shapes, mutation, and exported operation map
match the shared cross-library contract. The module also exposes the compiled
schema, view, and installed library versions used by benchmark tooling.
"""

from importlib.metadata import PackageNotFoundError, version

from benchapp.models import Author, Comment, Post
from contract import validate_response

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.mutation import DjangoModelMutation
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView


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
    """Expose the projected comment fields used by benchmark operations.

    The available filters match the shared cross-library schema.
    """

    class Meta:
        """Configure the comment model, projection, and filters.

        The projection keeps schema construction comparable across libraries.
        """

        model = Comment
        only_fields = ("id", "author_name", "text", "is_approved", "created_at")
        filter_fields = {"id": ("exact",), "text": ("icontains",)}


class PostType(DjangoObjectType):
    """Expose the projected post fields used by benchmark operations.

    The available filters support the shared flat and filtered workloads.
    """

    class Meta:
        """Configure the post model, projection, and filters.

        The projection includes the relations required by nested workloads.
        """

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
    """Provide the paginated comment list used by nested operations.

    Results use the shared comment cardinality and stable ordering.
    """

    class Meta:
        """Configure the comment list model and pagination policy.

        The default limit matches the shared nested-operation contract.
        """

        model = Comment
        pagination = LimitOffsetGraphqlPagination(default_limit=5, ordering="id")


class PostListType(DjangoListObjectType):
    """Provide the paginated post list used by benchmark operations.

    Results use the shared post cardinality and stable ordering.
    """

    class Meta:
        """Configure the post list model and pagination policy.

        The default limit matches the shared nested-operation contract.
        """

        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="id")


class AuthorType(DjangoObjectType):
    """Expose the projected author fields used by nested operations.

    The available filters match the shared cross-library schema.
    """

    class Meta:
        """Configure the author model, projection, and filters.

        The projection includes posts for the nested benchmark workload.
        """

        model = Author
        only_fields = ("id", "name", "email", "bio", "posts")
        filter_fields = {"id": ("exact",), "name": ("icontains",)}


class AuthorListType(DjangoListObjectType):
    """Provide the paginated author list used by nested operations.

    Results use the shared author cardinality and stable ordering.
    """

    class Meta:
        """Configure the author list model and pagination policy.

        The default limit matches the shared nested-operation contract.
        """

        model = Author
        pagination = LimitOffsetGraphqlPagination(default_limit=20, ordering="id")


# --------------------------------------------------------------------------- #
# Mutation: create_comment                                                    #
# --------------------------------------------------------------------------- #
class CommentMutation(DjangoModelMutation):
    """Expose the create-comment mutation used by the write workload.

    Only creation is enabled to match the shared benchmark contract.
    """

    class Meta:
        """Configure the comment model and allowed mutation operation.

        The mutation intentionally exposes only the create path.
        """

        model = Comment
        model_operations = ("create",)


# --------------------------------------------------------------------------- #
# Query root                                                                  #
# --------------------------------------------------------------------------- #
class Query(ObjectType):
    """Expose the read fields required by benchmark operations.

    The root supports single-post, post-list, and author-list workloads.
    """

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
    """Expose the write field required by the benchmark contract.

    The root provides the canonical create-comment operation.
    """

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
    validate_response("graphex", "flat_list", resp)


def _validate_nested(resp):
    validate_response("graphex", "nested", resp)


def _validate_single(resp):
    validate_response("graphex", "single", resp)


def _validate_filtered(resp):
    validate_response("graphex", "filtered", resp)


def _validate_create_comment(resp):
    validate_response("graphex", "create_comment", resp)


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
