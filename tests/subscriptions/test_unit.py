# -*- coding: utf-8 -*-
"""T-UNIT: group names, model label, enum generation and filter splitting.

Post-WU11 cutover: the bespoke-transport units (``project_fields``,
``OperationSubscriptionEnum``, the ``channel_id``/``operation``/``data`` argument
contract and the ``GraphqlAPIDemultiplexer`` resolution/filter branches) are
retired with the bespoke transport. What remains are the transport-agnostic
engine units the native path still relies on.
"""

from django_graphex.subscriptions import ActionSubscriptionEnum
from django_graphex.subscriptions.mixins import (
    MAX_GROUP_NAME_LENGTH,
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


def test_action_enum_values_snapshot():
    assert {e.name: e.value for e in ActionSubscriptionEnum} == {
        "CREATE": "create",
        "UPDATE": "update",
        "DELETE": "delete",
        "ALL_ACTIONS": "all_actions",
    }


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
    """Native-only arg set after the cutover: {action, id, filters}.

    The bespoke ``channel_id``/``operation`` args and the ``data`` field-projection
    enum are gone (selection-set projection + WS/SSE auth boundary replaced them).
    """
    from graphene import NonNull

    args = UserSubscription._meta.arguments
    assert set(args) == {"action", "id", "filters"}
    # `action` is required -> wrapped in NonNull(ActionSubscriptionEnum).
    action_type = args["action"].type
    assert isinstance(action_type, NonNull)
    assert action_type.of_type is ActionSubscriptionEnum


def test_serialize_instance_returns_jsonable_dict(db, django_user_model):
    user = django_user_model.objects.create(username="bob", email="bob@example.com")
    from django_graphex.native.backend import PydanticBackend

    data = serialize_instance(PydanticBackend(django_user_model), user)
    assert data["username"] == "bob"
    assert data["email"] == "bob@example.com"
    assert isinstance(data, dict)
