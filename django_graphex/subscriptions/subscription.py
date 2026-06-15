"""Provide the developer-facing "Subscription" type and subscribe resolver.

The public API (Meta keys, generated enums/arguments, output fields and the
exposed classmethods) is built directly on top of a Channels 4 broadcast
engine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.core.cache import caches
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
from graphene.utils.str_converters import to_camel_case, to_snake_case
from graphql import GraphQLError

from ..backends import resolve_backend
from ..settings import graphql_api_settings
from .bindings import SubscriptionBinding
from .mixins import safe_group_name

if TYPE_CHECKING:
    from typing import AsyncIterator, Callable

    from django.db.models import QuerySet
    from graphql import GraphQLResolveInfo


# ---------------------------------------------------------------------------
# Channel ownership registry — Django-cache backed
# ---------------------------------------------------------------------------
# Maps channel_name → session_key via the Django "default" cache.
# Key format: "dgx:subchan:<channel_name>"
# TTL: 24 h (refreshed on re-register).
#
# With LocMemCache (the Django default) the semantics are identical to the
# previous in-process dict — no shared state across workers.
# With a shared cache backend (Redis / Memcached) the guard works correctly
# across multiple HTTP + WebSocket workers.
#
# Tests may call register_channel() directly to inject entries without going
# through the consumer.  The conftest fixture clears the relevant cache keys
# between tests.

_CHANNEL_CACHE_PREFIX = "dgx:subchan:"
_CHANNEL_CACHE_TTL = 86_400  # 24 hours in seconds


def _channel_cache_key(channel_name: str) -> str:
    """Build the cache key for *channel_name*.

    Args:
        channel_name: The Channels channel name.

    Returns:
        The namespaced cache key.
    """
    return f"{_CHANNEL_CACHE_PREFIX}{channel_name}"


def register_channel(channel_name: str, *, session_key: str) -> None:
    """Record that *channel_name* is owned by *session_key*.

    Stores the ownership token in Django's ``"default"`` cache with a 24-hour
    TTL (refreshed on re-register).  Called by
    ``GraphqlAPIDemultiplexer.connect`` (and by test helpers that bypass the
    consumer).  Subsequent ``_subscribe`` calls for this channel must supply the
    same ``_session_key`` to be accepted.

    Args:
        channel_name: The Channels channel name as sent in the handshake frame.
        session_key: An opaque per-session identifier (session key, user pk
            formatted as a string, or any stable per-connection token).
    """
    cache = caches["default"]
    cache.set(_channel_cache_key(channel_name), session_key, _CHANNEL_CACHE_TTL)


def unregister_channel(channel_name: str) -> None:
    """Remove *channel_name* from the ownership registry on disconnect.

    Args:
        channel_name: The channel name to remove.
    """
    cache = caches["default"]
    cache.delete(_channel_cache_key(channel_name))


def _validate_channel_ownership(channel_name: str, session_key: str | None) -> None:
    """Raise ``GraphQLError`` when *channel_name* is not owned by *session_key*.

    Reads the ownership token from Django's ``"default"`` cache.

    Policy: fail-closed — an unknown (never-registered) channel is also
    rejected so an attacker cannot enumerate channels by guessing.

    ``None`` and ``""`` are treated as equivalent for the owner comparison so
    that anonymous connections (no Django session) registered with ``""`` are
    accepted by HTTP callers that have no session either.  A caller with a real
    session key can never match an empty-string owner (and vice-versa).

    Args:
        channel_name: The channel_id supplied by the subscribe caller.
        session_key: The session key supplied by the subscribe caller, or
            ``None`` when no session context is available.

    Raises:
        GraphQLError: When ownership cannot be confirmed.
    """
    cache = caches["default"]
    # cache.get returns None for both a missing key and an explicitly stored None.
    # We use a sentinel to distinguish "key not present" from "key stored as empty".
    _MISSING = object()
    owner = cache.get(_channel_cache_key(channel_name), default=_MISSING)
    if owner is _MISSING:
        raise GraphQLError(
            "channel_id is not registered; connect a WebSocket consumer first."
        )
    # Normalise: treat None and "" as the same (anonymous / no session).
    normalised_caller = session_key or ""
    normalised_owner = owner or ""
    if normalised_caller != normalised_owner:
        raise GraphQLError(
            "channel_id does not belong to the current session; subscription rejected."
        )


logger = logging.getLogger(__name__)


def _to_camel(snake: str) -> str:
    """Convert a snake_case payload key to its camelCase GraphQL wire name."""
    return to_camel_case(snake)


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

        if not isinstance(stream, str):
            raise TypeError(
                "You need to pass a valid string stream name in {}.Meta, received "
                '"{}"'.format(cls.__name__, stream)
            )

        if queryset is not None:
            if model != queryset.model:
                raise TypeError(
                    "The queryset model must correspond with the backend's model "
                    'passed on Meta class, received "{}", expected "{}"'.format(
                        queryset.model.__name__, model.__name__
                    )
                )

        description = description or "Subscription Type for {} model".format(
            model.__name__
        )

        if serialize_data not in (None, True, False):
            raise TypeError(
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
            # Percent-encode keys and values so that delimiter characters
            # ('=', '&') inside field values cannot produce ambiguous names.
            # safe="" encodes everything except unreserved chars; the delimiters
            # themselves ('=' between key/value, '&' between pairs) are
            # preserved as plain ASCII so the structure remains parseable.
            suffix = "&".join(
                "{}={}".format(
                    quote(str(key), safe=""),
                    quote(str(index[key]), safe=""),
                )
                for key in sorted(index)
            )
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
    def _validate_filters(cls, client_filters: dict[str, Any]) -> None:
        """Validate that all *client_filters* keys root on declared output fields.

        Each filter key may be a bare field name or a field name followed by a
        Django ORM lookup suffix (e.g. ``username__icontains``).  The root
        field (everything before the first ``__``) must be present in the
        subscription's serialized output field names.  Filters whose root is
        not declared raise ``GraphQLError`` so arbitrary ORM field probing is
        rejected at subscribe time.

        Server-forced scope filters (from ``subscription_scope``) are **not**
        subject to this check — they originate from server code, not the client.

        Args:
            client_filters: The raw ``filters`` dict supplied by the subscriber.

        Raises:
            GraphQLError: When a filter key roots on an undeclared field.
        """
        if not client_filters:
            return
        declared: set[str] = set(cls._meta.backend.output_field_names())
        for key in client_filters:
            root = key.split("__")[0]
            if root not in declared:
                raise GraphQLError(
                    "Subscription filter key '{}' is not a declared output field. "
                    "Allowed fields: {}.".format(key, ", ".join(sorted(declared)))
                )

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
            **kwargs: The subscription arguments (action, operation, etc.) plus
                the internal ``_session_key`` used for channel ownership checks.

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

        # _session_key is an internal kwarg injected by the consumer (or by
        # test helpers) for ownership validation.  It is not part of the public
        # GraphQL argument schema — strip it before forwarding to other hooks.
        # When not explicitly provided, attempt to extract the session key from
        # the Django HTTP request available as info.context (the real HTTP path
        # via SubscriptionGraphQLView).
        session_key: str | None = kwargs.pop("_session_key", None)
        if session_key is None and info is not None:
            context = info.context
            session = getattr(context, "session", None)
            if session is not None:
                session_key = getattr(session, "session_key", None) or ""

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

            # --- (a) Channel ownership guard ---
            # Validate that the calling session owns the presented channel_id
            # before any group_add or group_send is performed.  This prevents
            # a client from hijacking another user's channel by guessing its ID.
            # The guard is skipped when SUBSCRIPTIONS_CHANNEL_GUARD=False (escape
            # hatch for multi-worker deployments without a shared cache backend).
            if graphql_api_settings.SUBSCRIPTIONS_CHANNEL_GUARD:
                _validate_channel_ownership(channel_name, session_key)

            # Authorize the subscribe (may raise -> surfaced as ok=False).
            # authorize_subscription and subscription_scope are sync classmethods
            # (the user-overridable hooks may touch the Django ORM, which raises
            # SynchronousOnlyOperation when called directly from the async
            # _subscribe coroutine on an ASGI server).  Wrapping them via
            # sync_to_async runs them in a thread-pool executor so they are safe
            # to await regardless of whether the current implementation is
            # trivial (returns None) or performs real database access.
            if operation == "subscribe":
                await sync_to_async(cls.authorize_subscription)(info, **kwargs)

                # --- (b) Filter key validation ---
                # Reject filters whose root field is not in the declared output
                # so an attacker cannot probe arbitrary ORM fields (e.g. password).
                cls._validate_filters(client_filters)

            # The server-forced scope is deterministic from the request, so it is
            # recomputed here for both subscribe (to register filters) and
            # unsubscribe (to target the very same group).
            scope = await sync_to_async(cls.subscription_scope)(info, **kwargs) or {}
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

    # -----------------------------------------------------------------------
    # Native compile path (Phase 6 WU6) — GDX_BACKEND=native ONLY.
    #
    # ADD-ONLY: the graphene ``Subscription(ObjectType)`` base + the graphene
    # ``_subscribe``/``Field``/``SubscriptionField`` path above stay INTACT
    # (design C-A, #1452 — the metaclass swap is Phase 7). These methods build
    # the NATIVE compile path WITHOUT importing graphene: a graphql-core
    # ``GraphQLObjectType`` event type whose fields carry WU1 snake-closure
    # resolvers + ``extensions['gdx']``, a fully-populated WU5
    # ``SubscriptionSpec``, and a DIRECT graphql-core ``GraphQLField`` whose
    # subscribe factory runs WU5 ``native_subscribe`` and whose delivery runs
    # WU5 ``drive_subscription`` (COND-A). The full per-field auto-gen +
    # COND-B build-time call are WU7 (types.py); WU6 keeps the seam clean.
    # -----------------------------------------------------------------------

    @classmethod
    def _native_event_type_name(cls) -> str:
        """Return the native event output type name for this subscription."""
        return f"{cls._meta.model.__name__}SubscriptionEvent"

    @classmethod
    def _build_native_event_type(cls) -> Any:
        """Build the native event output ``GraphQLObjectType`` (deliverable pk shape).

        DESIGN RECONCILIATION (#1432 §3 vs §8): the serialize-once payload
        (``native/backend.py:to_representation``) is FLAT PKS by design — one
        serialize feeds N subscribers with ZERO DB per subscriber. So the event
        type's relation fields MUST render the DELIVERABLE pk scalars/lists the
        flat payload actually carries, NOT the DB-backed nested output-type SDL
        (§8's "byte-identical to the DjangoObjectType OUTPUT type" goal is a
        category error vs the §3 flat-pk payload — nested FK/M2M resolution over a
        subscription event would need a per-subscriber DB query, the N+1 cliff
        serialize-once forbids). The deliverable representation is:

          * scalars -> the Phase-5 native names/nullability (``id: ID!``, model
            scalars NULLABLE, ``Date`` -> ``CustomDate`` / ``UUID`` -> ``UUID`` /
            ``JSON`` -> ``JSONString`` / ``Decimal`` -> ``Float`` …) reusing
            ``native.output_compiler.compile_output_fields`` — KEEP;
          * FK / O2O -> the PK SCALAR (``backend.to_representation`` carries the FK
            under key ``<field.name>`` as the pk int via ``getattr(obj,
            "<name>_id")``). Rendered as the pk's GraphQL scalar (``ID`` for an
            auto/id pk, else the pk field's scalar). NOT the nested object type;
          * M2M / reverse to-many -> a LIST of pk scalars (``to_representation``
            carries the M2M under key ``<field.name>`` as ``list(... values_list(
            "pk", flat=True))``). Rendered as ``[<pk scalar>]``. NOT the
            results/totalCount container.

        Each field's resolver is a WU1 ``make_snake_resolver`` closure (tagged
        ``_gdx_pure_projection`` so COND-B/``guard.py`` whitelists it) keyed by the
        SNAKE payload key ``backend.to_representation`` actually writes
        (``field.name`` for every kind — scalars, FK pk, M2M pk-list), fixing the
        camelCase-default-resolver silent-null. The flat serialize-once payload
        holds pks (``author=7``, ``co_authors=[7, 8]``) and the snake closure
        DELIVERS those pks directly (no DB, no re-serialize). The type carries
        ``extensions['gdx']`` (the native bridge); ``check_subscription_output_type``
        (COND-B) is run AFTER the sentinels are attached.

        Returns:
            A graphql-core ``GraphQLObjectType`` carrying ``extensions['gdx']``.
        """
        from graphql import GraphQLField as _GraphQLField
        from graphql import GraphQLObjectType

        from ..native.bridge import GdxPayload
        from ..native.ir import GdxMeta
        from .guard import check_subscription_output_type
        from .resolvers import make_snake_resolver

        type_name = cls._native_event_type_name()
        model = cls._meta.model

        def _fields() -> dict[str, Any]:
            from django.db import models as _dj_models
            from graphql import GraphQLID as _GraphQLID
            from graphql import GraphQLList as _GraphQLList

            from ..native.base import get_shared_output_registry
            from ..native.output_compiler import (
                _get_django_to_gql,
                _to_camel_case,
                compile_output_fields,
            )

            # 1) Scalars via the SHARED output registry — the SAME builder the
            # DjangoObjectType output thunk uses, so scalar NAMES/nullability are
            # byte-identical to the model output type (``id: ID!``, rest nullable).
            # compile_output_fields also emits FK/O2O as the NESTED object type,
            # which is DB-backed and WRONG for the flat-pk payload; those entries
            # are OVERWRITTEN below with the deliverable pk scalar.
            built: dict[str, Any] = dict(
                compile_output_fields(model, get_shared_output_registry())
            )

            def _pk_scalar(related_model: type) -> Any:
                # Render the related model's pk GraphQL scalar — ID for an
                # auto/id pk, else the pk field's mapped scalar. The flat payload
                # carries the literal pk value (an int for AutoField), which
                # GraphQLID coerces to its string form on output.
                pk_field = related_model._meta.pk
                mapping = _get_django_to_gql()
                for klass in type(pk_field).__mro__:
                    if klass in mapping:
                        return mapping[klass]
                return _GraphQLID

            # 2) Walk the backend's emitted output fields (the SAME set
            # ``to_representation`` serializes: concrete + M2M) and render every
            # RELATION as its DELIVERABLE pk shape, keyed by ``field.name`` (the
            # exact key the flat payload writes).
            for field in cls._meta.backend._output_fields():
                name = field.name
                wire = _to_camel_case(name)
                if isinstance(field, _dj_models.ManyToManyField):
                    # M2M -> [pk scalar]; payload carries a list of pks under
                    # key ``field.name``.
                    related = field.related_model
                    built[wire] = _GraphQLField(
                        _GraphQLList(_pk_scalar(related))
                    )
                elif isinstance(
                    field, (_dj_models.ForeignKey, _dj_models.OneToOneField)
                ):
                    # FK / O2O -> pk scalar; payload carries the pk int under key
                    # ``field.name`` (``getattr(obj, "<name>_id")``). NOT nested.
                    built[wire] = _GraphQLField(_pk_scalar(field.related_model))

            # 3) RE-WRAP every field's resolver with a sentinel snake-closure
            # keyed by the SNAKE payload key (the camelCase wire key would read
            # the wrong dict key -> silent NULL). ``to_representation`` keys every
            # field (scalar / FK pk / M2M pk-list) by ``field.name`` (snake), so
            # the closure key is to_snake_case(wire).
            from graphene.utils.str_converters import to_snake_case

            rewrapped: dict[str, Any] = {}
            for wire, field in built.items():
                snake = to_snake_case(wire)
                rewrapped[wire] = _GraphQLField(
                    field.type,
                    args=field.args,
                    resolve=make_snake_resolver(snake),
                    description=field.description,
                    deprecation_reason=field.deprecation_reason,
                )
            return rewrapped

        event_type = GraphQLObjectType(
            type_name,
            _fields,
            extensions={"gdx": GdxPayload(GdxMeta(name=type_name, model=model))},
        )
        # COND-B (build-time flat-type guard) AFTER the sentinels are attached:
        # forces field evaluation and asserts every field is sentinel-marked.
        check_subscription_output_type(event_type)
        return event_type

    @classmethod
    def _build_native_spec(cls, schema: Any, document: Any) -> Any:
        """Build the fully-populated WU5 ``SubscriptionSpec`` from this class.

        Wires the kept hooks (``authorize_subscription``/``subscription_scope``/
        ``_validate_filters``), ``group_name``/``instance_index`` = the kept
        ``_group_name``/``_instance_index`` (so producer + consumer group names
        match by construction), index_fields, and ``db_exists`` = the single-row
        ``.exists()`` narrowing that closes the WU4 conservative-drop gap so
        native ``__lookup`` subscriptions deliver DB-verified events.

        Args:
            schema: The native graphql-core ``GraphQLSchema`` the per-event
                ``execute`` runs against.
            document: The parsed subscription ``DocumentNode`` executed per event.

        Returns:
            A WU5 ``SubscriptionSpec``.
        """
        from .streaming import SubscriptionSpec

        def _authorize(context: Any, **kwargs: Any) -> None:
            # The kept classmethod takes (info, **kwargs); pass the
            # transport-neutral context as ``info`` (it exposes .user/.context).
            cls.authorize_subscription(context, **kwargs)

        def _scope(context: Any, **kwargs: Any) -> dict[str, Any] | None:
            return cls.subscription_scope(context, **kwargs)

        return SubscriptionSpec(
            model_label=cls.model_label(),
            stream=cls._meta.stream,
            schema=schema,
            document=document,
            declared_output_fields=set(cls._meta.backend.output_field_names()),
            index_fields=tuple(cls._meta.index_fields),
            authorize=_authorize,
            scope=_scope,
            group_name=cls._group_name,
            instance_index=cls._instance_index,
            db_exists=cls._native_db_exists,
            event_type_name=cls._native_event_type_name(),
            serialize_data=cls._meta.serialize_data,
            model=cls._meta.model,
        )

    @classmethod
    def _native_db_exists(
        cls, remaining: dict[str, Any], event: dict[str, Any], *, obj_id: Any = None
    ) -> Any:
        """Single-row ``.exists()`` narrowing for non-empty ``__lookup`` filters.

        Closes the WU4 conservative-drop gap: a ``__lookup`` filter the in-memory
        equality gate cannot resolve (e.g. ``author__name`` / a relation lookup)
        is verified by a single-row ``.exists()`` against the changed instance's
        pk — so only events whose row actually matches the lookup are delivered.

        Wrapped via ``sync_to_async``: the source's ``db_verify`` runs inside the
        async receive loop, so a direct blocking ORM ``.exists()`` would raise
        ``SynchronousOnlyOperation`` on an ASGI server. The returned coroutine is
        awaited by the WU5 ``_build_db_verify`` wrapper (``_maybe_await``).

        Args:
            remaining: The non-empty ``__lookup`` filters left after the in-memory
                equality gate (Django ORM lookup -> expected value).
            event: The already-serialized flat snake dict for the changed instance.
            obj_id: An optional per-object id (unused — the pk is read from the
                event so the narrowing targets exactly the changed row).

        Returns:
            An awaitable resolving to ``True`` when the changed row matches every
            remaining lookup.
        """
        pk = event.get("id")
        if pk is None:
            return sync_to_async(lambda: False)()

        def _exists() -> bool:
            return cls._meta.model._default_manager.filter(pk=pk, **remaining).exists()

        return sync_to_async(_exists)()

    @classmethod
    async def _native_subscribe(
        cls,
        channel_layer: Any,
        schema: Any,
        document: Any,
        *,
        action: str,
        obj_id: Any = None,
        filters: dict[str, Any] | None = None,
        context: Any = None,
    ) -> Any:
        """Run the native subscribe (WU5 ``native_subscribe``) for this subscription.

        Builds the spec from this class and delegates to WU5 ``native_subscribe``,
        which runs the KEPT hooks BEFORE any ``group_add`` (deny short-circuits
        before the source), joins exactly the action-selected groups (#1420), and
        wires ``source.db_verify`` to the single-row ``.exists()`` narrowing.

        Args:
            channel_layer: The constructed Channels channel layer (injected).
            schema: The native graphql-core schema for the per-event execute.
            document: The parsed subscription document executed per event.
            action: The requested action (``create``/``update``/``delete``/
                ``all_actions``); picks the join set.
            obj_id: An optional per-object primary key.
            filters: The raw client-supplied filters.
            context: The transport-neutral context (``.user`` + scope mapping).

        Returns:
            The STARTED :class:`ChannelLayerSource` (drive via
            :func:`drive_subscription`).
        """
        from .streaming import native_subscribe

        spec = cls._build_native_spec(schema, document)
        return await native_subscribe(
            spec,
            channel_layer,
            action=action,
            obj_id=obj_id,
            filters=filters,
            context=context,
        )

    @classmethod
    def _build_native_field(
        cls, schema: Any = None, document: Any = None
    ) -> Any:
        """Build the native subscription field as a DIRECT graphql-core ``GraphQLField``.

        NOT a graphene ``Field``/``SubscriptionField`` (design §3 / C-A). The field
        carries:

          * ``type`` = the native event output type (``extensions['gdx']`` +
            snake-closure resolvers),
          * ``subscribe`` = a source factory that runs WU5 ``native_subscribe``
            (returning a :class:`ChannelLayerSource`; the transport layer drives
            it via WU5 ``drive_subscription``),
          * ``resolve`` = identity (the source dict IS the root; the event type's
            snake-closure resolvers project it),
          * ``args`` reduced to ``{action, id, filters}`` under native (the
            graphene-only ``channel_id``/``operation`` args are dropped).

        ``schema``/``document`` are OPTIONAL: the subscribe factory only builds the
        :class:`ChannelLayerSource` (group join), which does NOT read the spec's
        ``schema``/``document`` (only ``drive_subscription`` — the transport's
        per-event delivery — does). So the field is buildable at SCHEMA-COMPILE
        time (``compile_native_root``, WU7 root wiring) when the assembled native
        schema and the per-request document are not yet known; the transport layer
        (WU8/WU9) supplies the live schema + parsed request document to
        ``drive_subscription`` at delivery time. When provided here they are
        forwarded for direct/test drive paths.

        Args:
            schema: The native graphql-core schema for the per-event execute
                (optional — supplied by the transport at delivery time).
            document: The parsed subscription document executed per event
                (optional — the per-request selection set, supplied at delivery).

        Returns:
            A graphql-core ``GraphQLField``.
        """
        from graphql import (
            GraphQLArgument,
            GraphQLNonNull,
        )
        from graphql import (
            GraphQLField as _GraphQLField,
        )
        from graphql import (
            GraphQLID as _GraphQLID,
        )
        from graphql import (
            GraphQLString as _GraphQLString,
        )
        from graphql.type import GraphQLEnumType, GraphQLEnumValue

        action_enum = GraphQLEnumType(
            f"{cls._meta.model.__name__}SubscriptionAction",
            {
                "CREATE": GraphQLEnumValue("create"),
                "UPDATE": GraphQLEnumValue("update"),
                "DELETE": GraphQLEnumValue("delete"),
                "ALL_ACTIONS": GraphQLEnumValue("all_actions"),
            },
        )
        # Reduced native arg set: {action, id, filters} (no channel_id/operation).
        args = {
            "action": GraphQLArgument(
                GraphQLNonNull(action_enum),
                description="Model change action to listen to.",
                out_name="action",
            ),
            "id": GraphQLArgument(
                _GraphQLID,
                description="Optional object id to scope a per-object subscription.",
                out_name="id",
            ),
            "filters": GraphQLArgument(
                _GraphQLString,
                description="Optional JSON-encoded per-subscriber field filters.",
                out_name="filters",
            ),
        }

        async def _subscribe_source(root: Any, info: Any, **kwargs: Any) -> Any:
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            if channel_layer is None:
                raise RuntimeError(
                    "No channel layer configured; set CHANNEL_LAYERS to enable "
                    "subscriptions."
                )
            action = _enum_value(kwargs.get("action"))
            obj_id = kwargs.get("id")
            client_filters = kwargs.get("filters") or None
            if isinstance(client_filters, str):
                import json

                client_filters = json.loads(client_filters) if client_filters else None
            return await cls._native_subscribe(
                channel_layer,
                schema,
                document,
                action=action,
                obj_id=obj_id,
                filters=client_filters,
                context=getattr(info, "context", None),
            )

        return _GraphQLField(
            cls._build_native_event_type(),
            args=args,
            subscribe=_subscribe_source,
            # The source dict IS the root; the event type's snake-closure
            # resolvers project it. ``**_kwargs`` absorbs the field arguments
            # ({action, id, filters}) that graphql-core's ``execute`` passes to the
            # resolver per delivered event (the COND-A delivery path uses bare
            # ``execute``, NOT ``subscribe``, so the root field's resolve receives
            # the coerced args alongside root/info).
            resolve=lambda root, _info, **_kwargs: root,
            description=f"Native subscription for {cls._meta.model.__name__} model",
        )

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
    "register_channel",
    "unregister_channel",
]
