# -*- coding: utf-8 -*-
"""Tests for the P3 bounded parse+validate document cache.

The cache lives in "django_graphex.views" and memoizes:

* "parse(query) -> DocumentNode" in a global bounded LRU (AST is immutable), and
* "validate(schema, document, rules, max_errors) -> tuple[errors]" in a
  per-schema bounded LRU keyed on the schema OBJECT (weakref) so a stale verdict
  is never served across two different (permission-pruned) schemas.

These tests spy on "graphql.parse" / "graphql.validation.validate" as seen
by the view module to prove work is done exactly once on cache hits.
"""

import json
from typing import Any, Callable

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex import views as views_module
from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


class _Query(ObjectType):
    """Simple query type used across the cache tests."""

    __test__ = False

    hello = field(
        GraphQLString,
        args={"name": GraphQLArgument(GraphQLString, default_value="World")},
    )

    def resolve_hello(self: Any, info: Any, name: str) -> str:
        """Resolve the "hello" field to a greeting for the given name.

        Args:
            info: The GraphQL resolve info (unused).
            name: The name to greet.

        Returns:
            greeting: The string "Hello {name}!".
        """
        return f"Hello {name}!"


cache_test_schema = DjangoGraphQLSchema(query=_Query)


class _CountingSpy:
    """Wrap a callable, forwarding calls while counting invocations."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        """Store the wrapped callable and initialize the call counter.

        Args:
            fn: The callable to wrap and count invocations of.
        """
        self._fn = fn
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Increment the call counter, then delegate to the wrapped callable.

        Args:
            args: Positional arguments forwarded to the wrapped callable.
            kwargs: Keyword arguments forwarded to the wrapped callable.

        Returns:
            result: Whatever the wrapped callable returns.
        """
        self.calls += 1
        return self._fn(*args, **kwargs)


class DocumentCacheTestBase(TestCase):
    """Shared setup: fresh request factory + cleared document caches per test.

    Subclassed by every test class in this module.
    """

    def setUp(self) -> None:
        """Reset the module-level caches so tests do not leak state.

        Runs before each test in every subclass of this base class.
        """
        self.factory = RequestFactory()
        views_module.clear_document_caches()

    def _post(self, view: Any, query: str) -> HttpResponse:
        """POST the given query through the given view and return the response.

        Args:
            view: The view callable to dispatch the request to.
            query: The raw GraphQL query text.

        Returns:
            response: The HTTP response produced by the view.
        """
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )
        return view(request)


class TestParseValidateMemoization(DocumentCacheTestBase):
    """Change 1: identical requests parse + validate exactly once.

    Also covers that distinct query text gets its own cache entries.
    """

    def test_two_identical_requests_parse_and_validate_once(self) -> None:
        """Ship-broken contract: two identical POSTs must parse and validate
        the query exactly once each, with identical response bodies.
        """
        parse_spy = _CountingSpy(views_module.parse)
        validate_spy = _CountingSpy(views_module.validate)
        view = GraphQLView.as_view(schema=cache_test_schema)

        with (
            _patch(views_module, "parse", parse_spy),
            _patch(views_module, "validate", validate_spy),
        ):
            r1 = self._post(view, "{ hello }")
            r2 = self._post(view, "{ hello }")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.content, r2.content)
        self.assertEqual(
            parse_spy.calls, 1, "parse should run once for two identical queries"
        )
        self.assertEqual(
            validate_spy.calls, 1, "validate should run once for two identical queries"
        )

    def test_distinct_queries_get_distinct_entries(self) -> None:
        """Ship-broken contract: a different query text must parse and
        validate separately, not reuse the prior query's cache entry.
        """
        parse_spy = _CountingSpy(views_module.parse)
        validate_spy = _CountingSpy(views_module.validate)
        view = GraphQLView.as_view(schema=cache_test_schema)

        with (
            _patch(views_module, "parse", parse_spy),
            _patch(views_module, "validate", validate_spy),
        ):
            self._post(view, "{ hello }")
            self._post(view, '{ hello(name: "X") }')

        self.assertEqual(parse_spy.calls, 2)
        self.assertEqual(validate_spy.calls, 2)


