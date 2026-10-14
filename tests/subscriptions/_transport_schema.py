# -*- coding: utf-8 -*-
"""Share one isolated public output graph across subscription transport tests.

The four model node types below form one schema-local Registry group. All
transport modules reuse those classes and one cached native schema, rather
than repeatedly defining distinct public outputs for the same models in one
registry. The paired native output registry preserves relation identity.
"""

from __future__ import annotations

from functools import lru_cache

from graphql import GraphQLSchema

from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_pair
from tests.models import Author, Category, Post, Tag

_TRANSPORT_REGISTRY = Registry()


class _TagT(DjangoObjectType):
    class Meta:
        model = Tag
        registry = _TRANSPORT_REGISTRY


class _CategoryT(DjangoObjectType):
    class Meta:
        model = Category
        registry = _TRANSPORT_REGISTRY


class _AuthorT(DjangoObjectType):
    class Meta:
        model = Author
        registry = _TRANSPORT_REGISTRY


class _PostT(DjangoObjectType):
    class Meta:
        model = Post
        registry = _TRANSPORT_REGISTRY


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
    schema = DjangoGraphQLSchema(
        query=Query,
        subscription=SubscriptionRoot,
        registries=isolated_pair(_TRANSPORT_REGISTRY),
    )
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
    schema = DjangoGraphQLSchema(
        query=Query,
        subscription=SubscriptionRoot,
        registries=isolated_pair(_TRANSPORT_REGISTRY),
    )
    return schema.graphql_schema
