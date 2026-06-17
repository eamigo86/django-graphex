"""Pytest fixtures for the playground end-to-end tests.

These tests run under the PLAYGROUND's own Django settings
(``config.settings``) — NOT the library's ``tests/`` settings. They exercise the
example exactly as a user would run it: the real ``blog.schema``, the real
``config.asgi`` WebSocket consumer, and the real SSE view wired in
``config/urls.py``.

Run them from this directory::

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q
"""

from __future__ import annotations

import pytest


@pytest.fixture
def demo_user(db):
    """A persisted, authenticated demo user (mirrors the seed superuser)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="demo", defaults={"email": "demo@example.com"}
    )
    user.set_password("demo12345")
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user


@pytest.fixture
def author(db):
    """A persisted Author to hang Posts off in the round-trip tests."""
    from blog.models import Author

    return Author.objects.create(name="Round-trip Author", bio="e2e")