class TestValidationCacheSchemaIdentity(DocumentCacheTestBase):
    """THE SECURITY TEST: verdicts are keyed by the schema OBJECT.

    Pins the invariant that a validation verdict never leaks across two
    distinct schema instances, even for the identical query text.
    """

    def test_same_query_two_schemas_get_own_verdict(self) -> None:
        """Ship-broken contract: a query valid on schema A but invalid on
        schema B must not be served schema A's cached verdict.

        Simulates permission-scoped pruning: schema A exposes "secret", schema B
        does not. The identical query "{ secret }" must be VALID on A and INVALID
        on B — proving the validation cache never crosses schema boundaries.
        """
        query_a = GraphQLObjectType(
            "Query",
            {
                "public": GraphQLField(GraphQLString, resolve=lambda *_: "p"),
                "secret": GraphQLField(GraphQLString, resolve=lambda *_: "s"),
            },
        )
        query_b = GraphQLObjectType(
            "Query",
            {"public": GraphQLField(GraphQLString, resolve=lambda *_: "p")},
        )
        schema_a = GraphQLSchema(query=query_a)
        schema_b = GraphQLSchema(query=query_b)

        doc = views_module.cached_parse("{ secret }")

        errors_a = views_module.cached_validate(schema_a, "{ secret }", doc, None, None)
        errors_b = views_module.cached_validate(schema_b, "{ secret }", doc, None, None)

        self.assertEqual(errors_a, (), "secret exists on schema A -> valid")
        self.assertTrue(errors_b, "secret absent on schema B -> must be invalid")
        # Re-reading the cached verdict must still be schema-scoped.
        again_a = views_module.cached_validate(schema_a, "{ secret }", doc, None, None)
        again_b = views_module.cached_validate(schema_b, "{ secret }", doc, None, None)
        self.assertEqual(again_a, ())
        self.assertTrue(again_b)


