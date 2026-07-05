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

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
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
    """Root mutation exposing the shared "_Mut" field for these tests."""

    do_thing = _Mut.Field()


_schema = DjangoGraphQLSchema(query=_Q, mutation=_MRoot)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}


# ---------------------------------------------------------------------------
# P4 — MAX_BATCH_SIZE error body must NOT be double-encoded
# ---------------------------------------------------------------------------


class MaxBatchSizeErrorBodyTest(TestCase):
    """P4: the MAX_BATCH_SIZE error body must not be double-encoded.

    When MAX_BATCH_SIZE is exceeded the response body must be a single,
    clean {"errors":[{"message":"Batch size ..."}]} — not double-encoded.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Each test needs its own factory to build isolated request objects.
        """
        self.factory = RequestFactory()

    @patch("django_graphex.views.graphql_api_settings.MAX_BATCH_SIZE", 2)
    def test_batch_size_exceeded_returns_single_encoded_error(self) -> None:
        """Assert exceeding MAX_BATCH_SIZE returns a cleanly encoded 400 error.

        If this fails, the error body would be double-JSON-encoded (a
        JSON string containing more JSON) instead of a single, parseable
        error payload.
        """
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
    def test_no_limit_does_not_raise(self) -> None:
        """Assert an unset MAX_BATCH_SIZE does not reject a large batch.

        If this fails, leaving MAX_BATCH_SIZE unconfigured would still
        impose an implicit batch-size limit instead of allowing any size.
        """
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

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" and clear the cache before each test.

        Clearing the cache avoids state leaking between cache-related tests.
        """
        self.factory = RequestFactory()
        cache.clear()

    def test_initial_version_is_integer(self) -> None:
        """Assert "_get_cache_version" seeds the version token as an integer (1).

        If this fails, the version token would be stored as a non-integer
        (for example, None), making a subsequent "cache.incr" call raise.
        """
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

    def test_bump_increments_version(self) -> None:
        """Assert "_bump_cache_version" increments the counter across two bumps.

        Uses captureOnCommitCallbacks(execute=True) because bump is
        deferred via transaction.on_commit and Django's TestCase holds the
        test inside a transaction that never commits.

        If this fails, repeated cache invalidation bumps would not
        monotonically increase the version token, breaking cache
        invalidation.
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

    def test_bump_fallback_on_incr_failure(self) -> None:
        """Assert a failed "cache.incr" call heals the token back to integer 1.

        The heal value is 1 (not 0) to avoid the ambiguous zero-state
        (issue #60c). captureOnCommitCallbacks flushes the on_commit
        callback immediately.

        If this fails, a cache backend raising on "incr" (for example,
        after a corrupted or evicted key) would leave the version token in
        a broken, non-integer state instead of healing it.
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
    """P6: batch body validation must raise clean 400s, not AssertionError.

    Covers a dict body, an empty list body, and the valid non-empty case.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" for building test requests.

        Each test needs its own factory to build isolated request objects.
        """
        self.factory = RequestFactory()

    def test_dict_body_with_batch_true_returns_400(self) -> None:
        """Assert a single-op dict body to a batch endpoint returns 400.

        If this fails, a request body shaped for the non-batch endpoint
        would raise an unhandled AssertionError instead of a clean 400.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps({"query": "{ hello }"})
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("errors", payload)

    def test_empty_list_body_with_batch_true_returns_400(self) -> None:
        """Assert an empty list body to a batch endpoint returns 400.

        If this fails, an empty batch would either raise an unhandled
        AssertionError or be silently accepted as a no-op success.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("errors", payload)

    def test_valid_batch_list_is_accepted(self) -> None:
        """Assert a non-empty batch list body is accepted normally.

        If this fails, the stricter body validation added for P6 would
        have regressed the happy-path batch request handling.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }"}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# P7 — @number directive value vs spec error messages
# ---------------------------------------------------------------------------


