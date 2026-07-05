"""COND-A lightweight async delivery iterator for subscriptions.

graphql-core's stock "subscribe()" wraps the source event stream in a delivery
class whose "__anext__" does, PER YIELDED VALUE (while open):

    aclose = ensure_future(self._close_event.wait())   # 1x ensure_future
    anext  = ensure_future(self.iterator.__anext__())   # 1x ensure_future
    pending = (await wait([aclose, anext], FIRST_COMPLETED))[1]  # 1x asyncio.wait
    for task in pending: task.cancel()                  # 1x Task.cancel

The GO-gate spike (engram #1516) measured ~47 us/value for that stock path vs
~0.19 us/value for a plain "async for" wrapper on Python 3.12 — a ~250x swing.
This module OWNS the delivery layer (the COND-A decision, design §4): a
lightweight wrapper that iterates an underlying async source, applies an async
(or plain) map function per value, and supports OUT-OF-BAND CLOSE so a caller
("complete{id}" / disconnect) can stop iteration IMMEDIATELY.

Two close mechanisms are provided, both out-of-band:

  * "aclose()" — a coroutine that sets the close flag AND closes the underlying
    source. Closing the source is what unblocks a consumer that is parked in
    "receive()" waiting for the next broadcast, so the close is prompt even
    while "__anext__" is pending.
  * the "_close_event" (an "asyncio.Event", surfaced read-only via
    "DeliveryIterator.is_closed") — checked at the top of every "__anext__" so
    a flag set between values stops iteration on the next pull without any
    per-value "asyncio.wait" machinery.

The hot path stays a single "await source.__anext__()" with no per-value
"ensure_future" / "asyncio.wait" — that is the whole point of COND-A.

Transport-agnostic: this module imports neither channels, Django, nor
graphene. It is pure asyncio and may be imported safely in any async context.

This delivery class is deliberately NOT graphql-core's stock mapping iterator;
the structural guard in "tests/subscriptions/test_delivery_iterator.py"
enforces that no such type ever appears on the subscription delivery path.
"""

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any, AsyncIterator, Callable

__all__ = ["DeliveryIterator", "make_delivery_iterator"]


class DeliveryIterator:
    """Lightweight async-for wrapper over an async source with out-of-band close.

    Wraps an underlying async iterable/iterator (e.g. a Channels group consumer
    or an async generator, iterated via "source.__aiter__()") and applies a
    per-value mapping callable "map_fn(value) -> result" to each delivered
    value. In the subscription engine (WU5) that map becomes the "execute(...)"
    call that runs the GraphQL document over the flat source dict; the result is
    awaited only when it is awaitable, so both coroutine functions and plain
    callables are supported.

    The hot path ("__anext__") is a single "await source.__anext__()" with no
    per-value "ensure_future" / "asyncio.wait" — this is the COND-A performance
    win over graphql-core's stock delivery class. Out-of-band close is handled
    by (a) an "asyncio.Event" checked at the top of every pull and (b) "aclose"
    closing the underlying source so a blocked "receive()" is released promptly.
    """

    __slots__ = ("_source", "_map", "_close_event")

    def __init__(
        self,
        source: AsyncIterator[Any],
        map_fn: Callable[[Any], Any],
    ) -> None:
        """Wrap "source" and apply "map_fn" per delivered value.

        Args:
            source: The underlying async iterable/iterator to wrap.
            map_fn: The per-value mapping callable applied to each delivered
                value; awaited when it returns an awaitable.
        """
        self._source = source.__aiter__()
        self._map = map_fn
        self._close_event = asyncio.Event()

    def __aiter__(self) -> "DeliveryIterator":
        """Return self — this object is its own async iterator."""
        return self

    async def __anext__(self) -> Any:
        """Pull the next source value, map it, and return the result."""
        # Out-of-band close set between values -> stop on the next pull without
        # any asyncio.wait machinery.
        if self._close_event.is_set():
            raise StopAsyncIteration

        value = await self._source.__anext__()

        # If a close fired while we were awaiting the source (e.g. aclose()
        # released a blocked receive), do not deliver a trailing value.
        if self._close_event.is_set():
            raise StopAsyncIteration

        result = self._map(value)
        return await result if isawaitable(result) else result

    async def aclose(self) -> None:
        """Out-of-band close: flag the iterator and close the underlying source.

        Idempotent. Setting the close flag first guarantees that any pending or
        subsequent "__anext__" stops; closing the underlying source releases a
        consumer blocked in "receive()" so the stop is prompt.
        """
        if self._close_event.is_set():
            return
        self._close_event.set()
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except RuntimeError:
                # An already-closing/closed async generator can raise
                # RuntimeError; treat close as best-effort and idempotent.
                pass

    @property
    def is_closed(self) -> bool:
        """Return whether the iterator has been closed out-of-band.

        Returns:
            "True" once "aclose" has run, else "False".
        """
        return self._close_event.is_set()


def make_delivery_iterator(
    source: AsyncIterator[Any],
    map_fn: Callable[[Any], Any],
) -> DeliveryIterator:
    """Return a "DeliveryIterator" wrapping "source" with "map_fn".

    Factory mirroring "make_snake_resolver" (resolvers.py): callers depend on
    the factory, not the concrete class, so the delivery implementation can
    evolve without touching the engine call sites (WU5 "drive_subscription").

    Args:
        source: The underlying async iterable/iterator to wrap.
        map_fn: The per-value mapping callable applied to each delivered value.

    Returns:
        A "DeliveryIterator" wrapping "source" and applying "map_fn".
    """
    return DeliveryIterator(source, map_fn)
