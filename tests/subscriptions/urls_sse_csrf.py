# -*- coding: utf-8 -*-
"""A minimal URLConf mounting the SSE subscription view for the CSRF test.

The real "CsrfViewMiddleware" only runs when a request is dispatched through
the middleware chain (Django's test "Client"), which needs a resolvable route.
This URLConf mounts "subscription_sse_view" at "/graphql/stream" so the CSRF
regression test can POST a subscription document through the full middleware
stack and assert the endpoint is NOT rejected with 403.

The schema is built lazily (on first import) via the same native-schema helper
the transport tests use, so importing this module has no import-time side effect
beyond the shared output registry the suite already relies on.
"""

from __future__ import annotations

from django.urls import path

from django_graphex.subscriptions.transports.sse import subscription_sse_view


def _build_native_schema():
    """Assemble a native subscription schema (a ``post`` SubscriptionField)."""
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType
    from tests.models import Post

    class _CsrfPostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = _CsrfPostModelType.SubscriptionField()

    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


urlpatterns = [
    path("graphql/stream", subscription_sse_view(schema=_build_native_schema())),
]
