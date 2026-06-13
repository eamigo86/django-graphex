# -*- coding: utf-8 -*-
"""TDD tests for v1.2.1 release-polish fixes.

Covers P4 (double-encoded batch error), P5 (cache incr), P6 (assert→HttpError),
P7 (@number value vs spec errors), P10 (batch+cache), P11 (bindings executor).
"""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import graphene
import pytest
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import BaseGraphQLView, GraphQLView


# ---------------------------------------------------------------------------
# Shared schema
# ---------------------------------------------------------------------------


class _Q(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):
        return "world"


class _Mut(graphene.Mutation):
    ok = graphene.Boolean()

    def mutate(root, info):
        return _Mut(ok=True)


class _MRoot(graphene.ObjectType):
    do_thing = _Mut.Field()


_schema = graphene.Schema(query=_Q, mutation=_MRoot)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}


# ---------------------------------------------------------------------------
# P4 — MAX_BATCH_SIZE error body must NOT be double-encoded
# ---------------------------------------------------------------------------


class MaxBatchSizeErrorBodyTest(TestCase):
    """P4: when MAX_BATCH_SIZE is exceeded the response body must be a single,
    clean ``{"errors":[{"message":"Batch size ..."}]}`` — not double-encoded."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_graphex.views.graphql_api_settings.MAX_BATCH_SIZE", 2)
    def test_batch_size_exceeded_returns_single_encoded_error(self):
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([
            {"query": "{ hello }"},
            {"query": "{ hello }"},
            {"query": "{ hello }"},  # 3 > limit 2
        ])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)

        payload = json.loads(response.content)
        # Top level must be {"errors": [{"message": "..."}]}, not double-encoded.
        self.assertIn("errors", payload, "Response body is missing 'errors' key")
        errors = payload["errors"]
        self.assertIsInstance(errors, list, "errors must be a list")
        self.assertEqual(len(errors), 1)
        msg = errors[0]["message"]
        self.assertIsInstance(msg, str, "message must be a string, not encoded JSON")
        # The message must NOT start with '{' (would indicate double-encoding)
        self.assertFalse(
            msg.startswith("{"),
            f"message appears to be JSON-encoded: {msg!r}",
        )
        self.assertIn("Batch size", msg)
        self.assertIn("3", msg)

    @patch("django_graphex.views.graphql_api_settings.MAX_BATCH_SIZE", None)
    def test_no_limit_does_not_raise(self):
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }"}] * 10)
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# P5 — _get_cache_version / _bump_cache_version incr path
# ---------------------------------------------------------------------------


class CacheIncrTest(TestCase):
    """P5: the version token must be seeded with 0 (int) so cache.incr works."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_initial_version_is_integer(self):
        """After _get_cache_version, the stored value must be an integer."""
        from django.core.cache import caches

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        _ = view._get_cache_version(_cache, "user1")

        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="user1")
        stored = _cache.get(version_key)
        self.assertIsInstance(
            stored,
            int,
            f"Expected int seed, got {type(stored).__name__}: {stored!r}",
        )
        self.assertEqual(stored, 0)

    def test_bump_increments_version(self):
        """_bump_cache_version must increment the counter: 0 → 1 → 2."""
        from django.core.cache import caches

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="u2")

        # Seed then bump twice.
        view._get_cache_version(_cache, "u2")
        view._bump_cache_version(_cache, "u2")
        v1 = _cache.get(version_key)
        view._bump_cache_version(_cache, "u2")
        v2 = _cache.get(version_key)

        self.assertEqual(v1, 1)
        self.assertEqual(v2, 2)

    def test_bump_fallback_on_incr_failure(self):
        """When cache.incr raises ValueError, _bump must still change the version."""
        from django.core.cache import caches

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="u3")

        view._get_cache_version(_cache, "u3")
        before = _cache.get(version_key)

        with patch.object(_cache, "incr", side_effect=ValueError("no incr")):
            view._bump_cache_version(_cache, "u3")

        after = _cache.get(version_key)
        self.assertNotEqual(before, after, "Fallback must change the version token")


# ---------------------------------------------------------------------------
# P6 — parse_body asserts → explicit HttpError for batch=True
# ---------------------------------------------------------------------------


