# -*- coding: utf-8 -*-
"""Small async helpers for the subscription tests."""

_SENTINEL_SESSION = "__test_sentinel__"


async def run_subscribe(subscription_cls, info=None, **kwargs):
    """Drive a subscription's ``_subscribe`` generator for its single value.

    When ``_session_key`` is not explicitly provided, the helper auto-registers
    the channel under a sentinel session key so existing non-security tests do
    not need to set up the channel registry themselves.  Security tests that
    want to exercise rejection must register the channel explicitly (via
    ``register_channel``) with the *desired* session key BEFORE calling this
    helper, and then pass the *attacker's* ``_session_key`` as a kwarg to
    trigger the ownership mismatch.
    """
    from django_graphex.subscriptions.subscription import register_channel

    channel_id = kwargs.get("channel_id")

    # Only auto-register when the caller has not injected _session_key, so the
    # security tests (which pre-register the channel under a specific key) are
    # not overwritten here.
    if "_session_key" not in kwargs and channel_id:
        register_channel(channel_id, session_key=_SENTINEL_SESSION)
        kwargs["_session_key"] = _SENTINEL_SESSION

    generator = subscription_cls._subscribe(None, info, **kwargs)
    try:
        result = await generator.__anext__()
    finally:
        await generator.aclose()
    return result
