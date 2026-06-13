# -*- coding: utf-8 -*-
"""Regression tests for cache multipart 500 + CSRF cookie replay (issue #53).

(a) MULTIPART POST 500: with CACHE_ACTIVE=True, a multipart/form-data GraphQL
    query POST raises RawPostDataException → HTTP 500.
    Fix: bypass the response cache for multipart content types (fall through to
    super_call uncached), mirroring the existing batch bypass.

(b) CSRF/Set-Cookie REPLAY: a cached HttpResponse carries Set-Cookie (CSRF
    token); subsequent clients in the same identity namespace receive the first
    client's cookie verbatim.
    Fix: do not cache responses that carry Set-Cookie headers; let ensure_csrf_cookie
    set a fresh token on each response.

(c) Normal JSON POST/GET requests continue to be cached correctly (regression guard).
"""

import json

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView

# Shared minimal schema and helpers avoid duplication across the ~9 cache/view
# test files that previously defined identical scaffolding independently.
from tests.cache_helpers import CACHE_ON
from tests.cache_helpers import minimal_cache_schema as _schema

# ---------------------------------------------------------------------------
# (a) Multipart POST with CACHE_ACTIVE=True must not raise RawPostDataException
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class MultipartCacheBypassTest(TestCase):
    """#53a — multipart/form-data query POST under CACHE_ACTIVE=True must return 200.

    The old code called get_operation_ast(request) which invoked parse_body → request.POST
    (consuming the WSGI input stream), then fetch_cache_key(request) tried to read
    request.body → RawPostDataException → HTTP 500.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_multipart_query_post_returns_200_not_500(self):
        """A multipart/form-data query POST MUST return HTTP 200 (not 500)."""
        request = self.factory.post(
            "/graphql/",
            data={"query": "{ hello }"},
            # Django's RequestFactory uses multipart/form-data when data is a dict
            # without an explicit content_type — equivalent to a browser form POST.
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(
            response.status_code,
            200,
            f"Multipart query POST under CACHE_ACTIVE=True returned {response.status_code} "
            f"(expected 200; likely RawPostDataException → 500)",
        )

    def test_multipart_query_post_returns_valid_graphql_response(self):
        """The multipart bypass MUST still execute and return the GraphQL result."""
        request = self.factory.post(
            "/graphql/",
            data={"query": "{ hello }"},
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("data", data)
        self.assertEqual(data["data"]["hello"], "world")

    def test_json_post_still_caches(self):
        """Normal JSON POST requests MUST still be served from cache on second call."""
        from unittest.mock import patch

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        body = json.dumps({"query": "{ hello }"})
        req1 = self.factory.post("/graphql/", body, content_type="application/json")
        req2 = self.factory.post("/graphql/", body, content_type="application/json")
        req1.user = AnonymousUser()
        req2.user = AnonymousUser()

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "JSON POST caching broken — backend called twice for the same query",
        )

    def test_multipart_query_is_not_cached(self):
        """Multipart requests MUST NOT be cached (bypass falls through to super_call each time)."""
        from unittest.mock import patch

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        req1 = self.factory.post("/graphql/", data={"query": "{ hello }"})
        req2 = self.factory.post("/graphql/", data={"query": "{ hello }"})
        req1.user = AnonymousUser()
        req2.user = AnonymousUser()

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            2,
            "Multipart request was unexpectedly cached (second call did not reach backend)",
        )


# ---------------------------------------------------------------------------
# (b) Cached response MUST NOT replay Set-Cookie to other clients
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class CsrfCookieReplayTest(TestCase):
    """#53b — a cached response MUST NOT replay a Set-Cookie header to other clients.

    BaseGraphQLView.dispatch is decorated with @method_decorator(ensure_csrf_cookie),
    which adds Set-Cookie: csrftoken=<secret> to every response.  If the whole
    HttpResponse object is cached and returned verbatim to the second client, they
    share one CSRF secret.

    Fix: do not cache responses that carry Set-Cookie headers.  Each client's
    response goes through ensure_csrf_cookie and gets its own fresh token.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def _json_post(self, query):
        body = json.dumps({"query": query})
        req = self.factory.post("/graphql/", body, content_type="application/json")
        req.user = AnonymousUser()
        return req

    def test_two_anonymous_clients_get_distinct_csrf_tokens(self):
        """Two anonymous clients issuing the same query MUST NOT share a CSRF token.

        Regression guard: if the whole HttpResponse were cached and returned
        verbatim the second client would receive the first client's CSRF token
        (a security violation, issue #53b).  The fix stores only
        (body, status_code, content_type) and reconstructs a cookie-free
        HttpResponse on cache hits — so resp2 MUST have no Set-Cookie header.

        This test MUST fail if cookie-stripping were reverted (i.e. if the
        cached HttpResponse were returned directly, resp2 would carry cookie1's
        token and assertNotIn would catch it).
        """
        from unittest.mock import patch

        # Track how many times the backend resolver is called.
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        req1 = self._json_post("{ hello }")
        req2 = self._json_post("{ hello }")

        with patch.object(GraphQLView, "super_call", counting_super_call):
            resp1 = self.view(req1)
            resp2 = self.view(req2)

        # The backend MUST have been called exactly once (cache hit on req2).
        self.assertEqual(
            call_count["n"],
            1,
            "Backend was called twice — caching is not working for JSON POSTs.",
        )

        # The cached response MUST NOT carry any Set-Cookie header.
        # If the implementation regresses to caching the live HttpResponse, resp2
        # would inherit resp1's CSRF cookie and this assertion would fail.
        self.assertNotIn(
            "Set-Cookie",
            resp2,
            "The cached response carries a Set-Cookie header — "
            "it replays the first client's CSRF token to subsequent clients (issue #53b).",
        )
        self.assertEqual(
            dict(resp2.cookies),
            {},
            "resp2 cookies dict is non-empty — Set-Cookie was replayed from the cache.",
        )

    def test_cached_response_has_no_set_cookie(self):
        """A cached response MUST NOT carry a Set-Cookie header.

        The implementation stores only (body, status_code, content_type) and
        reconstructs a fresh HttpResponse on cache hits — so the cache hit
        response (resp2) carries ZERO cookies, regardless of whether the
        original cache-miss response (resp1) carried a CSRF cookie.

        Regression guard: this test MUST fail if the implementation reverted
        to caching and replaying the live HttpResponse object (resp2 would
        then carry resp1's CSRF cookie and assertNotIn would catch it).
        """
        from unittest.mock import patch

        # Count how many times the backend resolver is called.
        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        req1 = self._json_post("{ hello }")
        req2 = self._json_post("{ hello }")

        with patch.object(GraphQLView, "super_call", counting_super_call):
            resp1 = self.view(req1)  # cache miss — super_call runs, result cached
            resp2 = self.view(req2)  # cache hit  — super_call NOT called again

        # The backend MUST have been called exactly once (cache hit on req2).
        self.assertEqual(
            call_count["n"],
            1,
            "Backend was called twice — caching is not working for JSON POSTs.",
        )

        # resp2 is reconstructed from a (body, status_code, content_type) tuple
        # and MUST have no Set-Cookie header — unconditional assertion.
        self.assertNotIn(
            "Set-Cookie",
            resp2,
            "The cached response carries a Set-Cookie header — "
            "the live HttpResponse was returned verbatim instead of being reconstructed.",
        )
        self.assertEqual(
            dict(resp2.cookies),
            {},
            "resp2 cookies dict is non-empty — "
            "cookie-stripping from cached responses is broken.",
        )

        # Bonus: resp1 (cache miss) may have a CSRF cookie — that is expected
        # behaviour (ensure_csrf_cookie ran on the real super_call response).
        # We do not assert anything about resp1.cookies; that is not the SUT here.
        _ = resp1  # kept in scope for clarity

    def test_cookie_free_response_is_still_cached(self):
        """A response WITHOUT Set-Cookie MUST still be cached normally.

        Ensure the fix does not break the happy-path caching for responses that
        don't carry a Set-Cookie header.
        """
        from unittest.mock import patch

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            response = original_super_call(self_view, request, *args, **kwargs)
            # Explicitly clear any cookies the ensure_csrf_cookie decorator may
            # have set, so the response is cookie-free.
            response.cookies.clear()
            return response

        req1 = self._json_post("{ hello }")
        req2 = self._json_post("{ hello }")

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(req1)
            self.view(req2)

        self.assertEqual(
            call_count["n"],
            1,
            "Cookie-free response was NOT cached — normal caching behaviour is broken.",
        )
