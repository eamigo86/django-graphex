"""Provide the developer-facing "Subscription" type and subscribe resolver.

The public API (Meta keys, generated enums/arguments, output fields and the
exposed classmethods) is built directly on top of a Channels 4 broadcast
engine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from channels.layers import get_channel_layer
from graphene import (
    ID,
    Argument,
    Boolean,
    Enum,
    Field,
    List,
    ObjectType,
    String,
)
from graphene.types.generic import GenericScalar
from graphene.types.objecttype import ObjectTypeOptions
from graphene.utils.str_converters import to_snake_case

from ..backends import resolve_backend
from ..settings import graphql_api_settings
from .bindings import SubscriptionBinding
from .mixins import safe_group_name

if TYPE_CHECKING:
    from typing import AsyncIterator, Callable

    from django.db.models import QuerySet
    from graphql import GraphQLResolveInfo

logger = logging.getLogger(__name__)


def _enum_value(value: Any) -> Any:
    """Unwrap a (possibly nested) Enum member down to its raw value.

    Plain strings pass through unchanged, so the resolver works both when driven
    by graphql-core (enum members) and when called directly in tests (strings).

    Args:
        value: An Enum member, nested Enum member, or plain value.

    Returns:
        The unwrapped raw value.
    """
    while hasattr(value, "value"):
        value = value.value
    return value


class ActionSubscriptionEnum(Enum):
    """Model change actions a subscriber can listen to."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ALL_ACTIONS = "all_actions"


