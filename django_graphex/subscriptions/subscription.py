"""Provide the developer-facing "Subscription" type and subscribe resolver.

The public API (Meta keys, generated enums/arguments, output fields and the
exposed classmethods) is built directly on top of a Channels 4 broadcast
engine.
"""

from __future__ import annotations

from inspect import isawaitable
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

# S6e re-parent (#1452): ``Subscription`` is re-parented off graphene
# ``ObjectType`` onto the graphene-free native base (``native.base.ObjectType``)
# so ``type(<a Subscription subclass>) is pydantic.ModelMetaclass`` (the systemic
# metaclass-identity invariant). ``SubscriptionOptions`` becomes a thin subclass
# of the mutable ``NativeObjectTypeOptions`` (graphene-free _meta).
#
# S-sub-6 (graphene-removal): the subscription BUILD path is now graphene-free.
# Defining a ``Subscription`` subclass and mounting it (``.Field()``) no longer
# fires graphene at all (S8g had only LAZY-DEFERRED these — the firing still
# happened at subclass-def + mount time, pinning graphene for the process):
#   * ``_meta.arguments`` is now a NATIVE ``{action, id, filter}`` dict built
#     from graphql-core (``GraphQLArgument`` + a graphql-core action enum), NOT
#     graphene ``Argument(ActionSubscriptionEnum)``/``ID``/``GenericScalar``. It
#     mirrors the ``_build_native_field`` arg shape (the native compile path
#     already builds its OWN args and never read this dict — the dict is now a
#     graphene-free presence/keys contract). ``_generic_scalar`` and the cached
#     ``_g()`` accessor are RETIRED.
#   * ``SubscriptionField`` is now a NATIVE marker class (NOT a graphene ``Field``
#     subclass). The native root compiler detects it purely by class NAME
#     (``schema_compiler._is_subscription_field`` gates on
#     ``type(field).__name__ == 'SubscriptionField'`` + ``field.type`` carrying
#     ``_build_native_field``); a graphene base was never required for the mount.
#   * ``ActionSubscriptionEnum`` (the graphene ``Enum``) is retired from the build
#     path. It is kept lazily (PEP 562 ``__getattr__`` + cached factory) ONLY for
#     the graphene-backend-only test contract (``test_unit``/``test_isolation``
#     iterate the public re-export); those tests are deleted in S-del-tests-10 and
#     the lazy factory with them. Nothing on the native build path references it.
from ..backends import resolve_backend
from ..core.base import NativeObjectTypeOptions
from ..core.base import ObjectType as NativeObjectType
from ..core.descriptors import NativeMountedField
from ..settings import graphql_api_settings
from .bindings import SubscriptionBinding
from .mixins import safe_group_name, serialize_instance
from .streaming import build_middleware_manager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from typing import Callable

    from django.db.models import QuerySet
    from graphql import GraphQLResolveInfo


