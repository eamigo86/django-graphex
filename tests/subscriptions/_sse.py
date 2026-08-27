# -*- coding: utf-8 -*-
"""Shared SSE stream reader for the transport tests.

The SSE response opens with a comment line so the ASGI server flushes the
status line and headers before the first event — see "_PREAMBLE_FRAME" in
"django_graphex.subscriptions.transports.sse". A comment is not a frame, so
every test that reads FRAMES goes through "sse_frames" and never sees it. The
preamble itself is pinned by its own two tests in "test_transport_sse.py".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterator


async def sse_frames(response: Any) -> "AsyncIterator[Any]":
    """Iterate a streaming SSE response's frames, dropping comment chunks.

    Args:
        response: The streaming response returned by the SSE view.

    Yields:
        chunk: Each body chunk that carries an SSE event, in order.
    """
    async for chunk in response.streaming_content:
        text = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else chunk
        if text.startswith(":"):
            continue
        yield chunk
