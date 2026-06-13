# -*- coding: utf-8 -*-
"""TDD tests for v1.2.1 audit HIGH defects (H1, H2, H3).

H1 — _bump_cache_version plants a STRING token → TypeError on next incr → HTTP 500
H2 — @number DoS guard bypassed by digit fill+align specs
H3 — _safe_group_send blocks event-loop thread → 5s stall
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from unittest.mock import MagicMock

import graphene
import pytest
from django.test import TestCase

_CHANNELS_AVAILABLE = importlib.util.find_spec("channels") is not None

# ---------------------------------------------------------------------------
# Shared minimal schema
# ---------------------------------------------------------------------------


class _Q(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):
        return "world"


_schema = graphene.Schema(query=_Q)


# ===========================================================================
# H1 — _bump_cache_version must seed integer 0 in the except branch
# ===========================================================================


class BumpCacheVersionPoisonHealingTest(TestCase):
    """H1: a pre-existing STRING token in the cache must be healed to an integer
    so that subsequent _bump_cache_version calls succeed (no TypeError, no HTTP 500).
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def test_happy_path_bump_increments(self):
        """Seed via _get_cache_version → bump → bump; version goes 0→1→2."""
        from django.core.cache import caches

        from django_graphex.views import GraphQLView

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(
            identity="h1-happy"
        )

        view._get_cache_version(_cache, "h1-happy")
        view._bump_cache_version(_cache, "h1-happy")
        v1 = _cache.get(version_key)
        view._bump_cache_version(_cache, "h1-happy")
        v2 = _cache.get(version_key)

        assert v1 == 1, f"Expected 1 after first bump, got {v1!r}"
        assert v2 == 2, f"Expected 2 after second bump, got {v2!r}"

    def test_missing_key_reseeds_to_integer(self):
        """When the version key is absent, _bump_cache_version re-seeds to integer
        0 and a subsequent bump increments cleanly."""
        from django.core.cache import caches

        from django_graphex.views import GraphQLView

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(
            identity="h1-missing"
        )

        # Key does not exist at all.
        _cache.delete(version_key)

        # Must not raise.
        view._bump_cache_version(_cache, "h1-missing")

        stored = _cache.get(version_key)
        assert isinstance(stored, int), (
            f"Expected integer re-seed after missing key, got {type(stored).__name__}: "
            f"{stored!r}"
        )

        # Subsequent bump must succeed (not raise TypeError).
        view._bump_cache_version(_cache, "h1-missing")
        stored2 = _cache.get(version_key)
        assert isinstance(stored2, int), (
            f"Expected integer after follow-up bump, got {type(stored2).__name__}: "
            f"{stored2!r}"
        )
        assert stored2 > stored, (
            f"Expected version to increment; got {stored} then {stored2}"
        )

    def test_poison_string_token_is_healed_to_integer(self):
        """The ACTUAL BUG: if the cache contains a uuid-hex string (from an older
        deploy's except branch), _bump_cache_version must NOT raise TypeError and must
        heal the key to an integer; a follow-up bump must also succeed cleanly."""
        from django.core.cache import caches

        from django_graphex.views import GraphQLView

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(
            identity="h1-poison"
        )

        # Plant a uuid-hex string as the existing cache value (simulates an older
        # deploy that set a string token in the except branch).
        _cache.set(version_key, "deadbeef0123456789abcdef12345678")

        # Must NOT raise TypeError (this is the bug: LocMemCache.incr on a
        # string raises TypeError which the old except ValueError did not catch).
        try:
            view._bump_cache_version(_cache, "h1-poison")
        except TypeError as exc:
            pytest.fail(
                f"_bump_cache_version raised TypeError on a string token (H1 bug): {exc}"
            )

        # The stored value must be an integer afterward.
        stored = _cache.get(version_key)
        assert isinstance(stored, int), (
            f"Expected poison string to be healed to int, got "
            f"{type(stored).__name__}: {stored!r}"
        )

        # A follow-up bump must also succeed and increment.
        view._bump_cache_version(_cache, "h1-poison")
        stored2 = _cache.get(version_key)
        assert isinstance(stored2, int), (
            f"Expected integer after follow-up bump, got {type(stored2).__name__}: "
            f"{stored2!r}"
        )
        assert stored2 > stored, (
            f"Expected version to increment after healing; got {stored} then {stored2}"
        )


# ===========================================================================
# H2 — @number DoS guard must reject digit-fill + align bypass specs
# ===========================================================================


