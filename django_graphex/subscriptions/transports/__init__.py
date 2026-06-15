"""Transport adapters for the native serialize-once subscription engine.

Two transports drive the SAME engine (design §1, §7): one HTTP request / one
WebSocket connection → ``drive_subscription`` over the serialize-once flat-pk
data path. The engine core (``ChannelLayerSource`` group consumer, COND-A
delivery iterator, snake-closure projection) is transport-agnostic; these
adapters only frame ``ExecutionResult`` values for the wire and translate
client disconnect into ``source.aclose()`` teardown.

  * :mod:`.sse` — Server-Sent Events (SHIP FIRST, the cheap engine validator).
  * ``.ws`` — graphql-transport-ws over Channels (SHIP SECOND).

No module here imports graphene; ``channels`` is imported lazily/guarded so the
base package never hard-requires it.
"""
from __future__ import annotations

__all__ = ["sse"]
