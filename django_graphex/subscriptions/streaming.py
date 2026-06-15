"""Native subscription engine glue: ``SubscriptionSpec`` + ``drive_subscription``.

This module is the WU5 integration core of the serialize-once streaming engine
(design §2, §3, §4, §6, §7). It composes the three lower layers built earlier:

  * :class:`~django_graphex.subscriptions.source.ChannelLayerSource` (WU4) — the
    Channels group consumer that yields already-serialized flat snake dicts.
  * :class:`~django_graphex.subscriptions.delivery.DeliveryIterator` (WU2) — the
    COND-A lightweight delivery wrapper (NOT graphql-core's stock mapping
    delivery class; out-of-band close).
  * :func:`~django_graphex.subscriptions.resolvers.make_snake_resolver` (WU1) —
    the per-field snake-closure projection attached to the event type.

Two public entry points:

``native_subscribe`` (the subscribe entry)
    Runs the KEPT subscription hooks BEFORE the source is created, so a DENY in
    ``authorize`` short-circuits BEFORE any ``group_add`` (design §3):
    ``authorize`` -> ``validate_filters`` -> ``scope`` -> ``filters = client ∪
    scope`` (scope WINS on conflict) -> compute index + group names (the action
    arg picks the join set: ``('create','update','delete')`` for ``all_actions``
    else ``(action,)`` — never hardcodes three, the #1420 guard) -> construct
    ``ChannelLayerSource`` -> ``start()`` (join groups) -> wire ``source.db_verify``
    to the spec's single-row ``.exists()`` narrowing AFTER setting
    ``source.filters`` (the WU4 contract: closes the conservative-drop gap so
    ``__lookup`` subscriptions actually deliver verified events). Returns the
    STARTED source; the caller wraps it via :func:`drive_subscription`.

``drive_subscription`` (the delivery path)
    Composes the source through the WU2 ``DeliveryIterator`` whose per-value map
    is a graphql-core ``execute(schema, document, root_value=<flat dict>, ...)``
    call. ``execute`` returns an ``ExecutionResult`` SYNCHRONOUSLY over the flat
    dict (the source value IS the root; the snake-closure resolvers project it —
    NO DB, NO re-serialize, NO model instantiation). The delivery path is the WU2
    lightweight wrapper, NOT graphql-core's stock mapping delivery class (COND-A).
    Out-of-band close (``aclose()``) propagates to the source so ``complete{id}``
    / disconnect cancels promptly.

Transport-neutral context (design §7): the hooks and ``execute`` receive a
``context`` exposing ``.user`` and a ``scope`` mapping — satisfied by BOTH the
SSE ``HttpRequest`` and the WS Channels ``scope``. Nothing here assumes
``HttpRequest``.

This module imports neither graphene nor channels at module scope (channels is
injected as a constructed layer by the caller); ``graphql-core`` is the only
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

__all__ = ["SubscriptionSpec", "drive_subscription", "native_subscribe"]


# ---------------------------------------------------------------------------
# Default hooks — used when a spec leaves a hook unset (allow-all / no-scope).
# ---------------------------------------------------------------------------


def _default_authorize(context: Any, **kwargs: Any) -> None:
    """Default ``authorize``: allow every subscribe (no-op)."""
    return None


def _default_scope(context: Any, **kwargs: Any) -> "dict[str, Any] | None":
    """Default ``scope``: no server-forced filters."""
    return None


def _default_instance_index(instance: Any) -> "dict[str, Any] | None":
    """Default ``instance_index``: no value-scoped routing."""
    return None


@dataclass
class SubscriptionSpec:
    """The native-path subscription options carrier (design §2, C-A).

    A PLAIN ``@dataclass`` — NOT a ``BaseModel``/``ModelMetaclass`` re-home
    (#1452). It replaces graphene's ``SubscriptionOptions`` only as the
    native-path options carrier; the public ``Subscription`` base stays an
    ``ObjectType`` until Phase 7. ``native_subscribe`` and ``drive_subscription``
    read everything they need from a spec instance, so the engine is decoupled
    from the graphene-based ``Subscription`` class.

    Attributes:
        model_label:
            The ``app_label.modelname`` identifier used to build group names.
        stream:
            The stream name this subscription serves.
        schema:
            The graphql-core ``GraphQLSchema`` the per-event ``execute`` runs
            against (the native subscription schema).
        document:
            The parsed subscription ``DocumentNode`` (the client's selection set)
            executed PER delivered event over the flat source dict.
        declared_output_fields:
            The set of declared serialized output field names; client filter keys
            must root on one of these (filter-key validation, design §3 / cap 4).
        index_fields:
            Optional model field names used to route notifications to value-scoped
            groups (the indexed-groups optimization). When every index field is
            present in the merged scope, the source joins a value-scoped group.
        authorize:
            ``authorize(context, **kwargs) -> None`` — runs BEFORE the source is
            created; raise to DENY (short-circuits before any ``group_add``).
        scope:
            ``scope(context, **kwargs) -> Mapping | None`` — server-forced filters
            merged with client filters at SERVER precedence (scope wins).
        group_name:
            ``group_name(action, *, id=None, index=None) -> str`` — builds the
            Channels group name (matches the producer's ``_group_name`` by
            construction). Reuses the kept ``Subscription._group_name``.
        instance_index:
            ``instance_index(instance) -> Mapping | None`` — builds the index
            mapping from a changed instance (kept ``Subscription._instance_index``).
            Carried for the producer side; unused in the subscribe path.
        db_exists:
            Optional ``db_exists(remaining, event, *, obj_id=None) -> bool`` — the
            single-row ``.exists()`` narrowing wired into ``source.db_verify`` for
            non-empty ``__lookup`` "remaining" filters. ``None`` keeps the source's
            conservative drop (no unverified ``__lookup`` event is ever yielded).
        event_type_name:
            Optional name of the subscription event output type (diagnostics).
        serialize_data:
            Optional full/id-only payload mode flag (carried for the producer side).
        model:
            Optional Django model object (carried for the producer side).
        pydantic_model:
            Optional user Pydantic base (carried for the producer side).
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
    serialize_data: bool | None = None
    model: Any = None
    pydantic_model: Any = None


# ---------------------------------------------------------------------------
# Filter-key validation (design §3 / capability 4): a client filter key must
# root on a declared output field, so an attacker cannot probe arbitrary ORM
# fields. Server-forced scope filters are NOT subject to this check.
# ---------------------------------------------------------------------------


def _validate_client_filters(
    client_filters: "Mapping[str, Any]",
    declared: set[str],
) -> None:
    """Raise when any *client_filters* key roots on an undeclared output field.

    A key may be a bare field name or a field followed by a Django ORM lookup
    suffix (``username__icontains``). The root (everything before the first
    ``__``) must be a declared output field.

    Args:
        client_filters: The raw filters supplied by the subscriber.
        declared: The set of declared serialized output field names.

    Raises:
        ValueError: When a filter key roots on an undeclared field. (A plain
            exception keeps this module free of any graphene/graphql error
            coupling; the transport layer translates it into an error frame.)
    """
    if not client_filters:
        return
    for key in client_filters:
        root = key.split("__")[0]
        if root not in declared:
            raise ValueError(
                "Subscription filter key '{}' is not a declared output field. "
                "Allowed fields: {}.".format(key, ", ".join(sorted(declared)))
            )


async def _maybe_await(value: Any) -> Any:
    """Await *value* when it is awaitable, else return it unchanged."""
    return await value if isawaitable(value) else value


def _actions_for(action: str) -> tuple[str, ...]:
    """Map a requested action to the join set (the #1420 guard).

    ``all_actions`` -> ``('create','update','delete')``; any other action ->
    ``(action,)``. NEVER hardcodes all three for a single-action subscribe.
    """
    if action == "all_actions":
        return ("create", "update", "delete")
    return (action,)


def _build_db_verify(
    spec: "SubscriptionSpec",
    obj_id: Any,
) -> "Callable[[dict[str, Any], dict[str, Any]], Any] | None":
    """Wrap the spec's ``db_exists`` narrowing into the source ``db_verify`` hook.

    The WU4 contract: ``source.db_verify`` is ``async (remaining, event) -> bool``.
    When the spec carries a ``db_exists`` callable (the single-row ``.exists()``
    narrowing for non-empty ``__lookup`` "remaining" filters), wrap it so the
    source can ``await`` it; otherwise return ``None`` so the source keeps its
    conservative drop (never yields an unverified ``__lookup`` event).

    Args:
        spec: The subscription spec carrying the optional ``db_exists`` narrowing.
        obj_id: The optional per-object id, forwarded to the narrowing.

    Returns:
        An async ``db_verify`` hook, or ``None`` when no narrowing is configured.
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

    The hooks run BEFORE any group is joined (design §3), so a DENY in
    ``authorize`` short-circuits BEFORE any ``group_add``:

      1. ``authorize(context, **kwargs)`` — raise to DENY (NO source, NO join).
      2. ``_validate_client_filters`` — reject filter keys on undeclared fields.
      3. ``scope(context, **kwargs)`` — server-forced filters.
      4. ``filters = {**client, **scope}`` — scope WINS on conflict.
      5. compute the index (SCOPE-ONLY parity with the kept ``_subscribe`` hook:
         a value-scoped group is joined only when the SERVER scope supplies every
         index field — never from a client value) and the group names; the
         *action* arg picks the join set (``all_actions`` -> three groups, else
         the single action — #1420 guard).
      6. construct ``ChannelLayerSource(groups, channel_layer, filters=filters)``
         and ``start()`` it (the ONLY place ``group_add`` happens).
      7. wire ``source.db_verify`` to the spec's single-row ``.exists()``
         narrowing AFTER setting ``source.filters`` (the WU4 contract).

    The hooks may be sync or async; awaitable returns are awaited.

    Args:
        spec: The native-path subscription spec.
        channel_layer: The constructed Channels channel layer (injected — this
            module never imports channels).
        action: The requested action (``create``/``update``/``delete``/
            ``all_actions``); picks the join set.
        obj_id: An optional per-object primary key for a per-object group.
        filters: The raw client-supplied filters (Django ORM lookup -> value).
        context: The transport-neutral context (``.user`` + ``scope`` mapping);
            passed to the hooks. NOT assumed to be an ``HttpRequest`` (design §7).

    Returns:
        The STARTED :class:`ChannelLayerSource` (groups joined, ``db_verify``
        wired). The caller wraps it via :func:`drive_subscription`.

    Raises:
        Exception: Whatever ``authorize`` raises to DENY, or ``ValueError`` from
            filter-key validation — both BEFORE any ``group_add``.
    """
    client_filters: dict[str, Any] = dict(filters) if filters else {}

    # (1) Authorize — DENY short-circuits BEFORE the source is created.
    await _maybe_await(spec.authorize(context, action=action, id=obj_id, filters=filters))

    # (2) Validate client filter keys against declared output fields.
    _validate_client_filters(client_filters, spec.declared_output_fields)

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
    groups = [
        group_name(act, id=obj_id, index=index) for act in _actions_for(action)
    ]

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
    """Compose *source* through the COND-A delivery iterator with per-event execute.

    Each flat source dict is mapped by a graphql-core ``execute(schema, document,
    root_value=<flat dict>, context_value=context, ...)`` call that returns an
    ``ExecutionResult`` SYNCHRONOUSLY (the source dict IS the root; the
    snake-closure resolvers project it — NO DB, NO re-serialize). The result of
    each map is the yielded value.

    The delivery path is the WU2 :class:`DeliveryIterator` (NOT graphql-core's
    stock mapping delivery class — the COND-A structural invariant). Out-of-band
    close (``aclose()``) propagates to the source so ``complete{id}`` /
    disconnect cancels promptly.

    Args:
        source: The STARTED :class:`ChannelLayerSource` from
            :func:`native_subscribe`.
        spec: The subscription spec carrying the ``schema`` and ``document`` the
            per-event ``execute`` runs.
        context: The transport-neutral ``context_value`` passed to ``execute``
            (``.user`` + scope; design §7). Defaults to ``None``.

    Returns:
        A :class:`DeliveryIterator` async-iterable yielding one ``ExecutionResult``
        per delivered (filtered, verified) event.
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
        )

    return make_delivery_iterator(source, _execute_over_flat_dict)
