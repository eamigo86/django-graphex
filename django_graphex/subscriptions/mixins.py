"""Provide serialization and field-projection helpers for subscriptions."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.core.serializers.json import DjangoJSONEncoder

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.db.models import Model

    from ..backends import SerializerBackend

# Channels restricts group names to this charset and length (see
# ``channels.layers.BaseChannelLayer.valid_group_name``).
MAX_GROUP_NAME_LENGTH = 100
_GROUP_NAME_RE = re.compile(r"^[a-zA-Z\d\-_.]+$")


def _matches_decimal_snapshot(snapshot: Any, expected: Decimal) -> bool:
    """Compare a finite JSON-safe Decimal snapshot to a typed filter value.

    Args:
        snapshot: The value captured when the notification was produced.
        expected: The parsed Decimal filter value.

    Returns:
        Whether both finite values represent the same number.
    """
    if not isinstance(snapshot, str) or not expected.is_finite():
        return False
    try:
        captured = Decimal(snapshot)
    except InvalidOperation:
        return False
    return captured.is_finite() and captured == expected


def _matches_datetime_snapshot(snapshot: Any, expected: datetime) -> bool:
    """Compare an ISO wire value with an exact typed DateTime filter.

    Args:
        snapshot: The JSON-safe value captured at event time.
        expected: The parsed DateTime filter value.

    Returns:
        Whether both values denote the same instant without rounding.
    """
    if not isinstance(snapshot, str):
        return False
    try:
        captured = datetime.fromisoformat(snapshot)
    except ValueError:
        return False
    return captured == expected


def _matches_numeric_snapshot(snapshot: Any, expected: Any) -> bool:
    """Compare a numeric snapshot to a numeric filter value by value.

    Mirrors database equality: an int or Decimal compared with a float is first
    rounded to the nearest float (what a float column stores), so
    "2**53 + 1" equals "float(2**53)" and "Decimal('0.1')" equals "0.1". Int
    and Decimal compare exactly. Booleans, non-finite values and integers
    beyond the float range never match.

    Args:
        snapshot: The value captured when the notification was produced.
        expected: The parsed filter value.

    Returns:
        Whether both are finite int, float or Decimal values of equal value.
    """
    kinds = (type(snapshot), type(expected))
    if not all(kind in (int, float, Decimal) for kind in kinds):
        return False
    for kind, value in zip(kinds, (snapshot, expected), strict=True):
        # An int is always finite (and math.isfinite overflows on huge ones).
        if kind is float and not math.isfinite(value):
            return False
        if kind is Decimal and not value.is_finite():
            return False
    if float in kinds:
        try:
            return float(snapshot) == float(expected)
        except OverflowError:
            return False
    return bool(snapshot == expected)


class _LosslessDateTimeJSONEncoder(DjangoJSONEncoder):
    """Keep DateTime microseconds while retaining Django's other JSON rules."""

    def default(self, value: Any) -> Any:
        """Encode DateTime without Django's millisecond truncation.

        Args:
            value: The value to encode.

        Returns:
            An ISO DateTime or Django's existing representation.
        """
        if isinstance(value, datetime):
            return value.isoformat()
        return super().default(value)


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

    Plain-equality keys (no "__" lookup) whose field is present in the serialized
    "data" are compared in memory. Existing equal string forms still match
    (including 7 and "7"); a typed Decimal filter also matches a finite,
    numerically equal JSON-safe string snapshot. Finite int, float and Decimal
    values (never bool) match by value, including opposite signed zeros; a float
    on either side rounds the other operand to the nearest float first, like a
    float column. A mismatch short-circuits the notification without consulting the current database row.

    Args:
        data: The serialized instance mapping carried by the notification.
        filters: A mapping of Django ORM lookup to expected value.

    Returns:
        "None" when an in-memory comparison already fails (drop the
        notification), otherwise the mapping of remaining filters that require a
        single-row database check (possibly empty, meaning fully matched).
    """
    remaining: dict[str, Any] = {}
    for key, value in filters.items():
        if "__" not in key and isinstance(data, dict) and key in data:
            if (
                str(data[key]) != str(value)
                and not (
                    isinstance(value, Decimal)
                    and _matches_decimal_snapshot(data[key], value)
                )
                and not (
                    isinstance(value, datetime)
                    and _matches_datetime_snapshot(data[key], value)
                )
                and not _matches_numeric_snapshot(data[key], value)
            ):
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
    normalized through Django's JSON rules to keep dates/decimals safe.
    DateTime values retain all six microsecond digits when present.

    Args:
        backend: The subscription's serializer backend.
        instance: The model instance to serialize.

    Returns:
        A JSON-safe mapping of the serialized instance.
    """
    data = backend.to_representation(instance)
    return json.loads(json.dumps(data, cls=_LosslessDateTimeJSONEncoder))
