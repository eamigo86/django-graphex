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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import Model

__all__ = ("required_perms_for",)

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