class NumberDirectiveDoSGuardTest(TestCase):
    """H2: format specs using a digit fill char + align spec bypass the old
    regex (width parsed as 0 → guard skipped) and can emit ~1M-char strings.
    These must now be REJECTED with GraphQLError."""

    def _resolve(self, value, spec):
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        return directive.resolve(value, {"as": spec}, None, None, None)

    def _assert_rejected(self, spec, description=""):
        from graphql import GraphQLError

        with pytest.raises(GraphQLError, match="width/precision"):
            self._resolve(42, spec)
        _ = description  # used for documentation only

    def _assert_accepted(self, value, spec, expected=None):
        result = self._resolve(value, spec)
        if expected is not None:
            assert result == expected, (
                f"spec={spec!r}: expected {expected!r}, got {result!r}"
            )

    # --- bypass specs that MUST be rejected ---

    def test_digit_fill_left_align_huge_width_rejected(self):
        """0<1000000f — digit fill '0', align '<', width 1000000 → REJECT."""
        self._assert_rejected("0<1000000f", "digit fill 0 with left-align")

    def test_digit_fill_center_align_huge_width_rejected(self):
        """9^900000f — digit fill '9', align '^', width 900000 → REJECT."""
        self._assert_rejected("9^900000f", "digit fill 9 with center-align")

    def test_digit_fill_eq_align_huge_precision_rejected(self):
        """5=3000000.2f — digit fill '5', align '=', width 3000000 → REJECT."""
        self._assert_rejected("5=3000000.2f", "digit fill 5 with eq-align, huge width")

    def test_star_fill_right_align_huge_width_rejected(self):
        """*>500000d — non-digit fill '*', align '>', width 500000 → REJECT."""
        self._assert_rejected("*>500000d", "star fill with right-align")

    def test_digit_fill_zero_align_huge_width_rejected(self):
        """08<200000f — '0' fill, '<' is NOT the second char (spec[1]='8'), so this
        is actually a malformed spec Python rejects outright.  Still REJECTED with
        a GraphQLError — just via the format() error path, not the width guard."""
        from graphql import GraphQLError

        with pytest.raises(GraphQLError):
            self._resolve(42, "08<200000f")

    def test_plain_huge_width_still_rejected(self):
        """1000000f — no fill/align, just a huge plain width → REJECT (existing guard)."""
        self._assert_rejected("1000000f", "plain huge width")

    # --- legit specs that MUST still work ---

    def test_precision_only(self):
        """.2f is valid and should format correctly."""
        self._assert_accepted(3.14159, ".2f", "3.14")

    def test_comma_precision(self):
        """,.2f is valid."""
        self._assert_accepted(1234.5, ",.2f", "1,234.50")

    def test_sign_precision_percent(self):
        """+.1% formats as percent."""
        self._assert_accepted(0.75, "+.1%", "+75.0%")

    def test_width_precision(self):
        """20.2f — modest width and precision."""
        self._assert_accepted(3.14, "20.2f", f"{3.14:20.2f}")

    def test_zero_pad_precision(self):
        """08.2f — zero-fill with modest width."""
        self._assert_accepted(3.14, "08.2f", "00003.14")

    def test_right_align_width(self):
        """>10.2f — right-align with modest width."""
        self._assert_accepted(3.14, ">10.2f", f"{3.14:>10.2f}")

    def test_center_align_small_width(self):
        """^8d — center-align with modest width on integer."""
        # The directive always does float(value) first, so 42.0 formatted as d
        # will raise; use f type for floats when center-aligning.
        self._assert_accepted(42, "^8f", f"{42.0:^8f}")

    def test_sign_zero_pad_precision(self):
        """+08.3f — sign + zero-pad + modest width."""
        self._assert_accepted(3.14, "+08.3f", f"{3.14:+08.3f}")

    def test_comma_grouping_integer(self):
        """,.0f — comma grouping for an integer-like float."""
        self._assert_accepted(1000000, ",.0f", "1,000,000")

    def test_underscore_grouping(self):
        """_.0f — underscore grouping for an integer-like float."""
        self._assert_accepted(1000000, "_.0f", "1_000_000")


# ===========================================================================
# H3 — _safe_group_send must NOT block when called on the event-loop thread
# ===========================================================================


