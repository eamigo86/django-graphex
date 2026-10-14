"""Regression tests for body-size enforcement before response-cache work."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings

from django_graphex import views as views_module
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView
from tests.cache_helpers import minimal_cache_schema

_QUERY = "{ hello }"
_BODY = json.dumps({"query": _QUERY}).encode()
_CACHE_CAP = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "MAX_REQUEST_BODY_SIZE": 8}}


class CacheActiveBodyCapTests(TestCase):
    """Apply the existing body cap before cache-active document work.

    Exercise the real endpoint with isolated parse and response caches.
    """

    def setUp(self) -> None:
        """Reset only the caches exercised by this request-boundary suite.

        Each test starts without retained documents or responses.
        """
        cache.clear()
        views_module.clear_document_caches()
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=minimal_cache_schema)

    def tearDown(self) -> None:
        """Remove entries created by these requests before the next test.

        Cache state is not allowed to influence unrelated test modules.
        """
        cache.clear()
        views_module.clear_document_caches()

    def _post(self, body: bytes = _BODY) -> HttpRequest:
        """Build a JSON POST with an anonymous request principal.

        Args:
            body: Raw request body to dispatch.

        Returns:
            A fresh request with a test-local anonymous principal.
        """
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()
        return request

    @override_settings(**_CACHE_CAP)
    def test_oversized_cache_active_body_is_rejected_before_parse_or_cache(
        self,
    ) -> None:
        """Reject a 22-byte body at cap eight before any GraphQL/cache work.

        A status-only assertion would miss the original parse/cache ordering bug.
        """
        with (
            patch.object(views_module, "parse", wraps=views_module.parse) as parse_spy,
            patch.object(cache, "get", wraps=cache.get) as get_spy,
            patch.object(cache, "set", wraps=cache.set) as set_spy,
        ):
            response = self.view(self._post())

        self.assertEqual(response.status_code, 413)
        self.assertEqual(parse_spy.call_count, 0)
        self.assertEqual(get_spy.call_count, 0)
        self.assertEqual(set_spy.call_count, 0)
        self.assertFalse(views_module._PARSE_CACHE)
        self.assertFalse(views_module._VALIDATE_CACHE)

    @override_settings(
        DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "MAX_REQUEST_BODY_SIZE": len(_BODY)}
    )
    def test_body_at_cap_still_warms_and_hits_response_cache(self) -> None:
        """Allow an exactly bounded query and preserve its later cache hit.

        Equality with the cap must not be mistaken for an oversized request.
        """
        with patch.object(views_module, "parse", wraps=views_module.parse) as spy:
            first = self.view(self._post())
            second = self.view(self._post())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(json.loads(first.content), json.loads(second.content))
        self.assertEqual(spy.call_count, 1)

    @override_settings(
        DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "MAX_REQUEST_BODY_SIZE": len(_BODY)}
    )
    def test_tightened_cap_rejects_an_already_cached_query(self) -> None:
        """Refuse a previously cached query after the configured cap tightens.

        A response hit must not bypass the current request's body limit.
        """
        self.assertEqual(self.view(self._post()).status_code, 200)
        with override_settings(DJANGO_GRAPHEX=_CACHE_CAP["DJANGO_GRAPHEX"]):
            with (
                patch.object(cache, "get", wraps=cache.get) as get_spy,
                patch.object(cache, "set", wraps=cache.set) as set_spy,
            ):
                response = self.view(self._post())
        self.assertEqual(response.status_code, 413)
        self.assertEqual(get_spy.call_count, 0)
        self.assertEqual(set_spy.call_count, 0)

    @override_settings(**_CACHE_CAP)
    def test_spoofed_low_content_length_still_rejects_actual_body(self) -> None:
        """Use the actual body length when a client understates its size.

        The cache-active preflight retains the base guard's second stage.
        """
        request = self._post()
        request.META["CONTENT_LENGTH"] = "1"
        with patch.object(views_module, "parse", wraps=views_module.parse) as spy:
            response = self.view(request)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(spy.call_count, 0)

    @override_settings(
        DJANGO_GRAPHEX={"CACHE_ACTIVE": False, "MAX_REQUEST_BODY_SIZE": 8}
    )
    def test_cache_disabled_retains_early_base_view_rejection(self) -> None:
        """Keep the existing cache-off 413 and zero-parse behavior.

        This is the original control path, not the regression path.
        """
        with patch.object(views_module, "parse", wraps=views_module.parse) as spy:
            response = self.view(self._post())
        self.assertEqual(response.status_code, 413)
        self.assertEqual(spy.call_count, 0)

    @override_settings(
        DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "MAX_REQUEST_BODY_SIZE": None}
    )
    def test_disabled_cap_allows_the_same_query(self) -> None:
        """Retain the opt-out setting without an implicit new body limit.

        A configured None remains distinct from the finite cap.
        """
        response = self.view(self._post())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    @override_settings(**_CACHE_CAP)
    def test_get_with_invalid_body_keeps_bad_request_not_body_cap(self) -> None:
        """Preserve the GET body parse error without applying the POST cap.

        Invalid JSON still fails as 400 rather than a new size-based 413.
        """
        request = self.factory.generic(
            "GET",
            "/graphql/?query=%7B%20hello%20%7D",
            data=b"x" * 16,
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.status_code, 413)

    @override_settings(**_CACHE_CAP)
    def test_authentication_denial_precedes_body_cap(self) -> None:
        """Retain endpoint permission precedence over body-size refusal.

        Anonymous access is denied before the inherited cache-active preflight.
        """
        view = AuthenticatedGraphQLView.as_view(schema=minimal_cache_schema)
        response = view(self._post())
        self.assertEqual(response.status_code, 403)
