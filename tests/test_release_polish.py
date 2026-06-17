# -*- coding: utf-8 -*-
"""TDD tests for v1.2.1 release-polish fixes.

Covers P4 (double-encoded batch error), P5 (cache incr), P6 (assert→HttpError),
P7 (@number value vs spec errors), P10 (batch+cache), P11 (bindings executor).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLBoolean, GraphQLString

from django_graphex import DjangoGraphQLSchema, Mutation, ObjectType, field
from django_graphex.views import BaseGraphQLView, GraphQLView

# The subscriptions package hard-requires the optional ``channels`` extra at
# import time, so tests that touch it must be skipped on the channels-free
# ``base-install`` matrix cell (mirrors tests/subscriptions/conftest.py).
_CHANNELS_AVAILABLE = importlib.util.find_spec("channels") is not None

# ---------------------------------------------------------------------------
# Shared schema
# ---------------------------------------------------------------------------


class _Q(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root, info):
        return "world"


class _Mut(Mutation):
    ok = field(GraphQLBoolean)

    def mutate(root, info):
        return _Mut(ok=True)


class _MRoot(ObjectType):
    do_thing = _Mut.Field()


_schema = DjangoGraphQLSchema(query=_Q, mutation=_MRoot)

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
        body = json.dumps(
            [
                {"query": "{ hello }"},
                {"query": "{ hello }"},
                {"query": "{ hello }"},  # 3 > limit 2
            ]
        )
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
    """P5: the version token must be seeded with 1 (int) so cache.incr works.

    Updated for issue #60: initial value is 1 (not 0), heal is 1 (not 0), and
    bump is deferred via transaction.on_commit — captureOnCommitCallbacks is
    required to flush the callback inside TestCase.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_initial_version_is_integer(self):
        """After _get_cache_version, the stored value must be an integer (1)."""
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
        # Seeded to 1 (not 0) so version 0 is never used as a live cache key.
        self.assertEqual(stored, 1)

    def test_bump_increments_version(self):
        """_bump_cache_version must increment the counter: 1 → 2 → 3.

        Uses captureOnCommitCallbacks(execute=True) because bump is deferred
        via transaction.on_commit and Django's TestCase holds the test inside a
        transaction that never commits.
        """
        from django.core.cache import caches

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="u2")

        # Seed then bump twice.
        view._get_cache_version(_cache, "u2")
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "u2")
        v1 = _cache.get(version_key)
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "u2")
        v2 = _cache.get(version_key)

        self.assertEqual(v1, 2)
        self.assertEqual(v2, 3)

    def test_bump_fallback_on_incr_failure(self):
        """When cache.incr raises ValueError, _bump must reset the key to integer 1
        so the next incr always finds an integer and can succeed.

        The heal value is 1 (not 0) to avoid the ambiguous zero-state (issue #60c).
        captureOnCommitCallbacks flushes the on_commit callback immediately.
        """
        from django.core.cache import caches

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="u3")

        view._get_cache_version(_cache, "u3")

        with patch.object(_cache, "incr", side_effect=ValueError("no incr")):
            with self.captureOnCommitCallbacks(execute=True):
                view._bump_cache_version(_cache, "u3")

        after = _cache.get(version_key)
        self.assertIsInstance(
            after,
            int,
            f"Fallback must reset the version token to integer 1; got {after!r}",
        )
        self.assertEqual(after, 1, "Fallback must set the token to integer 1 (not 0)")


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
        body = json.dumps(
            [
                {"query": "{ hello }"},
                {"query": "{ hello }"},
            ]
        )
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


@pytest.mark.skipif(
    not _CHANNELS_AVAILABLE,
    reason="requires the 'subscriptions' extra (channels)",
)
class SafeGroupSendTest(TestCase):
    """P11 (updated for H3 fix): _safe_group_send must use fire-and-forget
    create_task on the running-loop path (no blocking executor) and
    async_to_sync on the no-loop path."""

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

    def test_running_loop_fire_and_forget(self):
        """With a running event loop on the CURRENT thread, _safe_group_send must
        return immediately (fire-and-forget via create_task) — not block ~5s."""
        import time

        from django_graphex.subscriptions import bindings

        group_sends = []

        async def fake_group_send(group_name, message):
            group_sends.append((group_name, message))

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = fake_group_send

        elapsed_holder = []
        exc_holder = []

        async def run_test():
            start = time.monotonic()
            try:
                bindings._safe_group_send(
                    mock_channel_layer, "loop-group", {"type": "loop-test"}
                )
            except Exception as e:
                exc_holder.append(e)
            elapsed_holder.append(time.monotonic() - start)
            # Give the scheduled task a chance to execute.
            await asyncio.sleep(0.05)

        asyncio.run(run_test())

        assert not exc_holder, f"_safe_group_send raised: {exc_holder}"
        assert elapsed_holder[0] < 1.0, (
            f"Running-loop path blocked for {elapsed_holder[0]:.2f}s "
            f"(expected fire-and-forget <1s)"
        )
        assert ("loop-group", {"type": "loop-test"}) in group_sends

    def test_no_executor_on_bindings_module(self):
        """After the H3 fix, the singleton ThreadPoolExecutor is removed.
        _GROUP_SEND_EXECUTOR must NOT be present on the bindings module."""
        from django_graphex.subscriptions import bindings

        assert not hasattr(bindings, "_GROUP_SEND_EXECUTOR"), (
            "bindings._GROUP_SEND_EXECUTOR still present — "
            "the executor was removed in the H3 fix"
        )
