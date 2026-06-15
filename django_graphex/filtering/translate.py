"""Translate a ``<Model>FilterInput`` value into a Django ``Q`` object.

The recursive walker :func:`to_q` turns a nested filter node (the dict-like
``InputObjectTypeContainer`` graphene hands a resolver) into a single
``django.db.models.Q`` plus a flag recording whether any to-many relation was
traversed (so the backend can apply ``.distinct()``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from django.db.models import Q
from graphql import GraphQLError, Undefined

from .lookups import ALL_LOOKUPS

if TYPE_CHECKING:
    from django.db.models import Model

__all__ = ("to_q",)

#: Lookup names recognized at a leaf (drives relation-direct pk detection).
_LOOKUP_NAMES = frozenset(ALL_LOOKUPS)

#: Backend flag, read once at import time (the flag is process-global and set
#: before import — D7). Under the native backend graphql-core delivers raw enum
#: values already, so the graphene-specific ``_unwrap_enum`` is a no-op that we
#: skip entirely (A5). The graphene path retains it (graphene Enum has ``.value``).
_NATIVE_BACKEND: bool = os.environ.get("GDX_BACKEND", "graphene") == "native"


def _is_set(value: Any) -> bool:
    """Return whether an input value was actually provided (not ``Undefined``)."""
    return value is not Undefined and value is not None


def _relation_target(model: type[Model], name: str) -> type[Model] | None:
    """Return the related model for a relation field name, else ``None``.

    Args:
        model: The model owning the field.
        name: The field name to inspect.

    Returns:
        The related model class when ``name`` is a relation, otherwise None.
    """
    try:
        field = model._meta.get_field(name)
    except Exception:
        return None
    if field.is_relation:
        return field.related_model
    return None


def _is_pk_lookups(value: Any) -> bool:
    """Return whether a relation's value is a plain-pk lookups mapping.

    A relation declared directly (e.g. ``"author": ("exact", "in")``) yields a
    value whose keys are lookup names (``exact``/``in``/...), not related-model
    field names. Such a value is applied as a leaf against the FK column.

    Args:
        value: The value mapped under a relation key.

    Returns:
        True when every set key is a known lookup name (and there is at least
        one), so the relation should be treated as plain-pk lookups.
    """
    if not hasattr(value, "items"):
        return False
    keys = [key for key, val in value.items() if _is_set(val)]
    return bool(keys) and all(key in _LOOKUP_NAMES for key in keys)


def _is_to_many(model: type[Model], name: str) -> bool:
    """Return whether ``name`` is a to-many relation on ``model``."""
    try:
        field = model._meta.get_field(name)
    except Exception:
        return False
    return bool(getattr(field, "many_to_many", False)) or bool(
        getattr(field, "one_to_many", False)
    )


def _is_model_field(model: type[Model], name: str) -> bool:
    """Return whether ``name`` is a real concrete/relation field on ``model``.

    Custom ``@filter_field`` args (e.g. ``search``) appear in the same filter
    input value as the standard lookups but are NOT model fields — they are
    applied separately by ``apply_custom_filters`` in the field resolver. ``to_q``
    must therefore SKIP any key that is not a model field (and not a combinator),
    otherwise it would reach ``_leaf_q`` and try to call ``.items()`` on the
    custom filter's scalar value (``'str' object has no attribute 'items'``).

    Args:
        model: The model owning the field.
        name: The key to inspect.

    Returns:
        ``True`` when ``model._meta.get_field(name)`` resolves a real field.
    """
    try:
        model._meta.get_field(name)
    except Exception:
        return False
    return True


def _looks_like_graphene_enum(value: Any) -> bool:
    """Return whether a value (or any list item) is a graphene Enum member.

    A graphene Enum member's class name ends with ``Enum`` and exposes ``.value``.
    Native graphql-core enums deliver the raw Python value (a plain scalar), so
    they never match. This drives the dual-backend safety fallback in ``_leaf_q``:
    a graphene.Schema-built filter executed in a ``GDX_BACKEND=native`` process
    still gets its Enum members unwrapped.

    Args:
        value: A lookup value (scalar, Enum member, or list thereof).

    Returns:
        True when the value (or any item, for list lookups) is a graphene Enum
        member that still needs unwrapping.
    """
    if isinstance(value, (list, tuple)):
        return any(_looks_like_graphene_enum(item) for item in value)
    return hasattr(value, "value") and type(value).__name__.endswith("Enum")


def _unwrap_enum(value: Any) -> Any:
    """Return an Enum member's raw value, unwrapping list items too.

    GRAPHENE PATH ONLY (A5): graphene delivers Enum *members* (with a ``.value``)
    to the resolver, so the raw ORM value must be unwrapped before building the
    ``Q``. graphql-core (native backend) delivers the raw value directly, so
    ``to_q`` skips this call entirely under ``GDX_BACKEND=native`` — this helper
    is retained unchanged for the dual-backend graphene path.

    Args:
        value: A lookup value (scalar, Enum member, or list thereof).

    Returns:
        The value with any graphene Enum members replaced by their raw value.
    """
    if isinstance(value, (list, tuple)):
        return [_unwrap_enum(item) for item in value]
    if hasattr(value, "value") and type(value).__name__.endswith("Enum"):
        return value.value
    return value


def _leaf_q(prefix: str, field: str, lookups: Any) -> Q:
    """Build the AND of a single field's ``{lookup: value}`` mapping.

    Args:
        prefix: The dotted ORM prefix accumulated from parent relations.
        field: The model field name.
        lookups: The ``{lookup: value}`` mapping for the field.

    Returns:
        A ``Q`` combining every set lookup with ``&``.

    Raises:
        GraphQLError: If a ``range`` lookup is not a two-element list.
    """
    q = Q()
    for lookup, value in lookups.items():
        if not _is_set(value):
            continue
        if lookup == "range":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise GraphQLError(
                    f"The '{prefix}{field}__range' lookup requires a list of "
                    "exactly two elements."
                )
            value = list(value)
        # A5: under a genuine native schema graphql-core delivers RAW enum values,
        # so the graphene-specific ``_unwrap_enum`` is unnecessary. Skip it on the
        # native path. The graphene path always unwraps (graphene Enum members
        # carry a ``.value`` that must be resolved before the ORM).
        #
        # DUAL-BACKEND SAFETY: ``_unwrap_enum`` is value-driven (a no-op unless
        # the value is a graphene-Enum-like member), so even under the native
        # env flag we still unwrap a value that IS a graphene Enum member — this
        # keeps graphene.Schema-built filters correct when executed in a process
        # where ``GDX_BACKEND=native`` (the v1 graphene integration suite).
        if not _NATIVE_BACKEND or _looks_like_graphene_enum(value):
            value = _unwrap_enum(value)
        q &= Q(**{f"{prefix}{field}__{lookup}": value})
    return q


def to_q(node: Any, model: type[Model], prefix: str = "") -> tuple[Q, bool]:
    """Translate a filter node into a ``(Q, touched_to_many)`` pair.

    Rules:
        * Multiple keys in one node are AND-ed together.
        * ``and: [...]`` combines its children with ``&``.
        * ``or: [...]`` combines its children with ``|``.
        * ``not: {...}`` negates its child.
        * A relation field recurses with the prefix ``field__``.
        * A scalar field's ``{lookup: value}`` maps to
          ``Q(**{f"{prefix}field__{lookup}": value})``.

    An empty node (or empty ``or: []``) contributes nothing.

    Args:
        node: The dict-like filter node (an ``InputObjectTypeContainer``).
        model: The model the node filters (relations resolve against it).
        prefix: The dotted ORM prefix accumulated from parent relations.

    Returns:
        A pair of the combined ``Q`` and whether any to-many relation was
        traversed (used to decide ``.distinct()``).
    """
    result = Q()
    touched_to_many = False

    if node is None or node is Undefined:
        return result, touched_to_many

    for key, value in node.items():
        if not _is_set(value):
            continue

        if key == "and":
            for child in value:
                child_q, child_many = to_q(child, model, prefix)
                result &= child_q
                touched_to_many = touched_to_many or child_many
            continue
        if key == "or":
            combined = Q()
            has_any = False
            for child in value:
                child_q, child_many = to_q(child, model, prefix)
                combined = child_q if not has_any else (combined | child_q)
                has_any = True
                touched_to_many = touched_to_many or child_many
            if has_any:
                result &= combined
            continue
        if key == "not":
            child_q, child_many = to_q(value, model, prefix)
            result &= ~child_q
            touched_to_many = touched_to_many or child_many
            continue

        related = _relation_target(model, key)
        if related is not None and not _is_pk_lookups(value):
            if _is_to_many(model, key):
                touched_to_many = True
            child_q, child_many = to_q(value, related, f"{prefix}{key}__")
            result &= child_q
            touched_to_many = touched_to_many or child_many
            continue

        # Skip keys that are NOT real model fields: custom ``@filter_field`` args
        # (e.g. ``search``) ride in the same filter input value but are applied by
        # ``apply_custom_filters`` in the resolver, not by ``to_q``. Without this
        # guard ``_leaf_q`` would call ``.items()`` on the custom filter's scalar
        # value and raise ``'str' object has no attribute 'items'`` (#1571).
        if not _is_model_field(model, key):
            continue

        # A scalar field, or a relation declared directly (plain-pk lookups:
        # ``field__exact`` / ``field__in`` resolve against the related pk).
        result &= _leaf_q(prefix, key, value)

    return result, touched_to_many
