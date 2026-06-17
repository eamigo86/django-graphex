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
``django_graphex.ObjectType`` + ``field()`` for the query root, the native
``Mutation`` base for the version-bump mutation, and ``DjangoGraphQLSchema`` for
assembly — a drop-in for the retired ``graphene.Schema(query=..., mutation=...)``.
The query/mutation/context dispatch behavior its consumers rely on (``{ hello }``
-> ``"world"``, ``{ me }`` -> auth-aware username/``"anon"`` read from
``info.context.user``, ``mutation { doThing { ok } }`` -> ``ok == True`` to bump
the cache version) is preserved byte-for-byte.
"""

import json

from django.contrib.auth.models import AnonymousUser
from graphql import GraphQLBoolean, GraphQLString

from django_graphex import DjangoGraphQLSchema, Mutation, ObjectType, field

# ---------------------------------------------------------------------------
# Shared minimal cache schema (native backend)
# ---------------------------------------------------------------------------


class _MinimalQ(ObjectType):
    """Query root for the shared minimal cache test schema."""

    hello = field(GraphQLString)
    me = field(GraphQLString)

    def resolve_hello(root, info):  # noqa: N805
        return "world"

    def resolve_me(root, info):  # noqa: N805
        user = info.context.user
        if getattr(user, "is_authenticated", False):
            return user.username
        return "anon"


class _MinimalMut(Mutation):
    """A no-op mutation used to exercise the cache version-bump path."""

    class args:
        pass

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root, info):
        return cls(ok=True)


class _MinimalMutationRoot(ObjectType):
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

#: Override-settings dict for tests that need a longer CACHE_TIMEOUT (e.g.
#: to exercise TTL-skew bugs where CACHE_TIMEOUT > backend default 300 s).
CACHE_ON_LONG_TIMEOUT = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 600}}

# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


def graphql_post(factory, query, user=None):
    """Build a JSON-POST GraphQL request via *factory*.

    Args:
        factory: A :class:`django.test.RequestFactory` instance.
        query: GraphQL query string (str).
        user: Optional Django user; defaults to
            :class:`~django.contrib.auth.models.AnonymousUser`.

    Returns:
        A :class:`django.http.HttpRequest` ready to be dispatched to a view.
    """
    body = json.dumps({"query": query})
    req = factory.post("/graphql/", body, content_type="application/json")
    req.user = user if user is not None else AnonymousUser()
    return req
