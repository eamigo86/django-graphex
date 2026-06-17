# -*- coding: utf-8 -*-
"""T-UNIT: group names, model label, enum generation and filter splitting.

Post-WU11 cutover: the bespoke-transport units (``project_fields``,
``OperationSubscriptionEnum``, the ``channel_id``/``operation``/``data`` argument
contract and the ``GraphqlAPIDemultiplexer`` resolution/filter branches) are
retired with the bespoke transport. What remains are the transport-agnostic
engine units the native path still relies on.
"""

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
    """The native action enum (built into ``_meta.arguments``) carries the
    canonical {CREATE, UPDATE, DELETE, ALL_ACTIONS} values.

    S-del-backend-11: the graphene ``ActionSubscriptionEnum`` re-export was deleted
    with the graphene backend; the action enum is now the native graphql-core
    ``GraphQLEnumType`` the subscription field carries.
    """
    from graphql import GraphQLNonNull

    action_type = UserSubscription._meta.arguments["action"].type
    assert isinstance(action_type, GraphQLNonNull)
    enum_values = {
        name: value.value for name, value in action_type.of_type.values.items()
    }
    assert enum_values == {
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

    S-sub-6: ``_meta.arguments`` is now built NATIVELY (graphene-free) — graphql-core
    ``GraphQLArgument`` values, ``action`` wrapped in ``GraphQLNonNull`` of a
    graphql-core action ``GraphQLEnumType``. (The graphene ``ActionSubscriptionEnum``
    is no longer on the build path.)
    """
    from graphql import GraphQLNonNull
    from graphql.type import GraphQLEnumType

    args = UserSubscription._meta.arguments
    assert set(args) == {"action", "id", "filters"}
    # `action` is required -> wrapped in GraphQLNonNull of the action enum.
    action_type = args["action"].type
    assert isinstance(action_type, GraphQLNonNull)
    assert isinstance(action_type.of_type, GraphQLEnumType)
    assert action_type.of_type.name == "UserSubscriptionAction"


def test_serialize_instance_returns_jsonable_dict(db, django_user_model):
    user = django_user_model.objects.create(username="bob", email="bob@example.com")
    from django_graphex.native.backend import PydanticBackend

    data = serialize_instance(PydanticBackend(django_user_model), user)
    assert data["username"] == "bob"
    assert data["email"] == "bob@example.com"
    assert isinstance(data, dict)


# --------------------------------------------------------------------------- #
# Audit rank 20: the WS live-consumer registry is a WeakValueDictionary. When  #
# the consumer (the weak VALUE) is garbage-collected, get_live_consumer()      #
# returns None. This is a test/introspection-utility caveat only — a real      #
# subscription is unaffected because the live consumer keeps its own strong    #
# refs (Channels + its operation registry/sources). ws.py imports channels     #
# LAZILY, so get_live_consumer / _LIVE_CONSUMERS are importable without it.    #
# --------------------------------------------------------------------------- #
def test_get_live_consumer_returns_none_after_consumer_gc():
    """A collected (weak) consumer value -> get_live_consumer() returns None."""
    import gc

    from django_graphex.subscriptions.transports import ws

    class _FakeConsumer:
        """Stand-in consumer; only its identity (weak-referenceability) matters."""

    scope = {"type": "websocket"}

    consumer = _FakeConsumer()
    ws._LIVE_CONSUMERS[id(scope)] = consumer
    # While a strong ref is held, the consumer is observable.
    assert ws.get_live_consumer(scope) is consumer

    # Drop the only strong ref and force collection: the weak entry evaporates.
    del consumer
    gc.collect()

    assert ws.get_live_consumer(scope) is None, (
        "get_live_consumer must return None once the consumer is GC'd "
        "(WeakValueDictionary entry collected)"
    )


def test_get_live_consumer_returns_none_for_unregistered_scope():
    """An unknown scope (never registered) -> None (the not-connected path)."""
    from django_graphex.subscriptions.transports import ws

    assert ws.get_live_consumer({"type": "websocket", "never": "registered"}) is None
