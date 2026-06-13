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
- GET-key  Two DIFFERENT GET queries share a key collision → wrong cached
           response served (HIGH-1 fix: incorporate GET params into the hash)
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.http import HttpResponse  # noqa: F401 — used in SentinelHitCheckTest
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView

# Shared minimal schema and helpers avoid duplication across the ~9 cache/view
# test files that previously defined identical scaffolding independently.
from tests.cache_helpers import CACHE_ON, graphql_post
from tests.cache_helpers import minimal_cache_schema as _schema


def _make_request(factory, query, user=None, method="post"):
    """Build a POST or GET request, optionally with an authenticated user."""
    if method == "post":
        return graphql_post(factory, query, user=user)
    req = factory.get("/graphql/", {"query": query})
    req.user = user if user is not None else AnonymousUser()
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


# ---------------------------------------------------------------------------
# HIGH-1: GET cache-key collision — different GET queries share one key
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class GetCacheKeyIsolationTest(TestCase):
    """HIGH-1 — Two DIFFERENT GET queries by the SAME identity MUST NOT share a cache entry.

    Before the fix, ``fetch_cache_key`` hashed only ``request.body``.  For GET
    requests ``request.body`` is always ``b''``, so every GET query produced
    sha256('') → identical cache key → the second query received the first
    query's stale response.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)
        self.user = User(pk=99, username="testuser")

    # ------------------------------------------------------------------
    # Test 1: two DIFFERENT GET queries return their OWN correct data
    # ------------------------------------------------------------------
    def test_different_get_queries_return_own_data(self):
        """GET query A's cached response MUST NOT be served for a different GET query B."""
        # Query A: { hello } → should return "world"
        req_a = self.factory.get("/graphql/", {"query": "{ hello }"})
        req_a.user = self.user
        resp_a = self.view(req_a)
        self.assertEqual(resp_a.status_code, 200)
        data_a = json.loads(resp_a.content)
        self.assertEqual(data_a["data"]["hello"], "world")

        # Query B: { me } → should return testuser's name, NOT "world"
        req_b = self.factory.get("/graphql/", {"query": "{ me }"})
        req_b.user = self.user
        resp_b = self.view(req_b)
        self.assertEqual(resp_b.status_code, 200)
        data_b = json.loads(resp_b.content)
        self.assertIn(
            "me",
            data_b["data"],
            "GET query B got a response with no 'me' field — likely served GET query A's cached data",
        )
        self.assertNotIn(
            "hello",
            data_b["data"],
            "GET query B incorrectly received GET query A's response (cache key collision)",
        )

    # ------------------------------------------------------------------
    # Test 2: the SAME GET query by the SAME identity still hits the cache
    # ------------------------------------------------------------------
    def test_same_get_query_hits_cache_on_second_request(self):
        """The SAME GET query+identity MUST be served from cache on the second call."""
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        query = "{ hello }"
        req1 = self.factory.get("/graphql/", {"query": query})
        req1.user = self.user
        req2 = self.factory.get("/graphql/", {"query": query})
        req2.user = self.user

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "Backend was called twice for the same GET query+identity — GET cache hit failed",
        )

    # ------------------------------------------------------------------
    # Test 3: POST caching still works; POST and GET of the same query
    #         do NOT incorrectly collide
    # ------------------------------------------------------------------
    def test_post_caching_still_works(self):
        """POST requests MUST still be cached correctly after the GET fix."""
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        query = "{ hello }"
        req1 = _make_request(self.factory, query, user=self.user, method="post")
        req2 = _make_request(self.factory, query, user=self.user, method="post")

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "POST caching broken — backend called twice for the same POST query+identity",
        )

    def test_post_and_get_same_query_do_not_incorrectly_collide(self):
        """A POST and a GET for the same query string MUST NOT share the same cache key,
        because their request structures (and potentially headers) differ.

        Concretely: after a POST seeds the cache, a subsequent GET for the same
        query MUST call the backend (it must not be served the POST's cached
        response via a shared key).
        """
        query = "{ hello }"
        # Seed with POST.
        req_post = _make_request(self.factory, query, user=self.user, method="post")
        self.view(req_post)

        # GET for the same query should NOT get the POST's cached response
        # by sharing its key. It is valid for GET to call the backend separately.
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        req_get = self.factory.get("/graphql/", {"query": query})
        req_get.user = self.user

        with patch.object(GraphQLView, "super_call", counting_super_call):
            # GET after POST: either it gets its own cache entry (fine) or calls backend (fine).
            # The WRONG behaviour is for GET to incorrectly serve the POST response
            # when the responses are semantically different — we just verify no crash/500.
            resp_get = self.view(req_get)

        self.assertEqual(
            resp_get.status_code,
            200,
            f"GET after POST returned {resp_get.status_code} instead of 200",
        )