@pytest.mark.skipif(
    not _CHANNELS_AVAILABLE,
    reason="requires the 'subscriptions' extra (channels)",
)
class SafeGroupSendNonBlockingTest(TestCase):
    """H3: when _safe_group_send is called FROM the running event-loop thread,
    it must return IMMEDIATELY (fire-and-forget via create_task) — not block ~5s."""

    def test_no_running_loop_delivers_message(self):
        """WSGI path: no running loop → async_to_sync → message delivered, fast."""
        from django_graphex.subscriptions import bindings

        group_sends = []

        async def fake_group_send(group_name, message):
            group_sends.append((group_name, message))

        mock_layer = MagicMock()
        mock_layer.group_send = fake_group_send

        start = time.monotonic()
        bindings._safe_group_send(mock_layer, "test-group", {"type": "test"})
        elapsed = time.monotonic() - start

        assert ("test-group", {"type": "test"}) in group_sends
        assert elapsed < 1.0, f"No-loop path took {elapsed:.2f}s — expected <1s"

    def test_running_loop_returns_immediately_no_block(self):
        """ASGI path: called ON the loop thread → must return in <1s, NOT block ~5s.
        The coroutine is scheduled fire-and-forget via create_task."""
        from django_graphex.subscriptions import bindings

        group_sends = []

        async def fake_group_send(group_name, message):
            group_sends.append((group_name, message))

        mock_layer = MagicMock()
        mock_layer.group_send = fake_group_send

        elapsed_holder = []
        exc_holder = []

        async def run_test():
            start = time.monotonic()
            try:
                bindings._safe_group_send(
                    mock_layer, "loop-group", {"type": "loop-test"}
                )
            except Exception as exc:
                exc_holder.append(exc)
            elapsed = time.monotonic() - start
            elapsed_holder.append(elapsed)

            # Give the scheduled task a chance to run.
            await asyncio.sleep(0.05)

        asyncio.run(run_test())

        assert not exc_holder, f"_safe_group_send raised: {exc_holder}"
        assert elapsed_holder[0] < 1.0, (
            f"Running-loop path BLOCKED for {elapsed_holder[0]:.2f}s — "
            f"expected fire-and-forget (<1s). H3 bug not fixed."
        )
        assert ("loop-group", {"type": "loop-test"}) in group_sends, (
            "group_send was never called after returning from _safe_group_send"
        )

    def test_no_executor_attribute_on_bindings(self):
        """After the H3 fix, the module-level executor is removed.
        _GROUP_SEND_EXECUTOR must NOT exist on bindings."""
        from django_graphex.subscriptions import bindings

        assert not hasattr(bindings, "_GROUP_SEND_EXECUTOR"), (
            "bindings._GROUP_SEND_EXECUTOR still present — "
            "the executor should have been removed in the H3 fix"
        )

    def test_no_timeout_constant_on_bindings(self):
        """After the H3 fix, the _GROUP_SEND_TIMEOUT constant is removed."""
        from django_graphex.subscriptions import bindings

        assert not hasattr(bindings, "_GROUP_SEND_TIMEOUT"), (
            "bindings._GROUP_SEND_TIMEOUT still present — "
            "the timeout constant should have been removed in the H3 fix"
        )


# ===========================================================================
# R1 — digit-bomb: int() on a 5000-digit string must NOT reach the caller
# ===========================================================================


