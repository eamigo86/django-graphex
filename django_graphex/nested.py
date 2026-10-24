"""Shared nested-object create/update handling for serializer-backed types.

"DjangoModelType" and "DjangoModelMutation" accept
"Meta.nested_fields = {field_name: Model}" to write related objects
in the same create/update call. This mixin centralizes that logic (the two hosts
previously carried duplicate, buggy copies) and makes it:

* atomic when routing stays on the boundary alias -- nested creates using the
  shipped Pydantic backend route a populated unsaved parent once, then pin
  native parent and child saves to that alias. A divergent M2M through route
  is rejected before writes or, if it depends on a generated ID, before
  linking with local writes rolled back. Updates use the existing instance's
  database alias. Custom backend overrides keep their prior create contract,
  and cross-database writes are not coordinated,
* relation-aware -- forward FK/O2O children are saved before the parent and
  their pk injected; reverse FK/O2O and M2M children are saved after the parent
  and linked to it, all decided by Django's relation introspection,
* upsert-capable -- a child payload carrying its pk updates that row (partial),
  otherwise a new row is created (the nested input only exposes the pk on the
  parent's update, so creates stay create-only),
* link-not-rewrite -- on a relation whose rows the parent does not own (forward
  FK/O2O and M2M) a pk the parent is not already attached to only LINKS that
  row; its other fields are ignored, so no client can edit an arbitrary row of
  the related table by naming its pk. FK/M2M ID links additionally check the
  registered destination output type's request-scoped get_queryset hook,
* safe by default -- additive M2M/reverse semantics (existing links are never
  removed) and empty "[]" / "{}" payloads are a no-op.

One level of nesting is supported (parent -> direct children).
"""

from __future__ import annotations

import enum
from contextlib import nullcontext
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, router, transaction
from django.db.models import ForeignKey, ManyToManyField, Subquery
from graphql import GraphQLError

from .backends import backend_for_nested
from .errors import ErrorType
from .permissions import supported_kwargs
from .utils import (
    apply_object_type_get_queryset,
    get_Object_or_None,
    not_found_error,
    present_values,
    scope_to_output_type,
)

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo

__all__ = (
    "NestedFieldsMixin",
    "host_registries",
    "hosts_for_nested",
    "hosts_serving",
    "record_nested_input",
    "register_nested_host",
)


#: The only operations a nested input is ever built for. A parent's nested
#: surface is a create or an update; "delete" / "list" / "retrieve" never mint
#: one, so a host's stance on them says nothing about it.
_NESTED_OPS = frozenset({"create", "update"})


#: Default for "_persist_child(instance=...)". "None" already means "the payload
#: names no row I could find", so it cannot double as "I did not look" -- the
#: two must stay distinguishable for the caller to hand its own lookup over.
_UNRESOLVED: Any = object()


def _redact_generated_integrity_error(
    resolver: Callable[..., Any],
) -> Callable[..., Any]:
    """Hide unclassified database details at a generated mutation field.

    The resolver has already left any nested or backend atomic block when its
    exception reaches this adapter, so replacing the exception does not prevent
    rollback. Backend-attributed validation errors remain ordinary return values.

    Args:
        resolver: Adapted generated create, update, or delete resolver.

    Returns:
        A resolver with the same successful result and a generic integrity error.
    """

    @wraps(resolver)
    def guarded(root: Any, info: Any, **kwargs: Any) -> Any:
        """Call the generated resolver without exposing SQL diagnostics.

        Args:
            root: GraphQL root value.
            info: GraphQL resolver metadata.
            **kwargs: Generated mutation arguments.

        Returns:
            The original resolver result.

        Raises:
            GraphQLError: If an unclassified database integrity failure escapes.
        """
        try:
            return resolver(root, info, **kwargs)
        except IntegrityError:
            raise GraphQLError(
                "A database constraint prevented this operation."
            ) from None

    return guarded


def host_registries(registry: Any) -> tuple[Any, ...]:
    """Return the registries a parent's child hosts may legitimately live in.

    A parent's OWN registry plus the global one, because "Meta.registry" is an
    option on "DjangoModelMutation" alone: "DjangoModelType" -- the only host
    class that carries "permission_classes" -- always registers globally and
    cannot be bound elsewhere. Reading the parent's registry alone therefore
    left a parent declared with "Meta.registry" finding NO hosts for its
    children at all, and the runtime permission gate went quiet: front door
    pruned, back door open, which is the exact shape this whole path exists to
    close. A host that never named a registry lives in the global one and is
    still that model's host, wherever the parent lives.

    The isolation that survives is the one that was always the point: a host
    bound to a NON-global registry describes that schema's surface only, and
    still cannot reach any other registry's parents.

    Args:
        registry: The registry the surface is being built or written for.

    Returns:
        The registries to read hosts from, nearest first.
    """
    from .registry import get_global_registry

    global_registry = get_global_registry()
    if registry is global_registry:
        return (registry,)
    return (registry, global_registry)


def record_nested_input(registry: Any, child_model: Any, parent_model: Any) -> None:
    """Record that a child's nested input has been built for a parent.

    Recorded on every registry the build read hosts from (see
    "host_registries"), so the late-host refusal keeps working in both
    directions: a globally-declared host arriving after a LOCAL registry's
    parent froze its surface can no longer reach it either, and must say so.

    Args:
        registry: The registry that owns the memo the input was stored in.
        child_model: The nested child's Django model.
        parent_model: The nesting parent's Django model.
    """
    for target in host_registries(registry):
        parents = target.nested_materialized.setdefault(child_model, [])
        if parent_model not in parents:
            parents.append(parent_model)


