# -*- coding: utf-8 -*-
"""Tests for GraphQLView response-cache cross-user isolation (issue #11).

Covers:
- #11a  Cross-user isolation: user A's cached response NOT served to user B
- #11a  Anonymous requests share a single cache entry (no per-anon partitioning)
- #11a  Anon and authenticated requests do NOT share a cache entry
- #11b  Mutation invalidates only the issuing user's namespace; other users'
        cached entries survive
- #11c  Malformed query with CACHE_ACTIVE=True returns HTTP 400, not 500
- #11d  Cache key prefix is ``_graphql_``, not the typo ``_graplql_``
- sentinel  A legitimately cached falsy/empty body is served from cache on
            the second request (no spurious cache miss for falsy values)
"""

import json
from unittest.mock import patch

import graphene
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.http import HttpResponse  # noqa: F401 — used in SentinelHitCheckTest
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView

# ---------------------------------------------------------------------------
# Minimal test schema
# ---------------------------------------------------------------------------


class _Q(graphene.ObjectType):
    me = graphene.String()
    hello = graphene.String()

    def resolve_me(root, info):
        user = info.context.user
        if getattr(user, "is_authenticated", False):
            return user.username
        return "anon"

    def resolve_hello(root, info):
        return "world"


class _M(graphene.ObjectType):
    touch = graphene.Field(lambda: _MutationResult)

    def resolve_touch(root, info):  # pragma: no cover
        pass


class _MutationResult(graphene.ObjectType):
    ok = graphene.Boolean()


class _Mut(graphene.Mutation):
    class Arguments:
        pass

    ok = graphene.Boolean()

    def mutate(root, info):
        return _Mut(ok=True)


class _MutationRoot(graphene.ObjectType):
    do_thing = _Mut.Field()


_schema = graphene.Schema(query=_Q, mutation=_MutationRoot)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}


def _make_request(factory, query, user=None, method="post"):
    """Build a POST or GET request, optionally with an authenticated user."""
    if method == "post":
        body = json.dumps({"query": query})
        req = factory.post("/graphql/", body, content_type="application/json")
    else:
        req = factory.get("/graphql/", {"query": query})
    if user is not None:
        req.user = user
    else:
        req.user = AnonymousUser()
    return req


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class CrossUserIsolationTest(TestCase):
    """#11a — Authenticated user A's cached response MUST NOT be served to user B."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.user_a = User(pk=1, username="alice")
        self.user_b = User(pk=2, username="bob")
        self.view = GraphQLView.as_view(schema=_schema)

    def test_user_a_response_not_served_to_user_b(self):
        """User B MUST receive their own resolver result, not user A's cached data."""
        query = "{ me }"

        # User A populates the cache.
        req_a = _make_request(self.factory, query, user=self.user_a)
        resp_a = self.view(req_a)
        self.assertEqual(resp_a.status_code, 200)
        data_a = json.loads(resp_a.content)
        self.assertEqual(data_a["data"]["me"], "alice")

        # User B makes the same query — MUST get their own result.
        req_b = _make_request(self.factory, query, user=self.user_b)
        resp_b = self.view(req_b)
        self.assertEqual(resp_b.status_code, 200)
        data_b = json.loads(resp_b.content)
        self.assertEqual(
            data_b["data"]["me"],
            "bob",
            "User B received user A's cached response (cross-user leak)",
        )

    def test_same_user_hits_cache_on_second_request(self):
        """The SAME user MUST benefit from caching (second call hits cache)."""
        query = "{ hello }"
        req1 = _make_request(self.factory, query, user=self.user_a)
        req2 = _make_request(self.factory, query, user=self.user_a)

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "Backend was called twice for the same user+query — cache hit failed",
        )

    def test_anon_and_authenticated_do_not_share_cache(self):
        """Anonymous and authenticated requests for the same query body MUST be isolated."""
        query = "{ me }"

        req_auth = _make_request(self.factory, query, user=self.user_a)
        resp_auth = self.view(req_auth)
        data_auth = json.loads(resp_auth.content)
        self.assertEqual(data_auth["data"]["me"], "alice")

        req_anon = _make_request(self.factory, query)  # AnonymousUser
        resp_anon = self.view(req_anon)
        data_anon = json.loads(resp_anon.content)
        self.assertEqual(
            data_anon["data"]["me"],
            "anon",
            "Anonymous request received authenticated user's cached response",
        )


