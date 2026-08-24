"""Shared nested-object create/update handling for serializer-backed types.

"DjangoModelType" and "DjangoModelMutation" accept
"Meta.nested_fields = {field_name: Model}" to write related objects
in the same create/update call. This mixin centralizes that logic (the two hosts
previously carried duplicate, buggy copies) and makes it:

* atomic -- the whole operation runs in "transaction.atomic()"; a nested or
  parent validation failure rolls everything back (no orphan rows),
* relation-aware -- forward FK/O2O children are saved before the parent and
  their pk injected; reverse FK/O2O and M2M children are saved after the parent
  and linked to it, all decided by Django's relation introspection,
* upsert-capable -- a child payload carrying its pk updates that row (partial),
  otherwise a new row is created (the nested input only exposes the pk on the
  parent's update, so creates stay create-only),
* link-not-rewrite -- on a relation whose rows the parent does not own (forward
  FK/O2O and M2M) a pk the parent is not already attached to only LINKS that
  row; its other fields are ignored, so no client can edit an arbitrary row of
  the related table by naming its pk,
* safe by default -- additive M2M/reverse semantics (existing links are never
  removed) and empty "[]" / "{}" payloads are a no-op.

One level of nesting is supported (parent -> direct children).
"""

from __future__ import annotations

import enum
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from django.db import transaction

from .backends import backend_for_nested
from .errors import ErrorType
from .utils import get_Object_or_None

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo

__all__ = ("NestedFieldsMixin",)


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
    def save_with_nested(  # noqa: DOC005
        cls,
        root: Any,
        info: GraphQLResolveInfo,
        data: dict[str, Any],
        instance: Model | None = None,
        serializer_kwargs: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Validate and persist the parent plus its nested children atomically.

        Forward relations (the parent holds the key) are written first and their
        pk injected into "data"; the parent is then saved via the backend (so
        its validation/error handling is used); reverse and M2M children
        are written last and linked to the saved parent. Any failure rolls the
        whole transaction back -- no orphan rows are left behind.

        Subscription broadcasts and commit-time delivery: model saves inside
        the "transaction.atomic()" block trigger "post_save" / "post_delete"
        signals, which are connected to "SubscriptionBinding" receivers.
        Those receivers defer their broadcast via "transaction.on_commit",
        so subscribers only receive notifications for rows that were actually
        persisted. A subsequent failure within the same atomic block causes a
        rollback and suppresses all pending broadcast callbacks, eliminating
        phantom notifications for non-existent rows.

        A child is validated by the backend of a host that declared custom
        validation for its model when one exists (see "backend_for_nested"), so
        a nested write applies the same rules the child's own mutation does.

        A forward payload carrying a pk the parent is not already linked to
        LINKS that row rather than writing it; the M2M branch applies the same
        rule (see "_attach_children"). Both relations point at rows the parent
        does not own, so without the rule a client could rewrite any row of the
        related table by naming its pk.

        Every internal validation failure is raised as a private "_NestedError"
        and caught here, so this method never propagates it; it always returns a
        result tuple instead.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            data: Mutable input data; nested entries are popped from it.
            instance: Existing instance for an update, or None for a create.
            serializer_kwargs: Reserved (unused by the native backend).

        Returns:
            A tuple of a success flag and either the saved object or a list of
            "ErrorType" entries.
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
        boundary = transaction.atomic() if has_nested_work else nullcontext()

        try:
            with boundary:
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
                        # rewrite ANY row of the related table by naming its pk
                        # (a shared lookup row belongs to nobody, so no scope
                        # hid it either).
                        item_pk = cls._child_pk(child_model, item)
                        current_pk = (
                            getattr(instance, relation.attname, None)
                            if instance is not None
                            else None
                        )
                        if item_pk is not None and str(item_pk) != str(current_pk):
                            data[field] = item_pk  # link only, no child write
                            continue
                        child = cls._persist_child(field, child_model, item, info)
                        data[field] = child.pk
                    elif kind is None:
                        # Not an introspectable relation: leave it for the
                        # parent backend to handle.
                        data[field] = sub_data
                    else:
                        # Reverse/M2M children need the parent pk: defer them.
                        deferred.append((field, child_model, kind, relation, sub_data))

                ok, obj = cls._meta.backend.save_object(
                    cls,
                    root,
                    info,
                    data,
                    instance=instance,
                    partial=instance is not None,
                    serializer_kwargs=serializer_kwargs,
                )
                if not ok:
                    raise _NestedError(obj if isinstance(obj, list) else [obj])

                for field, child_model, kind, relation, sub_data in deferred:
                    cls._attach_children(
                        obj, field, child_model, kind, relation, sub_data, info
                    )

                return True, obj
        except _NestedError as error:
            return False, error.errors

    # -- relation introspection ------------------------------------------------

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
                if child_pk is not None:
                    # Through the shared lookup helper, so a pk the field cannot
                    # parse is "no row" here too instead of a raw ORM error.
                    existing = get_Object_or_None(child_model, pk=child_pk)
                    if existing is not None:
                        current_owner_id = getattr(existing, f"{fk_name}_id", None)
                        if (
                            current_owner_id is not None
                            and current_owner_id != parent.pk
                        ):
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

                cls._persist_child(
                    field, child_model, item, info, save_kwargs={fk_name: parent}
                )
        elif kind == "m2m":
            items = sub_data if isinstance(sub_data, list) else [sub_data]
            manager = getattr(parent, field)
            children = []
            for item in items:
                # Same link rule as the forward branch of "save_with_nested":
                # an M2M row is shared by every parent that links it, so a
                # payload naming a row this parent is NOT already linked to may
                # only ATTACH it -- writing its fields would let a client edit
                # an arbitrary row of the related table by naming its pk. A pk
                # that matches no row falls through to the writer, which creates,
                # exactly as it did before.
                #
                # The row is resolved FIRST, through the lookup helper that
                # reports an uncoercible pk as "no row", so a malformed pk never
                # reaches the linkage query as a raw ORM error.
                item_pk = cls._child_pk(child_model, item)
                linked = None
                if item_pk is not None:
                    existing = get_Object_or_None(child_model, pk=item_pk)
                    if existing is not None and not manager.filter(pk=item_pk).exists():
                        linked = existing
                if linked is None:
                    linked = cls._persist_child(field, child_model, item, info)
                children.append(linked)
            manager.add(*children)  # additive: never removes

    @classmethod
    def _persist_child(
        cls,
        field: str,
        child_spec: Any,
        item: dict[str, Any],
        info: GraphQLResolveInfo,
        save_kwargs: dict[str, Any] | None = None,
    ) -> Model:
        """Upsert a single nested child, raising on validation failure.

        Args:
            field: The nested field name (used to prefix error fields).
            child_spec: The nested-field value -- the child's Django model class.
            item: The child payload.
            info: GraphQL resolve info for the current request.
            save_kwargs: Extra attributes injected at save time (e.g. the reverse
                FK pointing back at the parent).

        Returns:
            The saved child instance.

        Raises:
            _NestedError: If the child payload fails validation.
        """
        item = cls._unwrap_enums(dict(item))
        child_backend = backend_for_nested(child_spec)
        model = child_backend.get_model()
        pk = cls._child_pk(model, item)
        instance = get_Object_or_None(model, pk=pk) if pk is not None else None

        ok, result = child_backend.save_object(
            cls,
            None,
            info,
            item,
            instance=instance,
            partial=instance is not None,
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