def register_nested_host(model: Any, host: Any, registry: Any) -> None:
    """Record a declared host class under the model it is bound to.

    Args:
        model: The host's "Meta.model".
        host: The "DjangoModelType" / "DjangoModelMutation" subclass.
        registry: The host's own registry: it owns the host list this is
            appended to, and its materialization record decides whether the
            declaration arrived too late.

    Raises:
        ImproperlyConfigured: If a nested input this host can reach was already
            built and this host declares something that input can no longer
            honour.
    """
    hosts = registry.nested_hosts.setdefault(model, [])
    # A host bound to a SECOND registry through "Meta.registry" reaches only
    # that registry's parents, and it has frozen nothing here, so its own
    # record is the one that decides. The global record covers every parent
    # (see "record_nested_input"), which is why a globally-declared host -- the
    # only kind a "DjangoModelType" can be -- is still refused for a LOCAL
    # registry's parent it arrived too late for.
    parents = registry.nested_materialized.get(model)
    if (
        parents
        and _narrows_nested_input(host)
        # A declaration that repeats one already contributing cannot change the
        # built surface: all three merges (excludes, "only_fields" and labels)
        # are unions, and a union is idempotent. Refusing a no-op buys nothing.
        and _narrowing_signature(host)
        not in {
            _narrowing_signature(other) for other in hosts_for_nested(registry, model)
        }
    ):
        # LOUD, because the alternative is invisible: graphql-core resolves an
        # input object's field map once and caches it forever, so a projection
        # declared after that point never reaches the nested surface -- and no
        # schema rebuild, registry swap or memo clear brings it back. Silently
        # ignoring it leaves the WIDER surface baked in for the process
        # lifetime, which is the order dependence this whole path exists to
        # remove. Only the frozen half is fatal: "permission_classes" are read
        # from this registry at write time, so a late host still gates writes.
        raise ImproperlyConfigured(
            "{} is declared for {} after that model's nested input was already "
            "built for {}. graphql-core caches the parent input's field map, so "
            'this host\'s "only_fields" / "exclude_fields" / "required_perms" '
            "can never reach the nested surface. Declare every host for a model "
            "before the first schema build.".format(
                host.__name__,
                model.__name__,
                ", ".join(parent.__name__ for parent in parents),
            )
        )
    hosts.append(host)


def _narrows_nested_input(host: Any) -> bool:
    """Return whether a host declares anything the nested INPUT bakes in.

    Args:
        host: The "DjangoModelType" / "DjangoModelMutation" subclass.

    Returns:
        True when the host declares a projection or a non-empty
        "required_perms" -- the only things a built nested input can no longer
        pick up. An EMPTY "required_perms" is not one of them: the nested stamp
        UNIONS the overrides onto the composite default, so an empty one
        contributes nothing whenever it is declared.
    """
    meta = host._meta
    return bool(
        getattr(meta, "only_fields", None)
        or getattr(meta, "exclude_fields", None)
        or getattr(host, "required_perms", None)
    )


def _narrowing_signature(host: Any) -> tuple[Any, ...]:
    """Return everything about a host the nested input bakes in, comparably.

    Args:
        host: The "DjangoModelType" / "DjangoModelMutation" subclass.

    Returns:
        The projection axes, the label override and the NESTED-RELEVANT
        operations the host serves, normalized to sets so two hosts that
        contribute the same thing compare equal. The operations are part of it
        because the allowance axis and the label axis are both read per
        operation: two hosts declaring the same "only_fields" for DIFFERENT
        operations contribute to different surfaces, so the later one is not a
        no-op. Only the two nested verbs count -- a "DjangoModelType" also
        serves "list" / "retrieve" / "delete", none of which a nested input is
        ever built for, so counting them would make it differ from an
        equivalent "DjangoModelMutation" over nothing.
    """
    meta = host._meta
    return (
        frozenset(getattr(meta, "only_fields", None) or ()),
        frozenset(getattr(meta, "exclude_fields", None) or ()),
        frozenset(getattr(host, "required_perms", None) or ()),
        frozenset(meta.model_operations) & _NESTED_OPS,
    )


def hosts_for_nested(registry: Any, model: Any) -> tuple[Any, ...]:
    """Return the declared hosts for a child model, in declaration order.

    Args:
        registry: The registry whose surface is being built or written.
        model: The child's Django model class.

    Returns:
        The hosts declared for the model in that registry AND in the global one
        (see "host_registries"), nearest first, or an empty tuple when there
        are none. With no host, existing nullable reverse-FK orphans cannot be
        adopted by ID; other child creation and owned-child paths remain.
        No de-duplication is needed: "host_registries" never repeats
        a registry, and a host is appended to exactly one of them.
    """
    return tuple(
        host
        for source in host_registries(registry)
        for host in source.nested_hosts.get(model, ())
    )


def hosts_serving(registry: Any, child_model: Any, op: str) -> tuple[Any, ...]:
    """Return the child's declared hosts that actually serve an operation.

    A host has no say over an operation it does not generate. Collecting every
    host regardless made a create-only and an update-only mutation for one child
    -- an ordinary split-surface configuration -- poison each other: the nested
    CREATE payload lost the fields only the create host exposes, while the
    child's own "create" kept accepting them.

    Args:
        registry: The registry whose surface is being built or written.
        child_model: The child's Django model class.
        op: The operation the nested input is being built for.

    Returns:
        The hosts that serve "op", in declaration order. Both host classes take
        "Meta.model_operations" and both DEFAULT to every operation they can
        generate, so a host that declares nothing serves this one. That default
        is what the no-allowance branch of the projection merge rests on: it can
        only be reached by a project explicitly saying a host is not a write
        host.
    """
    return tuple(
        host
        for host in hosts_for_nested(registry, child_model)
        if op in host._meta.model_operations
    )


