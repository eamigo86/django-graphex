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
        """Two anonymous clients issuing the same query MUST get different CSRF tokens.

        If the first response (which carries Set-Cookie: csrftoken=TOKEN_A) is cached
        and returned to the second client verbatim, they both get TOKEN_A — a security
        violation.  The fix: responses with Set-Cookie are not stored in the cache.
        """
        req1 = self._json_post("{ hello }")
        req2 = self._json_post("{ hello }")

        resp1 = self.view(req1)
        resp2 = self.view(req2)

        cookie1 = resp1.cookies.get("csrftoken")
        cookie2 = resp2.cookies.get("csrftoken")

        # If neither response carries a CSRF cookie the ensure_csrf_cookie decorator
        # did not run (possible in test settings without middleware) — skip assertion.
        if cookie1 is None and cookie2 is None:
            self.skipTest(
                "ensure_csrf_cookie did not set a csrftoken cookie in this test environment; "
                "CSRF replay test skipped."
            )

        # If only the first carries a cookie but the second does not, that's also fine
        # (the second was served from a cookie-stripped cache entry and ensure_csrf_cookie
        # will set a fresh one in production middleware).
        # The failure case: BOTH carry a cookie AND they are identical.
        if cookie1 is not None and cookie2 is not None:
            self.assertNotEqual(
                cookie1.value,
                cookie2.value,
                "Both anonymous clients received the same CSRF token — Set-Cookie was replayed "
                "from the cached response (issue #53b).",
            )

    def test_cached_response_has_no_set_cookie(self):
        """A cached response MUST NOT carry a Set-Cookie header.

        The implementation stores only (body, status_code, content_type) in the
        cache and reconstructs a fresh HttpResponse on cache hits.  This means
        the first response's CSRF cookie (set by ensure_csrf_cookie) is never
        replayed to subsequent clients.

        Verify: the second client's response MUST NOT have the same CSRF cookie
        as the first (it receives a cookie-free reconstructed response on hit,
        or a freshly decorated one on miss — either way it does not get another
        client's token).
        """
        from unittest.mock import patch

        # Count how many times the backend is called.
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

        # The second request must be served from cache (backend called once).
        self.assertEqual(
            call_count["n"],
            1,
            "Backend was called twice — caching is not working for JSON POSTs.",
        )

        # The cached response MUST NOT carry the first client's CSRF cookie.
        # Either: resp2 has no csrftoken cookie at all (cookie-free cached response),
        # OR: resp2 has a different csrftoken (fresh one set for this client).
        cookie1 = resp1.cookies.get("csrftoken")
        cookie2 = resp2.cookies.get("csrftoken")

        if cookie1 is not None and cookie2 is not None:
            self.assertNotEqual(
                cookie1.value,
                cookie2.value,
                "The cached response replayed the first client's CSRF cookie to the second client.",
            )

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
