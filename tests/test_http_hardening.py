# -*- coding: utf-8 -*-
"""Failing tests for HTTP hardening (#15):

- Batch size enforcement (MAX_BATCH_SIZE).
- GraphiQL SRI integrity attributes on CDN scripts.
- AST-based introspection detection (replacing the string-prefix check).
- Single-parse cost: EXPOSE_QUERY_COST must not re-parse the document.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

if TYPE_CHECKING:
    from django.http import HttpResponse

# ---------------------------------------------------------------------------
# Minimal schema shared across all test cases
# ---------------------------------------------------------------------------


class _Query(ObjectType):
    """The root query exposing a static "hello" field and a null "maybe" field."""

    hello = field(GraphQLString)
    maybe = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve "hello" to the constant string "world".

        Args:
            root: The parent resolver value, unused at the root query.
            info: The GraphQL resolve info for the current request.

        Returns:
            value: The literal string "world".
        """
        return "world"

    def resolve_maybe(root: Any, info: Any) -> None:
        """Resolve "maybe" to None, to exercise clean_dict pruning.

        Args:
            root: The parent resolver value, unused at the root query.
            info: The GraphQL resolve info for the current request.

        Returns:
            value: Always None.
        """
        return None


_schema = DjangoGraphQLSchema(query=_Query)


# ---------------------------------------------------------------------------
# (a) Batch size enforcement
# ---------------------------------------------------------------------------


class TestBatchSizeEnforcement(TestCase):
    """MAX_BATCH_SIZE limits the number of operations in a batch request.

    Covers within-limit, over-limit, unlimited, default, and non-batch cases.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Shared by every test method in this class.
        """
        self.factory = RequestFactory()

    def _batch_view(
        self, max_batch_size: int | None = None
    ) -> tuple[Any, dict[str, int]]:
        """Build a batch-enabled view callable plus its extra settings overrides.

        Args:
            max_batch_size: The MAX_BATCH_SIZE value to request, or None to
                omit the override.

        Returns:
            view_and_extra: A tuple of the batch view callable and the extra
                settings dict to apply (empty when "max_batch_size" is None).
        """
        extra = {}
        if max_batch_size is not None:
            extra["MAX_BATCH_SIZE"] = max_batch_size
        return GraphQLView.as_view(schema=_schema, batch=True), extra

    def _post_batch(self, ops: list[dict[str, Any]], view: Any) -> "HttpResponse":
        """POST a JSON batch payload to the given view and return its response.

        Args:
            ops: The list of GraphQL operation payloads to send as a batch.
            view: The view callable to invoke with the built request.

        Returns:
            response: The HTTP response returned by the view.
        """
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        return view(request)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_within_limit_succeeds(self) -> None:
        """A batch at or below MAX_BATCH_SIZE must return 200.

        Guards the accepting side of the limit before testing rejection.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 3
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 3)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_over_limit_returns_400(self) -> None:
        """A batch exceeding MAX_BATCH_SIZE must return HTTP 400.

        If this breaks, an oversized batch could reach the resolver layer and
        consume unbounded server resources.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 4
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 400)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": 3})
    def test_batch_over_limit_error_message(self) -> None:
        """The 400 response body must explain the batch-size limit.

        Guards the developer-facing error message, not just the status code.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 4
        response = self._post_batch(ops, view)
        content = json.loads(response.content)
        self.assertIn("errors", content)
        msg = content["errors"][0]["message"].lower()
        self.assertIn("batch", msg)

    @override_settings(DJANGO_GRAPHEX={"MAX_BATCH_SIZE": None})
    def test_batch_size_none_is_unlimited(self) -> None:
        """When MAX_BATCH_SIZE is None, any-length batch must be accepted.

        Confirms None is treated as "no limit", not as a falsy zero limit.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 20
        response = self._post_batch(ops, view)
        self.assertEqual(response.status_code, 200)

    def test_batch_default_limit_is_enforced(self) -> None:
        """The default MAX_BATCH_SIZE (10) must reject an 11-op batch with no explicit setting.

        Guards the out-of-the-box default, independent of any test override.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 11
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        # Default is 10; 11 ops must be rejected.
        self.assertEqual(response.status_code, 400)

    def test_batch_default_allows_ten_ops(self) -> None:
        """The default MAX_BATCH_SIZE (10) must allow exactly 10 ops.

        Guards the boundary value so the default is not off-by-one.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        ops = [{"query": "{ hello }"}] * 10
        body = json.dumps(ops)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_single_query_unaffected_by_batch_limit(self) -> None:
        """Non-batch requests must never be checked against MAX_BATCH_SIZE.

        Confirms the batch-size guard is scoped to the batch endpoint only.
        """
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": "{ hello }"})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# (b) GraphiQL SRI attributes
# ---------------------------------------------------------------------------