class _NestedError(Exception):
    """Carry a list of "ErrorType" entries out of the atomic block.

    Raised internally by the nested-save helpers to unwind the transaction and
    is always caught by "NestedFieldsMixin.save_with_nested"; it never escapes
    the mixin.
    """

    def __init__(self, errors: list[ErrorType]) -> None:
        """Store the formatted error list.

        Args:
            errors: The "ErrorType" entries describing the failure.
        """
        self.errors = errors
        super().__init__("nested validation failed")


class NestedFieldsMixin:
    """Atomic, relation-aware nested create/update for model types.

    Mixed into the model-backed mutation and type hosts to write a parent and
    its declared "Meta.nested_fields" children in a single create/update call.
    Forward relations are written before the parent, reverse/M2M relations
    after, and the whole operation is wrapped in a transaction so a partial
    failure leaves no orphan rows.
    """

    @classmethod
    def save_with_nested(
        cls,
        root: Any,
        info: GraphQLResolveInfo,
        data: dict[str, Any],
        instance: Model | None = None,
        serializer_kwargs: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Validate and persist nested writes within a selected alias boundary.

        Forward relations (the parent holds the key) are written first and their
        pk injected into "data"; the parent is then saved via the backend (so
        its validation/error handling is used); reverse and M2M children
        are written last and linked to the saved parent. The transaction uses
        a selected boundary alias, so a failure rolls back writes on that
        alias. A nested create using the shipped Pydantic backend prepares one
        populated unsaved parent and routes with that instance before the
        first write; its native child saves use the same alias. Divergent M2M
        through routes are checked before writes and again before linking
        after an ID may have been generated. Custom backend overrides retain
        their existing call contract and are not pinned by this path. An
        update uses the existing instance's database alias.
        Transactions do not coordinate writes across different databases.

        Subscription broadcasts and commit-time delivery: model saves inside
        the "transaction.atomic()" block trigger "post_save" / "post_delete"
        signals, which are connected to "SubscriptionBinding" receivers.
        Those receivers defer their broadcast via "transaction.on_commit",
        so subscribers only receive notifications for rows that were actually
        persisted. A subsequent failure within the same atomic block rolls
        back writes and suppresses pending callbacks on that alias. Parent
        and child writes must use the boundary alias for this protection.

        A child is validated by the backend of a host that declared custom
        validation for its model when one exists (see "backend_for_nested"), so
        a nested write applies the same rules the child's own mutation does.

        A forward payload carrying a pk the parent is not already linked to
        LINKS that row rather than writing it; the M2M branch applies the same
        rule (see "_attach_children"). Both relations point at rows the parent
        does not own, so without the rule a client could rewrite any row of the
        related table by naming its pk.

        Every VALIDATION failure is raised as a private "_NestedError" and caught
        here, so a bad payload always comes back as a result tuple. A child's
        permission DENIAL is different on purpose: "_persist_child" calls the
        child host's "authorize", which raises "GraphQLError" and is left to
        propagate, so the caller sees the byte-identical denial the child's own
        mutation returns instead of a field-level error the parent invented.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            data: Mutable input data; nested entries are popped from it.
            instance: Existing instance for an update, or None for a create.
            serializer_kwargs: Reserved (unused by the native backend).

        Returns:
            A tuple of a success flag and either the saved object or a list of
            "ErrorType" entries.

        Raises:
            GraphQLError: If a child host's "authorize" denies the nested write
                (PERMISSION_DENIED / 403). The atomic block rolls back writes
                on its selected alias on the way out.
            TypeError: If a destination row-scope hook returns an invalid
                queryset for a generated FK or M2M ID link.
        """
        nested = cls._meta.nested_fields
        nested = nested if isinstance(nested, dict) else {}

        # Savepoint-only-when-needed invariant: the outer ``transaction.atomic()``
        # exists solely to make a MULTI-object write (parent + nested children)
        # all-or-nothing. When this call writes ONLY the parent, no outer
        # boundary is required — ``PydanticBackend.save_object`` already opens
        # its own recovery boundary when it needs one (see backend.py), so an
        # extra SAVEPOINT/RELEASE here would be pure overhead.
        #
        # Nested work exists when at least one declared nested field is present
        # in ``data`` with a non-no-op payload (``None`` / ``[]`` / ``{}`` are
        # no-ops that leave the relation untouched — see the loop below). Only
        # then do we open the atomic block.
        #
        # on_commit note: subscription broadcasts defer via
        # ``transaction.on_commit``. With no outer atomic AND an autocommit
        # (or backend-savepoint-free) parent save, the callback fires at the
        # parent's own commit boundary — exactly once — preserving delivery
        # semantics in both modes.
        has_nested_work = any(
            field in data and data[field] not in (None, [], {}) for field in nested
        )
        # Only the shipped backend can accept an unsaved instance without
        # changing the public SerializerBackend contract. Build it once so
        # defaults and instance-dependent routers see the same create object.
        from .core.backend import PydanticBackend

        native_create = (
            has_nested_work
            and instance is None
            and type(cls._meta.backend) is PydanticBackend
        )
        prepared = cls._meta.model() if native_create else None
        if prepared is not None:
            scalar_data = cls._unwrap_enums(dict(data))
            for model_field in cls._meta.model._meta.concrete_fields:
                if model_field.name in scalar_data and model_field.name not in nested:
                    setattr(
                        prepared,
                        model_field.attname,
                        scalar_data[model_field.name],
                    )
        routed_instance = prepared if prepared is not None else instance
        using = (
            routed_instance._state.db if routed_instance is not None else None
        ) or router.db_for_write(cls._meta.model, instance=routed_instance)
        if prepared is not None:
            prepared._state.db = using
        boundary = transaction.atomic(using=using) if has_nested_work else nullcontext()

        try:
            if native_create and prepared is not None:
                for field in nested:
                    if field not in data or data[field] in (None, [], {}):
                        continue
                    kind, relation = cls._relation_kind(field)
                    if kind == "m2m":
                        cls._check_native_m2m_through_route(
                            field, relation, prepared, using
                        )
            with boundary:
                route_kwargs = {"using": using} if native_create else {}
                cls._validate_destination_links(
                    data, instance, nested, info, **route_kwargs
                )
                deferred: list[tuple[str, Any, str, Any, Any]] = []
                for field, child_model in nested.items():
                    if field not in data:
                        continue
                    sub_data = data.pop(field)
                    if sub_data in (None, [], {}):
                        continue  # empty payload -> no-op (relation untouched)

                    kind, relation = cls._relation_kind(field)
                    if kind == "forward":
                        if isinstance(sub_data, list):
                            if len(sub_data) > 1:
                                raise _NestedError(
                                    [
                                        ErrorType(
                                            field=field,
                                            messages=[
                                                f"{field!r} is a to-one relation; "
                                                "provide a single object, not a list."
                                            ],
                                        )
                                    ]
                                )
                            item = sub_data[0]
                        else:
                            item = sub_data
                        # Forward link rule: a payload carrying a pk updates that
                        # row ONLY when the parent is already linked to it;
                        # any other pk is a LINK -- the row is attached and its
                        # remaining fields are ignored.  A forward target is not
                        # owned by the parent, so the reverse ownership guard
                        # cannot apply, and without this rule a client could
                        # rewrite ANY row of the related table by naming its pk.
                        #
                        # This FK link has already passed the request's
                        # destination output scope before the first write;
                        # child WRITE permissions still do not run for a link.
                        item_pk = cls._child_pk(child_model, item)
                        current_pk = (
                            getattr(instance, relation.attname, None)
                            if instance is not None
                            else None
                        )
                        if item_pk is not None and str(item_pk) != str(current_pk):
                            # The child's update hosts scope a link exactly as
                            # they scope a reverse child, and a hidden id answers
                            # like a missing one (the backend's FK check).
                            if hosts_serving(cls._meta.registry, child_model, "update"):
                                try:
                                    cls._reject_hidden_row(
                                        field,
                                        child_model,
                                        item_pk,
                                        info,
                                        output_scope=False,
                                        **route_kwargs,
                                    )
                                except _NestedError:
                                    raise _NestedError(
                                        [
                                            ErrorType(
                                                field=field,
                                                messages=[
                                                    f'Invalid pk "{item_pk}" - '
                                                    "object does not exist."
                                                ],
                                            )
                                        ]
                                    ) from None
                            data[field] = item_pk  # link only, no child write
                            continue
                        # An id-only re-send of the current target writes
                        # nothing: no save, no signals, so the output scope
                        # applies only when the payload carries field data.
                        writes = set(item) - {child_model._meta.pk.name, "id"}
                        if item_pk is not None and not writes:
                            data[field] = current_pk
                            continue
                        child = cls._persist_child(
                            field,
                            child_model,
                            item,
                            info,
                            **route_kwargs,
                        )
                        data[field] = child.pk
                    else:
                        # Reverse/M2M children need the parent pk: defer them.
                        #
                        # "kind" cannot be None here, so there is no
                        # pass-through branch to fall into: every
                        # "Meta.nested_fields" KEY is checked against the
                        # model's relations at class definition
                        # ("types._check_nested_field_keys", run by both hosts
                        # that own a "_meta.nested_fields"), and it accepts
                        # exactly the four relation flags "_relation_kind"
                        # classifies. A key naming no relation never reaches a
                        # write -- the class raises ImproperlyConfigured.
                        deferred.append((field, child_model, kind, relation, sub_data))

                ok, obj = cls._meta.backend.save_object(
                    cls,
                    root,
                    info,
                    data,
                    instance=prepared if prepared is not None else instance,
                    partial=instance is not None,
                    serializer_kwargs=serializer_kwargs,
                )
                if not ok:
                    raise _NestedError(obj if isinstance(obj, list) else [obj])

                for field, child_model, kind, relation, sub_data in deferred:
                    cls._attach_children(
                        obj,
                        field,
                        child_model,
                        kind,
                        relation,
                        sub_data,
                        info,
                        **route_kwargs,
                    )

                return True, obj
        except _NestedError as error:
            return False, error.errors

    @classmethod
    def _validate_destination_links(
        cls,
        data: dict[str, Any],
        instance: Model | None,
        nested: dict[str, Any],
        info: GraphQLResolveInfo,
        using: str | None = None,
    ) -> None:
        """Reject ID links outside the request's destination output scope.

        Only a registered public output type with an overridden row hook adds
        a lookup. The ordinary unscoped path still delegates existence checks
        to the backend, without a new query on successful writes. A nested
        payload with extra fields is still a link when the existing writer
        ignores those fields; an actual child create/update stays outside this
        row-scope guard.

        Args:
            data: The mutation input before nested fields are removed.
            instance: The parent being updated, or None for a create.
            nested: Declared nested relation fields.
            info: Request resolve info carrying the schema's Registry pair.
            using: Already-selected transaction alias for a native nested create.

        Raises:
            _NestedError: If a requested link is hidden or nonexistent.
            TypeError: If a destination hook returns a non-queryset value or a
                queryset for a different concrete model.
        """
        from .types import DjangoObjectType

        schema = getattr(info, "schema", None)
        extensions = getattr(schema, "extensions", None) or {}
        pair = extensions.get("gdx_registry")
        if pair is not None:
            registry = pair.graphene
        else:
            registry = cls._meta.registry
        alias = (
            using
            or (instance._state.db if instance is not None else None)
            or router.db_for_write(cls._meta.model, instance=instance)
        )

        for relation in cls._meta.model._meta.get_fields():
            field = relation.name
            if field not in data or data[field] in (None, [], {}):
                continue
            is_fk = isinstance(relation, ForeignKey)
            is_m2m = isinstance(relation, ManyToManyField)
            if not (is_fk or is_m2m):
                continue
            target = relation.related_model
            output_type = registry.get_type_for_model(target) if registry else None
            if output_type is None or not issubclass(output_type, DjangoObjectType):
                continue
            hook = output_type.get_queryset
            if (
                getattr(hook, "__func__", hook)
                is DjangoObjectType.get_queryset.__func__
            ):
                continue

            if field in nested:
                values = data[field] if isinstance(data[field], list) else [data[field]]
                pairs = [(item, cls._child_pk(target, item)) for item in values]
                pairs = [(item, pk) for item, pk in pairs if pk is not None]
                lookup_field = target._meta.pk
                if is_fk and instance is not None:
                    current = str(getattr(instance, relation.attname, None))
                    pairs = [(item, pk) for item, pk in pairs if str(pk) != current]
                if is_m2m and pairs:
                    candidates = [pk for _, pk in pairs]
                    linked = (
                        present_values(
                            getattr(instance, field).all(), lookup_field, candidates
                        )
                        if instance is not None
                        else set()
                    )
                    # An already-linked row is an actual child update; any other
                    # id, missing included, must be visible (a missing id never
                    # creates, so it answers like a hidden one).
                    pairs = [(item, pk) for item, pk in pairs if pk not in linked]
                ids = [pk for _, pk in pairs]
            elif is_fk and not hasattr(data[field], "keys"):
                ids = [data[field]]
                lookup_field = relation.target_field
            elif is_m2m and isinstance(data[field], (list, tuple)):
                ids = [value for value in data[field] if not hasattr(value, "keys")]
                lookup_field = target._meta.pk
            else:
                continue

            if not ids:
                continue
            queryset = target._default_manager.db_manager(alias).all()
            scoped = apply_object_type_get_queryset(queryset, output_type, info)
            if scoped.model._meta.concrete_model is not target._meta.concrete_model:
                raise TypeError(
                    f"{output_type.__name__}.get_queryset returned a queryset "
                    f"for {scoped.model.__name__}, expected {target.__name__}."
                )
            distinct = list(dict.fromkeys(ids))
            # Membership, not uniqueness: JOINs may duplicate a row and a
            # sliced scope cannot be filtered after its window is applied.
            visible = present_values(
                target._default_manager.db_manager(scoped.db).filter(
                    pk__in=Subquery(scoped.values("pk"))
                ),
                lookup_field,
                distinct,
            )
            for identifier in distinct:
                if identifier not in visible:
                    raise _NestedError(
                        [
                            ErrorType(
                                field=field,
                                messages=[
                                    f'Invalid pk "{identifier}" - object does not exist.'
                                ],
                            )
                        ]
                    )

    # -- relation introspection ------------------------------------------------

    @staticmethod
    def _check_native_m2m_through_route(
        field: str,
        relation: Any,
        parent: Model,
        using: str | None,
    ) -> None:
        """Keep a native nested CREATE's through writes on its chosen alias.

        Django's many-related manager independently routes its through model
        with the parent as a hint. Check the same choice before the first write
        and again immediately before linking, because a generated parent key
        may change an instance-dependent router's answer.

        Args:
            field: Nested M2M field or reverse accessor name.
            relation: Django M2M field or reverse relation.
            parent: Prepared or saved parent used as the router hint.
            using: Alias selected for the native CREATE transaction.

        Raises:
            _NestedError: If the through manager would use another database.
        """
        through = (
            relation.remote_field.through
            if isinstance(relation, ManyToManyField)
            else relation.through
        )
        if router.db_for_write(through, instance=parent) != using:
            raise _NestedError(
                [
                    ErrorType(
                        field=field,
                        messages=[
                            "The nested relation cannot be written with this "
                            "routing configuration."
                        ],
                    )
                ]
            )

    @classmethod
    def _relation_kind(cls, field_name: str) -> tuple[str | None, Any]:
        """Classify the model relation backing a nested field.

        Args:
            field_name: The model field/accessor name.

        Returns:
            A pair of a relation-kind tag ("forward", "reverse_one",
            "reverse_many", "m2m", or None) and the Django field/relation
            object.
        """
        try:
            relation = cls._meta.model._meta.get_field(field_name)
        except Exception:
            return None, None

        if relation.many_to_one:
            return "forward", relation
        if getattr(relation, "one_to_one", False):
            return ("forward" if relation.concrete else "reverse_one"), relation
        if relation.one_to_many:
            return "reverse_many", relation
        if relation.many_to_many:
            return "m2m", relation
        return None, relation

    @staticmethod
    def _child_pk(child_model: Any, item: Any) -> Any:
        """Read the primary key a nested child payload carries, if any.

        Explicit None checks are used throughout so a falsy-but-valid pk (0 or
        an empty string) counts as present. The model's own pk name is tried
        first and "id" second, because the generated input always exposes the
        key as "id" even when the model names it differently.

        Args:
            child_model: The Django model class for the child.
            item: The child payload; a non-mapping yields None.

        Returns:
            The primary key carried by the payload, or None when absent.
        """
        if not hasattr(item, "get"):
            return None
        pk = item.get(child_model._meta.pk.name)
        if pk is None:
            pk = item.get("id")
        return pk

    # -- child persistence -----------------------------------------------------

    @classmethod
    def _attach_children(
        cls,
        parent: Model,
        field: str,
        child_model: Any,
        kind: str,
        relation: Any,
        sub_data: Any,
        info: GraphQLResolveInfo,
        using: str | None = None,
    ) -> None:
        """Persist and link reverse/M2M children after the parent is saved.

        Args:
            parent: The saved parent instance.
            field: The nested field/accessor name.
            child_model: The Django model class for the children.
            kind: The relation kind ("reverse_one", "reverse_many", "m2m").
            relation: The Django relation object.
            sub_data: The nested payload (dict or list).
            info: GraphQL resolve info for the current request.
            using: Selected alias for native nested child lookups and writes.

        Raises:
            _NestedError: If a child is hidden by a write host, belongs to
                another parent, lacks an update-serving host for orphan adoption,
                has invalid reverse-one cardinality, or fails child validation.
            GraphQLError: If child permission checks deny the write.
        """
        if kind in ("reverse_one", "reverse_many"):
            fk_name = relation.field.name  # FK on the child pointing to parent
            items = sub_data if isinstance(sub_data, list) else [sub_data]

            # Reverse-O2O (kind == "reverse_one") only ever allows a single
            # child.  A list of more than one would hit a UNIQUE constraint at
            # the DB level; reject it cleanly before any DB work.
            if kind == "reverse_one" and len(items) > 1:
                raise _NestedError(
                    [
                        ErrorType(
                            field=field,
                            messages=[
                                f"{field!r} is a one-to-one relation; "
                                "provide a single object, not a list."
                            ],
                        )
                    ]
                )

            for item in items:
                # Reverse ownership guard: if the client supplies a pk for an
                # existing child, verify that child currently points to *this*
                # parent.  Without this check a client can silently re-parent
                # (steal) a row that belongs to a different owner.  It covers
                # BOTH reverse kinds -- reverse FK and reverse O2O -- because
                # in both the child carries a single key naming its owner.
                child_pk = cls._child_pk(child_model, item)
                # Through the shared lookup helper, so a pk the field cannot
                # parse is "no row" here too instead of a raw ORM error.
                existing = (
                    get_Object_or_None(
                        child_model._default_manager.db_manager(using)
                        if using
                        else child_model,
                        pk=child_pk,
                    )
                    if child_pk is not None
                    else None
                )
                if existing is not None:
                    # SECURITY: BEFORE the ownership guard, which resolves
                    # the pk unscoped and would answer a hidden row with
                    # "does not belong to this <Parent>" -- disclosing that
                    # the row exists. Deciding scope first makes every
                    # hidden row answer the same not-found, whether or not
                    # it happens to have an owner.
                    cls._reject_hidden_row(
                        field,
                        child_model,
                        child_pk,
                        info,
                        **({"using": using} if using is not None else {}),
                    )
                    current_owner_id = getattr(existing, f"{fk_name}_id", None)
                    if current_owner_id is not None and current_owner_id != parent.pk:
                        parent_model_name = parent.__class__.__name__
                        raise _NestedError(
                            [
                                ErrorType(
                                    field=field,
                                    messages=[
                                        f"Object {child_pk} does not "
                                        f"belong to this "
                                        f"{parent_model_name}."
                                    ],
                                )
                            ]
                        )

                    # Adopting an existing nullable reverse-FK/O2O orphan is a
                    # CHILD update, even when the parent names it by ID. The
                    # scope check above keeps its usual privacy precedence;
                    # without an update-serving child host there is no policy
                    # capable of authorizing this otherwise unscoped write.
                    if (
                        relation.field.null
                        and current_owner_id is None
                        and not hosts_serving(cls._meta.registry, child_model, "update")
                    ):
                        raise _NestedError(
                            [
                                ErrorType(
                                    field=field,
                                    messages=[
                                        "Adopting an existing child by ID requires "
                                        "a registered child update host."
                                    ],
                                )
                            ]
                        )

                # The writer resolves the same model on the same pk and applies
                # the same scope, so both are handed over rather than paid for
                # twice -- 2x(1 + H) SELECTs per child, H being the hosts that
                # serve the child's update. "scope_checked" is true exactly when
                # the guard above ran, which is exactly when there is a row for
                # it to have checked.
                cls._persist_child(
                    field,
                    child_model,
                    item,
                    info,
                    save_kwargs={fk_name: parent},
                    instance=existing,
                    scope_checked=existing is not None,
                    **({"using": using} if using is not None else {}),
                )
        elif kind == "m2m":
            items = sub_data if isinstance(sub_data, list) else [sub_data]
            manager = getattr(parent, field)
            children = []
            for item in items:
                # Same link rule as the forward branch of "save_with_nested":
                # an M2M row is shared by every parent that links it, so a
                # payload naming a row this parent is NOT already linked to
                # may only ATTACH it. This ID-link operation already passed the
                # destination output scope before the parent was written, but
                # does not run child WRITE permissions. A missing pk with
                # actual child data still falls through to the writer, which
                # creates; a missing link-only pk is refused by the preceding
                # destination check when scoped. A pk this parent ALREADY
                # carries falls through, and "_persist_child" applies the
                # child's write scope.
                #
                # The row is resolved FIRST, through the lookup helper that
                # reports an uncoercible pk as "no row", so a malformed pk never
                # reaches the linkage query as a raw ORM error.
                item_pk = cls._child_pk(child_model, item)
                existing = (
                    get_Object_or_None(
                        child_model._default_manager.db_manager(using)
                        if using
                        else child_model,
                        pk=item_pk,
                    )
                    if item_pk is not None
                    else None
                )
                linked = None
                if existing is not None and not manager.filter(pk=item_pk).exists():
                    # A link is scoped by the child's update hosts like any
                    # other id the child's own mutation would refuse; a hidden
                    # row answers like a missing one.
                    cls._reject_hidden_row(
                        field,
                        child_model,
                        item_pk,
                        info,
                        output_scope=False,
                        **({"using": using} if using is not None else {}),
                    )
                    linked = existing
                if linked is None:
                    # Same de-duplication as the reverse branch, and NO
                    # "scope_checked": nothing above consulted the child's hosts,
                    # so the writer must still apply their scope to the row it is
                    # about to write.
                    linked = cls._persist_child(
                        field,
                        child_model,
                        item,
                        info,
                        instance=existing,
                        **({"using": using} if using is not None else {}),
                    )
                children.append(linked)
            if using is not None:
                cls._check_native_m2m_through_route(field, relation, parent, using)
            manager.add(*children)  # additive: never removes

    @classmethod
    def _reject_hidden_row(
        cls,
        field: str,
        model: Any,
        pk: Any,
        info: GraphQLResolveInfo,
        using: str | None = None,
        output_scope: bool = True,
    ) -> None:
        """Refuse a nested pk the child's own write hosts cannot see.

        The row must be reachable through the scope of every host that serves
        the WRITE, exactly as that host's own "update" / "delete" require. A
        hidden row must not fall through either: Django's "save()" with a
        primary key issues an UPDATE, so the row the scope was hiding would be
        rewritten in place.

        Only the hosts SERVING the operation are consulted: a host narrowed to
        "model_operations = ("create",)" has no "update" to mirror, and applying
        its scope refused nested updates the child's own update accepts. BOTH
        host classes take "Meta.model_operations" -- "DjangoModelMutation" over
        ("create", "update", "delete") and "DjangoModelType" over those plus
        ("list", "retrieve") -- so a read-only "DjangoModelType" opts its
        "Meta.queryset" out of gating the nested path, which is what a project
        wants when that queryset is a display default rather than a policy.

        Args:
            field: The nested field name (used to prefix error fields).
            model: The child's Django model class.
            pk: The primary key named by the nested payload.
            info: GraphQL resolve info for the current request.
            using: Selected alias for the native nested child scope lookup.
            output_scope: Whether the child's registered output type must also
                expose the row (intersected with the host scope). False only
                for an id-only re-send of a forward relation's current target,
                which writes nothing.

        Raises:
            _NestedError: If any host serving "update", or the child's registered
                output type when "output_scope" is set, hides the row.
        """
        for host in hosts_serving(cls._meta.registry, model, "update"):
            manager = (
                model._default_manager.db_manager(using)
                if using
                else model._default_manager
            )
            scoped = host.get_queryset(manager, info)
            if get_Object_or_None(scoped, pk=pk) is None:
                raise _NestedError(
                    cls._prefix_errors(field, not_found_error(model, pk))
                )
        if output_scope:
            base = (
                model._default_manager.db_manager(using).all()
                if using
                else model._default_manager.all()
            )
            scoped = scope_to_output_type(base, info)
            if scoped is not base and get_Object_or_None(scoped, pk=pk) is None:
                raise _NestedError(
                    cls._prefix_errors(field, not_found_error(model, pk))
                )

    @classmethod
    def _persist_child(
        cls,
        field: str,
        child_spec: Any,
        item: dict[str, Any],
        info: GraphQLResolveInfo,
        save_kwargs: dict[str, Any] | None = None,
        instance: Model | None = _UNRESOLVED,
        scope_checked: bool = False,
        using: str | None = None,
        output_scope: bool = True,
    ) -> Model:
        """Upsert a single nested child, raising on validation failure.

        The permission pass below runs over "hosts_for_nested" -- EVERY host of
        the child model -- and not over "hosts_serving(..., op)" the way its
        three siblings do. That asymmetry is deliberate. "hosts_serving" exists
        because a SCOPE and a PROJECTION describe a surface a host offers, and
        "A host has no say over an operation it does not generate"; a
        "permission_classes" declaration describes the opposite thing, a
        PROHIBITION over the model itself, exactly as the exclusion merged in
        "nested_child_input" is. Narrowing this loop to the serving hosts would
        REMOVE checks rather than fix a mismatch: a host declared
        "model_operations = ("create",)" would stop being consulted on the
        nested UPDATE path, and the project's only stated policy for that child
        would go unasked precisely where a row already exists to be rewritten.
        The extra calls are the fail-closed side of the trade, so they stay.

        Args:
            field: The nested field name (used to prefix error fields).
            child_spec: The nested-field value -- the child's Django model class.
            item: The child payload.
            info: GraphQL resolve info for the current request.
            save_kwargs: Extra attributes injected at save time (e.g. the reverse
                FK pointing back at the parent).
            instance: The row the payload names, when the caller already looked
                it up on the SAME model and pk this method would use -- "None"
                meaning it found none. Left at the "_UNRESOLVED" sentinel, the
                lookup is done here as before. It is a pure de-duplication: the
                branches that pass it resolve through "get_Object_or_None" too,
                so what is saved is a SELECT, never a decision.
            scope_checked: True when the caller already ran "_reject_hidden_row"
                for that row. It only ever suppresses a REPEAT of the check the
                caller just ran and passed; a caller that resolved the row
                WITHOUT checking its scope leaves this False and the check runs
                here, which is why the many-to-many branch does exactly that.
            using: Selected alias for the native child lookup and save.
            output_scope: Whether the child's output type scope applies to an
                existing row; False for an id-only forward re-send.

        Returns:
            The saved child instance.

        Raises:
            _NestedError: If the child payload fails validation, or names a row
                the child's own host does not expose.
        """
        item = cls._unwrap_enums(dict(item))
        child_backend = backend_for_nested(child_spec)
        model = child_backend.get_model()
        hosts = hosts_for_nested(cls._meta.registry, model)
        pk = cls._child_pk(model, item)
        if instance is _UNRESOLVED:
            instance = (
                get_Object_or_None(
                    model._default_manager.db_manager(using) if using else model,
                    pk=pk,
                )
                if pk is not None
                else None
            )

        if instance is None and pk is not None:
            # SECURITY: an id-bearing payload that resolves to no row is
            # answered exactly like a row the child's hosts hide. Creating
            # silently on a missing id would let a client tell hidden ids
            # (error) from unused ones (created) -- an existence oracle.
            raise _NestedError(cls._prefix_errors(field, not_found_error(model, pk)))

        if instance is not None and not scope_checked:
            cls._reject_hidden_row(
                field,
                model,
                pk,
                info,
                output_scope=output_scope,
                **({"using": using} if using is not None else {}),
            )

        # SECURITY: the child's OWN permissions, which the parent's single
        # "authorize" call never consulted. "authorize" raises "GraphQLError"
        # (PERMISSION_DENIED / 403), not "_NestedError", so it escapes
        # "save_with_nested" through the atomic block: the whole write rolls
        # back and the caller sees the byte-identical denial the child's own
        # mutation returns. "nested_parent" tells a policy the write arrived
        # through a parent, which is what makes "writable only via its parent"
        # expressible. A "DjangoModelMutation" host has no permissions at all,
        # so it contributes the scoping half above and nothing here.
        action = "update" if instance is not None else "create"
        extras = {"data": item, "nested_parent": cls._meta.model}
        for host in hosts:
            authorize = getattr(host, "authorize", None)
            if authorize is not None:
                # "supported_kwargs": an "authorize" override (or a permission
                # class) that spells its arguments out predates "nested_parent"
                # and must not turn a GRANT into a 500. Dropping the marker is
                # fail-closed -- the policy then reads the nested write exactly
                # as it reads a direct one.
                authorize(info, action, **supported_kwargs(authorize, extras))

        if instance is None and using is not None:
            from .core.backend import PydanticBackend

            if type(child_backend) is PydanticBackend:
                instance = model()
                instance._state.db = using

        ok, result = child_backend.save_object(
            cls,
            None,
            info,
            item,
            instance=instance,
            partial=pk is not None
            and instance is not None
            and not instance._state.adding,
            save_kwargs=save_kwargs,
        )
        if not ok:
            raise _NestedError(cls._prefix_errors(field, result))
        return result

    @staticmethod
    def _unwrap_enums(item: dict[str, Any]) -> dict[str, Any]:
        """Replace graphene Enum members in a payload with their raw values.

        Scalar Enum members are replaced with their "value". List and
        tuple values are recursed into so that multi-valued choice fields
        (e.g. a "MultiSelectField" / "DjangoListField(enum)") also arrive
        at the backend with plain Python values rather than wrapped Enum
        members.

        Args:
            item: The child payload.

        Returns:
            The payload with enum members unwrapped to their raw values.
        """
        for key, value in item.items():
            if isinstance(value, enum.Enum):
                item[key] = value.value
            elif isinstance(value, (list, tuple)):
                item[key] = [v.value if isinstance(v, enum.Enum) else v for v in value]
        return item

    @staticmethod
    def _prefix_errors(field: str, errors: list[ErrorType]) -> list[ErrorType]:
        """Prefix a child's "ErrorType" list with the nested field name.

        Args:
            field: The nested field name used as the prefix.
            errors: The child's "ErrorType" entries (flat field names).

        Returns:
            New entries with fields like "addresses.zip_code" (object-level
            errors keep just the nested field name).
        """
        result: list[ErrorType] = []
        for error in errors:
            sub = getattr(error, "field", "") or ""
            name = field if sub in ("", "non_field_errors") else f"{field}.{sub}"
            result.append(ErrorType(field=name, messages=error.messages))
        return result