# --------------------------------------------------------------------------- #
# Native subscription mount marker (S-sub-6 graphene-removal)                 #
# --------------------------------------------------------------------------- #
class SubscriptionField(NativeMountedField):
    """Provide the MOUNT-SEAM marker the native root compiler detects.

    S-sub-6: this is now a NATIVE marker class (graphene-free) subclassing
    "NativeMountedField". Subclassing that base is what keeps the MOUNT SEAM intact
    on a graphene root: graphene's root metaclass DROPS any non-graphene attribute
    from "_meta.fields", but the native schema compiler's
    "_collect_dropped_native_fields" recovers every class-body "NativeMountedField"
    (and orders them by "creation_counter"), so the dropped subscription field is
    re-merged and ordered for byte-stable SDL.

    The native root compiler ("schema_compiler._is_subscription_field") then
    detects the recovered field purely by class NAME ("type(field).__name__ ==
    'SubscriptionField'") and "field.type" carrying "_build_native_field" — it
    never required a graphene "Field" base. The compiler ignores the args /
    subscribe carried here and calls "field.type._build_native_field()" to build
    the DIRECT graphql-core subscription field (its own action enum + "{action,
    id, filter}" args + native event output type).

    "field.type" resolves to the "Subscription" subclass verbatim (a class is
    returned as-is by "_resolve_thunk"); "args" carries the native
    "_meta.arguments" (presence/keys contract).
    """

    def __init__(
        self,
        type: Any,  # noqa: A002 - mirrors the historic graphene Field(type) API
        *,
        args: Any = None,
        subscribe: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the mounted "Subscription" subclass + its args/subscribe.

        Args:
            type: The "Subscription" subclass ("_meta.output") this field
                mounts. The native compiler reads "_build_native_field" off it
                (via "NativeMountedField.type", which returns a class verbatim).
            args: The native "_meta.arguments" mapping (presence/keys contract;
                unused by the native compile path which builds its own args).
            subscribe: An optional subscribe resolver (unused under native — the
                native field carries its own "subscribe" source factory).
            **kwargs: Extra mount kwargs (e.g. "description"); "description" is
                forwarded to the base, the rest retained for API parity.
        """
        super().__init__(
            type,
            args=args or {},
            description=kwargs.pop("description", None),
        )
        self._subscribe_fn = subscribe
        self.kwargs = kwargs


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


class SubscriptionOptions(NativeObjectTypeOptions):
    """Provide the Meta options container for "Subscription" subclasses.

    S6e (#1452): graphene-free. Was a subclass of graphene's frozen
    "ObjectTypeOptions"; now a thin subclass of the mutable
    "NativeObjectTypeOptions" whose parity-table surface ALREADY enumerates
    every subscription "_meta" attribute ("output"/"arguments"/"model"/
    "stream"/"backend"/"queryset"/"payload_mode"/"index_fields"/
    "subscription_index_fields") with graphene-equivalent defaults. The driver
    plain-assigns each attr below (no "object.__setattr__" freeze-bypass — the
    native Options is mutable by design), so this subclass adds nothing beyond a
    stable, subscription-named type the duck-typed callers can keep referencing.
    """


class Subscription(NativeObjectType):
    """Define the subscription type.

    Subclass it through "Meta" and mount it on the schema's subscription root
    via "Field":

        class UserSubscription(Subscription):
            class Meta:
                model = User
                stream = "users"

    S6e (#1452): re-parented off graphene "ObjectType" onto the graphene-free
    native base. The native base's "__init_subclass__" driver reproduces
    graphene's "SubclassWithMeta" dispatch (read "Meta", pop "abstract",
    dispatch "super(cls, cls).__init_subclass_with_meta__"), so this base stays
    abstract and each concrete subclass routes into the driver below — exactly as
    under graphene's metaclass, but now "type(<subclass>) is
    pydantic.ModelMetaclass".
    """

    class Meta:
        """Mark the "Subscription" base itself as abstract (not a schema type).

        The native base's "__init_subclass__" driver reads this "Meta", pops
        "abstract", and skips schema-type registration for the base class.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        stream: str | None = None,
        queryset: QuerySet | None = None,
        payload_mode: str | None = None,
        subscription_index_fields: tuple[str, ...] | list[str] | None = None,
        only_fields: tuple[str, ...] | list[str] | None = None,
        exclude_fields: tuple[str, ...] | list[str] | None = None,
        description: str = "",
        **options: Any,
    ) -> None:
        """Validate Meta and generate the enums, arguments and options.

        Args:
            model: The Django model this subscription serves (native backend).
            pydantic_model: Optional user Pydantic base for custom validation.
            stream: The stream name this subscription serves.
            queryset: An optional queryset whose model must match the backend's.
            payload_mode: Force "full" or "id_only" payloads, or "None" to inherit
                the global setting.
            only_fields: Restrict the subscription's serialized output to these
                field names ("None"/empty keeps every backend output field). The
                projection gates the event type, the broadcast payload AND the
                declared set client filters must root on.
            exclude_fields: Drop these field names from the subscription's
                serialized output. Use it to keep a sensitive column ("password")
                out of both the payload and the client-filter surface.
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

        # HARD rename guard (v2.0): the legacy ``Meta.serialize_data`` key is
        # caught in ``**options`` — fail loudly with the new spelling.
        if "serialize_data" in options:
            raise ImproperlyConfigured(
                "{}.Meta.serialize_data was renamed to payload_mode in v2.0 "
                '(use "full" or "id_only").'.format(cls.__name__)
            )

        if payload_mode not in (None, "full", "id_only"):
            raise ImproperlyConfigured(
                '{}.Meta.payload_mode must be "full", "id_only" or None, '
                'received "{}".'.format(cls.__name__, payload_mode)
            )

        index_fields = tuple(subscription_index_fields or ())
        for field_name in index_fields:
            # Fail fast: an index field must be a concrete field we can read
            # off the instance (FK -> "<name>_id") at notification time.
            model._meta.get_field(field_name)

        # S6e kwarg-audit (#1543): the native ObjectType TERMINAL only honors
        # ``name``/``description``/``interfaces``/``_meta`` — every other attr
        # graphene's old super() would have set must be assigned explicitly here
        # BEFORE the super() call or it vanishes into ``**_kwargs``. This driver
        # already builds the ENTIRE ``_meta`` (it passes ``_meta=_meta`` to super,
        # graphene's driver never derived these from kwargs), so the audit is a
        # no-op for the subscription attrs below: ``output``/``model``/``stream``/
        # ``backend``/``queryset``/``payload_mode``/``index_fields``/
        # ``arguments`` are all plain-assigned onto the mutable
        # ``NativeObjectTypeOptions`` (each one exists on its parity surface, so
        # no silent ``AttributeError`` on read). No ``types=`` analogue exists for
        # subscriptions, so no kwarg is dropped from the super() call.
        _meta = SubscriptionOptions(cls)
        _meta.output = cls
        _meta.model = model
        _meta.stream = stream
        _meta.backend = backend
        _meta.queryset = queryset
        _meta.payload_mode = payload_mode
        _meta.index_fields = index_fields
        # SECURITY (2.0.1): the output projection. Previously swallowed by
        # ``**options`` — so ``exclude_fields = ("password",)``, documented as THE
        # way to keep a column out of a subscription, silently did nothing and the
        # column stayed both serialized and client-filterable.
        _meta.only_fields = tuple(only_fields or ())
        _meta.exclude_fields = tuple(exclude_fields or ())

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

        # Native-only argument set: {action, id, filter}. The bespoke
        # ``channel_id``/``operation`` args and the ``data`` field-projection
        # enum are gone (the cutover replaced field projection with the GraphQL
        # selection set, and the WS/SSE transports are the auth boundary, so no
        # channel handshake id is needed). The reduced set mirrors the native
        # ``_build_native_field`` args (subscription.py native compile path).
        # S-sub-6: built NATIVELY (graphene-free) — graphql-core ``GraphQLArgument``
        # + a graphql-core action enum, NOT graphene ``Argument(ActionSubscription
        # Enum)``/``ID``/``GenericScalar``. The native compile path
        # (``_build_native_field``) already builds its OWN args and never read this
        # dict; it now exists as a graphene-free presence/keys contract (the only
        # native consumer reads ``set(_meta.arguments)``). Built from this class'
        # own ``_build_native_field_args`` so the arg shape stays in lockstep.
        # Assigned AFTER super(): 2.1.0's generated ``filter`` input is built
        # from ``cls._output_field_names()``, which reads the ``Meta`` output
        # projection off ``cls._meta`` — bound by the super() call above. The
        # options object is mutable (no graphene ``freeze()``), and ``cls._meta``
        # IS this very object, so the late assignment lands on the class.
        _meta.arguments = cls._build_native_field_args(model=model)

    @classmethod
    def _payload_is_full(cls) -> bool:
        """Tell whether notifications carry the full serialized instance.

        "Meta.payload_mode" (if set) wins; otherwise the global
        "SUBSCRIPTION_PAYLOAD_MODE" setting decides. Read at broadcast time so
        runtime/"override_settings" changes are honored.

        Returns:
            "True" when the full serialized instance should be sent ("full" mode);
            "False" for id-only payloads.

        Raises:
            ImproperlyConfigured: If the legacy "SUBSCRIPTION_SERIALIZE_DATA"
                setting key is still present, or the resolved payload mode is not
                one of "full" / "id_only".
        """
        # HARD rename guard (v2.0): the old setting key would otherwise be
        # silently ignored by the settings reader — fail loudly instead.
        user_settings = getattr(django_settings, "DJANGO_GRAPHEX", {})
        if "SUBSCRIPTION_SERIALIZE_DATA" in user_settings:
            raise ImproperlyConfigured(
                "The DJANGO_GRAPHEX setting SUBSCRIPTION_SERIALIZE_DATA was renamed "
                'to SUBSCRIPTION_PAYLOAD_MODE in v2.0 (use "full" or "id_only").'
            )

        value = cls._meta.payload_mode
        if value is None:
            value = graphql_api_settings.SUBSCRIPTION_PAYLOAD_MODE
        if value not in ("full", "id_only"):
            raise ImproperlyConfigured(
                'SUBSCRIPTION_PAYLOAD_MODE must be "full" or "id_only", '
                'received "{}".'.format(value)
            )
        return value == "full"

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

        The name is scoped by "Meta.stream" as well as the model label. Two
        subscriptions on the SAME model with different streams both register
        their signal receivers (the binding's "dispatch_uid" already carries the
        stream), so without the stream in the group name both would fan out into
        the identical groups and every subscriber would receive the other
        stream's payload — an id-only broadcast delivering nulls for every field
        a full-payload subscriber selected.

        When an "index" mapping is given, a canonical ":k=v&..." suffix
        (keys sorted) is appended so that subscribers scoped to those values land
        in their own group. The subscribe side and the broadcast side build the
        same suffix -- one from the scope, the other from the changed instance --
        so the names match by construction (no group enumeration needed).

        Args:
            action: The change action the group is built for.
            id: An optional object primary key for a per-object group.
            index: An optional "{field: value}" mapping for value-scoped groups.

        Returns:
            The Channels-safe group name.
        """
        base = "{}.{}".format(cls.model_label(), cls._meta.stream)
        if id:
            name = f"{base}-{action}-{id}"
        else:
            name = f"{base}-{action}"
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
        """Build the index "{field: value}" mapping from a live instance.

        Reads each "Meta.index_fields" entry by its "attname" so foreign keys
        yield the raw id (e.g. "owner_id") without a related-object query and
        plain fields yield their value. Returns "None" when no index is
        configured.

        Args:
            instance: The model instance that changed.

        Returns:
            The index mapping, or "None" when "index_fields" is empty.
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

        Hook meant to be overridden (or injected by "DjangoModelType").
        Raise "GraphQLError" to deny; the denial is surfaced to the client as
        "ok: False" / "error". The default allows. Runs in the HTTP request
        context, so "info.context.user" is available -- keep it free of
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

        Hook meant to be overridden (or injected by "DjangoModelType").
        The returned mapping (Django ORM lookup -> value, e.g.
        "{'owner': info.context.user.pk}") is merged into the subscriber's
        filters with SERVER PRECEDENCE, so it cannot be widened or removed by
        the client, and is enforced per event at delivery time. The default
        returns "None" (no scoping).

        Args:
            info: GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments.

        Returns:
            The forced filter mapping, or "None".
        """
        return None

    @classmethod
    def _projection_keeps(cls, name: str) -> bool:
        """Check whether "name" survives the "Meta" output projection.

        Args:
            name: A serialized output field name.

        Returns:
            "True" when "Meta.only_fields" is empty or lists "name" AND
            "Meta.exclude_fields" does not list it.
        """
        only = cls._meta.only_fields
        return (not only or name in only) and name not in cls._meta.exclude_fields

    @classmethod
    def _output_field_names(cls) -> list[str]:
        """Return the serialized output field names left by the "Meta" projection.

        This is the subscription's DECLARED set: what the event payload carries
        and what a client filter key may root on.

        Returns:
            The projected output field names, in model field order.
        """
        return [
            name
            for name in cls._meta.backend.output_field_names()
            if cls._projection_keeps(name)
        ]

    @classmethod
    def _serialize_payload(cls, instance: Any) -> dict[str, Any]:
        """Serialize "instance" once, keeping only the projected output fields.

        Args:
            instance: The changed model instance to serialize.

        Returns:
            The JSON-safe payload mapping with projected-out columns removed.
        """
        data = serialize_instance(cls._meta.backend, instance)
        return {key: value for key, value in data.items() if cls._projection_keeps(key)}

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
    # Native compile path (Phase 6 WU6).
    #
    # These methods build the NATIVE compile path: a graphql-core
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
        """Build the native event output "GraphQLObjectType" (deliverable pk shape).

        DESIGN RECONCILIATION (#1432 section 3 vs section 8): the serialize-once
        payload ("native/backend.py:to_representation") is FLAT PKS by design — one
        serialize feeds N subscribers with ZERO DB per subscriber. So the event
        type's relation fields MUST render the DELIVERABLE pk scalars/lists the
        flat payload actually carries, NOT the DB-backed nested output-type SDL
        (section 8's "byte-identical to the DjangoObjectType OUTPUT type" goal is a
        category error vs the section 3 flat-pk payload — nested FK/M2M resolution
        over a subscription event would need a per-subscriber DB query, the N+1
        cliff serialize-once forbids). The deliverable representation is:

          * scalars -> the Phase-5 native names/nullability ("id: ID!", model
            scalars NULLABLE, "Date" -> "CustomDate" / "UUID" -> "UUID" /
            "JSON" -> "JSONString" / "Decimal" -> "Float" …) reusing
            "native.output_compiler.compile_output_fields" — KEEP;
          * FK / O2O -> the PK SCALAR ("backend.to_representation" carries the FK
            under key "<field.name>" as the pk int via "getattr(obj,
            '<name>_id')"). Rendered as the pk's GraphQL scalar ("ID" for an
            auto/id pk, else the pk field's scalar). NOT the nested object type;
          * M2M / reverse to-many -> a LIST of pk scalars ("to_representation"
            carries the M2M under key "<field.name>" as "list(... values_list(
            'pk', flat=True))"). Rendered as "[<pk scalar>]". NOT the
            results/totalCount container.

        Each field's resolver is a WU1 "make_snake_resolver" closure (tagged
        "_gdx_pure_projection" so COND-B/"guard.py" whitelists it) keyed by the
        SNAKE payload key "backend.to_representation" actually writes
        ("field.name" for every kind — scalars, FK pk, M2M pk-list), fixing the
        camelCase-default-resolver silent-null. The flat serialize-once payload
        holds pks ("author=7", "co_authors=[7, 8]") and the snake closure
        DELIVERS those pks directly (no DB, no re-serialize). The type carries
        "extensions['gdx']" (the native bridge); "check_subscription_output_type"
        (COND-B) is run AFTER the sentinels are attached.

        Returns:
            A graphql-core "GraphQLObjectType" carrying "extensions['gdx']".
        """
        from graphql import GraphQLField as _GraphQLField
        from graphql import GraphQLObjectType

        from ..core.bridge import GdxPayload
        from ..core.ir import GdxMeta
        from .guard import check_subscription_output_type
        from .resolvers import make_snake_resolver

        type_name = cls._native_event_type_name()
        model = cls._meta.model

        def _fields() -> dict[str, Any]:
            from django.db import models as _dj_models
            from graphql import GraphQLID as _GraphQLID
            from graphql import GraphQLList as _GraphQLList

            from ..core.base import get_shared_output_registry
            from ..core.output_compiler import (
                _get_django_to_gql,
                _to_camel_case,
                compile_output_fields,
            )
            from ..registry import get_global_registry

            # 1) Scalars via the SHARED output registry — the SAME builder the
            # DjangoObjectType output thunk uses, so scalar NAMES/nullability are
            # byte-identical to the model output type (``id: ID!``, rest nullable).
            # compile_output_fields also emits FK/O2O as the NESTED object type,
            # which is DB-backed and WRONG for the flat-pk payload; those entries
            # are OVERWRITTEN below with the deliverable pk scalar.
            #
            # S-sub-6 (watch-item #6 reconcile): thread the SHARED graphene
            # ``Registry`` (the DEFAULT pair's ``graphene`` member IS
            # ``get_global_registry()`` — see types._schema_scoped_registry) so a
            # choices field in the payload renders the CANONICAL ``GraphQLEnumType``
            # (the SAME instance the regular OUTPUT + FILTER-INPUT paths resolve via
            # ``converter.build_choices_enum_type``'s memoized registry slot), NOT
            # the ``String`` fallback ``graphene_registry=None`` produced before.
            built: dict[str, Any] = dict(
                compile_output_fields(
                    model,
                    get_shared_output_registry(),
                    graphene_registry=get_global_registry(),
                )
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
                    built[wire] = _GraphQLField(_GraphQLList(_pk_scalar(related)))
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
            from django_graphex._strconv import to_snake_case

            rewrapped: dict[str, Any] = {}
            for wire, field in built.items():
                snake = to_snake_case(wire)
                # SECURITY (2.0.1): honor the ``Meta`` output projection so a
                # projected-out column is absent from the event TYPE too — not
                # merely absent from the payload dict (which would render as a
                # silent NULL and still advertise the column in the SDL).
                if not cls._projection_keeps(snake):
                    continue
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
        """Build the fully-populated WU5 "SubscriptionSpec" from this class.

        Wires the kept hooks ("authorize_subscription"/"subscription_scope"),
        "group_name"/"instance_index" = the kept "_group_name"/
        "_instance_index" (so producer + consumer group names match by
        construction), index_fields, and "db_exists" = the single-row
        ".exists()" narrowing that closes the WU4 conservative-drop gap so
        native "__lookup" subscriptions deliver DB-verified events.

        Filter-key validation lives in "streaming.py":
        "_validate_client_filters" checks every key against
        "declared_output_fields" (the PROJECTED "_output_field_names()") and the
        spec's "model" (the Django lookup registry the key suffixes are checked
        against), both passed on the spec below. That is the ONE choke point —
        there is no second, weaker validator.

        Args:
            schema: The native graphql-core "GraphQLSchema" the per-event
                "execute" runs against.
            document: The parsed subscription "DocumentNode" executed per event.

        Returns:
            A WU5 "SubscriptionSpec".
        """
        from .streaming import SubscriptionSpec

        def _authorize(context: Any, **kwargs: Any) -> None:
            # The kept classmethod takes (info, **kwargs); pass the
            # transport-neutral context as ``info``. Both transports' contexts
            # expose ``.user`` AND a ``.context`` self-alias, so the documented
            # ``info.context.user`` spelling resolves here exactly as it does in
            # a resolver (where ``info`` is a real GraphQLResolveInfo).
            cls.authorize_subscription(context, **kwargs)

        def _scope(context: Any, **kwargs: Any) -> dict[str, Any] | None:
            return cls.subscription_scope(context, **kwargs)

        return SubscriptionSpec(
            model_label=cls.model_label(),
            stream=cls._meta.stream,
            schema=schema,
            document=document,
            declared_output_fields=set(cls._output_field_names()),
            index_fields=tuple(cls._meta.index_fields),
            authorize=_authorize,
            scope=_scope,
            group_name=cls._group_name,
            instance_index=cls._instance_index,
            db_exists=cls._native_db_exists,
            event_type_name=cls._native_event_type_name(),
            payload_mode=cls._meta.payload_mode,
            model=cls._meta.model,
        )

    @classmethod
    def _native_db_exists(
        cls, remaining: dict[str, Any], event: dict[str, Any], *, obj_id: Any = None
    ) -> Any:
        """Single-row ".exists()" narrowing for non-empty "__lookup" filters.

        Closes the WU4 conservative-drop gap: a "__lookup" filter the in-memory
        equality gate cannot resolve (e.g. "author__name" / a relation lookup)
        is verified by a single-row ".exists()" against the changed instance's
        pk — so only events whose row actually matches the lookup are delivered.

        Wrapped via "sync_to_async": the source's "db_verify" runs inside the
        async receive loop, so a direct blocking ORM ".exists()" would raise
        "SynchronousOnlyOperation" on an ASGI server. The returned coroutine is
        awaited by the WU5 "_build_db_verify" wrapper ("_maybe_await").

        Args:
            remaining: The non-empty "__lookup" filters left after the in-memory
                equality gate (Django ORM lookup -> expected value).
            event: The already-serialized flat snake dict for the changed instance.
            obj_id: An optional per-object id (unused — the pk is read from the
                event so the narrowing targets exactly the changed row).

        Returns:
            An awaitable resolving to "True" when the changed row matches every
            remaining lookup.
        """
        # The flat payload keys the primary key by its real field name (a "slug"
        # pk lands under "slug"), in both "id_only" and "full" payload modes.
        pk = event.get(cls._meta.model._meta.pk.name)
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
        """Run the native subscribe (WU5 "native_subscribe") for this subscription.

        Builds the spec from this class and delegates to WU5 "native_subscribe",
        which runs the KEPT hooks BEFORE any "group_add" (deny short-circuits
        before the source), joins exactly the action-selected groups (#1420), and
        wires "source.db_verify" to the single-row ".exists()" narrowing.

        Args:
            channel_layer: The constructed Channels channel layer (injected).
            schema: The native graphql-core schema for the per-event execute.
            document: The parsed subscription document executed per event.
            action: The requested action ("create"/"update"/"delete"/
                "all_actions"); picks the join set.
            obj_id: An optional per-object primary key.
            filters: The raw client-supplied filters.
            context: The transport-neutral context (".user" + scope mapping).

        Returns:
            The STARTED "ChannelLayerSource" (drive via "drive_subscription").
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
    def _build_native_field_args(cls, model: Any = None) -> dict[str, Any]:
        """Build the native "{action, id, filter}" graphql-core args (graphene-free).

        S-sub-6: the single source of truth for the subscription field arguments.
        Used both for "_meta.arguments" (the graphene-free presence/keys
        contract built at subclass-def) and for the live "_build_native_field"
        compile (the DIRECT graphql-core "GraphQLField" the native root compiler
        mounts). Building it here keeps the two in lockstep with ZERO graphene.

        2.1.0: "filters" (a "GraphQLString" carrying JSON) became "filter", a
        GENERATED "<Model>SubscriptionFilterInput" using the same nested shape
        queries use, so the schema itself enforces the projected field set and
        the 2.0.1 lookup allow list.

        Args:
            model: The Django model whose name scopes the action enum. Kept for
                API parity with the historical subclass-def call; defaults to
                "cls._meta.model".

        Returns:
            A "{name: GraphQLArgument}" mapping with a non-null model-scoped
            action enum, an optional "id" ("GraphQLID"), and an optional
            "filter" typed by the generated subscription filter input. The
            "filter" argument is omitted when the projection leaves no
            filterable field.
        """
        from graphql import (
            GraphQLArgument,
            GraphQLNonNull,
        )
        from graphql import (
            GraphQLID as _GraphQLID,
        )
        from graphql.type import GraphQLEnumType, GraphQLEnumValue

        from django_graphex.filtering.native_schema import (
            build_subscription_filter_input_type,
        )

        if model is None:
            model = cls._meta.model
        action_enum = GraphQLEnumType(
            f"{model.__name__}SubscriptionAction",
            {
                "CREATE": GraphQLEnumValue("create"),
                "UPDATE": GraphQLEnumValue("update"),
                "DELETE": GraphQLEnumValue("delete"),
                "ALL_ACTIONS": GraphQLEnumValue("all_actions"),
            },
        )
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
        }
        filter_input = build_subscription_filter_input_type(
            model, cls._output_field_names()
        )
        if filter_input is not None:
            args["filter"] = GraphQLArgument(
                filter_input,
                description="Optional per-subscriber field filters.",
                out_name="filter",
            )
        return args

    @classmethod
    def _filter_lookup_key(cls, field_name: str, lookup: str) -> str:
        """Map one "(field, lookup)" pair to the ORM key the delivery gate reads.

        Everything downstream — "streaming._validate_client_filters", the
        in-memory equality gate and the single-row ".exists()" narrowing —
        consumes a FLAT mapping of Django ORM lookups, so the nested input has
        to collapse to one.

        "exact" collapses to the BARE field name rather than "<field>__exact",
        which is the same ORM lookup but keeps the serialize-once promise: the
        in-memory gate ("mixins.split_filters") can only decide a key WITHOUT a
        "__" suffix, so "<field>__exact" would push the documented scoping case
        ("filter: { post: { exact: 7 } }") onto a per-event database query. The
        one exception is a to-many field, whose serialized payload value is a
        LIST of primary keys that no scalar comparison can decide — it keeps the
        suffix so the ".exists()" narrowing answers it against the database.

        Args:
            field_name: The snake ORM field name (the input field's out_name).
            lookup: The lookup name ("exact"/"iexact"/"in"/"isnull").

        Returns:
            The flat Django ORM lookup key.
        """
        if lookup != "exact":
            return f"{field_name}__{lookup}"
        try:
            many = bool(cls._meta.model._meta.get_field(field_name).many_to_many)
        except Exception:  # noqa: BLE001 - an unknown name is rejected downstream
            many = False
        return f"{field_name}__exact" if many else field_name

    @classmethod
    def _flatten_filter_input(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Flatten the coerced "filter" input object into ORM lookup keys.

        Turns the nested wire shape "{'post': {'exact': 7}}" into the flat
        "{'post': 7}" the delivery path consumes. graphql-core already delivered
        snake keys here (every generated input field carries an "out_name"), so
        this only has to join the two levels.

        Args:
            value: The coerced "filter" argument, or "None" when omitted.

        Returns:
            The flat Django-ORM-lookup mapping, or "None" when the client asked
            for no filtering at all.
        """
        if not value:
            return None
        flat: dict[str, Any] = {}
        for field_name, lookups in value.items():
            for lookup, expected in (lookups or {}).items():
                flat[cls._filter_lookup_key(field_name, lookup)] = expected
        return flat or None

    @classmethod
    def _build_native_field(cls, schema: Any = None, document: Any = None) -> Any:
        """Build the native subscription field as a DIRECT graphql-core "GraphQLField".

        NOT a graphene "Field"/"SubscriptionField" (design section 3 / C-A). The
        field carries:

          * "type" = the native event output type ("extensions['gdx']" +
            snake-closure resolvers),
          * "subscribe" = a source factory that runs WU5 "native_subscribe"
            (returning a "ChannelLayerSource"; the transport layer drives
            it via WU5 "drive_subscription"),
          * "resolve" = identity (the source dict IS the root; the event type's
            snake-closure resolvers project it),
          * "args" reduced to "{action, id, filter}" under native (the
            graphene-only "channel_id"/"operation" args are dropped).

        "schema"/"document" are OPTIONAL: the subscribe factory only builds the
        "ChannelLayerSource" (group join), which does NOT read the spec's
        "schema"/"document" (only "drive_subscription" — the transport's
        per-event delivery — does). So the field is buildable at SCHEMA-COMPILE
        time ("compile_native_root", WU7 root wiring) when the assembled native
        schema and the per-request document are not yet known; the transport layer
        (WU8/WU9) supplies the live schema + parsed request document to
        "drive_subscription" at delivery time. When provided here they are
        forwarded for direct/test drive paths.

        Args:
            schema: The native graphql-core schema for the per-event execute
                (optional — supplied by the transport at delivery time).
            document: The parsed subscription document executed per event
                (optional — the per-request selection set, supplied at delivery).

        Returns:
            A graphql-core "GraphQLField".
        """
        from graphql import (
            GraphQLField as _GraphQLField,
        )

        # Reduced native arg set: {action, id, filter} (no channel_id/operation).
        # S-sub-6: shared with ``_meta.arguments`` via the single builder so the
        # live field + the subclass-def presence contract stay in lockstep.
        args = cls._build_native_field_args()

        async def _subscribe_source(root: Any, info: Any, **kwargs: Any) -> Any:
            # SECURITY (2.0.1): graphql-core's ``create_source_event_stream``
            # accepts NO ``middleware=`` argument, and this resolver is the ONE
            # choke point every transport's subscribe routes through — so the
            # connection's configured chain (``DJANGO_GRAPHEX['MIDDLEWARE']``,
            # e.g. ``AuthenticatedFieldsMiddleware``) is applied HERE, before any
            # ``group_add``. A raising middleware short-circuits with no source.
            # The manager is built once per connection by the transport and
            # carried on the neutral context; a non-transport caller falls back to
            # the setting so protection is never OFF by omission.
            context = getattr(info, "context", None)
            manager = getattr(context, "middleware", None)
            if manager is None:
                manager = build_middleware_manager()
            resolver = (
                _start_source
                if manager is None
                else manager.get_field_resolver(_start_source)
            )
            result = resolver(root, info, **kwargs)
            return await result if isawaitable(result) else result

        async def _start_source(root: Any, info: Any, **kwargs: Any) -> Any:
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            if channel_layer is None:
                raise RuntimeError(
                    "No channel layer configured; set CHANNEL_LAYERS to enable "
                    "subscriptions."
                )
            action = _enum_value(kwargs.get("action"))
            obj_id = kwargs.get("id")
            client_filters = cls._flatten_filter_input(kwargs.get("filter"))
            return await cls._native_subscribe(
                channel_layer,
                schema,
                document,
                action=action,
                obj_id=obj_id,
                filters=client_filters,
                context=getattr(info, "context", None),
            )

        _sub_field = _GraphQLField(
            cls._build_native_event_type(),
            args=args,
            subscribe=_subscribe_source,
            # The source dict IS the root; the event type's snake-closure
            # resolvers project it. ``**_kwargs`` absorbs the field arguments
            # ({action, id, filter}) that graphql-core's ``execute`` passes to the
            # resolver per delivered event (the COND-A delivery path uses bare
            # ``execute``, NOT ``subscribe``, so the root field's resolve receives
            # the coerced args alongside root/info).
            resolve=lambda root, _info, **_kwargs: root,
            description=f"Native subscription for {cls._meta.model.__name__} model",
        )
        # P0: stamp per-action composite permissions so the pruner can filter the
        # subscription action enum per signature. The value is a
        # ``dict{action_value: frozenset}`` (create/update/delete/all_actions).
        from django_graphex.core.perm_labels import required_perms_for

        _model = cls._meta.model
        _sub_field.extensions = {
            **(_sub_field.extensions or {}),
            "gdx_required_perms": {
                _sub_action: required_perms_for(_model, "subscribe", _sub_action)
                for _sub_action in ("create", "update", "delete", "all_actions")
            },
        }
        return _sub_field

    @classmethod
    def Field(cls, *args: Any, **kwargs: Any) -> SubscriptionField:
        """Mount this subscription on a root subscription "ObjectType".

        The mounted "SubscriptionField" is the seam the native schema compiler
        reads ("schema_compiler.compile_native_root" detects the field by class
        name and calls "field.type._build_native_field()" to build the DIRECT
        graphql-core subscription field — the native compile path). The native
        field drives the source.

        Args:
            *args: Positional mount arguments (accepted for graphene "Field" API
                parity; unused).
            **kwargs: Extra mount kwargs; "description" defaults to a generated
                label when omitted.

        Returns:
            The "SubscriptionField" carrying this subscription's output type.
        """
        kwargs.setdefault(
            "description", f"Subscription for {cls._meta.model.__name__} model"
        )
        # Ensure the signal binding exists as soon as the schema is wired.
        cls.get_binding()
        # S-sub-6: ``SubscriptionField`` is now the NATIVE marker class defined at
        # module level (no graphene base). The native root compiler detects it by
        # class NAME (``schema_compiler._is_subscription_field``) and calls
        # ``cls._build_native_field()`` for the live field, so the marker just
        # carries ``type`` (the Subscription subclass) + the native
        # ``_meta.arguments`` (presence/keys contract).
        return SubscriptionField(
            cls._meta.output,
            args=cls._meta.arguments,
            **kwargs,
        )


# Re-exported for convenience / typing.
__all__ = [
    "Subscription",
    "SubscriptionField",
    "SubscriptionOptions",
]