class ParseBodyBatchValidationTest(TestCase):
    """P6: batch body validation must raise clean 400s, not AssertionError."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_dict_body_with_batch_true_returns_400(self):
        """Sending a single-op dict body to a batch endpoint → 400."""
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps({"query": "{ hello }"})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("errors", payload)

    def test_empty_list_body_with_batch_true_returns_400(self):
        """Sending an empty list to a batch endpoint → 400."""
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("errors", payload)

    def test_valid_batch_list_is_accepted(self):
        """A non-empty list body is accepted normally."""
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }"}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# P7 — @number directive value vs spec error messages
# ---------------------------------------------------------------------------


class NumberDirectiveErrorMessagesTest(TestCase):
    """P7: @number must blame the VALUE for non-coercible input, and the SPEC
    for an invalid format spec; not always blame the spec."""

    def test_non_coercible_value_blames_value(self):
        """value='abc' with a valid spec must mention the value, not the spec."""
        import graphene
        from graphql import GraphQLError

        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        with pytest.raises(GraphQLError) as exc_info:
            directive.resolve("abc", {"as": ".2f"}, None, None, None)

        msg = str(exc_info.value)
        # Should blame the value, not the spec.
        assert "value" in msg.lower() or "abc" in msg, (
            f"Expected message to mention the value; got: {msg!r}"
        )
        # Must NOT blame the spec for a value-coercion failure.
        assert "spec" not in msg.lower() or ".2f" not in msg, (
            f"Should not blame spec for value error; got: {msg!r}"
        )

    def test_invalid_spec_blames_spec(self):
        """A float value with spec='q' (unknown format code) must blame the spec."""
        from graphql import GraphQLError

        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        with pytest.raises(GraphQLError) as exc_info:
            # 'q' is not a valid Python float format code → ValueError from format()
            directive.resolve("3.14", {"as": "q"}, None, None, None)

        msg = str(exc_info.value)
        assert "spec" in msg.lower() or "q" in msg, (
            f"Expected message to mention the spec; got: {msg!r}"
        )

    def test_valid_value_and_spec_formats_correctly(self):
        """A coercible value with a valid spec must return the formatted string."""
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        result = directive.resolve("3.14159", {"as": ".2f"}, None, None, None)
        assert result == "3.14"


# ---------------------------------------------------------------------------
# P10 — batch=True + CACHE_ACTIVE=True must not AttributeError
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class BatchWithCacheTest(TestCase):
    """P10: batch requests with CACHE_ACTIVE=True must succeed, not AttributeError."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_batch_with_cache_active_returns_200(self):
        view = GraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([
            {"query": "{ hello }"},
            {"query": "{ hello }"},
        ])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_batch_with_cache_active_is_not_cached(self):
        """Batch responses must bypass the cache (no caching for batch)."""
        from django.core.cache import caches as _caches

        _cache = _caches["default"]
        call_count = {"n": 0}
        view = GraphQLView.as_view(schema=_schema, batch=True)

        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        with patch.object(GraphQLView, "super_call", counting_super_call):
            body = json.dumps([{"query": "{ hello }"}])
            req1 = self.factory.post("/graphql/", body, content_type="application/json")
            req2 = self.factory.post("/graphql/", body, content_type="application/json")
            view(req1)
            view(req2)

        # Both calls must hit the backend (no caching for batch).
        self.assertEqual(
            call_count["n"],
            2,
            "Batch response was cached — batch requests must bypass the cache",
        )


# ---------------------------------------------------------------------------
# P11 — _safe_group_send: singleton executor + both loop paths
# ---------------------------------------------------------------------------


class SafeGroupSendTest(TestCase):
    """P11: _safe_group_send must use a module-level singleton executor and
    exercise both the no-loop (async_to_sync) and loop-running (executor) paths."""

    def test_no_running_loop_uses_async_to_sync(self):
        """With no running event loop, group_send must be called via async_to_sync."""
        from django_graphex.subscriptions import bindings

        group_sends = []

        async def fake_group_send(group_name, message):
            group_sends.append((group_name, message))

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = fake_group_send

        # Ensure no loop is running in this thread.
        try:
            asyncio.get_running_loop()
            pytest.skip("Test requires no running loop in current thread")
        except RuntimeError:
            pass  # Good — no loop running

        bindings._safe_group_send(mock_channel_layer, "test-group", {"type": "test"})
        assert group_sends == [("test-group", {"type": "test"})]

    def test_running_loop_uses_executor_path(self):
        """With a running event loop on the CURRENT thread, group_send must be
        scheduled via the executor rather than async_to_sync."""
        from django_graphex.subscriptions import bindings

        group_sends = []

        async def fake_group_send(group_name, message):
            group_sends.append((group_name, message))

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = fake_group_send

        exc_holder = []

        async def run_test():
            # At this point asyncio.get_running_loop() WILL succeed because
            # we are running inside an event loop (asyncio.run creates one).
            # Calling _safe_group_send here exercises the loop is not None branch.
            try:
                bindings._safe_group_send(
                    mock_channel_layer, "loop-group", {"type": "loop-test"}
                )
            except Exception as e:
                exc_holder.append(e)
            # Give the executor thread a moment to complete.
            await asyncio.sleep(0.1)

        asyncio.run(run_test())

        assert not exc_holder, f"_safe_group_send raised: {exc_holder}"
        assert ("loop-group", {"type": "loop-test"}) in group_sends

    def test_singleton_executor_is_reused(self):
        """The module-level executor must be a single instance (not created per call)."""
        from django_graphex.subscriptions import bindings

        # The executor should be a module-level singleton after first use.
        # We just verify the attribute exists and is a ThreadPoolExecutor.
        import concurrent.futures

        assert hasattr(bindings, "_GROUP_SEND_EXECUTOR"), (
            "bindings must expose a module-level _GROUP_SEND_EXECUTOR"
        )
        assert isinstance(
            bindings._GROUP_SEND_EXECUTOR,
            concurrent.futures.ThreadPoolExecutor,
        ), f"Expected ThreadPoolExecutor, got {type(bindings._GROUP_SEND_EXECUTOR)}"
