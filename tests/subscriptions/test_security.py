# -*- coding: utf-8 -*-
"""T-SECURITY: subscription security hardening tests.

Covers:
  (a) channel_id ownership guard — own channel accepted, foreign channel rejected
  (b) filter key validation — declared fields + lookup suffixes accepted,
      unknown root fields rejected at subscribe time
  (c) assert → raise — validation errors survive python -O
  (d) percent-encoded index group names — delimiter ambiguity resolved
  (e) client.py HTML escaping for ws_path / http_path
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from .helpers import run_subscribe
from .schema import UserSubscription

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# (c) assert → raise: these should work even under python -O
# ---------------------------------------------------------------------------


def test_missing_stream_raises_type_error():
    """stream must be a str — TypeError raised (not an AssertionError)."""

    with pytest.raises(TypeError, match="valid string stream name"):

        class _Bad(UserSubscription):
            class Meta:
                model = __import__("django.contrib.auth.models", fromlist=["User"]).User
                stream = 123  # not a str


def test_queryset_model_mismatch_raises_type_error():
    """queryset model != backend model — TypeError raised (not AssertionError)."""
    from django.contrib.auth.models import Permission, User

    with pytest.raises(TypeError, match="queryset model must correspond"):

        class _Bad(UserSubscription):
            class Meta:
                model = User
                stream = "bad_qs"
                queryset = Permission.objects.all()


def test_serialize_data_invalid_value_raises_type_error():
    """serialize_data not in (None, True, False) — TypeError raised."""

    with pytest.raises(TypeError, match="serialize_data must be None"):

        class _Bad(UserSubscription):
            class Meta:
                model = __import__("django.contrib.auth.models", fromlist=["User"]).User
                stream = "bad_sd"
                serialize_data = "yes"


# ---------------------------------------------------------------------------
# (a) channel_id ownership guard
# ---------------------------------------------------------------------------


async def test_own_channel_accepted():
    """A subscribe call with the channel's own ID succeeds."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("my-channel", session_key="sess-abc")
    result = await run_subscribe(
        UserSubscription,
        channel_id="my-channel",
        action="create",
        operation="subscribe",
        _session_key="sess-abc",
    )
    assert result.ok is True
    assert result.error is None


async def test_foreign_channel_rejected():
    """Subscribing with a channel owned by a different session is rejected."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("victim-channel", session_key="victim-session")

    result = await run_subscribe(
        UserSubscription,
        channel_id="victim-channel",
        action="create",
        operation="subscribe",
        _session_key="attacker-session",  # different session
    )
    assert result.ok is False
    assert result.error is not None


async def test_unknown_channel_rejected():
    """Subscribing with a channel that was never registered is rejected (fail-closed)."""
    result = await run_subscribe(
        UserSubscription,
        channel_id="never-registered-channel",
        action="create",
        operation="subscribe",
        _session_key="any-session",
    )
    assert result.ok is False
    assert result.error is not None


async def test_unsubscribe_with_own_channel_succeeds():
    """Unsubscribe with the correct channel ID succeeds."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("unsub-channel", session_key="unsub-session")

    # First subscribe
    await run_subscribe(
        UserSubscription,
        channel_id="unsub-channel",
        action="create",
        operation="subscribe",
        _session_key="unsub-session",
    )
    # Then unsubscribe — should succeed
    result = await run_subscribe(
        UserSubscription,
        channel_id="unsub-channel",
        action="create",
        operation="unsubscribe",
        _session_key="unsub-session",
    )
    assert result.ok is True


async def test_no_session_key_and_channel_not_registered_rejected():
    """No _session_key supplied and channel not registered → fail-closed.

    This test calls ``_subscribe`` directly (bypassing the auto-register logic
    in ``run_subscribe``) to simulate a raw HTTP caller that supplies no
    session context and whose channel was never registered.
    """
    # Call _subscribe directly — no channel registered, no _session_key.
    gen = UserSubscription._subscribe(
        None,
        None,
        channel_id="never-registered-xyz",
        action="create",
        operation="subscribe",
    )
    try:
        result = await gen.__anext__()
    finally:
        await gen.aclose()
    assert result.ok is False


# ---------------------------------------------------------------------------
# (b) filter key validation
# ---------------------------------------------------------------------------


async def test_declared_field_filter_accepted():
    """A filter on a declared output field is accepted."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-1", session_key="s1")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-1",
        action="create",
        operation="subscribe",
        filters={"username": "neo"},
        _session_key="s1",
    )
    assert result.ok is True


async def test_declared_field_with_lookup_suffix_accepted():
    """Filters like ``username__icontains`` are accepted (declared root + suffix)."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-2", session_key="s2")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-2",
        action="create",
        operation="subscribe",
        filters={"username__icontains": "neo"},
        _session_key="s2",
    )
    assert result.ok is True


async def test_undeclared_root_field_rejected():
    """A filter whose root field is not in the output type is rejected.

    Uses ``logentry_set`` — a reverse relation not exposed in the serialized
    output — to confirm that ORM traversal into undeclared fields is blocked.
    """
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-3", session_key="s3")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-3",
        action="create",
        operation="subscribe",
        # logentry_set is a reverse relation, not in output_field_names()
        filters={"logentry_set__action_flag": 1},
        _session_key="s3",
    )
    assert result.ok is False
    assert "filter" in result.error.lower() or "field" in result.error.lower()


