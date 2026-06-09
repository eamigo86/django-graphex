# -*- coding: utf-8 -*-
"""T-UNIT: group names, model label, enum generation and field projection."""

from graphene import NonNull, String

from django_graphex.subscriptions import (
    ActionSubscriptionEnum,
    OperationSubscriptionEnum,
)
from django_graphex.subscriptions.mixins import (
    MAX_GROUP_NAME_LENGTH,
    project_fields,
    safe_group_name,
    serialize_instance,
    split_filters,
)

from .schema import UserSubscription


def test_model_label():
    assert UserSubscription.model_label() == "auth.user"


def test_group_name_with_and_without_id():
    assert UserSubscription._group_name("create") == "auth.user-create"
    assert UserSubscription._group_name("update", id=5) == "auth.user-update-5"


def test_safe_group_name_passthrough():
    name = "auth.user-update-5"
    assert safe_group_name(name) == name


def test_safe_group_name_hashes_overflowing_label():
    long_name = "auth.user-update-" + "x" * (MAX_GROUP_NAME_LENGTH + 10)
    safe = safe_group_name(long_name)
    assert safe != long_name
    assert len(safe) <= MAX_GROUP_NAME_LENGTH
    assert safe.startswith("gde.")
    # Deterministic: same input -> same group name on both producer & consumer.
    assert safe_group_name(long_name) == safe


def test_safe_group_name_hashes_invalid_charset():
    invalid = "auth.user-update-josé/garcía"
    assert safe_group_name(invalid).startswith("gde.")


def test_project_fields():
    data = {"id": 1, "username": "a", "email": "b"}
    assert project_fields(data, ["username"]) == {"username": "a"}
    assert project_fields(data, None) == data
    assert project_fields(data, []) == data
    assert project_fields(data, ["username", "email"]) == {
        "username": "a",
        "email": "b",
    }


def test_action_enum_values_snapshot():
    assert {e.name: e.value for e in ActionSubscriptionEnum} == {
        "CREATE": "create",
        "UPDATE": "update",
        "DELETE": "delete",
        "ALL_ACTIONS": "all_actions",
    }


def test_operation_enum_values_snapshot():
    assert {e.name: e.value for e in OperationSubscriptionEnum} == {
        "SUBSCRIBE": "subscribe",
        "UNSUBSCRIBE": "unsubscribe",
    }


def test_generated_fields_enum():
    data_arg = UserSubscription._meta.arguments["data"]
    enum_cls = data_arg.of_type  # List(<Model>Fields)
    names = {member.name for member in enum_cls._meta.enum}
    values = {member.value for member in enum_cls._meta.enum}
    assert {"ID", "USERNAME", "EMAIL"} <= names
    assert {"id", "username", "email"} <= values


def test_split_filters_in_memory_match_and_mismatch():
    data = {"id": 1, "post": 7, "text": "hello"}
    # Plain-equality match (string-coerced) -> nothing left for the DB.
    assert split_filters(data, {"post": 7}) == {}
    assert split_filters(data, {"post": "7"}) == {}
    # Plain-equality mismatch -> drop (None), no DB needed.
    assert split_filters(data, {"post": 9}) is None
    # Lookups and absent fields are deferred to the DB.
    assert split_filters(data, {"text__icontains": "ell"}) == {"text__icontains": "ell"}
    assert split_filters(data, {"author": 3}) == {"author": 3}
    # A satisfied equality is dropped while the lookup is deferred.
    assert split_filters(data, {"post": 7, "text__icontains": "ell"}) == {
        "text__icontains": "ell"
    }


def test_generated_arguments_contract():
    args = UserSubscription._meta.arguments
    assert set(args) == {
        "channel_id",
        "action",
        "operation",
        "id",
        "data",
        "filters",
    }
    # `channel_id` is required -> wrapped in NonNull(String).
    channel_id_type = args["channel_id"].type
    assert isinstance(channel_id_type, NonNull)
    assert channel_id_type.of_type is String


def test_serialize_instance_returns_jsonable_dict(db, django_user_model):
    user = django_user_model.objects.create(username="bob", email="bob@example.com")
    from django_graphex.native.backend import PydanticBackend

    data = serialize_instance(PydanticBackend(django_user_model), user)
    assert data["username"] == "bob"
    assert data["email"] == "bob@example.com"
    assert isinstance(data, dict)


# --------------------------------------------------------------------------- #
# GraphqlAPIDemultiplexer._resolve_subscription / _matches_filters branches    #
# --------------------------------------------------------------------------- #
def test_resolve_subscription_from_subclass_and_binding():
    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    # A plain Subscription subclass resolves to itself.
    assert (
        GraphqlAPIDemultiplexer._resolve_subscription(UserSubscription)
        is UserSubscription
    )

    # A SubscriptionBinding resolves to its .subscription_cls (line 188).
    binding = UserSubscription.get_binding()
    assert (
        GraphqlAPIDemultiplexer._resolve_subscription(binding)
        is binding.subscription_cls
    )


def test_resolve_subscription_from_object_with_subscription_cls():
    from types import SimpleNamespace

    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    # An object exposing `.subscription_cls` (line 189-190).
    holder = SimpleNamespace(subscription_cls=UserSubscription)
    assert GraphqlAPIDemultiplexer._resolve_subscription(holder) is UserSubscription


async def test_matches_filters_fails_closed_without_subscription_or_pk():
    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    consumer = GraphqlAPIDemultiplexer()
    consumer.subscriptions = {"users": UserSubscription}
    # A filter that can't be settled in memory (the key isn't in the payload),
    # with no pk in the event -> the DB-verification path fails closed (line 133).
    event = {"stream": "users", "pk": None}
    payload = {"data": {"username": "x"}}
    filters = {"is_staff": True}
    assert await consumer._matches_filters(event, payload, filters) is False


async def test_matches_filters_db_lookup_invalid_filter_fails_closed(db):
    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    consumer = GraphqlAPIDemultiplexer()
    consumer.subscriptions = {"users": UserSubscription}
    # A bogus field name -> FieldError when the DB-verification query is built
    # inside _exists -> the notification is dropped (fails closed, lines 139-145).
    # The pk need not exist; the FieldError fires before any row is matched.
    event = {"stream": "users", "pk": 1}
    payload = {"data": {"username": "u1"}}
    filters = {"not_a_real_field": "x"}
    assert await consumer._matches_filters(event, payload, filters) is False