class TestCacheDisabled(DocumentCacheTestBase):
    """Change 3: DOCUMENT_CACHE_MAXSIZE=0 disables both caches.

    Confirms the disable switch actually turns memoization off end-to-end.
    """

    @override_settings(DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAXSIZE": 0, "SCHEMA": None})
    def test_maxsize_zero_reparses_and_revalidates_every_time(self) -> None:
        """Ship-broken contract: with the cache off, parse and validate must
        run on every identical request, never memoizing.
        """
        parse_spy = _CountingSpy(views_module.parse)
        validate_spy = _CountingSpy(views_module.validate)
        view = GraphQLView.as_view(schema=cache_test_schema)

        with (
            _patch(views_module, "parse", parse_spy),
            _patch(views_module, "validate", validate_spy),
        ):
            self._post(view, "{ hello }")
            self._post(view, "{ hello }")

        self.assertEqual(parse_spy.calls, 2, "cache off -> parse every request")
        self.assertEqual(validate_spy.calls, 2, "cache off -> validate every request")


class TestParseCacheLruBound(DocumentCacheTestBase):
    """Change 4: the parse LRU evicts past maxsize.

    Covers both the shared parse cache and the per-schema validation cache.
    """

    @override_settings(DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAXSIZE": 2, "SCHEMA": None})
    def test_lru_evicts_oldest_and_reparses(self) -> None:
        """Ship-broken contract: once maxsize+1 distinct queries have been
        parsed, the oldest entry must be evicted and re-parsed on next use.
        """
        parse_spy = _CountingSpy(views_module.parse)

        with _patch(views_module, "parse", parse_spy):
            q0, q1, q2 = "{ a }", "{ b }", "{ c }"
            views_module.cached_parse(q0)  # fills slot 0
            views_module.cached_parse(q1)  # fills slot 1
            views_module.cached_parse(q2)  # evicts q0 (maxsize=2)
            self.assertEqual(parse_spy.calls, 3)
            # q1/q2 still cached (no new parse); q0 evicted -> re-parse.
            views_module.cached_parse(q1)
            views_module.cached_parse(q2)
            self.assertEqual(parse_spy.calls, 3, "q1/q2 must be cache hits")
            views_module.cached_parse(q0)
            self.assertEqual(parse_spy.calls, 4, "q0 was evicted -> re-parsed")

    @override_settings(DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAXSIZE": 2, "SCHEMA": None})
    def test_validation_sub_cache_evicts_oldest_and_revalidates(self) -> None:
        """Ship-broken contract: the per-schema validation LRU must also
        evict its oldest entry past maxsize and re-validate on next use.
        """
        validate_spy = _CountingSpy(views_module.validate)
        schema = cache_test_schema.graphql_schema

        with _patch(views_module, "validate", validate_spy):
            q0, q1, q2 = "{ hello }", '{ hello(name: "b") }', '{ hello(name: "c") }'
            for q in (q0, q1, q2):
                views_module.cached_validate(
                    schema, q, views_module.cached_parse(q), None, None
                )
            self.assertEqual(validate_spy.calls, 3)
            # q0 evicted (maxsize=2) -> re-validate; q1/q2 remain cached.
            views_module.cached_validate(
                schema, q1, views_module.cached_parse(q1), None, None
            )
            self.assertEqual(validate_spy.calls, 3, "q1 must be a validation cache hit")
            views_module.cached_validate(
                schema, q0, views_module.cached_parse(q0), None, None
            )
            self.assertEqual(validate_spy.calls, 4, "q0 evicted -> re-validated")


class TestCachedErrorSerialization(DocumentCacheTestBase):
    """Design constraint 4: cached errors serialize identically to fresh ones.

    Guards against the cache silently altering error message formatting.
    """

    def test_cached_validation_errors_format_identically(self) -> None:
        """Ship-broken contract: the cached error tuple's "formatted" output
        must match a fresh "validate()" call, and stay stable across repeated
        cache hits.
        """
        schema = cache_test_schema.graphql_schema
        query = "{ nope }"
        doc = views_module.cached_parse(query)

        fresh = tuple(views_module.validate(schema, doc, None, None))
        cached_first = views_module.cached_validate(schema, query, doc, None, None)
        cached_second = views_module.cached_validate(schema, query, doc, None, None)

        self.assertTrue(fresh and cached_first and cached_second)
        self.assertEqual(
            [e.formatted for e in fresh],
            [e.formatted for e in cached_first],
        )
        # Same objects reused on the second hit -> byte-identical formatting.
        self.assertEqual(
            [e.formatted for e in cached_first],
            [e.formatted for e in cached_second],
        )


class TestInvalidDocumentIdenticalPayload(DocumentCacheTestBase):
    """Change 5: an invalid document yields identical 400 payloads across requests.

    Confirms the cache does not alter the shape of an error response.
    """

    def test_invalid_query_same_400_first_and_cached_second(self) -> None:
        """Ship-broken contract: a query referencing a missing field must
        produce the same 400 body on both the first and the cached request.
        """
        view = GraphQLView.as_view(schema=cache_test_schema)

        r1 = self._post(view, "{ nope }")
        r2 = self._post(view, "{ nope }")

        self.assertEqual(r1.status_code, 400)
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r1.content, r2.content)
        payload = json.loads(r1.content)
        self.assertIn("errors", payload)


class TestCacheActiveSingleParse(DocumentCacheTestBase):
    """Change 6: CACHE_ACTIVE path parses the document only once (no double-parse).

    Guards against the response-cache path re-tokenizing the same query.
    """

    @override_settings(DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "SCHEMA": None})
    def test_cache_active_single_parse_total(self) -> None:
        """Ship-broken contract: with CACHE_ACTIVE, a single request must
        parse the query exactly once, even though the response-cache path
        calls "get_operation_ast" (its own parse), "get_response" (another
        parse), and "execute_graphql_request".
        """
        from django.core.cache import cache as dj_cache

        dj_cache.clear()
        parse_spy = _CountingSpy(views_module.parse)
        view = GraphQLView.as_view(schema=cache_test_schema)

        with _patch(views_module, "parse", parse_spy):
            r = self._post(view, "{ hello }")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            parse_spy.calls, 1, "CACHE_ACTIVE must parse the document once total"
        )


