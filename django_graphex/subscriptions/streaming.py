"""Native subscription engine glue: "SubscriptionSpec" + "drive_subscription".

This module is the WU5 integration core of the serialize-once streaming engine
(design sections 2, 3, 4, 6, 7). It composes the three lower layers built
earlier:

  * "ChannelLayerSource" (WU4, source.py) — the Channels group consumer that
    yields already-serialized flat snake dicts.
  * "DeliveryIterator" (WU2, delivery.py) — the COND-A lightweight delivery
    wrapper (NOT graphql-core's stock mapping delivery class; out-of-band close).
  * "make_snake_resolver" (WU1, resolvers.py) — the per-field snake-closure
    projection attached to the event type.

Two public entry points:

"native_subscribe" (the subscribe entry)
    Runs the KEPT subscription hooks BEFORE the source is created, so a DENY in
    "authorize" short-circuits BEFORE any "group_add" (design section 3):
    "authorize" -> "validate_filters" -> "scope" -> "filters = client union
    scope" (scope WINS on conflict) -> compute index + group names (the action
    arg picks the join set: "('create','update','delete')" for "all_actions"
    else "(action,)" — never hardcodes three, the #1420 guard) -> construct
    "ChannelLayerSource" -> "start()" (join groups) -> wire "source.db_verify"
    to the spec's single-row ".exists()" narrowing AFTER setting
    "source.filters" (the WU4 contract: closes the conservative-drop gap so
    "__lookup" subscriptions actually deliver verified events). Returns the
    STARTED source; the caller wraps it via "drive_subscription".

"drive_subscription" (the delivery path)
    Composes the source through the WU2 "DeliveryIterator" whose per-value map
    is a graphql-core "execute(schema, document, root_value=<flat dict>, ...)"
    call. "execute" returns an "ExecutionResult" SYNCHRONOUSLY over the flat
    dict (the source value IS the root; the snake-closure resolvers project it —
    NO DB, NO re-serialize, NO model instantiation). The delivery path is the WU2
    lightweight wrapper, NOT graphql-core's stock mapping delivery class (COND-A).
    Out-of-band close ("aclose()") propagates to the source so "complete{id}"
    / disconnect cancels promptly.

Transport-neutral context (design section 7): the hooks and "execute" receive a
"context" exposing ".user" and a "scope" mapping — satisfied by BOTH the SSE
"HttpRequest" and the WS Channels "scope". Nothing here assumes "HttpRequest".

This module imports neither graphene nor channels at module scope (channels is
injected as a constructed layer by the caller); "graphql-core" is the only
GraphQL dependency, mirroring the rest of the native engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from graphql import execute

from .delivery import make_delivery_iterator
from .source import ChannelLayerSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping

    from graphql import DocumentNode, ExecutionResult, GraphQLSchema

    from .delivery import DeliveryIterator

__all__ = [
    "SubscriptionSpec",
    "build_middleware_manager",
    "drive_subscription",
    "native_subscribe",
]


# ---------------------------------------------------------------------------
# Default hooks — used when a spec leaves a hook unset (allow-all / no-scope).
# ---------------------------------------------------------------------------


def _default_authorize(context: Any, **kwargs: Any) -> None:
    """Default "authorize": allow every subscribe (no-op)."""
    return None


def _default_scope(context: Any, **kwargs: Any) -> "dict[str, Any] | None":
    """Default "scope": no server-forced filters."""
    return None


def _default_instance_index(instance: Any) -> "dict[str, Any] | None":
    """Default "instance_index": no value-scoped routing."""
    return None


@dataclass
class SubscriptionSpec:
    """The native-path subscription options carrier (design section 2, C-A).

    A PLAIN "@dataclass" — NOT a "BaseModel"/"ModelMetaclass" re-home (#1452). It
    replaces graphene's "SubscriptionOptions" only as the native-path options
    carrier; the public "Subscription" base stays an "ObjectType" until Phase 7.
    "native_subscribe" and "drive_subscription" read everything they need from a
    spec instance, so the engine is decoupled from the graphene-based
    "Subscription" class.

    Attributes:
        model_label: The "app_label.modelname" identifier used to build group
            names.
        stream: The stream name this subscription serves.
        schema: The graphql-core "GraphQLSchema" the per-event "execute" runs
            against (the native subscription schema).
        document: The parsed subscription "DocumentNode" (the client's selection
            set) executed PER delivered event over the flat source dict.
        declared_output_fields: The set of declared serialized output field names;
            client filter keys must root on one of these (filter-key validation,
            design section 3 / cap 4).
        index_fields: Optional model field names used to route notifications to
            value-scoped groups (the indexed-groups optimization). When every
            index field is present in the merged scope, the source joins a
            value-scoped group.
        authorize: "authorize(context, **kwargs) -> None" — runs BEFORE the source
            is created; raise to DENY (short-circuits before any "group_add").
        scope: "scope(context, **kwargs) -> Mapping | None" — server-forced
            filters merged with client filters at SERVER precedence (scope wins).
        group_name: "group_name(action, *, id=None, index=None) -> str" — builds
            the Channels group name (matches the producer's "_group_name" by
            construction). Reuses the kept "Subscription._group_name".
        instance_index: "instance_index(instance) -> Mapping | None" — builds the
            index mapping from a changed instance (kept
            "Subscription._instance_index"). Carried for the producer side; unused
            in the subscribe path.
        db_exists: Optional "db_exists(remaining, event, *, obj_id=None) -> bool" —
            the single-row ".exists()" narrowing wired into "source.db_verify" for
            non-empty "__lookup" "remaining" filters. "None" keeps the source's
            conservative drop (no unverified "__lookup" event is ever yielded).
        event_type_name: Optional name of the subscription event output type
            (diagnostics).
        payload_mode: Optional "full"/"id_only" payload mode (carried for the
            producer side).
        model: Optional Django model object. Also the model the client
            filter-key lookup suffixes are validated against.
        pydantic_model: Optional user Pydantic base (carried for the producer
            side).
        middleware: Optional graphql-core "MiddlewareManager" for the connection
            (built by the transport from "DJANGO_GRAPHEX['MIDDLEWARE']"). Passed
            to the per-event delivery "execute" so the configured chain — e.g.
            "AuthenticatedFieldsMiddleware" — gates subscription delivery exactly
            as it gates the HTTP view. "None" runs delivery unwrapped.
    """

    model_label: str
    stream: str
    schema: "GraphQLSchema"
    document: "DocumentNode"
    declared_output_fields: set[str] = field(default_factory=set)
    index_fields: tuple[str, ...] = ()
    authorize: "Callable[..., Any]" = _default_authorize
    scope: "Callable[..., Any]" = _default_scope
    group_name: "Callable[..., str] | None" = None
    instance_index: "Callable[[Any], Any]" = _default_instance_index
    db_exists: "Callable[..., Any] | None" = None
    event_type_name: str | None = None
    payload_mode: str | None = None
    model: Any = None
    pydantic_model: Any = None
    middleware: Any = None


# ---------------------------------------------------------------------------
# Execution middleware (CVE-2.0.1 #3): ``DJANGO_GRAPHEX['MIDDLEWARE']`` used to
# be read ONLY by ``GraphQLView``, so every bundled security middleware (notably
# ``AuthenticatedFieldsMiddleware``, the enforcement half of
# ``private_subscription``) was INERT on subscriptions — the only transports that
# serve them. The manager is built ONCE per connection by the transport and
# threaded through BOTH the subscribe entry (via the transport context) and this
# spec (the per-event delivery ``execute``).
# ---------------------------------------------------------------------------


def build_middleware_manager() -> Any:
    """Build the graphql-core middleware manager for a subscription connection.

    Reuses the exact construction "views.GraphQLView" performs
    ("instantiate_middleware" + "MiddlewareManager") over the SAME
    "DJANGO_GRAPHEX['MIDDLEWARE']" setting, so a subscription runs the chain an
    HTTP operation runs. The setting is read per call (never memoized at import)
    so "override_settings" is honored.

    Returns:
        A "MiddlewareManager", or "None" when no middleware is configured.
    """
    from graphql.execution.middleware import MiddlewareManager

    from ..settings import graphql_api_settings
    from ..views import instantiate_middleware

    middleware = graphql_api_settings.MIDDLEWARE
    if not middleware:
        return None
    return MiddlewareManager(*instantiate_middleware(middleware))


# ---------------------------------------------------------------------------
# Filter-key validation (design §3 / capability 4): a client filter key must
# root on a declared output field, so an attacker cannot probe arbitrary ORM
# fields. Server-forced scope filters are NOT subject to this check.
#
# The suffix ALLOW LIST below is the second half of that guard. Rooting a key on
# a declared field is not enough: in the DEFAULT configuration (no
# ``only_fields``/``exclude_fields``) EVERY serialized column is declared, and
# delivery evaluates the key as ``.filter(pk=..., **client_filters).exists()`` —
# a boolean oracle over a column an id-only subscriber cannot even select.
#
# What makes that oracle exploitable is INCREMENTAL extraction. An ordered or
# pattern lookup (``gt``, ``startswith``, ``icontains``, ``regex``, a date part,
# …) answers "is the hidden value greater than / does it begin with X?", so an
# attacker walks a secret prefix-by-prefix or binary-searches it in a linear
# number of probes. Equality and membership answer only "is it exactly X?",
# which forces a whole-value guess — infeasible against a secret. So the allowed
# suffixes are exactly equality/membership; everything else is refused.
# ---------------------------------------------------------------------------

#: The lookup suffixes a CLIENT filter key may carry. Equality and membership
#: only: they cannot be composed into an incremental extraction of a value the
#: subscriber is not allowed to read. Server-forced scope filters are exempt.
_ALLOWED_LOOKUPS = frozenset({"exact", "iexact", "in", "isnull"})


def _lookup_names(model: Any, root: str) -> "set[str]":
    """Return the Django lookup/transform names registered for a model field.

    Args:
        model: The subscribed Django model, or "None" when the spec carries no
            model (a bare driver spec) — the base "Field" registry is used then,
            which is the conservative common subset.
        root: The declared output field name the lookups are read from.

    Returns:
        The registered lookup and transform names accepted after "root".
    """
    from django.db.models import Field

    field: Any = None
    if model is not None:
        try:
            field = model._meta.get_field(root)
        except Exception:  # noqa: BLE001 - an unknown name has no lookups
            field = None
    return set((field or Field()).get_lookups())


def _validate_client_filters(
    client_filters: "Mapping[str, Any]",
    declared: set[str],
    model: Any = None,
) -> None:
    """Raise when any "client_filters" key is not a declared field plus lookups.

    The FULL key is validated, not just its root:

      * the root (everything before the first "__") must be a declared —
        i.e. "only_fields"/"exclude_fields"-projected — output field;
      * every remaining segment must be a Django lookup or transform registered
        on that field (so relation traversal is rejected);
      * every remaining segment must ALSO be in the equality/membership allow
        list, because delivery turns the key into a boolean oracle.

    Relation traversal into another model's columns ("groups__name__startswith")
    is REJECTED: "name" is not a lookup registered on the "groups" field.
    Without this, event delivery ran "filter(pk=..., **client_filters)" and
    became a boolean oracle over columns the payload never exposes.

    Ordered and pattern lookups ("password__startswith", "created__gt",
    "text__icontains", a date part) are REJECTED even on a declared field: they
    answer comparisons, so an attacker composes them into a prefix walk or a
    binary search and extracts a column an id-only subscriber cannot select.
    Equality and membership only answer "is it exactly this value?", which
    forces an infeasible whole-value guess, so they stay allowed and the
    documented scoping use ("filters: { post: 7 }") keeps working.

    A client can still test EQUALITY against any field the developer DECLARED as
    subscription output. Keep sensitive columns out with
    "only_fields"/"exclude_fields".

    Server-forced scope filters are NOT subject to this check — they originate
    from server code, not the client.

    Args:
        client_filters: The raw filters supplied by the subscriber.
        declared: The set of declared serialized output field names.
        model: The subscribed Django model whose field lookups are consulted.

    Raises:
        ValueError: When a filter key roots on an undeclared field, carries a
            segment that is not a registered lookup, or carries a lookup outside
            the equality/membership allow list. (A plain exception keeps this
            module free of any graphene/graphql error coupling; the transport
            layer translates it into an error frame.)
    """
    if not client_filters:
        return
    for key in client_filters:
        root, *rest = key.split("__")
        if root not in declared:
            raise ValueError(
                "Subscription filter key '{}' is not a declared output field. "
                "Allowed fields: {}.".format(key, ", ".join(sorted(declared)))
            )
        if not rest:
            continue
        lookups = _lookup_names(model, root)
        for segment in rest:
            if segment not in lookups:
                raise ValueError(
                    "Subscription filter key '{}' is not a valid Django lookup "
                    "on the declared output field '{}': '{}' is neither a "
                    "lookup nor a transform. Relation traversal is not allowed "
                    "in client filters.".format(key, root, segment)
                )
            if segment not in _ALLOWED_LOOKUPS:
                raise ValueError(
                    "Subscription filter key '{}' uses '{}', which is not an "
                    "allowed lookup in client filters. Allowed lookups: {} (or "
                    "a bare field name, which means exact). Ordered and pattern "
                    "lookups are refused because event delivery makes them a "
                    "boolean oracle that can extract a field value one "
                    "comparison at a time.".format(
                        key, segment, ", ".join(sorted(_ALLOWED_LOOKUPS))
                    )
                )


async def _maybe_await(value: Any) -> Any:
    """Await "value" when it is awaitable, else return it unchanged."""
    return await value if isawaitable(value) else value


def _actions_for(action: str) -> tuple[str, ...]:
    """Map a requested action to the join set (the #1420 guard).

    "all_actions" -> "('create','update','delete')"; any other action ->
    "(action,)". NEVER hardcodes all three for a single-action subscribe.
    """
    if action == "all_actions":
        return ("create", "update", "delete")
    return (action,)


def _build_db_verify(
    spec: "SubscriptionSpec",
    obj_id: Any,
) -> "Callable[[dict[str, Any], dict[str, Any]], Any] | None":
    """Wrap the spec's "db_exists" narrowing into the source "db_verify" hook.

    The WU4 contract: "source.db_verify" is "async (remaining, event) -> bool".
    When the spec carries a "db_exists" callable (the single-row ".exists()"
    narrowing for non-empty "__lookup" "remaining" filters), wrap it so the
    source can "await" it; otherwise return "None" so the source keeps its
    conservative drop (never yields an unverified "__lookup" event).

    Args:
        spec: The subscription spec carrying the optional "db_exists" narrowing.
        obj_id: The optional per-object id, forwarded to the narrowing.

    Returns:
        An async "db_verify" hook, or "None" when no narrowing is configured.
    """
    db_exists = spec.db_exists
    if db_exists is None:
        return None

    async def _db_verify(remaining: dict[str, Any], event: dict[str, Any]) -> bool:
        # SECURITY: verify the non-empty "remaining" __lookup filters against the
        # database (a single-row .exists() narrowing) so an unverified __lookup
        # event is never yielded. The result is coerced to bool.
        result = db_exists(remaining, event, obj_id=obj_id)
        result = await _maybe_await(result)
        return bool(result)

    return _db_verify


async def native_subscribe(
    spec: "SubscriptionSpec",
    channel_layer: Any,
    *,
    action: str,
    obj_id: Any = None,
    filters: "Mapping[str, Any] | None" = None,
    context: Any = None,
) -> "ChannelLayerSource":
    """Run the subscribe hooks, then build and start the group source.

    The hooks run BEFORE any group is joined (design section 3), so a DENY in
    "authorize" short-circuits BEFORE any "group_add":

      1. "authorize(context, **kwargs)" — raise to DENY (NO source, NO join).
      2. "_validate_client_filters" — reject filter keys on undeclared fields.
      3. "scope(context, **kwargs)" — server-forced filters.
      4. "filters = {**client, **scope}" — scope WINS on conflict.
      5. compute the index (SCOPE-ONLY parity with the kept "_subscribe" hook:
         a value-scoped group is joined only when the SERVER scope supplies every
         index field — never from a client value) and the group names; the
         "action" arg picks the join set ("all_actions" -> three groups, else
         the single action — #1420 guard).
      6. construct "ChannelLayerSource(groups, channel_layer, filters=filters)"
         and "start()" it (the ONLY place "group_add" happens).
      7. wire "source.db_verify" to the spec's single-row ".exists()"
         narrowing AFTER setting "source.filters" (the WU4 contract).

    The hooks may be sync or async; awaitable returns are awaited.

    Args:
        spec: The native-path subscription spec.
        channel_layer: The constructed Channels channel layer (injected — this
            module never imports channels).
        action: The requested action ("create"/"update"/"delete"/"all_actions");
            picks the join set.
        obj_id: An optional per-object primary key for a per-object group.
        filters: The raw client-supplied filters (Django ORM lookup -> value).
        context: The transport-neutral context (".user" + "scope" mapping);
            passed to the hooks. NOT assumed to be an "HttpRequest" (design
            section 7).

    Returns:
        The STARTED "ChannelLayerSource" (groups joined, "db_verify" wired). The
        caller wraps it via "drive_subscription".

    Raises:
        Exception: Whatever "authorize" raises to DENY, or "ValueError" from
            filter-key validation — both BEFORE any "group_add".
    """
    client_filters: dict[str, Any] = dict(filters) if filters else {}

    # (1) Authorize — DENY short-circuits BEFORE the source is created.
    await _maybe_await(
        spec.authorize(context, action=action, id=obj_id, filters=filters)
    )

    # (2) Validate client filter keys against declared output fields (FULL key:
    # declared root + registered lookup suffixes — no relation traversal).
    _validate_client_filters(client_filters, spec.declared_output_fields, spec.model)

    # (3) Server-forced scope.
    scope = await _maybe_await(
        spec.scope(context, action=action, id=obj_id, filters=filters)
    )
    scope = dict(scope) if scope else {}

    # (4) Merge — scope WINS on conflict (server precedence).
    merged: dict[str, Any] = {**client_filters, **scope}

    # (5) Index routing: SCOPE-ONLY parity with the kept ``Subscription._subscribe``
    # hook (subscription.py: ``all(field in scope for field in index_fields)``).
    # A value-scoped group is joined ONLY when the SERVER scope supplies every
    # index field — NEVER from a client-supplied value. Routing on ``merged``
    # (client ∪ scope) would let a client pick a value-scoped group it should not
    # see (a cross-subscriber routing leak); the WU6 reconciliation of the WU5
    # SUGGESTION pins this to ``scope`` alone. The PARITY INVARIANT below makes
    # the equivalence explicit and guards against a future regression.
    index: dict[str, Any] | None = None
    if spec.index_fields and all(f in scope for f in spec.index_fields):
        index = {f: scope[f] for f in spec.index_fields}
        # Parity assertion: a scope-routed index value must equal the merged value
        # (scope wins on conflict, so they cannot diverge) — proving SCOPE-ONLY
        # routing matches the kept hook's effective filter exactly.
        assert all(index[f] == merged[f] for f in index), (
            "index routing must be SCOPE-ONLY parity with the kept _subscribe hook"
        )

    group_name = spec.group_name
    if group_name is None:  # pragma: no cover - spec must provide a namer
        raise ValueError("SubscriptionSpec.group_name must be provided")
    groups = [group_name(act, id=obj_id, index=index) for act in _actions_for(action)]

    # (6) Construct + start the source (the ONLY group_add happens here, AFTER
    # all hooks have run — deny never reaches this point).
    source = ChannelLayerSource(
        groups=groups,
        channel_layer=channel_layer,
        filters=merged or None,
    )
    await source.start()

    # (7) Wire the db_verify hook AFTER source.filters is set (the WU4 contract),
    # closing the conservative-drop gap for non-empty __lookup "remaining" filters.
    source.db_verify = _build_db_verify(spec, obj_id)

    return source


def drive_subscription(
    source: "ChannelLayerSource",
    spec: "SubscriptionSpec",
    context: Any = None,
) -> "DeliveryIterator":
    """Compose "source" through the COND-A delivery iterator with per-event execute.

    Each flat source dict is mapped by a graphql-core "execute(schema, document,
    root_value=<flat dict>, context_value=context, ...)" call that returns an
    "ExecutionResult" SYNCHRONOUSLY (the source dict IS the root; the
    snake-closure resolvers project it — NO DB, NO re-serialize). The result of
    each map is the yielded value.

    The delivery path is the WU2 "DeliveryIterator" (NOT graphql-core's stock
    mapping delivery class — the COND-A structural invariant). Out-of-band close
    ("aclose()") propagates to the source so "complete{id}" / disconnect cancels
    promptly.

    The spec's "middleware" manager (the connection's configured
    "DJANGO_GRAPHEX['MIDDLEWARE']" chain) wraps every per-event resolver, so a
    subscription is gated by the same middleware an HTTP operation is.

    Args:
        source: The STARTED "ChannelLayerSource" from "native_subscribe".
        spec: The subscription spec carrying the "schema", "document" and
            "middleware" the per-event "execute" runs with.
        context: The transport-neutral "context_value" passed to "execute"
            (".user" + scope; design section 7). Defaults to "None".

    Returns:
        A "DeliveryIterator" async-iterable yielding one "ExecutionResult" per
        delivered (filtered, verified) event.
    """

    def _execute_over_flat_dict(flat: dict[str, Any]) -> "ExecutionResult":
        # The flat already-serialized snake dict IS the root_value; the event
        # type's snake-closure resolvers project it in memory. execute() returns
        # an ExecutionResult synchronously and does NOT mutate the source, so one
        # dict can feed N executes (serialize-once invariant).
        return execute(
            spec.schema,
            spec.document,
            root_value=flat,
            context_value=context,
            middleware=spec.middleware,
        )

    return make_delivery_iterator(source, _execute_over_flat_dict)
