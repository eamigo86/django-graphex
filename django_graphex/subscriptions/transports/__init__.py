"""Transport adapters for the native serialize-once subscription engine.

Two transports drive the SAME engine (design §1, §7): one HTTP request / one
WebSocket connection → ``drive_subscription`` over the serialize-once flat-pk
data path. The engine core (``ChannelLayerSource`` group consumer, COND-A
delivery iterator, snake-closure projection) is transport-agnostic; these
adapters only frame ``ExecutionResult`` values for the wire and translate
client disconnect into ``source.aclose()`` teardown.

  * :mod:`.sse` — Server-Sent Events (SHIP FIRST, the cheap engine validator).
  * :mod:`.ws` — graphql-transport-ws over Channels (SHIP SECOND, the heavier
    transport: connection_init/ack auth handshake, per-id task registry, N ops
    multiplexed over one socket, close codes 4400/4401/4408/4409/4429).

No module here imports graphene; ``channels`` is imported lazily/guarded so the
base package never hard-requires it. The ``ws`` consumer module imports
``channels.generic.websocket`` only inside its factory, so importing this
package never pulls channels until WS is actually routed.
"""
from __future__ import annotations

__all__ = ["sse", "ws"]