class NumberDirectiveDigitBombTest(TestCase):
    """R1: _extract_width_precision must bound digit-string length BEFORE calling
    int() to avoid Python's ValueError: "Exceeds the limit (4300 digits) for
    integer string conversion" propagating as an uncaught exception (HTTP 500).

    All over-long specs must be routed to the existing GraphQLError width/precision
    path — never raise a raw ValueError from int().
    """

    def _resolve(self, value, spec):
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        return directive.resolve(value, {"as": spec}, None, None, None)

    def _assert_graphql_error_not_value_error(self, spec, description=""):
        """The spec must raise GraphQLError (not ValueError, not HTTP 500)."""
        from graphql import GraphQLError

        try:
            result = self._resolve(42, spec)
        except GraphQLError:
            pass  # correct — routed through the clean error path
        except ValueError as exc:
            pytest.fail(
                f"spec={spec[:30]!r}... ({description}): got raw ValueError "
                f"instead of GraphQLError — uncaught int() digit-bomb: {exc}"
            )
        except Exception as exc:
            pytest.fail(
                f"spec={spec[:30]!r}... ({description}): unexpected "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            pytest.fail(
                f"spec={spec[:30]!r}... ({description}): expected GraphQLError "
                f"but resolved successfully to {result!r}"
            )

    # --- digit-bomb specs: all must raise GraphQLError, NOT ValueError ---

    def test_huge_plain_width_raises_graphql_error_not_value_error(self):
        """'9'*5000 + 'f' — plain 5000-digit width — must raise GraphQLError."""
        self._assert_graphql_error_not_value_error(
            "9" * 5000 + "f",
            description="plain huge width digit-bomb",
        )

    def test_huge_precision_raises_graphql_error_not_value_error(self):
        """'.' + '9'*5000 + 'f' — 5000-digit precision — must raise GraphQLError."""
        self._assert_graphql_error_not_value_error(
            "." + "9" * 5000 + "f",
            description="precision digit-bomb",
        )

    def test_fill_align_huge_width_raises_graphql_error_not_value_error(self):
        """'0<' + '9'*5000 + 'f' — fill+align prefix + 5000-digit width."""
        self._assert_graphql_error_not_value_error(
            "0<" + "9" * 5000 + "f",
            description="fill+align + huge width digit-bomb",
        )

    # --- boundary specs: width=100 allowed, width=101 rejected cleanly ---

    def test_width_100_accepted(self):
        """'100f' — exactly at the cap — must succeed."""
        result = self._resolve(42, "100f")
        assert result is not None

    def test_width_101_rejected_cleanly(self):
        """'101f' — one over the cap — must raise GraphQLError (existing guard)."""
        from graphql import GraphQLError

        with pytest.raises(GraphQLError, match="width/precision"):
            self._resolve(42, "101f")


# ===========================================================================
# R2 — fire-and-forget error logging: done-callback must capture exceptions
# ===========================================================================


@pytest.mark.skipif(
    not _CHANNELS_AVAILABLE,
    reason="requires the 'subscriptions' extra (channels)",
)
class SafeGroupSendErrorCallbackTest(TestCase):
    """R2: when the scheduled group_send coroutine raises, the module logger
    must record the failure AND no 'Task exception was never retrieved' warning
    must escape to the asyncio unhandled-exception handler.

    The old fire-and-forget had no done-callback — so errors were silently
    swallowed or emitted as asyncio RuntimeWarning.
    """

    def test_group_send_failure_logged_not_leaked_as_warning(self):
        """group_send raises RuntimeError → logger.error records it; no
        'Task exception was never retrieved' RuntimeWarning is emitted."""
        import logging

        from django_graphex.subscriptions import bindings

        boom = RuntimeError("channel layer down — R2 test")

        async def failing_group_send(group_name, message):
            raise boom

        mock_layer = MagicMock()
        mock_layer.group_send = failing_group_send

        unhandled = []

        def capture_exception(loop, context):
            unhandled.append(context)

        logged_errors = []

        async def run_test():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(capture_exception)
            bindings._safe_group_send(mock_layer, "fail-group", {"type": "test"})
            # Let the task run and the done-callback fire.
            await asyncio.sleep(0.1)

        with self.assertLogs(
            "django_graphex.subscriptions.bindings", level=logging.ERROR
        ) as cm:
            asyncio.run(run_test())
            logged_errors.extend(cm.output)

        # The logger must have recorded the failure.
        assert logged_errors, (
            "Expected logger.error/exception to record group_send failure, but no "
            "ERROR log was emitted. Done-callback is missing (R2 bug)."
        )

        # asyncio must NOT have received an unhandled exception (which would emit
        # 'Task exception was never retrieved').
        assert not unhandled, (
            f"asyncio unhandled-exception handler was called with: {unhandled}. "
            f"This means the done-callback is missing or not calling task.exception()."
        )

    def test_cancelled_error_not_logged_as_error(self):
        """CancelledError must be swallowed silently — not treated as a failure."""
        import logging

        from django_graphex.subscriptions import bindings

        async def cancellable_group_send(group_name, message):
            # Simulate cancellation during execution.
            await asyncio.sleep(10)

        mock_layer = MagicMock()
        mock_layer.group_send = cancellable_group_send

        unhandled = []
        error_records = []

        class _ErrorCapture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    error_records.append(record.getMessage())

        async def run_test():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(lambda lp, ctx: unhandled.append(ctx))
            bindings._safe_group_send(mock_layer, "cancel-group", {"type": "test"})
            # Cancel all tasks except the current one.
            current = asyncio.current_task()
            for task in asyncio.all_tasks():
                if task is not current:
                    task.cancel()
            await asyncio.sleep(0.05)

        handler = _ErrorCapture()
        bindings_logger = logging.getLogger("django_graphex.subscriptions.bindings")
        bindings_logger.addHandler(handler)
        try:
            asyncio.run(run_test())
        finally:
            bindings_logger.removeHandler(handler)

        assert not error_records, (
            f"CancelledError must NOT be logged as an error, got: {error_records}"
        )
        # asyncio exception handler must not have been called for CancelledError.
        assert not unhandled, (
            f"asyncio exception handler called unexpectedly: {unhandled}"
        )
