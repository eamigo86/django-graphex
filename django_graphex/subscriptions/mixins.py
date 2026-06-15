"""Provide serialization and field-projection helpers for subscriptions."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from django.core.serializers.json import DjangoJSONEncoder

if TYPE_CHECKING:
    from django.db.models import Model

    from ..backends import SerializerBackend

# Channels restricts group names to this charset and length (see
# ``channels.layers.BaseChannelLayer.valid_group_name``).
MAX_GROUP_NAME_LENGTH = 100
_GROUP_NAME_RE = re.compile(r"^[a-zA-Z\d\-_.]+$")


def safe_group_name(name: str) -> str:
    """Return a Channels-safe group name.

    Names that exceed the length limit or contain characters outside the
    allowed charset are deterministically hashed so that the producer (signal
    binding) and the consumer (resolver) always agree on the same value.

    Args:
        name: The desired group name.

    Returns:
        The original name when valid, otherwise a hashed, prefixed name.
    """
    if len(name) <= MAX_GROUP_NAME_LENGTH and _GROUP_NAME_RE.match(name):
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"gde.{digest}"


def split_filters(
    data: dict[str, Any] | None,
    filters: dict[str, Any],
) -> dict[str, Any] | None:
    """Decide notification filters in memory, returning what still needs the DB.

    Plain-equality keys (no ``"__"`` lookup) whose field is present in the
    serialized ``data`` are compared in memory (string-coerced, so ``7`` matches
    ``"7"``). A mismatch short-circuits the whole notification.

    Args:
        data: The serialized instance mapping carried by the notification.
        filters: A mapping of Django ORM lookup to expected value.

    Returns:
        ``None`` when an in-memory comparison already fails (drop the
        notification), otherwise the mapping of remaining filters that require a
        single-row database check (possibly empty, meaning "fully matched").
    """
    remaining: dict[str, Any] = {}
    for key, value in filters.items():
        if "__" not in key and isinstance(data, dict) and key in data:
            if str(data[key]) != str(value):
                return None
        else:
            remaining[key] = value
    return remaining


def serialize_instance(
    backend: SerializerBackend,
    instance: Model,
) -> dict[str, Any]:
    """Serialize "instance" once into a JSON-safe mapping.

    The payload travels over the channel layer (msgpack/JSON), so values are
    normalized through "DjangoJSONEncoder" to keep dates/decimals safe.

    Args:
        backend: The subscription's serializer backend.
        instance: The model instance to serialize.

    Returns:
        A JSON-safe mapping of the serialized instance.
    """
    data = backend.to_representation(instance)
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