#: Query for the depth-cache regression tests: a self-referential ``Node`` type
#: so a single query can nest arbitrarily deep. ``{ node { node { node } } }``
#: is 2 nested object levels below the root ``node`` field.
_depth_node = GraphQLObjectType(
    "Node",
    lambda: {
        "value": GraphQLField(GraphQLString, resolve=lambda *_: "v"),
        "node": GraphQLField(_depth_node, resolve=lambda *_: object()),
    },
)
_depth_schema = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {"node": GraphQLField(_depth_node, resolve=lambda *_: object())},
    )
)

#: Query for the cost-cache regression tests: a ``list`` field carrying a
#: ``limit`` page-size argument so its cost scales with the page size. With
#: ``limit: 10`` the field costs ``own(1) + 10 * child_scalars(0) = 1`` plus the
#: multiplier applied to any object children — kept simple here with one object
#: child so the total tracks ``MAX_QUERY_COST`` predictably.
_cost_item = GraphQLObjectType(
    "Item",
    {
        "a": GraphQLField(GraphQLString, resolve=lambda *_: "a"),
        "child": GraphQLField(
            GraphQLObjectType(
                "Child", {"b": GraphQLField(GraphQLString, resolve=lambda *_: "b")}
            ),
            resolve=lambda *_: object(),
        ),
    },
)
_cost_schema = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {
            "items": GraphQLField(
                GraphQLList(_cost_item),
                args={"limit": GraphQLArgument(GraphQLInt)},
                resolve=lambda *_: [],
            )
        },
    )
)


class TestValidationCacheDynamicDepthLimit(DocumentCacheTestBase):
    """REGRESSION: a cached depth verdict must not survive a MAX_QUERY_DEPTH change.

    "DepthLimitValidationRule" reads "MAX_QUERY_DEPTH" dynamically at
    validation time. If the cache key ignores it, a query validated "valid" under
    a permissive limit is served that stale verdict after the limit is tightened —
    silently bypassing the depth guard until eviction/restart.
    """

    def _validate(self, query: str) -> tuple:
        """Validate the given query against the shared depth schema via the cache.

        Args:
            query: The raw GraphQL query text.

        Returns:
            errors: The tuple of validation errors (empty when valid).
        """
        doc = views_module.cached_parse(query)
        return views_module.cached_validate(
            _depth_schema, query, doc, GraphQLView.validation_rules, None
        )

    def test_tightened_depth_limit_rejects_previously_cached_valid_query(self) -> None:
        """Ship-broken contract: a query cached as valid under a permissive
        MAX_QUERY_DEPTH must be rejected once the limit is tightened, not
        served the stale cached verdict.
        """
        query = "{ node { node { value } } }"  # 2 nested object levels

        with override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 10, "SCHEMA": None}):
            allowed = self._validate(query)
        self.assertEqual(allowed, (), "depth 10 must allow the query (cached valid)")

        # Tighten the limit WITHOUT clearing the document caches.
        with override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 1, "SCHEMA": None}):
            rejected = self._validate(query)
        self.assertTrue(
            rejected, "depth 1 must reject the same query, not serve the cached verdict"
        )

    def test_unchanged_depth_limit_still_hits_cache(self) -> None:
        """Ship-broken contract: two validations at the same depth limit must
        call validate() exactly once (the second is a cache hit).
        """
        query = "{ node { node { value } } }"
        validate_spy = _CountingSpy(views_module.validate)

        with (
            override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 10, "SCHEMA": None}),
            _patch(views_module, "validate", validate_spy),
        ):
            first = self._validate(query)
            second = self._validate(query)

        self.assertEqual(first, ())
        self.assertEqual(second, ())
        self.assertEqual(
            validate_spy.calls, 1, "unchanged depth limit must be a cache hit"
        )


