# -*- coding: utf-8 -*-
"""The native subscription schema the transport test modules share.

Both halves of this module exist for the same reason: the output registry is
keyed by MODEL and is last-one-wins, so a second class minted for a model under
the SAME GraphQL type name leaves one holder with its own compiled node while
the registry hands the other's out through the relation graph. A schema that
reaches both then dies with "Schema must contain uniquely named types", and it
only happens under some test orders.

* The four node types below were copied into six transport modules, so six
  classes competed for each of "Tag" / "Category" / "Author" / "Post".
* "build_native_schema" was copied into those same modules and rebuilt its
  "PostModelType" on EVERY call — 85 of them in one suite run — and every
  "DjangoModelType" mints a "<Model>ListGenericType" container whose name the
  library derives from the model, so each call forked "PostListGenericType"
  again, at test-run time, long after other schemas had compiled.

One class per process is the honest answer for both: the transports need Post's
relation targets registered and one assembled schema to serve, not a private
copy per module and per call.
"""

from __future__ import annotations

from functools import lru_cache

from graphql import GraphQLSchema

from django_graphex.types import DjangoObjectType
from tests.models import Author, Category, Post, Tag


class _TagT(DjangoObjectType):
    class Meta:
        model = Tag


class _CategoryT(DjangoObjectType):
    class Meta:
        model = Category


class _AuthorT(DjangoObjectType):
    class Meta:
        model = Author


class _PostT(DjangoObjectType):
    class Meta:
        model = Post


@lru_cache(maxsize=1)
def build_native_schema() -> GraphQLSchema:
    """Assemble the native subscription schema mounting a Post SubscriptionField.

    Memoized: see the module docstring. Every caller only reads the schema, so
    one instance serves them all.

    Returns:
        The assembled GraphQLSchema with a "post" subscription field.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot)
    return schema.graphql_schema


@lru_cache(maxsize=1)
def build_auth_gated_schema() -> GraphQLSchema:  # noqa: DOC005 - nested hook raises
    """Assemble a schema whose subscribe hook READS the user before joining.

    "build_native_schema" mounts the default hooks, which allow everybody and
    therefore never touch "info.context.user" — so a schema built from it
    cannot tell a resolved user from an unresolved lazy one. This one gates on
    "user.is_authenticated", the same shape the playground and every documented
    example use, which is what makes the user resolution observable.

    Memoized for the same reason as "build_native_schema": one class per
    process, or the output registry forks a second node for Post.

    Returns:
        The assembled GraphQLSchema whose "post" subscription denies anyone
        who is not authenticated.
    """
    from graphql import GraphQLBoolean, GraphQLError

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.subscriptions import Subscription

    class _AuthGatedPost(Subscription):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

        @classmethod
        def authorize_subscription(cls, info: object, **kwargs: object) -> None:
            """Deny anyone who is not authenticated.

            Args:
                info: The transport-neutral context the engine passes as info.
                **kwargs: The subscription arguments (unused).

            Raises:
                GraphQLError: When the connection carries no authenticated user.
            """
            user = getattr(getattr(info, "context", None), "user", None)
            if not getattr(user, "is_authenticated", False):
                raise GraphQLError("authentication required")

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = _AuthGatedPost.Field()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot)
    return schema.graphql_schema