class NumberDirectiveErrorMessagesTest(TestCase):
    """P7: @number must blame the VALUE or the SPEC correctly.

    It must blame the VALUE for non-coercible input, and the SPEC for an
    invalid format spec; not always blame the spec.
    """

    def test_non_coercible_value_blames_value(self) -> None:
        """Assert value="abc" with a valid spec blames the value, not the spec.

        If this fails, a non-coercible input value would be misreported
        as a format-spec problem, misleading whoever debugs the error.

        Raises:
            GraphQLError: Expected from "NumberGraphQLDirective.resolve"
                and asserted via pytest.raises.
        """
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

    def test_invalid_spec_blames_spec(self) -> None:
        """Assert an unknown format code in the spec blames the spec, not the value.

        If this fails, an invalid format spec (for example, "q") would be
        misreported as a value-coercion problem.

        Raises:
            GraphQLError: Expected from "NumberGraphQLDirective.resolve"
                and asserted via pytest.raises.
        """
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

    def test_valid_value_and_spec_formats_correctly(self) -> None:
        """Assert a coercible value with a valid spec returns the formatted string.

        If this fails, the happy path of the number-formatting directive
        would have regressed alongside its error-message improvements.
        """
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        result = directive.resolve("3.14159", {"as": ".2f"}, None, None, None)
        assert result == "3.14"


# ---------------------------------------------------------------------------
# P10 — batch=True + CACHE_ACTIVE=True must not AttributeError
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class BatchWithCacheTest(TestCase):
    """P10: batch requests with CACHE_ACTIVE=True must succeed, not AttributeError.

    Also verifies batch responses bypass response caching entirely.
    """

    def setUp(self) -> None:
        """Create a fresh "RequestFactory" and clear the cache before each test.

        Clearing the cache avoids state leaking between cache-related tests.
        """
        self.factory = RequestFactory()
        cache.clear()

    def test_batch_with_cache_active_returns_200(self) -> None:
        """Assert a batch request succeeds when response caching is enabled.

        If this fails, enabling CACHE_ACTIVE would raise an
        AttributeError (or otherwise break) batch request handling
        instead of the two combined being a supported configuration.
        """
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

    def test_batch_with_cache_active_is_not_cached(self) -> None:
        """Assert batch responses bypass the cache (no caching for batch).

        If this fails, a second identical batch request would be served
        from a stale cache entry instead of re-invoking the resolver
        chain, since batch responses are not individually cacheable.
        """
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
    """P11 (updated for H3 fix): "_safe_group_send" dispatch strategy per loop state.

    It must use fire-and-forget create_task on the running-loop path (no
    blocking executor) and async_to_sync on the no-loop path.
    """

    def test_no_running_loop_uses_async_to_sync(self) -> None:
        """Assert group_send is called via async_to_sync with no running loop.

        If this fails, calling "_safe_group_send" from a plain
        synchronous context (no event loop) would fail to dispatch the
        message instead of falling back to "async_to_sync".
        """
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

    def test_running_loop_fire_and_forget(self) -> None:
        """Assert a running event loop dispatches via fire-and-forget, not blocking.

        With a running event loop on the CURRENT thread, "_safe_group_send"
        must return immediately (fire-and-forget via create_task) — not
        block for roughly 5 seconds.

        If this fails, calling "_safe_group_send" from inside an async
        context would block the event loop instead of scheduling the send
        as a background task.
        """
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

    def test_no_executor_on_bindings_module(self) -> None:
        """Assert the bindings module no longer carries a singleton executor.

        After the H3 fix, the singleton ThreadPoolExecutor is removed;
        "_GROUP_SEND_EXECUTOR" must NOT be present on the bindings module.

        If this fails, the removed executor would have been reintroduced,
        undoing the H3 fix's blocking-call elimination.
        """
        from django_graphex.subscriptions import bindings

        assert not hasattr(bindings, "_GROUP_SEND_EXECUTOR"), (
            "bindings._GROUP_SEND_EXECUTOR still present — "
            "the executor was removed in the H3 fix"
        )