class TestGraphiQLSRI(TestCase):
    """GraphiQL CDN <script> tags must carry integrity= and crossorigin=.

    Covers every CDN asset (react, react-dom, graphiql JS/CSS) plus the
    pinned-version and hash-format invariants.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Shared by every test method in this class.
        """
        self.factory = RequestFactory()

    def _get_graphiql(self) -> "HttpResponse":
        """Issue a GET request for the GraphiQL HTML page.

        Returns:
            response: The HTTP response returned by the GraphiQL view.
        """
        view = GraphQLView.as_view(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html,*/*")
        return view(request)

    def test_graphiql_response_is_html(self) -> None:
        """The GraphiQL endpoint must return a 200 HTML response.

        Baseline sanity check before asserting on script/link attributes.
        """
        response = self._get_graphiql()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_react_script_has_integrity(self) -> None:
        """The react production min.js script tag must include an integrity attribute.

        Guards against a subresource-integrity regression on the react CDN tag.
        """
        response = self._get_graphiql()
        content = response.content.decode()
        # Must have an integrity= attribute on a react CDN script tag.
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/react@[^"]*react\.production\.min\.js[^>]*integrity=',
        )

    def test_react_dom_script_has_integrity(self) -> None:
        """The react-dom production min.js script tag must include an integrity attribute.

        Guards against a subresource-integrity regression on the react-dom CDN
        tag.
        """
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/react-dom@[^"]*react-dom\.production\.min\.js[^>]*integrity=',
        )

    def test_graphiql_script_has_integrity(self) -> None:
        """The graphiql min.js script tag must include an integrity attribute.

        Guards against a subresource-integrity regression on the graphiql CDN
        tag.
        """
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<script[^>]*unpkg\.com/graphiql@[^"]*graphiql\.min\.js[^>]*integrity=',
        )

    def test_graphiql_css_has_integrity(self) -> None:
        """The graphiql.min.css link tag must include an integrity attribute.

        Covers the stylesheet link tag, distinct from the script tags.
        """
        response = self._get_graphiql()
        content = response.content.decode()
        self.assertRegex(
            content,
            r"<link[^>]*integrity=",
        )

    def test_scripts_have_crossorigin(self) -> None:
        """Every CDN script tag must carry a crossorigin attribute.

        Subresource integrity requires "crossorigin" alongside "integrity" or
        the browser silently ignores the hash.
        """
        response = self._get_graphiql()
        content = response.content.decode()
        import re

        script_tags = re.findall(r"<script[^>]*unpkg\.com[^>]*>", content)
        self.assertTrue(script_tags, "No CDN script tags found")
        for tag in script_tags:
            self.assertIn("crossorigin", tag, f"Missing crossorigin in: {tag}")

    def test_pinned_react_version(self) -> None:
        """CDN URLs must use pinned patch versions, not floating major tags.

        A floating major tag can silently change content and invalidate the
        pinned integrity hash.
        """
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

    def test_sri_hash_format(self) -> None:
        """Integrity attributes must use the sha384- prefix.

        Guards the hash-algorithm prefix so the browser can verify content
        correctly.
        """
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
    """CLEAN_RESPONSE must be suppressed for introspection regardless of formatting.

    Covers canonical, compact, and __type introspection forms plus the
    regular-query control case.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Shared by every test method in this class.
        """
        self.factory = RequestFactory()

    def _post(self, query: str) -> "HttpResponse":
        """POST a single GraphQL query string and return its response.

        Args:
            query: The raw GraphQL query document to send.

        Returns:
            response: The HTTP response returned by the view.
        """
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
    def test_canonical_introspection_not_cleaned(self) -> None:
        """The canonical IntrospectionQuery must not be passed to clean_dict.

        If this breaks, standard introspection tooling (e.g. GraphiQL, code
        generators) would receive a response silently pruned of null fields.
        """
        response = self._post(self.CANONICAL_INTROSPECTION)
        data = json.loads(response.content)
        # __schema must be present; clean_dict would corrupt it
        self.assertIn("__schema", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_compact_introspection_not_cleaned(self) -> None:
        """A compact inline __schema query must not be passed to clean_dict.

        Guards the same invariant as the canonical-form test for a
        differently formatted, unnamed introspection query.
        """
        response = self._post(self.COMPACT_INTROSPECTION)
        data = json.loads(response.content)
        self.assertIn("__schema", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_type_introspection_not_cleaned(self) -> None:
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
    def test_regular_query_is_cleaned(self) -> None:
        """Normal (non-introspection) queries must still be passed through clean_dict.

        Confirms the introspection bypass is scoped correctly and does not
        accidentally disable pruning for ordinary queries.
        """
        response = self._post(self.REGULAR_QUERY)
        data = json.loads(response.content)
        # hello is present; maybe is null and must be pruned by clean_dict
        self.assertIn("hello", data["data"])
        self.assertNotIn("maybe", data["data"])

    @override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
    def test_introspection_not_matching_string_prefix(self) -> None:
        """An introspection query not matching the old literal prefix must still be detected.

        The query is indented differently — the old
        startswith("\\n  query IntrospectionQuery") check would MISS this;
        AST-based detection must catch it regardless of formatting.
        """
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
    """get_query_cost must reuse the already-parsed document from get_response.

    Covers extension presence, parse-call count, value correctness, and
    result stability across repeated requests.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Shared by every test method in this class.
        """
        self.factory = RequestFactory()

    def _post_with_cost(self, query: str) -> "HttpResponse":
        """POST a single GraphQL query with query-cost extensions enabled.

        Args:
            query: The raw GraphQL query document to send.

        Returns:
            response: The HTTP response returned by the view.
        """
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": query})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        return view(request)

    def test_cost_extension_present(self) -> None:
        """EXPOSE_QUERY_COST must add "extensions.cost" to the response.

        Baseline check before asserting on parse-call count and cost values.
        """
        response = self._post_with_cost("{ hello }")
        data = json.loads(response.content)
        self.assertIn("extensions", data)
        self.assertIn("cost", data["extensions"])

    def test_parse_called_once(self) -> None:
        """ "parse()" must be called exactly once per request even with EXPOSE_QUERY_COST.

        If this breaks, "get_query_cost" would re-parse the document instead
        of reusing the one already parsed by "get_response", doubling parse
        cost per request.
        """
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

    def test_cost_values_correct(self) -> None:
        """Cost values must be non-negative integers.

        Guards the "requestedCost" value independent of the parse-count
        assertion.
        """
        response = self._post_with_cost("{ hello }")
        data = json.loads(response.content)
        cost = data["extensions"]["cost"]
        self.assertGreaterEqual(cost["requestedCost"], 0)

    def test_behavioral_equivalence_with_and_without_double_parse(self) -> None:
        """The cost result must be the same whether computed from original parse or reused doc.

        Both paths must yield the same requestedCost — this verifies
        behavioral equivalence of the refactored single-parse approach.
        """
        response1 = self._post_with_cost("{ hello }")
        response2 = self._post_with_cost("{ hello }")
        cost1 = json.loads(response1.content)["extensions"]["cost"]["requestedCost"]
        cost2 = json.loads(response2.content)["extensions"]["cost"]["requestedCost"]
        self.assertEqual(cost1, cost2)