@override_settings(**CACHE_ON)
class AnonSharingTest(TestCase):
    """#11a — Two anonymous requests for the same query MUST share the cache."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_two_anon_requests_share_cache(self):
        """The second anonymous request MUST be served from cache."""
        query = "{ hello }"
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        with patch.object(GraphQLView, "super_call", counting_super_call):
            req1 = _make_request(self.factory, query)
            req2 = _make_request(self.factory, query)
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "Anonymous cache NOT shared: backend called twice for same query",
        )


@override_settings(**CACHE_ON)
class MutationScopedInvalidationTest(TestCase):
    """#11b — Mutation MUST invalidate only the issuing user's namespace.

    User B's cache entries MUST survive when User A sends a mutation.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.user_a = User(pk=1, username="alice")
        self.user_b = User(pk=2, username="bob")
        self.view = GraphQLView.as_view(schema=_schema)

    def test_mutation_does_not_invalidate_other_users_cache(self):
        """User B's cached entry MUST survive User A's mutation."""
        query = "{ hello }"

        # Seed user B's cache first.
        req_b_seed = _make_request(self.factory, query, user=self.user_b)
        self.view(req_b_seed)

        # User A sends a mutation.
        mutation = "mutation { doThing { ok } }"
        req_a_mut = _make_request(self.factory, mutation, user=self.user_a)
        self.view(req_a_mut)

        # User B's second query MUST be served from cache (backend called only
        # once in total for user B's query — during seed, not after mutation).
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        with patch.object(GraphQLView, "super_call", counting_super_call):
            req_b_after = _make_request(self.factory, query, user=self.user_b)
            self.view(req_b_after)

        self.assertEqual(
            call_count["n"],
            0,
            "User A's mutation flushed user B's cache (global cache.clear() used)",
        )


@override_settings(**CACHE_ON)
class MalformedQueryParseGuardTest(TestCase):
    """#11c — A malformed query MUST return HTTP 400, not 500, with CACHE_ACTIVE=True."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_malformed_query_returns_400_with_cache_active(self):
        """Syntactically invalid GraphQL MUST return 400, not raise a 500."""
        malformed = "{ broken {{"
        body = json.dumps({"query": malformed})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(
            response.status_code,
            400,
            f"Expected 400 for malformed query with CACHE_ACTIVE=True, got {response.status_code}",
        )


class CacheKeyPrefixTest(TestCase):
    """#11d — The cache key prefix MUST be ``_graphql_`` (not the typo ``_graplql_``)."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    @override_settings(**CACHE_ON)
    def test_cache_key_uses_correct_prefix(self):
        """Cache entries MUST be stored with the ``_graphql_`` prefix."""
        from django.core.cache import caches as _caches

        stored_keys = []
        real_cache = _caches["default"]
        original_set = real_cache.set

        def capturing_set(key, value, *args, **kwargs):
            stored_keys.append(key)
            return original_set(key, value, *args, **kwargs)

        view = GraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
        )
        request.user = AnonymousUser()

        with patch.object(real_cache, "set", side_effect=capturing_set):
            view(request)

        self.assertTrue(
            any(k.startswith("_graphql_") for k in stored_keys),
            f"No cache key starts with '_graphql_'. Keys stored: {stored_keys}",
        )
        self.assertFalse(
            any(k.startswith("_graplql_") for k in stored_keys),
            f"Old typo prefix '_graplql_' still used. Keys stored: {stored_keys}",
        )


@override_settings(**CACHE_ON)
class SentinelHitCheckTest(TestCase):
    """Sentinel test — a cached falsy/empty body MUST be served from cache.

    The old ``if not response:`` check treats a falsy cached value as a cache
    miss, causing the backend to be called again. The sentinel pattern fixes this.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_empty_cached_response_is_served_without_re_executing(self):
        """A falsy cached value MUST be returned as-is (sentinel cache miss check)."""
        # Pre-seed the cache with an empty-body response (falsy content).
        empty_response = HttpResponse(b"", content_type="application/json", status=200)

        # Seed the cache by running the view once; our patched super_call returns
        # the empty response so that falsy value ends up in the cache.
        query = "{ hello }"
        request_seed = self.factory.post(
            "/graphql/", json.dumps({"query": query}), content_type="application/json"
        )
        request_seed.user = AnonymousUser()

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            # Discard real result; store an empty (falsy) response in its place.
            original_super_call(self_view, request, *args, **kwargs)
            return empty_response

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(request_seed)

        # Now make a second identical request — the empty response is cached.
        # The sentinel check MUST serve it without calling super_call again.
        request_2 = self.factory.post(
            "/graphql/", json.dumps({"query": query}), content_type="application/json"
        )
        request_2.user = AnonymousUser()

        call_count["n"] = 0  # Reset counter
        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(request_2)

        self.assertEqual(
            call_count["n"],
            0,
            "Backend was called for a cached falsy response — sentinel check missing",
        )