class OperationSubscriptionEnum(Enum):
    """Whether the request joins or leaves a subscription group."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class SubscriptionOptions(ObjectTypeOptions):
    """Provide the Meta options container for "Subscription" subclasses."""

    output = None
    arguments = None
    model = None
    stream = None
    #: SerializerBackend serializing the notification payload.
    backend = None
    queryset = None
    # None -> inherit the global SUBSCRIPTION_SERIALIZE_DATA setting;
    # True/False -> force full / id-only payload for this subscription.
    serialize_data = None
    # Optional tuple of model field names used to route notifications to
    # value-scoped groups (the "indexed groups" optimization). Empty -> the
    # traditional single coarse group per action.
    index_fields = ()


class SubscriptionField(Field):
    """Provide a "Field" carrying its own graphql-core subscribe resolver.

    graphene only wires a "subscribe_<name>" method declared on the root
    subscription type. By overriding "wrap_subscribe" we attach the resolver
    defined on the "Subscription" subclass itself, regardless of the attribute
    name it is mounted under on the root type.
    """

    def __init__(
        self, *args: Any, subscribe: Callable[..., Any] | None = None, **kwargs: Any
    ) -> None:
        """Store the field's own subscribe resolver before building the field.

        Args:
            subscribe: The graphql-core subscribe resolver for this field.
        """
        self._subscribe_fn = subscribe
        super().__init__(*args, **kwargs)

    def wrap_subscribe(
        self, parent_subscribe: Callable[..., Any] | None
    ) -> Callable[..., Any] | None:
        """Prefer a root "subscribe_<name>" if present, else our resolver.

        Args:
            parent_subscribe: The resolver declared on the root type, if any.

        Returns:
            The chosen subscribe resolver, or "None" when neither is set.
        """
        return parent_subscribe or self._subscribe_fn


class Subscription(ObjectType):
    """Define the subscription type.

    Subclass it through "Meta" and mount it on the schema's subscription root
    via "Field"::

        class UserSubscription(Subscription):
            class Meta:
                model = User
                stream = "users"
    """

    ok = Boolean(description="Boolean field that return subscription request result.")
    error = String(description="Subscribe or unsubscribe operation request error .")
    stream = String(description="Stream name.")
    operation = OperationSubscriptionEnum(description="Subscription operation.")
    action = ActionSubscriptionEnum(description="Subscription action.")

    class Meta:
        """Mark the "Subscription" base itself as abstract (not a schema type)."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        stream: str | None = None,
        queryset: QuerySet | None = None,
        serialize_data: bool | None = None,
        subscription_index_fields: tuple[str, ...] | list[str] | None = None,
        description: str = "",
        **options: Any,
    ) -> None:
        """Validate Meta and generate the enums, arguments and options.

        Args:
            model: The Django model this subscription serves (native backend).
            pydantic_model: Optional user Pydantic base for custom validation.
            stream: The stream name this subscription serves.
            queryset: An optional queryset whose model must match the backend's.
            serialize_data: Force full or id-only payloads, or "None" to inherit
                the global setting.
            subscription_index_fields: Optional model field names used to route
                notifications to value-scoped groups (only the matching
                subscribers are woken). Must be concrete fields and a subset of
                what "subscription_scope" returns; otherwise the subscriber falls
                back to the coarse group. Empty/None keeps today's behavior.
            description: The schema description for this subscription.
            **options: Additional options forwarded to the base implementation.
        """
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()

        assert isinstance(stream, str), (
            "You need to pass a valid string stream name in {}.Meta, received "
            '"{}"'.format(cls.__name__, stream)
        )

        if queryset is not None:
            assert model == queryset.model, (
                "The queryset model must correspond with the backend's model "
                'passed on Meta class, received "{}", expected "{}"'.format(
                    queryset.model.__name__, model.__name__
                )
            )

        description = description or "Subscription Type for {} model".format(
            model.__name__
        )

        assert serialize_data in (None, True, False), (
            '{}.Meta.serialize_data must be None, True or False, received "{}"'.format(
                cls.__name__, serialize_data
            )
        )

        index_fields = tuple(subscription_index_fields or ())
        for field_name in index_fields:
            # Fail fast: an index field must be a concrete field we can read
            # off the instance (FK -> "<name>_id") at notification time.
            model._meta.get_field(field_name)

        _meta = SubscriptionOptions(cls)
        _meta.output = cls
        _meta.model = model
        _meta.stream = stream
        _meta.backend = backend
        _meta.queryset = queryset
        _meta.serialize_data = serialize_data
        _meta.index_fields = index_fields

        arguments = {
            "channel_id": Argument(
                String,
                required=True,
                description="Websocket's channel connection identification",
            ),
            "action": Argument(
                ActionSubscriptionEnum,
                required=True,
                description="Model change action to listen to: create, update, delete or all_actions.",
            ),
            "operation": Argument(
                OperationSubscriptionEnum, required=True, description="Operation to do"
            ),
            "id": Argument(
                ID,
                description="ID field value that has the object to which you wish to subscribe",
            ),
            "filters": Argument(
                GenericScalar,
                description=(
                    "Optional per-subscriber field filters as a mapping of "
                    "Django ORM lookup to value, e.g. {post: 7} or "
                    '{text__icontains: "urgent"}. Notifications are delivered '
                    "only when the changed instance matches."
                ),
            ),
        }

        # The `data` argument (and its <Model>Fields enum) only makes sense when
        # the notification carries the full serialized instance. In id-only mode
        # there are no fields to pick, so we omit it from the schema entirely.
        # Effective mode is resolved at class-definition time: Meta override if
        # given, else the global setting at import time.
        effective_full = (
            serialize_data
            if serialize_data is not None
            else bool(graphql_api_settings.SUBSCRIPTION_SERIALIZE_DATA)
        )
        if effective_full:
            serializer_fields = [
                (to_snake_case(field.strip("_")).upper(), to_snake_case(field))
                for field in backend.output_field_names()
            ]
            model_fields_enum = Enum(
                f"{_meta.model.__name__}Fields",
                serializer_fields,
                description="Desired {} fields in subscription's notification.".format(
                    _meta.model.__name__
                ),
            )
            arguments["data"] = List(model_fields_enum, required=False)

        _meta.arguments = arguments

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

    @classmethod
    def _should_serialize_data(cls) -> bool:
        """Tell whether notifications carry the full serialized instance.

        "Meta.serialize_data" (if set) wins; otherwise the global
        "SUBSCRIPTION_SERIALIZE_DATA" setting decides. Read at broadcast time so
        runtime/"override_settings" changes are honored.

        Returns:
            "True" when the full serialized instance should be sent.
        """
        value = cls._meta.serialize_data
        if value is None:
            value = graphql_api_settings.SUBSCRIPTION_SERIALIZE_DATA
        return bool(value)

    @classmethod
    def model_label(cls) -> str:
        """Return the "app_label.modelname" identifier used in group names.

        Returns:
            The model label used to build the resolver's group names.
        """
        return "{}.{}".format(
            cls._meta.model._meta.app_label.lower(),
            cls._meta.model._meta.object_name.lower(),
        )

    @classmethod
    def _group_name(
        cls,
        action: str,
        id: Any | None = None,
        index: dict[str, Any] | None = None,
    ) -> str:
        """Build the Channels group name for an action (optionally per-object).

        When an ``index`` mapping is given, a canonical ``:k=v&...`` suffix
        (keys sorted) is appended so that subscribers scoped to those values land
        in their own group. The subscribe side and the broadcast side build the
        same suffix -- one from the scope, the other from the changed instance --
        so the names match by construction (no group enumeration needed).

        Args:
            action: The change action the group is built for.
            id: An optional object primary key for a per-object group.
            index: An optional ``{field: value}`` mapping for value-scoped groups.

        Returns:
            The Channels-safe group name.
        """
        if id:
            name = f"{cls.model_label()}-{action}-{id}"
        else:
            name = f"{cls.model_label()}-{action}"
        if index:
            suffix = "&".join(f"{key}={index[key]}" for key in sorted(index))
            name = f"{name}:{suffix}"
        return safe_group_name(name)

    @classmethod
    def _instance_index(cls, instance: Any) -> dict[str, Any] | None:
        """Build the index ``{field: value}`` mapping from a live instance.

        Reads each ``Meta.index_fields`` entry by its ``attname`` so foreign keys
        yield the raw id (e.g. ``owner_id``) without a related-object query and
        plain fields yield their value. Returns ``None`` when no index is
        configured.

        Args:
            instance: The model instance that changed.

        Returns:
            The index mapping, or ``None`` when ``index_fields`` is empty.
        """
        fields = cls._meta.index_fields
        if not fields:
            return None
        model = cls._meta.model
        return {
            field: getattr(instance, model._meta.get_field(field).attname)
            for field in fields
        }

    @classmethod
    def authorize_subscription(cls, info: GraphQLResolveInfo, **kwargs: Any) -> None:
        """Authorize a subscribe request before joining any group.

        Hook meant to be overridden (or injected by ``DjangoModelType``).
        Raise ``GraphQLError`` to deny; the denial is surfaced to the client as
        ``ok: False`` / ``error``. The default allows. Runs in the HTTP request
        context, so ``info.context.user`` is available -- keep it free of
        blocking ORM access.

        Args:
            info: GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments.
        """
        return None

    @classmethod
    def subscription_scope(
        cls, info: GraphQLResolveInfo, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Return server-forced notification filters for this subscriber.

        Hook meant to be overridden (or injected by ``DjangoModelType``).
        The returned mapping (Django ORM lookup -> value, e.g.
        ``{"owner": info.context.user.pk}``) is merged into the subscriber's
        filters with **server precedence**, so it cannot be widened or removed by
        the client, and is enforced per event at delivery time. The default
        returns ``None`` (no scoping).

        Args:
            info: GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments.

        Returns:
            The forced filter mapping, or ``None``.
        """
        return None

    @classmethod
    async def _subscribe(
        cls,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Yield the field's graphql-core subscribe confirmation object.

        Joins/leaves the relevant groups, registers the requested field set for
        per-connection projection, and yields exactly one confirmation object.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info.
            **kwargs: The subscription arguments (action, operation, etc.).

        Yields:
            A single confirmation object describing the subscribe result.
        """
        # graphql-core delivers enum arguments as their graphene Enum members;
        # normalize to the plain string values the engine and wire protocol use.
        action = _enum_value(kwargs.get("action"))
        operation = _enum_value(kwargs.get("operation"))
        data = kwargs.get("data", None)
        if data:
            data = [_enum_value(field) for field in data]
        obj_id = kwargs.get("id", None)
        client_filters = kwargs.get("filters", None)
        if not isinstance(client_filters, dict):
            client_filters = {}
        channel_name = kwargs.get("channel_id")

        response = {
            "stream": cls._meta.stream,
            "operation": operation,
            "action": action,
        }

        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                raise RuntimeError(
                    "No channel layer configured; set CHANNEL_LAYERS to enable "
                    "subscriptions."
                )

            # Authorize the subscribe (may raise -> surfaced as ok=False).
            if operation == "subscribe":
                cls.authorize_subscription(info, **kwargs)

            # The server-forced scope is deterministic from the request, so it is
            # recomputed here for both subscribe (to register filters) and
            # unsubscribe (to target the very same group).
            scope = cls.subscription_scope(info, **kwargs) or {}
            filters = {**client_filters, **scope} or None

            # When every index field is present in the scope, route to a
            # value-scoped group so only matching subscribers are woken;
            # otherwise fall back to the coarse group (still correct, just
            # broadcast + in-memory/DB filter).
            index = None
            index_fields = cls._meta.index_fields
            if index_fields and all(field in scope for field in index_fields):
                index = {field: scope[field] for field in index_fields}

            actions = (
                ("create", "update", "delete") if action == "all_actions" else (action,)
            )
            for act in actions:
                group_name = cls._group_name(act, id=obj_id, index=index)
                if operation == "subscribe":
                    await channel_layer.group_add(group_name, channel_name)
                    await channel_layer.send(
                        channel_name,
                        {
                            "type": "subscription.register",
                            "group": group_name,
                            "fields": list(data) if data else None,
                            "filters": filters,
                        },
                    )
                elif operation == "unsubscribe":
                    await channel_layer.group_discard(group_name, channel_name)
                    await channel_layer.send(
                        channel_name,
                        {"type": "subscription.deregister", "group": group_name},
                    )

            response.update(ok=True, error=None)
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as `error`
            logger.exception("Subscription %s failed", cls.__name__)
            response.update(ok=False, error=str(exc))

        yield cls(**response)

    @classmethod
    def get_binding(cls) -> SubscriptionBinding:
        """Return the cached, idempotent signal binding for this subscription.

        Returns:
            The "SubscriptionBinding" instance wired for this subscription.
        """
        binding = cls.__dict__.get("_binding")
        if binding is None:
            binding = SubscriptionBinding(cls)
            cls._binding = binding
        return binding

    @classmethod
    def Field(cls, *args: Any, **kwargs: Any) -> SubscriptionField:
        """Mount this subscription on a root subscription "ObjectType".

        Returns:
            The "SubscriptionField" carrying this subscription's resolver.
        """
        kwargs.setdefault(
            "description", f"Subscription for {cls._meta.model.__name__} model"
        )
        # Ensure the signal binding exists as soon as the schema is wired.
        cls.get_binding()
        return SubscriptionField(
            cls._meta.output,
            args=cls._meta.arguments,
            subscribe=cls._subscribe,
            **kwargs,
        )


# Re-exported for convenience / typing.
__all__ = [
    "ActionSubscriptionEnum",
    "OperationSubscriptionEnum",
    "Subscription",
    "SubscriptionField",
    "SubscriptionOptions",
]
