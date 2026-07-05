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

import pytest
from django.test import TestCase
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema

_CHANNELS_AVAILABLE = importlib.util.find_spec("channels") is not None

# ---------------------------------------------------------------------------
# Shared minimal schema
# ---------------------------------------------------------------------------


class _Q(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root, info):
        return "world"


_schema = DjangoGraphQLSchema(query=_Q)


# ===========================================================================
# H1 — _bump_cache_version must seed integer 0 in the except branch
# ===========================================================================


class BumpCacheVersionPoisonHealingTest(TestCase):
    """H1: a pre-existing STRING token in the cache must be healed to an integer
    so that subsequent _bump_cache_version calls succeed (no TypeError, no HTTP 500).

    Updated for issue #60: bump is deferred via transaction.on_commit;
    captureOnCommitCallbacks(execute=True) is required to flush it in TestCase.
    Initial/heal value is now 1 (not 0) to avoid the ambiguous zero-state.
    """

    def setUp(self) -> None:
        """Clear the cache before each test.

        Ensures version counters from a prior test cannot leak into this
        test's assertions.
        """
        from django.core.cache import cache

        cache.clear()

    def test_happy_path_bump_increments(self) -> None:
        """Seeding then bumping twice must advance the version 1 -> 2 -> 3.

        If this breaks, the cache-version counter is not incrementing
        correctly after being healed to an integer seed.
        """
        from django.core.cache import caches

        from django_graphex.views import GraphQLView

        _cache = caches["default"]
        view = GraphQLView(schema=_schema)
        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(
            identity="h1-happy"
        )

        view._get_cache_version(_cache, "h1-happy")
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "h1-happy")
        v1 = _cache.get(version_key)
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "h1-happy")
        v2 = _cache.get(version_key)

        assert v1 == 2, f"Expected 2 after first bump (seed=1), got {v1!r}"
        assert v2 == 3, f"Expected 3 after second bump, got {v2!r}"

    def test_missing_key_reseeds_to_integer(self) -> None:
        """A missing version key must be re-seeded to integer 1, not 0.

        A subsequent bump on the re-seeded key must then increment cleanly
        to 2, proving the heal path never leaves the ambiguous zero-state.
        """
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
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "h1-missing")

        stored = _cache.get(version_key)
        assert isinstance(stored, int), (
            f"Expected integer re-seed after missing key, got {type(stored).__name__}: "
            f"{stored!r}"
        )
        # Heal value is 1 (not 0) — zero-state is never used.
        assert stored == 1, f"Expected heal to 1, got {stored!r}"

        # Subsequent bump must succeed (not raise TypeError).
        with self.captureOnCommitCallbacks(execute=True):
            view._bump_cache_version(_cache, "h1-missing")
        stored2 = _cache.get(version_key)
        assert isinstance(stored2, int), (
            f"Expected integer after follow-up bump, got {type(stored2).__name__}: "
            f"{stored2!r}"
        )
        assert stored2 > stored, (
            f"Expected version to increment; got {stored} then {stored2}"
        )

    def test_poison_string_token_is_healed_to_integer(self) -> None:
        """A pre-existing uuid-hex string token must be healed, not crash the bump.

        If the cache contains a string token planted by an older deploy's
        except branch, "_bump_cache_version" must NOT raise TypeError and
        must heal the key to an integer; a follow-up bump must also succeed
        cleanly.
        """
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
            with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
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

    def _resolve(self, value: float, spec: str) -> str:
        """Run the "@number" directive's resolver against a raw value and spec.

        Args:
            value: The numeric value to format.
            spec: The Python format-spec string passed via the "as" argument.

        Returns:
            formatted: The formatted string produced by the directive.
        """
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        return directive.resolve(value, {"as": spec}, None, None, None)

    def _assert_rejected(self, spec: str, description: str = "") -> None:
        """Assert that a format spec is rejected with the width/precision error.

        Args:
            spec: The Python format-spec string expected to be rejected.
            description: A human-readable label for the spec, kept only for
                documentation purposes at call sites.
        """
        from graphql import GraphQLError

        with pytest.raises(GraphQLError, match="width/precision"):
            self._resolve(42, spec)
        _ = description  # used for documentation only

    def _assert_accepted(
        self, value: float, spec: str, expected: str | None = None
    ) -> None:
        """Assert that a format spec is accepted and formats as expected.

        Args:
            value: The numeric value to format.
            spec: The Python format-spec string expected to be accepted.
            expected: The exact expected formatted output; when None, only
                acceptance (no exception) is checked.
        """
        result = self._resolve(value, spec)
        if expected is not None:
            assert result == expected, (
                f"spec={spec!r}: expected {expected!r}, got {result!r}"
            )

    # --- bypass specs that MUST be rejected ---

    def test_digit_fill_left_align_huge_width_rejected(self) -> None:
        """A digit-fill left-align spec with a huge width must be rejected.

        "0<1000000f" uses digit fill "0", align "<", width 1000000, which
        must not bypass the DoS width guard.
        """
        self._assert_rejected("0<1000000f", "digit fill 0 with left-align")

    def test_digit_fill_center_align_huge_width_rejected(self) -> None:
        """A digit-fill center-align spec with a huge width must be rejected.

        "9^900000f" uses digit fill "9", align "^", width 900000, which must
        not bypass the DoS width guard.
        """
        self._assert_rejected("9^900000f", "digit fill 9 with center-align")

    def test_digit_fill_eq_align_huge_precision_rejected(self) -> None:
        """A digit-fill eq-align spec with a huge width must be rejected.

        "5=3000000.2f" uses digit fill "5", align "=", width 3000000, which
        must not bypass the DoS width guard.
        """
        self._assert_rejected("5=3000000.2f", "digit fill 5 with eq-align, huge width")

    def test_star_fill_right_align_huge_width_rejected(self) -> None:
        """A non-digit-fill right-align spec with a huge width must be rejected.

        "*>500000d" uses fill "*", align ">", width 500000, which must not
        bypass the DoS width guard.
        """
        self._assert_rejected("*>500000d", "star fill with right-align")

    def test_digit_fill_zero_align_huge_width_rejected(self) -> None:
        """A malformed fill/align prefix with a huge width must still be rejected.

        "08<200000f" has "<" as the third character rather than the second,
        so Python's format-spec parser rejects it outright before the width
        guard even runs; it must still surface as GraphQLError via the
        format() error path.
        """
        from graphql import GraphQLError

        with pytest.raises(GraphQLError):
            self._resolve(42, "08<200000f")

    def test_plain_huge_width_still_rejected(self) -> None:
        """A plain huge width with no fill or align must still be rejected.

        "1000000f" has no fill/align prefix, exercising the original
        (pre-fix) width guard directly.
        """
        self._assert_rejected("1000000f", "plain huge width")

    # --- legit specs that MUST still work ---

    def test_precision_only(self) -> None:
        """A precision-only spec must format correctly.

        ".2f" carries no width, so it must never trigger the width guard.
        """
        self._assert_accepted(3.14159, ".2f", "3.14")

    def test_comma_precision(self) -> None:
        """A comma-grouping precision spec must format correctly.

        ",.2f" carries no width, so it must never trigger the width guard.
        """
        self._assert_accepted(1234.5, ",.2f", "1,234.50")

    def test_sign_precision_percent(self) -> None:
        """A sign-and-precision percent spec must format correctly.

        "+.1%" carries no width, so it must never trigger the width guard.
        """
        self._assert_accepted(0.75, "+.1%", "+75.0%")

    def test_width_precision(self) -> None:
        """A modest width-and-precision spec must format correctly.

        "20.2f" is well under the width cap and must be accepted unchanged.
        """
        self._assert_accepted(3.14, "20.2f", f"{3.14:20.2f}")

    def test_zero_pad_precision(self) -> None:
        """A zero-fill modest-width spec must format correctly.

        "08.2f" is well under the width cap and must be accepted unchanged.
        """
        self._assert_accepted(3.14, "08.2f", "00003.14")

    def test_right_align_width(self) -> None:
        """A right-align modest-width spec must format correctly.

        ">10.2f" is well under the width cap and must be accepted unchanged.
        """
        self._assert_accepted(3.14, ">10.2f", f"{3.14:>10.2f}")

    def test_center_align_small_width(self) -> None:
        """A center-align modest-width spec must format correctly.

        "^8f" is well under the width cap and must be accepted unchanged.
        The directive always does float(value) first, so 42.0 formatted as
        "d" would raise; "f" is used here for floats when center-aligning.
        """
        self._assert_accepted(42, "^8f", f"{42.0:^8f}")

    def test_sign_zero_pad_precision(self) -> None:
        """A sign-plus-zero-pad modest-width spec must format correctly.

        "+08.3f" is well under the width cap and must be accepted unchanged.
        """
        self._assert_accepted(3.14, "+08.3f", f"{3.14:+08.3f}")

    def test_comma_grouping_integer(self) -> None:
        """A comma-grouping spec on an integer-like float must format correctly.

        ",.0f" carries no width and must never trigger the width guard.
        """
        self._assert_accepted(1000000, ",.0f", "1,000,000")

    def test_underscore_grouping(self) -> None:
        """An underscore-grouping spec on an integer-like float must format correctly.

        "_.0f" carries no width and must never trigger the width guard.
        """
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

    def test_no_running_loop_delivers_message(self) -> None:
        """The WSGI path (no running loop) must deliver the message quickly.

        With no running event loop, "_safe_group_send" must fall back to
        async_to_sync and deliver the message in well under a second.
        """
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

    def test_running_loop_returns_immediately_no_block(self) -> None:
        """The ASGI path (called on the loop thread) must not block for ~5s.

        The coroutine is scheduled fire-and-forget via create_task, so the
        call must return in under a second instead of blocking.
        """
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

    def test_no_executor_attribute_on_bindings(self) -> None:
        """The module-level executor attribute must be removed after the H3 fix.

        "_GROUP_SEND_EXECUTOR" must NOT exist on the bindings module.
        """
        from django_graphex.subscriptions import bindings

        assert not hasattr(bindings, "_GROUP_SEND_EXECUTOR"), (
            "bindings._GROUP_SEND_EXECUTOR still present — "
            "the executor should have been removed in the H3 fix"
        )

    def test_no_timeout_constant_on_bindings(self) -> None:
        """The module-level timeout constant must be removed after the H3 fix.

        "_GROUP_SEND_TIMEOUT" must NOT exist on the bindings module.
        """
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

    def _resolve(self, value: float, spec: str) -> str:
        """Run the "@number" directive's resolver against a raw value and spec.

        Args:
            value: The numeric value to format.
            spec: The Python format-spec string passed via the "as" argument.

        Returns:
            formatted: The formatted string produced by the directive.
        """
        from django_graphex.directives.string import NumberGraphQLDirective

        directive = NumberGraphQLDirective()
        return directive.resolve(value, {"as": spec}, None, None, None)

    def _assert_graphql_error_not_value_error(
        self, spec: str, description: str = ""
    ) -> None:
        """Assert that a spec raises GraphQLError, not ValueError or HTTP 500.

        Args:
            spec: The Python format-spec string expected to be rejected
                cleanly via GraphQLError.
            description: A human-readable label for the spec, used only in
                failure messages.

        Raises:
            AssertionError: Raised via pytest.fail when the spec resolves
                successfully, raises ValueError, or raises any exception
                other than GraphQLError.
        """
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

    def test_huge_plain_width_raises_graphql_error_not_value_error(self) -> None:
        """A plain 5000-digit width must raise GraphQLError, not a raw ValueError.

        "'9'*5000 + 'f'" would otherwise reach Python's int() digit-length
        limit and crash with an uncaught ValueError (HTTP 500).
        """
        self._assert_graphql_error_not_value_error(
            "9" * 5000 + "f",
            description="plain huge width digit-bomb",
        )

    def test_huge_precision_raises_graphql_error_not_value_error(self) -> None:
        """A 5000-digit precision must raise GraphQLError, not a raw ValueError.

        "'.' + '9'*5000 + 'f'" would otherwise reach Python's int()
        digit-length limit and crash with an uncaught ValueError (HTTP 500).
        """
        self._assert_graphql_error_not_value_error(
            "." + "9" * 5000 + "f",
            description="precision digit-bomb",
        )

    def test_fill_align_huge_width_raises_graphql_error_not_value_error(self) -> None:
        """A fill+align prefix with a 5000-digit width must raise GraphQLError.

        "'0<' + '9'*5000 + 'f'" must still be routed through the clean
        error path instead of raising a raw ValueError.
        """
        self._assert_graphql_error_not_value_error(
            "0<" + "9" * 5000 + "f",
            description="fill+align + huge width digit-bomb",
        )

    # --- boundary specs: width=100 allowed, width=101 rejected cleanly ---

    def test_width_100_accepted(self) -> None:
        """A width of exactly 100 (the cap) must succeed.

        Boundary check just below the reject threshold.
        """
        result = self._resolve(42, "100f")
        assert result is not None

    def test_width_101_rejected_cleanly(self) -> None:
        """A width of 101 (one over the cap) must raise GraphQLError.

        Boundary check confirming the existing width guard still triggers.
        """
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

    def test_group_send_failure_logged_not_leaked_as_warning(self) -> None:
        """A failing group_send must be logged, not leaked as an asyncio warning.

        When the scheduled group_send coroutine raises, "logger.error" must
        record the failure and no "Task exception was never retrieved"
        RuntimeWarning may escape to the asyncio unhandled-exception handler.

        Raises:
            RuntimeError: Raised by the fake "group_send" coroutine to
                simulate a channel-layer failure; caught internally by the
                done-callback under test, never propagated to the caller.
        """
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

    def test_cancelled_error_not_logged_as_error(self) -> None:
        """CancelledError must be swallowed silently, not treated as a failure.

        Cancelling the scheduled group_send task must not produce an ERROR
        log record or reach the asyncio unhandled-exception handler.
        """
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