class TestValidationCacheDynamicCostLimit(DocumentCacheTestBase):
    """REGRESSION: a cached cost verdict must not survive a MAX_QUERY_COST change.

    "CostLimitValidationRule" reads "MAX_QUERY_COST" (and the page-size
    settings that feed the estimate) dynamically at validation time. A cache key
    that ignores them serves a stale "valid" verdict after the budget is
    tightened, bypassing the cost guard.
    """

    def _validate(self, query: str) -> tuple:
        """Validate the given query against the shared cost schema via the cache.

        Args:
            query: The raw GraphQL query text.

        Returns:
            errors: The tuple of validation errors (empty when valid).
        """
        doc = views_module.cached_parse(query)
        return views_module.cached_validate(
            _cost_schema, query, doc, GraphQLView.validation_rules, None
        )

    def test_tightened_cost_limit_rejects_previously_cached_valid_query(self) -> None:
        """Ship-broken contract: a query cached as valid under a permissive
        MAX_QUERY_COST must be rejected once the budget is tightened, not
        served the stale cached verdict.
        """
        query = "{ items(limit: 10) { a child { b } } }"

        with override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1000, "SCHEMA": None}):
            allowed = self._validate(query)
        self.assertEqual(allowed, (), "cost 1000 must allow the query (cached valid)")

        with override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "SCHEMA": None}):
            rejected = self._validate(query)
        self.assertTrue(
            rejected, "cost 1 must reject the same query, not serve the cached verdict"
        )

    def test_tightened_page_size_cap_rejects_previously_cached_valid_query(
        self,
    ) -> None:
        """Ship-broken contract: MAX_PAGE_SIZE feeds the cost estimate, so
        shrinking it must force the verdict to be re-decided, not reuse a
        stale cached one.

        The multiplier is capped at MAX_PAGE_SIZE. At MAX_QUERY_COST=25 the query
        is valid with a small cap and invalid with a large one — proving the page
        settings are part of the verdict, not just MAX_QUERY_COST.
        """
        query = "{ items(limit: 100) { a child { b } } }"

        with override_settings(
            DJANGO_GRAPHEX={
                "MAX_QUERY_COST": 25,
                "MAX_PAGE_SIZE": 2,
                "SCHEMA": None,
            }
        ):
            allowed = self._validate(query)
        self.assertEqual(allowed, (), "small page cap keeps cost under budget")

        with override_settings(
            DJANGO_GRAPHEX={
                "MAX_QUERY_COST": 25,
                "MAX_PAGE_SIZE": 100,
                "SCHEMA": None,
            }
        ):
            rejected = self._validate(query)
        self.assertTrue(
            rejected, "large page cap pushes cost over budget -> must reject"
        )

    def test_unchanged_cost_limit_still_hits_cache(self) -> None:
        """Ship-broken contract: two validations at the same cost limit must
        call validate() exactly once (the second is a cache hit).
        """
        query = "{ items(limit: 10) { a child { b } } }"
        validate_spy = _CountingSpy(views_module.validate)

        with (
            override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1000, "SCHEMA": None}),
            _patch(views_module, "validate", validate_spy),
        ):
            first = self._validate(query)
            second = self._validate(query)

        self.assertEqual(first, ())
        self.assertEqual(second, ())
        self.assertEqual(
            validate_spy.calls, 1, "unchanged cost limit must be a cache hit"
        )


class _patch:
    """Minimal context-manager monkeypatch (setattr/restore) for module globals."""

    def __init__(self, obj: Any, name: str, value: Any) -> None:
        """Store the target object, attribute name, and replacement value.

        Args:
            obj: The object whose attribute will be temporarily replaced.
            name: The attribute name to patch.
            value: The replacement value to install on "__enter__".
        """
        self._obj = obj
        self._name = name
        self._value = value

    def __enter__(self) -> Any:
        """Install the replacement value, saving the original for restore.

        Returns:
            value: The replacement value that was installed.
        """
        self._orig = getattr(self._obj, self._name)
        setattr(self._obj, self._name, self._value)
        return self._value

    def __exit__(self, *exc: Any) -> bool:
        """Restore the original attribute value.

        Args:
            exc: The exception info tuple passed by the "with" statement
                (unused; the original value is always restored).

        Returns:
            suppress: False, so any exception raised in the "with" block
                propagates normally.
        """
        setattr(self._obj, self._name, self._orig)
        return False
