"""Composite permission table for permission-scoped-schema labels (P0).

This module owns the NORMATIVE mapping from a CRUD / subscribe action to the
Django permission codenames a caller must hold on a model. It is the single
source of truth the schema compiler consults when stamping
"extensions[gdx_required_perms]" on generated fields, and it mirrors
"DjangoModelPermissions.perms_map".

The table is COMPOSITE: because a mutation / subscription payload returns
instance data, each write verb requires BOTH its write permission AND "view".
Read / observe actions stay view-only.

With "M" written for "{app}.{verb}_{model}", the required permissions per action
are:

- retrieve: "view_M".
- list: "view_M".
- create: "add_M" + "view_M".
- update: "change_M" + "view_M".
- delete: "delete_M" + "view_M".
- subscribe CREATE: "view_M" + "add_M".
- subscribe UPDATE: "view_M" + "change_M".
- subscribe DELETE: "view_M" + "delete_M".
- subscribe ALL_ACTIONS: "view_M" + "add_M" + "change_M" + "delete_M".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import Model

__all__ = (
    "implicit_perms_for_type",
    "implicit_label_set",
    "input_label_set",
    "required_perms_for",
)

#: CRUD action -> the codename verbs it requires (``view`` is always included
#: for write verbs because the payload returns instance data).
_ACTION_VERBS: dict[str, tuple[str, ...]] = {
    "retrieve": ("view",),
    "list": ("view",),
    "create": ("add", "view"),
    "update": ("change", "view"),
    "delete": ("delete", "view"),
}

#: subscribe action-value -> the codename verbs it requires. ``all_actions``
#: spans every write verb (plus ``view``).
_SUBSCRIBE_VERBS: dict[str, tuple[str, ...]] = {
    "create": ("view", "add"),
    "update": ("view", "change"),
    "delete": ("view", "delete"),
    "all_actions": ("view", "add", "change", "delete"),
}


def _codename(model: type[Model], verb: str) -> str:
    """Return the ``{app_label}.{verb}_{model_name}`` codename for *model*."""
    opts = model._meta
    return f"{opts.app_label}.{verb}_{opts.model_name}"


def required_perms_for(
    model: type[Model], action: str, subaction: str | None = None
) -> frozenset[str]:
    """Return the permission codenames the action requires on the model.

    Args:
        model: The Django model class the action targets.
        action: A CRUD action ("retrieve" / "list" / "create" / "update" /
            "delete") or "subscribe".
        subaction: The subscription action-value ("create" / "update" /
            "delete" / "all_actions") — REQUIRED when "action" is "subscribe".

    Returns:
        The codenames, e.g. {"app.add_thing", "app.view_thing"}.

    Raises:
        KeyError: If "action" (or the subscribe "subaction") is unknown.
    """
    if action == "subscribe":
        verbs = _SUBSCRIBE_VERBS[subaction or "all_actions"]
    else:
        verbs = _ACTION_VERBS[action]
    return frozenset(_codename(model, verb) for verb in verbs)


def implicit_perms_for_type(gtype: Any) -> frozenset[str] | None:
    """Return the read permissions a generated model-backed output type implies.

    A GENERATED output type (a model node type or its "<Model>ListType"
    container) carries its Django model on 'extensions["gdx"]._meta.model'. Any
    field returning such a type is a READ of that model, so it requires the same
    perms the model's own "retrieve" root does — this is what closes the
    relation-traversal bypass (a nested relation field is never stamped at
    compile time, so the label is derived from its OUTPUT TYPE instead).

    Args:
        gtype: A named GraphQL type (already unwrapped of list / non-null).

    Returns:
        The model's read permissions, or None when "gtype" is not a generated
        model-backed type (a scalar, an enum, a plain "ObjectType" root, the
        flat "GenericForeignKeyType", …) and therefore implies nothing.
    """
    gdx = (getattr(gtype, "extensions", None) or {}).get("gdx")
    model = getattr(getattr(gdx, "_meta", None), "model", None)
    if model is None:
        return None
    return required_perms_for(model, "retrieve")


def implicit_label_set(schema: Any) -> frozenset[str]:
    """Return every implicit permission label reachable in a built schema.

    The schema-level "gdx_label_set" is the projection target the pruner's
    caller intersects a user's live permissions against, so a label the pruner
    consults but the set omits would be stripped before the pruner ever sees it
    (removing the field for EVERYONE, including callers who hold the perm).
    Relation labels are derived from output types rather than stamped at compile
    time, so they are collected HERE, from the built type map — the roots alone
    never reach a target model exposed only through a nested relation.

    Args:
        schema: The built "GraphQLSchema" whose type map is scanned.

    Returns:
        The union of every model-backed type's implicit read permissions.
    """
    labels: set[str] = set()
    for name, gtype in schema.type_map.items():
        if name.startswith("__"):
            continue
        perms = implicit_perms_for_type(gtype)
        if perms is not None:
            labels.update(perms)
    return frozenset(labels)


def input_label_set(schema: Any) -> frozenset[str]:
    """Return every permission label stamped on an INPUT field of a schema.

    The input-side twin of "implicit_label_set", and needed for the same
    reason: a nested-write label the root fields never mention would be
    stripped from the caller's granted set before the pruner runs, so the
    nested field would disappear for everyone -- including the callers who
    hold the permission.

    Args:
        schema: The built "GraphQLSchema" whose type map is scanned.

    Returns:
        The union of every input field's "gdx_required_perms".
    """
    from graphql import is_input_object_type

    labels: set[str] = set()
    for name, gtype in schema.type_map.items():
        if name.startswith("__") or not is_input_object_type(gtype):
            continue
        for ifield in gtype.fields.values():
            perms = (ifield.extensions or {}).get("gdx_required_perms")
            if perms is not None:
                labels.update(perms)
    return frozenset(labels)
