# -*- coding: utf-8 -*-
"""Shared helpers for cache-layer tests.

Several cache/view test files previously redefined an identical minimal
schema (_Q, _Mut, _MutationRoot, _schema) and JSON-POST request builder
independently (approximately 9 files).  All of those definitions are hoisted
here so each test module can import the shared objects instead of duplicating
them.

The schema is intentionally minimal — no real model dependencies — so it is
safe to instantiate with any Django cache backend, including DatabaseCache.

Usage in a test module::

    from tests.cache_helpers import CACHE_ON, graphql_post, minimal_cache_schema

    _schema = minimal_cache_schema  # local alias for readability

NOTE: this module is imported AFTER Django has been configured by
conftest.pytest_configure, so top-level Django imports are safe here.

This schema is built on the NATIVE backend (graphene-free): the public 2.0 API
"django_graphex.ObjectType" + "field()" for the query root, the native
"Mutation" base for the version-bump mutation, and "DjangoGraphQLSchema" for
assembly — a drop-in for the retired "graphene.Schema(query=..., mutation=...)".
The query/mutation/context dispatch behavior its consumers rely on ("{ hello }"
-> "world", "{ me }" -> auth-aware username/"anon" read from
"info.context.user", "mutation { doThing { ok } }" -> "ok == True" to bump
the cache version) is preserved byte-for-byte.
"""

import json
from typing import TYPE_CHECKING, Any

from django.contrib.auth.models import AnonymousUser
from graphql import GraphQLBoolean, GraphQLResolveInfo, GraphQLString

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest
    from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Shared minimal cache schema (native backend)
# ---------------------------------------------------------------------------


class _MinimalQ(ObjectType):
    """Query root for the shared minimal cache test schema."""

    hello = field(GraphQLString)
    me = field(GraphQLString)

    def resolve_hello(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Resolve the "hello" field to a constant greeting.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            The literal string "world".
        """
        return "world"

    def resolve_me(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Resolve the "me" field to the requesting user's username.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info, used to read "info.context.user".

        Returns:
            The authenticated user's username, or "anon" when unauthenticated.
        """
        user = info.context.user
        if getattr(user, "is_authenticated", False):
            return user.username
        return "anon"


class _MinimalMut(Mutation):
    """A no-op mutation used to exercise the cache version-bump path."""

    class Arguments:
        """No arguments are accepted by this mutation."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: Any, info: GraphQLResolveInfo) -> "_MinimalMut":
        """Run the no-op mutation, always reporting success.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            A new instance with "ok" set to True.
        """
        return cls(ok=True)


class _MinimalMutationRoot(ObjectType):
    """Mutation root exposing the shared cache-version-bump mutation."""

    do_thing = _MinimalMut.Field()


#: Shared minimal schema for cache tests.  Import this in any test module that
#: needs a lightweight query+mutation schema without model dependencies.
minimal_cache_schema = DjangoGraphQLSchema(
    query=_MinimalQ, mutation=_MinimalMutationRoot
)

# ---------------------------------------------------------------------------
# Common settings helpers
# ---------------------------------------------------------------------------

#: Override-settings dict for tests that require CACHE_ACTIVE=True.
CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}

#: Response caching with the 3.0 per-identity invalidation policy.
CACHE_ON_IDENTITY = {
    "DJANGO_GRAPHEX": {
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "CACHE_INVALIDATION_SCOPE": "identity",
    }
}

#: Override-settings dict for tests that need a longer CACHE_TIMEOUT (e.g.
#: to exercise TTL-skew bugs where CACHE_TIMEOUT > backend default 300 s).
CACHE_ON_LONG_TIMEOUT = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 600}}

# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


def graphql_post(
    factory: "RequestFactory", query: str, user: "User | AnonymousUser | None" = None
) -> "HttpRequest":
    """Build a JSON-POST GraphQL request via "factory".

    Args:
        factory: The request factory used to build the POST request.
        query: The GraphQL query string to embed in the JSON body.
        user: The Django user to attach to the request; defaults to an
            "AnonymousUser" when not given.

    Returns:
        A request ready to be dispatched to a view.
    """
    body = json.dumps({"query": query})
    req = factory.post("/graphql/", body, content_type="application/json")
    req.user = user if user is not None else AnonymousUser()
    return req
