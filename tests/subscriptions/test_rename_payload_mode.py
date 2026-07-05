"""TDD RED — Rename 2: subscription "Meta.serialize_data" to "Meta.payload_mode".

v2.0 HARD rename (no alias). The per-subscription override and the global setting
are renamed; the SEMANTICS are unchanged (only the NAME and value vocabulary):

- "payload_mode='id_only'" (default) -> payload is "{'id': <pk>}".
- "payload_mode='full'"              -> flat serialization of concrete fields.
- "payload_mode=None"                -> inherit the global setting.

Setting: "SUBSCRIPTION_SERIALIZE_DATA" (bool) -> "SUBSCRIPTION_PAYLOAD_MODE"
("id_only" | "full"), default "id_only".

Value mapping from the old booleans: True -> "full", False -> "id_only".

Guards:
- "Meta.serialize_data" present -> ImproperlyConfigured naming the rename.
- Old setting key "SUBSCRIPTION_SERIALIZE_DATA" in "DJANGO_GRAPHEX" -> loud error.
- "payload_mode" value other than "full"/"id_only"/None ->
  ImproperlyConfigured naming both valid values.

Run:
    .venv/bin/python -m pytest -q tests/subscriptions/test_rename_payload_mode.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test import override_settings

from tests.models import DummyModel

if TYPE_CHECKING:
    from django_graphex.subscriptions import Subscription


class RenamePayloadNote(DummyModel):
    """A minimal Django model used to exercise the payload_mode rename guards.

    Carries a single title field; the model's data itself is not exercised,
    only its presence as a valid Meta.model target.
    """

    title = models.CharField(max_length=50, default="")


# ---------------------------------------------------------------------------
# Meta.payload_mode — new name works, values map to the kept semantics
# ---------------------------------------------------------------------------

# Unique stream counter so each ad-hoc Subscription subclass gets its own stream.
_stream_seq = 0


def _make_subscription(
    payload_mode: str | None, *, stream: str | None = None
) -> type["Subscription"]:
    """Build an ad-hoc Subscription subclass over RenamePayloadNote.

    Args:
        payload_mode: The Meta.payload_mode value to set on the subclass.
        stream: An explicit stream name; when None, a unique name is
            generated from the module-level sequence counter.

    Returns:
        NoteSub: The freshly created Subscription subclass.
    """
    global _stream_seq
    from django_graphex.subscriptions import Subscription

    if stream is None:
        _stream_seq += 1
        stream = f"rename-notes-{_stream_seq}"

    stream_name = stream
    mode = payload_mode

    class NoteSub(Subscription):
        class Meta:
            model = RenamePayloadNote
            stream = stream_name
            payload_mode = mode

    return NoteSub


@pytest.mark.parametrize(
    "payload_mode,expected_full",
    [
        ("full", True),
        ("id_only", False),
    ],
)
def test_payload_mode_sets_meta_and_full_decision(
    payload_mode: str, expected_full: bool
) -> None:
    """ "Meta.payload_mode" must drive "_payload_is_full()" per the kept semantics.

    Contract: this test ships broken if either payload_mode value stops
    matching its expected full/id_only decision.

    Args:
        payload_mode: The parametrized Meta.payload_mode value under test.
        expected_full: The expected result of _payload_is_full() for that
            payload_mode value.
    """
    sub = _make_subscription(payload_mode)
    assert sub._meta.payload_mode == payload_mode
    assert sub._payload_is_full() is expected_full


def test_payload_mode_none_inherits_setting_full() -> None:
    """ "payload_mode=None" must inherit the global "SUBSCRIPTION_PAYLOAD_MODE".

    Contract: per-subscription inheritance ships broken if a None
    payload_mode ignores the global setting instead of following it.
    """
    sub = _make_subscription(None)
    with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PAYLOAD_MODE": "full"}):
        assert sub._payload_is_full() is True
    with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PAYLOAD_MODE": "id_only"}):
        assert sub._payload_is_full() is False


def test_setting_default_is_id_only() -> None:
    """The global default must be "id_only" (id-only payloads).

    Contract: existing deployments ship broken if the default silently
    switches to full-payload serialization.
    """
    from django_graphex.settings import graphql_api_settings

    assert graphql_api_settings.SUBSCRIPTION_PAYLOAD_MODE == "id_only"


# ---------------------------------------------------------------------------
# Guard: legacy Meta.serialize_data raises ImproperlyConfigured
# ---------------------------------------------------------------------------


def test_legacy_meta_serialize_data_raises() -> None:
    """Declaring the old "Meta.serialize_data" must fail loudly with a rename hint.

    Contract: users migrating from the old boolean flag ship broken if the
    raised error omits either the old or the new attribute name.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(ImproperlyConfigured) as exc:

        class NoteSub(Subscription):
            class Meta:
                model = RenamePayloadNote
                stream = "rename-legacy-serialize"
                serialize_data = True

    msg = str(exc.value)
    assert "serialize_data" in msg
    assert "payload_mode" in msg


# ---------------------------------------------------------------------------
# Guard: invalid payload_mode value
# ---------------------------------------------------------------------------


def test_invalid_payload_mode_value_raises() -> None:
    """An invalid "payload_mode" value must raise, naming both valid values.

    Contract: misconfiguration ships broken (silent wrong behavior) if a
    typo'd payload_mode value is accepted instead of raising with the two
    valid values named in the message.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(ImproperlyConfigured) as exc:

        class NoteSub(Subscription):
            class Meta:
                model = RenamePayloadNote
                stream = "rename-invalid-value"
                payload_mode = "everything"

    msg = str(exc.value)
    assert "full" in msg
    assert "id_only" in msg


# ---------------------------------------------------------------------------
# Guard: legacy setting key SUBSCRIPTION_SERIALIZE_DATA
# ---------------------------------------------------------------------------


def test_legacy_setting_key_raises() -> None:
    """The old "SUBSCRIPTION_SERIALIZE_DATA" setting key must fail loudly when read.

    Contract: projects still carrying the old setting key ship broken
    (silently ignored config) if reading it does not raise, naming both the
    old and new setting keys.
    """
    sub = _make_subscription(None)
    with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_SERIALIZE_DATA": True}):
        with pytest.raises(ImproperlyConfigured) as exc:
            sub._payload_is_full()
    msg = str(exc.value)
    assert "SUBSCRIPTION_SERIALIZE_DATA" in msg
    assert "SUBSCRIPTION_PAYLOAD_MODE" in msg


# ---------------------------------------------------------------------------
# DjangoModelType Meta forwarding
# ---------------------------------------------------------------------------


def test_model_type_forwards_payload_mode() -> None:
    """ "DjangoModelType" must forward "Meta.payload_mode" to its Subscription.

    Contract: the generated subscription ships broken (wrong payload shape)
    if the model type's payload_mode setting is not propagated to the
    Subscription it builds.
    """
    from django_graphex.types import DjangoModelType

    class NoteType(DjangoModelType):
        class Meta:
            model = RenamePayloadNote
            stream = "rename-note-model-stream"
            payload_mode = "full"

    sub_cls = NoteType.subscription_type()
    assert sub_cls._meta.payload_mode == "full"
    assert sub_cls._payload_is_full() is True