# ===========================================================================
# HIGH-2 (v1.2.1 whole-branch audit) — @center width ceiling (DoS)
# ===========================================================================


class CenterDirectiveWidthDoSGuardTest(TestCase):
    """HIGH-2: @center(width: 2_000_000_000) must raise GraphQLError, NOT allocate
    a ~2 GB string.  The fix introduces _CENTER_MAX_WIDTH and rejects any width
    above that constant before calling str.center().
    """

    def _resolve(self, value: str, width: int, fillchar: str | None = None) -> str:
        """Run the "@center" directive's resolver against a value and width.

        Args:
            value: The string to center.
            width: The requested output width.
            fillchar: The fill character to pad with; defaults to a space
                when None.

        Returns:
            centered: The centered string produced by the directive.
        """
        from django_graphex.directives.string import CenterGraphQLDirective

        args = {"width": width}
        if fillchar is not None:
            args["fillchar"] = fillchar
        return CenterGraphQLDirective.resolve(value, args, None, None, None)

    # ------------------------------------------------------------------
    # Test 1: max representable Int → GraphQLError (NOT a giant allocation)
    # ------------------------------------------------------------------
    def test_max_int_width_raises_graphql_error(self) -> None:
        """The maximum safe GraphQL Int width must raise GraphQLError, not OOM.

        width=2_000_000_000 must be rejected before "str.center" attempts a
        multi-gigabyte allocation.
        """
        from graphql import GraphQLError

        with pytest.raises(GraphQLError):
            self._resolve("hello", 2_000_000_000)

    # ------------------------------------------------------------------
    # Test 2: one over the cap → GraphQLError; one under the cap → works
    # ------------------------------------------------------------------
    def test_width_one_over_cap_raises_graphql_error(self) -> None:
        """A width one over the cap must raise GraphQLError.

        Boundary check just above "_CENTER_MAX_WIDTH".
        """
        from graphql import GraphQLError

        from django_graphex.directives.string import _CENTER_MAX_WIDTH

        with pytest.raises(GraphQLError):
            self._resolve("x", _CENTER_MAX_WIDTH + 1)

    def test_width_at_cap_is_accepted(self) -> None:
        """A width exactly at the cap must be accepted with no error.

        Boundary check at "_CENTER_MAX_WIDTH" itself.
        """
        from django_graphex.directives.string import _CENTER_MAX_WIDTH

        result = self._resolve("x", _CENTER_MAX_WIDTH)
        assert isinstance(result, str), (
            f"Expected a string result at cap width, got {type(result).__name__}"
        )

    def test_width_one_under_cap_is_accepted(self) -> None:
        """A width one under the cap must be accepted with no error.

        Boundary check just below "_CENTER_MAX_WIDTH".
        """
        from django_graphex.directives.string import _CENTER_MAX_WIDTH

        result = self._resolve("hello", _CENTER_MAX_WIDTH - 1)
        assert isinstance(result, str)

    # ------------------------------------------------------------------
    # Test 3: normal @center(width: 20) still centers correctly
    # ------------------------------------------------------------------
    def test_normal_center_works(self) -> None:
        """A normal centering call must match str.center exactly.

        "@center(width=20)" on "hello" must produce the same result as
        "'hello'.center(20)".
        """
        result = self._resolve("hello", 20)
        assert result == "hello".center(20), (
            f"@center(width=20) produced {result!r}, expected {'hello'.center(20)!r}"
        )

    def test_normal_center_with_fillchar(self) -> None:
        """A centering call with a custom fill char must match str.center exactly.

        "@center(width=15, fillchar='*')" on "Hello World" must produce the
        same result as "'Hello World'.center(15, '*')".
        """
        result = self._resolve("Hello World", 15, fillchar="*")
        assert result == "**Hello World**", (
            f"@center(width=15, fillchar='*') produced {result!r}"
        )