async def test_undeclared_root_field_no_suffix_rejected():
    """A plain filter on an undeclared field is rejected.

    ``logentry_set`` (reverse relation to LogEntry) is not in the serialized
    output of UserSubscription, so it must be rejected at subscribe time.
    """
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-4", session_key="s4")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-4",
        action="create",
        operation="subscribe",
        # non-existent output field — probing the raw DB column name not exposed
        filters={"logentry_set": None},
        _session_key="s4",
    )
    assert result.ok is False


async def test_empty_filters_accepted():
    """No filters at all is always accepted."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-5", session_key="s5")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-5",
        action="create",
        operation="subscribe",
        _session_key="s5",
    )
    assert result.ok is True


async def test_none_filters_accepted():
    """filters=None is always accepted (no filtering requested)."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("filter-chan-6", session_key="s6")
    result = await run_subscribe(
        UserSubscription,
        channel_id="filter-chan-6",
        action="create",
        operation="subscribe",
        filters=None,
        _session_key="s6",
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# (d) percent-encoded index group names
# ---------------------------------------------------------------------------


def test_index_group_name_encodes_equals_in_value():
    """A value containing '=' is percent-encoded in the group suffix."""
    from django_graphex.subscriptions.subscription import Subscription

    # The index group name must not contain raw '=' inside a value.
    name = Subscription._group_name.__func__(
        UserSubscription,
        "update",
        index={"owner": "a=b"},
    )
    # After safe_group_name processing, the raw '=' in the value should be
    # encoded — either the group was hashed or the suffix has %3D.
    from django_graphex.subscriptions.mixins import _GROUP_NAME_RE

    if _GROUP_NAME_RE.match(name):
        # The name is used verbatim: it must not contain raw ambiguous chars
        # in the value portion — either encoding is present or name was hashed.
        assert "a=b" not in name or name.startswith("gde.")
    # Either way the name must be Channels-safe.
    from django_graphex.subscriptions.mixins import safe_group_name

    assert safe_group_name(name) == name


def test_index_group_name_encodes_ampersand_in_value():
    """A value containing '&' is percent-encoded."""
    name = UserSubscription._group_name("create", index={"tag": "a&b"})

    # The raw '&' must not appear unencoded in the final group name.
    from django_graphex.subscriptions.mixins import safe_group_name

    assert safe_group_name(name) == name
    # The group name should not contain literal 'a&b' unless the whole thing
    # was hashed (starts with 'gde.').
    if not name.startswith("gde."):
        assert "a&b" not in name


def test_index_group_name_plain_values_unchanged():
    """Values with no special characters are not modified."""
    name = UserSubscription._group_name("update", index={"owner": "42"})
    # Should contain the plain value directly (no encoding needed).
    assert "owner=42" in name or name.startswith("gde.")


# ---------------------------------------------------------------------------
# (e) client.py HTML / JS escaping
# ---------------------------------------------------------------------------


def test_client_view_escapes_double_quote_in_ws_path():
    """ws_path containing a double-quote is JSON-escaped in the rendered HTML.

    A raw double quote would close the JS string literal and enable XSS.
    ``json.dumps`` escapes it as ``\\"``.
    """
    from django_graphex.subscriptions.client import SubscriptionClientView

    factory = RequestFactory()
    request = factory.get("/")
    view = SubscriptionClientView.as_view(
        ws_path='/ws/path"inject/', http_path="/graphql"
    )
    response = view(request)
    content = response.content.decode()
    # The raw double-quote must not appear unescaped inside the JS string.
    # json.dumps encodes it as \", so the rendered page has \".
    assert '"/ws/path"inject/' not in content
    # The escaped form must be present.
    assert r"path\"inject" in content or 'path\\"inject' in content


def test_client_view_escapes_backslash_in_http_path():
    """http_path containing a backslash is JSON-escaped.

    A raw backslash in a JS string literal can produce unintended escape
    sequences (e.g. ``\\n`` → newline, ``\\x00`` → null byte).
    ``json.dumps`` doubles the backslash so it renders as a literal backslash.
    """
    from django_graphex.subscriptions.client import SubscriptionClientView

    factory = RequestFactory()
    request = factory.get("/")
    view = SubscriptionClientView.as_view(ws_path="/ws/", http_path="/graphql\\path")
    response = view(request)
    content = response.content.decode()
    # A single raw backslash in the original path must not appear as a single
    # backslash in the JS source; it must be doubled (escaped).
    # We look for the doubled form in the rendered HTML.
    assert r"\\path" in content or "\\\\path" in content


def test_client_view_normal_paths_render_correctly():
    """Normal paths (no special chars) are injected correctly."""
    from django_graphex.subscriptions.client import SubscriptionClientView

    factory = RequestFactory()
    request = factory.get("/")
    view = SubscriptionClientView.as_view(ws_path="/ws/graphql/", http_path="/graphql")
    response = view(request)
    content = response.content.decode()
    # The paths must appear in the rendered output in some form.
    assert "/ws/graphql/" in content
    assert "/graphql" in content
