# -*- coding: utf-8 -*-
"""Small async helpers for the subscription tests."""


async def run_subscribe(subscription_cls, info=None, **kwargs):
    """Drive a subscription's ``_subscribe`` generator for its single value."""
    generator = subscription_cls._subscribe(None, info, **kwargs)
    try:
        result = await generator.__anext__()
    finally:
        await generator.aclose()
    return result
