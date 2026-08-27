# -*- coding: utf-8 -*-
"""The subscribe gate must still deny when it is declared "async def".

Both transports run "authorize_subscription" and "subscription_scope" on the
event loop, so any hook that needs the ORM has to be awaited — and the engine
already awaits an awaitable hook return ("streaming._maybe_await"). The scope
hook's wrapper forwards its return; the authorize wrapper did not, so an
"async def" gate produced a coroutine nobody awaited and the subscribe was
GRANTED. A gate that fails open is worse than no gate, and Python only whispers
about it through a "coroutine was never awaited" warning.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("channels")

from graphql import GraphQLError  # noqa: E402

from tests.models import Post  # noqa: E402


async def test_async_authorize_hook_denial_is_awaited() -> None:  # noqa: DOC005
    """An "async def" authorize hook that raises must deny the subscribe.

    Contract: this test ships broken if the spec's authorize wrapper drops the
    hook's return value, because the denial then lives in a coroutine nobody
    awaits and the subscribe succeeds — a gate failing OPEN.
    """
    from django_graphex.subscriptions import Subscription
    from django_graphex.subscriptions.streaming import _maybe_await

    class _AsyncGatedPost(Subscription):
        class Meta:
            model = Post
            stream = "posts"

        @classmethod
        async def authorize_subscription(cls, info: Any, **kwargs: Any) -> None:
            """Deny every subscribe, from an awaitable hook.

            Args:
                info: The transport-neutral context (unused).
                **kwargs: The subscription arguments (unused).

            Raises:
                GraphQLError: Always — this gate denies everyone.
            """
            raise GraphQLError("denied by an async gate")

    spec = _AsyncGatedPost._build_native_spec(schema=None, document=None)

    with pytest.raises(GraphQLError, match="denied by an async gate"):
        await _maybe_await(spec.authorize(None, action="create"))


async def test_async_scope_hook_return_is_awaited() -> None:
    """An "async def" scope hook's forced filters must reach the engine.

    Contract: parity check for the sibling wrapper — this test ships broken if
    the scope wrapper stops forwarding the hook's awaitable return, which would
    silently drop every server-forced filter.
    """
    from django_graphex.subscriptions import Subscription
    from django_graphex.subscriptions.streaming import _maybe_await

    class _AsyncScopedPost(Subscription):
        class Meta:
            model = Post
            stream = "posts"

        @classmethod
        async def subscription_scope(cls, info: Any, **kwargs: Any) -> dict[str, Any]:
            """Force one server-side filter, from an awaitable hook.

            Args:
                info: The transport-neutral context (unused).
                **kwargs: The subscription arguments (unused).

            Returns:
                The server-forced filter mapping.
            """
            return {"author": 7}

    spec = _AsyncScopedPost._build_native_spec(schema=None, document=None)

    forced = await _maybe_await(spec.scope(None, action="create"))
    assert forced == {"author": 7}
