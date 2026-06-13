# -*- coding: utf-8 -*-
"""Coverage for ``GraphQLView`` branches: cost extension, CLEAN_RESPONSE,
mutation cache invalidation, and ``get_query_cost``.
"""

import json
from unittest.mock import patch

import graphene
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView


class _Query(graphene.ObjectType):
    hello = graphene.String()
    maybe = graphene.String()

    def resolve_hello(root, info):
        return "world"

    def resolve_maybe(root, info):
        return None  # a null field, to exercise CLEAN_RESPONSE pruning


class _CreateThing(graphene.Mutation):
    ok = graphene.Boolean()

    def mutate(root, info):
        return _CreateThing(ok=True)


class _Mutation(graphene.ObjectType):
    create_thing = _CreateThing.Field()


_schema = graphene.Schema(query=_Query, mutation=_Mutation)


class ExtraViewBranchesTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def _post(self, query, view=None):
        view = view or GraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )
        return view(request)

    @patch("django_graphex.views.graphql_api_settings.CLEAN_RESPONSE", True)
    def test_clean_response_prunes_nulls(self):
        response = self._post("{ hello maybe }")
        data = json.loads(response.content)
        # `maybe` was null -> pruned by clean_dict.
        self.assertEqual(data["data"], {"hello": "world"})

    @override_settings(
        DJANGO_GRAPHEX={"EXPOSE_QUERY_COST": True, "MAX_PAGE_SIZE": 1000}
    )
    def test_cost_extension_added(self):
        response = self._post("{ hello }")
        data = json.loads(response.content)
        self.assertIn("extensions", data)
        self.assertIn("cost", data["extensions"])
        self.assertIn("requestedCost", data["extensions"]["cost"])

    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_mutation_bumps_cache_version(self):
        # A mutation must advance the per-user version counter so that
        # subsequent reads by the same identity result in a cache miss.
        # Unrelated cache entries (e.g. keys from other users or non-graphql
        # code) MUST survive — only the namespace version is invalidated.
        #
        # The bump is deferred via transaction.on_commit; captureOnCommitCallbacks
        # is required to flush it inside Django's TestCase transaction wrapper.
        from django.core.cache import caches as _caches

        _cache = _caches["default"]
        # Seed an unrelated key to confirm it is not wiped.
        _cache.set("sentinel", "value")

        # First: cache a query result so a version counter is set.
        view = GraphQLView.as_view(schema=_schema)
        seed_request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        view(seed_request)

        # Record the version token before mutation.
        from django_graphex.views import GraphQLView as _GV

        identity = _GV.cache_key_prefix(seed_request)
        version_key = _GV._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)
        version_before = _cache.get(version_key)

        # Send the mutation inside captureOnCommitCallbacks so the on_commit
        # callback that performs the incr is flushed immediately.
        mut_request = self.factory.post(
            "/graphql/",
            {"query": "mutation { createThing { ok } }"},
            content_type="application/json",
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = view(mut_request)
        self.assertEqual(response.status_code, 200)

        # Version MUST have changed for this identity.
        version_after = _cache.get(version_key)
        self.assertNotEqual(
            version_before,
            version_after,
            "Cache version was not bumped by mutation",
        )

        # The unrelated sentinel key MUST still be present (no global clear).
        self.assertEqual(
            _cache.get("sentinel"),
            "value",
            "Mutation wiped unrelated cache entries (global cache.clear() still used)",
        )

    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_query_cached_and_reused(self):
        first = self._post("{ hello }")
        self.assertEqual(first.status_code, 200)
        # Second identical request should hit the cached response.
        second = self._post("{ hello }")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            json.loads(first.content)["data"], json.loads(second.content)["data"]
        )

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_get_query_cost_returns_payload(self):
        view = GraphQLView()
        view.schema = _schema
        cost = view.get_query_cost("{ hello }", None, None)
        self.assertIsNotNone(cost)
        self.assertIn("requestedCost", cost)
        self.assertIn("maxCost", cost)

    def test_get_query_cost_unparseable_returns_none(self):
        view = GraphQLView()
        view.schema = _schema
        self.assertIsNone(view.get_query_cost("{ this is { not valid", None, None))

    def test_get_operation_ast_no_query_returns_none(self):
        view = GraphQLView()
        request = self.factory.post("/graphql/", {}, content_type="application/json")
        self.assertIsNone(view.get_operation_ast(request))
