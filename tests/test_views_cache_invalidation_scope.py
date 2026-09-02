# -*- coding: utf-8 -*-
"""Response-cache invalidation scope is global by default and versioned."""

from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.settings import graphql_api_settings
from django_graphex.views import GraphQLView
from tests.cache_helpers import CACHE_ON, graphql_post, minimal_cache_schema


@override_settings(**CACHE_ON)
class GlobalInvalidationScopeTest(TestCase):
    """A mutation invalidates cached reads across every response identity."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user_a = User(pk=1, username="alice")
        self.user_b = User(pk=2, username="bob")
        self.view = GraphQLView.as_view(schema=minimal_cache_schema)
        cache.clear()

    def _mutation(self, user: User) -> None:
        request = graphql_post(
            self.factory, "mutation { doThing { ok } }", user=user
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.view(request)

    def _assert_query_reexecutes(self, user: User | None) -> None:
        original = GraphQLView.super_call
        calls = 0
        def counting_call(
            view: GraphQLView, request: HttpRequest, *args: Any, **kwargs: Any
        ) -> HttpResponse:
            nonlocal calls
            calls += 1
            return original(view, request, *args, **kwargs)
        with patch.object(GraphQLView, "super_call", counting_call):
            self.view(graphql_post(self.factory, "{ hello }", user=user))
        self.assertEqual(calls, 1)

    def test_user_mutation_invalidates_other_response_identities(self) -> None:
        for user in (self.user_b, None):
            cache.clear()
            self.view(graphql_post(self.factory, "{ hello }", user=user))
            self._mutation(self.user_a)
            self._assert_query_reexecutes(user)

    def test_response_key_uses_v2_scope_and_version_namespace(self) -> None:
        cases = (
            ("global", "_graphql_v2_global_global_1_u2_"),
            ("identity", "_graphql_v2_identity_u2_1_u2_"),
        )
        for scope, fragment in cases:
            with self.subTest(scope=scope), self.settings(
                DJANGO_GRAPHEX={
                    "CACHE_ACTIVE": True,
                    "CACHE_TIMEOUT": 60,
                    "CACHE_INVALIDATION_SCOPE": scope,
                }
            ):
                cache.clear()
                stored: list[str] = []
                original_set = cache.set
                def record(key: str, value: Any, *args: Any, **kwargs: Any) -> Any:
                    stored.append(key)
                    return original_set(key, value, *args, **kwargs)
                with patch.object(cache, "set", record):
                    self.view(
                        graphql_post(self.factory, "{ hello }", user=self.user_b)
                    )
                response_keys = [k for k in stored if k.startswith("_graphql_v2_")]
                self.assertEqual(len(response_keys), 1)
                self.assertIn(fragment, response_keys[0])


class InvalidationScopeSettingTest(TestCase):
    """Reject misspelled invalidation policies instead of silently drifting."""

    @override_settings(DJANGO_GRAPHEX={"CACHE_INVALIDATION_SCOPE": "tenant"})
    def test_invalid_scope_raises_improperly_configured(self) -> None:
        with self.assertRaisesMessage(ImproperlyConfigured, "CACHE_INVALIDATION_SCOPE"):
            _ = graphql_api_settings.CACHE_INVALIDATION_SCOPE
