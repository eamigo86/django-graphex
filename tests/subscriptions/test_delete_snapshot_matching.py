"""Real native delete delivery and conservative private-snapshot regressions."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.db import transaction
from graphql import ExecutionResult, GraphQLBoolean, parse, subscribe

from django_graphex.core import ObjectType, field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.subscriptions import Subscription
from django_graphex.subscriptions.source import ChannelLayerSource
from tests._schema_isolation import isolated_pair
from tests.models import BasicModel, ScalarKindsModel


def test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep only projected native scalars and fail closed on backend mismatch.

    Args:
        monkeypatch: Restore the deliberately unsupported backend afterward.
    """

    class ProjectedSubscription(Subscription):
        """Expose several scalar and non-scalar projected model fields."""

        class Meta:
            """Use the native backend with a deliberately narrow projection."""

            model = ScalarKindsModel
            stream = "mu2_projected_scalar_capture"
            payload_mode = "id_only"
            only_fields = ("id", "char", "floating", "json_field", "author")

    instance = ScalarKindsModel(
        id=7,
        char="safe",
        floating=float("nan"),
        json_field={"private": "never copied"},
        author_id=9,
    )
    assert ProjectedSubscription._serialize_delete_match(instance) == {
        "id": 7,
        "char": "safe",
    }
    monkeypatch.setattr(ProjectedSubscription._meta, "backend", object())
    assert ProjectedSubscription._serialize_delete_match(instance) == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("mode", "scope", "client", "row_text", "excluded", "deferred", "delivered"),
    [
        ("id_only", {}, "tenant-a", "tenant-a", False, False, True),
        ("id_only", {"text": "tenant-a"}, None, "tenant-a", False, False, True),
        ("id_only", {"text": "tenant-a"}, "tenant-b", "tenant-a", False, False, True),
        ("id_only", {"text": "tenant-a"}, None, "tenant-b", False, False, False),
        ("id_only", {"text": "tenant-a"}, None, "tenant-a", True, False, False),
        ("id_only", {}, None, "tenant-a", False, False, True),
        ("id_only", {}, None, "tenant-a", False, True, True),
        ("id_only", {}, "pk", "tenant-a", False, True, True),
        ("id_only", {"text": "tenant-a"}, None, "tenant-a", False, True, False),
        ("full", {"text": "tenant-a"}, None, "tenant-a", False, False, True),
        ("full", {"text__startswith": "tenant"}, None, "tenant-a", False, False, False),
    ],
)
async def test_real_delete_uses_signal_time_projected_equality(
    mode: str,
    scope: dict[str, Any],
    client: str | None,
    row_text: str,
    excluded: bool,
    deferred: bool,
    delivered: bool,
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Deliver only equal projected deletes after the row has gone.

    Args:
        mode: Public notification payload mode.
        scope: Server-forced filters.
        client: Optional conflicting client equality.
        row_text: Actual deleted row value.
        excluded: Whether text is projected out of the subscription.
        deferred: Whether the deleted model instance omits text at signal time.
        delivered: Expected native GraphQL event outcome.
        captured_group_sends: Actual channel messages produced by the binding.
    """

    class ItemSubscription(Subscription):
        """Expose the real BasicModel signal path."""

        class Meta:
            """Configure a unique stream per native schema."""

            model = BasicModel
            stream = f"mu2_delete_{mode}_{row_text}_{client}_{len(scope)}_{deferred}"
            payload_mode = mode
            exclude_fields = ("text",) if excluded else ()

        @classmethod
        def subscription_scope(cls, info: Any, **kwargs: Any) -> dict[str, Any]:
            """Return the server's immutable test scope.

            Args:
                info: Native subscription context.
                **kwargs: GraphQL subscription arguments.

            Returns:
                The forced scope for this case.
            """
            return dict(scope)

    class Query(ObjectType):
        """Provide the required query root."""

        ok = field(GraphQLBoolean)

    class Root(ObjectType):
        """Expose the public subscription field."""

        item = ItemSubscription.Field()

    schema = DjangoGraphQLSchema(
        query=Query, subscription=Root, registries=isolated_pair(Registry())
    ).graphql_schema
    binding = ItemSubscription.get_binding()
    layer = get_channel_layer()
    await layer.flush()
    row = await sync_to_async(BasicModel.objects.create, thread_sensitive=True)(
        text=row_text
    )
    if deferred:
        row = await sync_to_async(
            BasicModel.objects.only("id").get, thread_sensitive=True
        )(pk=row.pk)
        assert row.get_deferred_fields() == {"text"}
    if client == "pk":
        client_arg = f', id: "{row.pk}"'
    else:
        client_arg = f', filter: {{text: {{exact: "{client}"}}}}' if client else ""
    selection = "id text" if mode == "full" else "id"
    document = parse(
        f"subscription {{ item(action: DELETE{client_arg}) {{ {selection} }} }}"
    )
    result = subscribe(schema, document, context_value=SimpleNamespace(user=None))
    stream = await result if inspect.isawaitable(result) else result
    assert not isinstance(stream, ExecutionResult)
    try:

        def delete_row() -> int:
            """Delete and commit the row through Django's actual signal path.

            Returns:
                The original primary key.
            """
            pk = row.pk
            with transaction.atomic():
                row.delete()
                row.text = "mutated after post_delete before commit"
            return pk

        pk = await sync_to_async(delete_row, thread_sensitive=True)()
        sends = [
            message
            for _, message in captured_group_sends
            if message.get("stream") == ItemSubscription._meta.stream
            and message["payload"]["action"] == "delete"
        ]
        assert len(sends) == 2
        assert all(message["pk"] == pk for message in sends)
        if excluded or deferred:
            assert all("text" not in message["delete_match"] for message in sends)
        if mode == "id_only":
            assert all(message["payload"]["data"] == {"id": pk} for message in sends)
        assert not await sync_to_async(
            BasicModel.objects.filter(pk=pk).exists, thread_sensitive=True
        )()
        try:
            event = await asyncio.wait_for(stream.__anext__(), timeout=0.35)
        except TimeoutError:
            assert not delivered
        else:
            assert delivered
            assert not event.errors
            assert event.data["item"]["id"] == str(pk)
            if mode == "id_only":
                assert set(event.data["item"]) == {"id"}
            else:
                assert event.data["item"]["text"] == row_text
    finally:
        await stream.aclose()
        binding.unregister()


@pytest.mark.parametrize(
    "private_snapshot",
    [
        None,
        {},
        {"text": None},
        {"text": ["tenant-a"]},
        {"text": "other"},
        {"text": float("nan")},
    ],
)
async def test_missing_or_malformed_private_delete_snapshot_fails_closed(
    private_snapshot: Any,
) -> None:
    """Never accept an unverified delete merely because its public PK exists.

    Args:
        private_snapshot: Absent, incomplete, invalid, or mismatched metadata.
    """
    layer = get_channel_layer()
    source = ChannelLayerSource(
        groups=["mu2-delete-fault"],
        channel_layer=layer,
        filters={"text": "tenant-a"},
    )
    await source.start()
    message = {
        "type": "subscription.notify",
        "group": "mu2-delete-fault",
        "pk": 1,
        "payload": {"action": "delete", "model": "tests.basicmodel", "data": {"id": 1}},
    }
    if private_snapshot is not None:
        message["delete_match"] = private_snapshot
    try:
        await layer.group_send("mu2-delete-fault", message)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(source.__anext__(), timeout=0.1)
    finally:
        await source.aclose()


@pytest.mark.parametrize(
    ("snapshot", "expected", "delivered"),
    [
        ("1.00", Decimal("1.0"), True),
        ("NaN", Decimal("1.0"), False),
        (
            "2026-10-18T12:00:00.123456+00:00",
            datetime.fromisoformat("2026-10-18T17:30:00.123456+05:30"),
            True,
        ),
        (
            "2026-10-18T12:00:00.123456+00:00",
            datetime.fromisoformat("2026-10-18T12:00:00.123457+00:00"),
            False,
        ),
        (None, "None", False),
        (None, None, True),
    ],
)
async def test_private_delete_equality_preserves_typed_scalar_contract(
    snapshot: Any, expected: Any, delivered: bool
) -> None:
    """Apply existing exact scalar semantics without coercing null to text.

    Args:
        snapshot: JSON-safe private value.
        expected: Parsed client or server equality value.
        delivered: Whether this value matches exactly.
    """
    layer = get_channel_layer()
    source = ChannelLayerSource(
        groups=["mu2-delete-typed"],
        channel_layer=layer,
        filters={"value": expected},
    )
    await source.start()
    message = {
        "type": "subscription.notify",
        "group": "mu2-delete-typed",
        "pk": 1,
        "payload": {"action": "delete", "model": "tests.basicmodel", "data": {"id": 1}},
        "delete_match": {"value": snapshot},
    }
    try:
        await layer.group_send("mu2-delete-typed", message)
        if delivered:
            assert await asyncio.wait_for(source.__anext__(), timeout=0.3) == {"id": 1}
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(source.__anext__(), timeout=0.1)
    finally:
        await source.aclose()
