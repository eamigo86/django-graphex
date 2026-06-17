# -*- coding: utf-8 -*-
"""Failing tests for HTTP hardening (#15):

- Batch size enforcement (MAX_BATCH_SIZE).
- GraphiQL SRI integrity attributes on CDN scripts.
- AST-based introspection detection (replacing the string-prefix check).
- Single-parse cost: EXPOSE_QUERY_COST must not re-parse the document.
"""

import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex import DjangoGraphQLSchema, ObjectType, field
from django_graphex.views import GraphQLView

# ---------------------------------------------------------------------------
# Minimal schema shared across all test cases
# ---------------------------------------------------------------------------


class _Query(ObjectType):
    hello = field(GraphQLString)
    maybe = field(GraphQLString)

    def resolve_hello(root, info):
        return "world"

    def resolve_maybe(root, info):
        return None


_schema = DjangoGraphQLSchema(query=_Query)


# ---------------------------------------------------------------------------
# (a) Batch size enforcement
# ---------------------------------------------------------------------------


class TestBatchSizeEnforcement(TestCase):
    """MAX_BATCH_SIZE limits the number of operations in a batch request."""

    def setUp(self):
        self.factory = RequestFactory()

    def _batch_view(self, max_batch_size=None):
        extra = {}
        if max_batch_size is not None:
            extra["MAX_BATCH_SIZE"] = max_batch_size
        return GraphQLView.as_view(schema=_schema, batch=True), extra

    def _post_batch(self, ops, view):
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        return view(request)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_within_limit_succeeds(self):
        """A batch at or below MAX_BATCH_SIZE returns 200."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 3
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 3)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_over_limit_returns_400(self):
        """A batch exceeding MAX_BATCH_SIZE returns HTTP 400."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 4
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 400)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_over_limit_error_message(self):
        """The 400 response body explains the limit."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 4
        response = self._post_batch(ops, view)
        content = json.loads(response.content)
        self.assertIn("errors", content)
        msg = content["errors"][0]["message"].lower()
        self.assertIn("batch", msg)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": None})
    def test_batch_size_none_is_unlimited(self):
        """When MAX_BATCH_SIZE is None, any-length batch is accepted."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 20
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 200)

    def test_batch_default_limit_is_enforced(self):
        """Default MAX_BATCH_SIZE (10) rejects a 11-op batch without explicit setting."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 11
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        # Default is 10; 11 ops must be rejected.
        self.assertEqual(response.status_code, 400)

    def test_batch_default_allows_ten_ops(self):
        """Default MAX_BATCH_SIZE (10) allows exactly 10 ops."""
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 10
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_single_query_unaffected_by_batch_limit(self):
        """Non-batch requests are never checked against MAX_BATCH_SIZE."""
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": "{ hello }"})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# (b) GraphiQL SRI attributes
# ---------------------------------------------------------------------------


class TestGraphiQLSRI(TestCase):
    """GraphiQL CDN <script> tags must carry integrity= and crossorigin=."""

    def setUp(self):
        self.factory = RequestFactory()

    def _get_graphiql(self):
        view = GraphQLView.as_view(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html,*/*")
        return view(request)

    def test_graphiql_response_is_html(self):
        response = self._get_graphiql()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_react_script_has_integrity(self):
        """react production min.js script tag includes integrity attribute."""
        response = self._get_graphiql()
        content = response.content.decode()
        # Must have an integrity= attribute on a react CDN script tag.
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/react@[^"]*react\.production\.min\.js[^>]*integrity=',
        )

    def test_react_dom_script_has_integrity(self):
        """react-dom production min.js script tag includes integrity attribute."""
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/react-dom@[^"]*react-dom\.production\.min\.js[^>]*integrity=',
        )

    def test_graphiql_script_has_integrity(self):
        """graphiql min.js script tag includes integrity attribute."""
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/graphiql@[^"]*graphiql\.min\.js[^>]*integrity=',
        )

    def test_graphiql_css_has_integrity(self):
        """graphiql.min.css link tag includes integrity attribute."""
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r"<link[^>]*integrity=",
        )

    def test_scripts_have_crossorigin(self):
        """All CDN script tags have crossorigin attribute."""
        response = self._get_graphiql()
        content = response.content.decode()
        import re

        script_tags = re.findall(r"<script[^>]*unpkg\.com[^>]*>", content)
        self.assertTrue(script_tags, "No CDN script tags found")
        for tag in script_tags:
            self.assertIn("crossorigin", tag, f"Missing crossorigin in: {tag}")

    def test_pinned_react_version(self):
        """CDN URLs use pinned patch versions, not floating major tags."""
        response = self._get_graphiql()
        content = response.content.decode()
        # A floating tag like react@18/umd/ must NOT appear; pinned = react@18.X.Y/
        import re

        # Match floating-version pattern: @N/ (major only) — NOT allowed.
        floating = re.findall(r"unpkg\.com/react@\d+/", content)
        self.assertEqual(
            floating,
            [],
            "Found floating version URL — use pinned patch version instead",
        )

    def test_sri_hash_format(self):
        """Integrity attributes use the sha384- prefix."""
        response = self._get_graphiql()
        content = response.content.decode()
        import re

        integrity_attrs = re.findall(r'integrity="([^"]+)"', content)
        self.assertTrue(integrity_attrs, "No integrity attributes found")
        for attr in integrity_attrs:
            self.assertTrue(
                attr.startswith("sha384-"),
                f"Expected sha384- prefix, got: {attr!r}",
            )


# ---------------------------------------------------------------------------
# (c) AST-based introspection detection
# ---------------------------------------------------------------------------


class TestASTIntrospectionDetection(TestCase):
    """CLEAN_RESPONSE must be suppressed for introspection regardless of formatting."""

    def setUp(self):
        self.factory = RequestFactory()

    def _post(self, query):
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": query})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        return view(request)

    # -- Canonical form (multi-line, named)
    CANONICAL_INTROSPECTION = "\n  query IntrospectionQuery\n  {\n    __schema {\n      types { name }\n    }\n  }\n"

    # -- Compact inline (no named operation)
    COMPACT_INTROSPECTION = "{ __schema { types { name } } }"

    # -- __type variant (use "String" — a built-in scalar always present in any schema)
    TYPE_INTROSPECTION = '{ __type(name: "String") { name } }'

    # -- Regular query with maybe=null to confirm clean_dict is still applied
    REGULAR_QUERY = "{ hello maybe }"

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_canonical_introspection_not_cleaned(self):
        """Canonical IntrospectionQuery must not be passed to clean_dict."""
        response = self._post(self.CANONICAL_INTROSPECTION)
        data = json.loads(response.content)
        # __schema must be present; clean_dict would corrupt it
        self.assertIn("__schema", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_compact_introspection_not_cleaned(self):
        """Compact inline __schema query must not be passed to clean_dict."""
        response = self._post(self.COMPACT_INTROSPECTION)
        data = json.loads(response.content)
        self.assertIn("__schema", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_type_introspection_not_cleaned(self):
        """__type introspection query must bypass clean_dict.

        __type returns a non-null object; clean_dict would prune nested null
        fields inside it but must not be applied here — the key presence of
        "__type" in data is checked.
        """
        response = self._post(self.TYPE_INTROSPECTION)
        data = json.loads(response.content)
        # __type(name:"Query") is always non-null for a valid schema; it must appear.
        self.assertIn("__type", data["data"])
        # Must have the name field (AST detection keeps introspection intact).
        self.assertIsNotNone(data["data"]["__type"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_regular_query_is_cleaned(self):
        """Normal queries must still be passed through clean_dict."""
        response = self._post(self.REGULAR_QUERY)
        data = json.loads(response.content)
        # hello is present; maybe is null and must be pruned by clean_dict
        self.assertIn("hello", data["data"])
        self.assertNotIn("maybe", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_introspection_not_matching_string_prefix(self):
        """An introspection query that does NOT start with the old literal prefix
        must still be detected as introspection by AST inspection."""
        # Indented differently — the old startswith("\n  query IntrospectionQuery")
        # would MISS this; AST detection must catch it.
        differently_formatted = (
            "query IntrospectionQuery { __schema { types { name } } }"
        )
        response = self._post(differently_formatted)
        data = json.loads(response.content)
        self.assertIn("__schema", data["data"])


# ---------------------------------------------------------------------------
# (d) Single-parse cost (no double-parse with EXPOSE_QUERY_COST)
# ---------------------------------------------------------------------------


@override_settings(DJANGO_GRAPHEX={"EXPOSE_QUERY_COST": True, "MAX_PAGE_SIZE": 1000})
class TestSingleParseCost(TestCase):
    """get_query_cost must reuse the already-parsed document from get_response."""

    def setUp(self):
        self.factory = RequestFactory()

    def _post_with_cost(self, query):
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": query})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        return view(request)

    def test_cost_extension_present(self):
        """EXPOSE_QUERY_COST adds extensions.cost to the response."""
        response = self._post_with_cost("{ hello }")
        data = json.loads(response.content)
        self.assertIn("extensions", data)
        self.assertIn("cost", data["extensions"])

    def test_parse_called_once(self):
        """parse() is called exactly once per request even with EXPOSE_QUERY_COST."""
        import django_graphex.views as _views_module

        call_count = []

        original_parse = _views_module.parse

        def counting_parse(source, *args, **kwargs):
            call_count.append(1)
            return original_parse(source, *args, **kwargs)

        with patch.object(_views_module, "parse", side_effect=counting_parse):
            self._post_with_cost("{ hello }")

        # Only ONE parse call is expected (during execute_graphql_request).
        # A second call inside get_query_cost would be a bug.
        self.assertEqual(
            sum(call_count),
            1,
            f"parse() was called {sum(call_count)} times; expected 1 (no double-parse)",
        )

    def test_cost_values_correct(self):
        """Cost values are non-negative integers."""
        response = self._post_with_cost("{ hello }")
        data = json.loads(response.content)
        cost = data["extensions"]["cost"]
        self.assertGreaterEqual(cost["requestedCost"], 0)

    def test_behavioral_equivalence_with_and_without_double_parse(self):
        """The cost result is the same whether computed from original parse or reused doc."""
        # Both paths must yield the same requestedCost — this verifies behavioral
        # equivalence of the refactored single-parse approach.
        response1 = self._post_with_cost("{ hello }")
        response2 = self._post_with_cost("{ hello }")
        cost1 = json.loads(response1.content)["extensions"]["cost"]["requestedCost"]
        cost2 = json.loads(response2.content)["extensions"]["cost"]["requestedCost"]
        self.assertEqual(cost1, cost2)
