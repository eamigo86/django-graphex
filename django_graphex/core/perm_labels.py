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


def implicit_perms_for_type(gtype: Any, schema: Any = None) -> frozenset[str] | None:
    """Return the read permissions a generated model-backed output type implies.

    A GENERATED output type (a model node type or its "<Model>ListType"
    container) carries its Django model on 'extensions["gdx"]._meta.model'. Any
    field returning such a type is a READ of that model, so it requires the same
    perms the model's own "retrieve" root does — this is what closes the
    relation-traversal bypass (a nested relation field is never stamped at
    compile time, so the label is derived from its OUTPUT TYPE instead).

    An ABSTRACT type carries no model of its own. A typed GFK union
    ("Meta.unions") compiles to a "GraphQLUnionType" and a "DjangoInterfaceType"
    compiles to a "GraphQLInterfaceType"; neither has a "_meta.model". Reading
    the model off one yields None, so the field stayed untagged == PUBLIC while
    a DIRECT root field to the very same member type was pruned — the abstract
    arm of the exact same bypass. The label of an abstract type is therefore the
    UNION of its members' labels: the field can return ANY of them, so a caller
    must hold the read permission of EVERY one to be handed it.

    That is an AND, and it deliberately over-prunes: a caller permitted on
    member A but not member B loses the field entirely rather than keeping a
    field that could still hand them a B row. An intersection (OR) would keep
    the field for such a caller and re-open the bypass, and a per-member answer
    is not expressible here — the return value is the single requirement the
    pruner applies to the WHOLE field. Over-pruning is the safe direction; the
    escape hatch is to expose the members through their own gated fields.

    The two abstract arms find their members differently because graphql-core
    stores them differently. A union enumerates its members on the type itself
    ("gtype.types"). An interface does NOT know its implementors, so they are
    read off the SCHEMA when one is supplied and off the declaring type's
    registry otherwise — see "_interface_perms" for why the difference matters.

    Args:
        gtype: A named GraphQL type (already unwrapped of list / non-null).
        schema: The built "GraphQLSchema" the type belongs to, used to scope an
            interface's implementors to the ones this schema actually mounts.
            "None" falls back to the process-wide registry.

    Returns:
        The model's read permissions, or None when "gtype" is not a generated
        model-backed type (a scalar, an enum, a plain "ObjectType" root, the
        flat "GenericForeignKeyType", a union or interface of none of them, …)
        and therefore implies nothing.
    """
    from graphql import is_interface_type, is_union_type

    gdx = (getattr(gtype, "extensions", None) or {}).get("gdx")
    model = getattr(getattr(gdx, "_meta", None), "model", None)
    if model is not None:
        return required_perms_for(model, "retrieve")
    if is_union_type(gtype):
        perms: set[str] = set()
        for member in gtype.types:
            member_perms = implicit_perms_for_type(member, schema)
            if member_perms:
                perms.update(member_perms)
        return frozenset(perms) or None
    if is_interface_type(gtype):
        return _interface_perms(gtype, gdx, schema)
    return None


def _interface_perms(gtype: Any, gdx: Any, schema: Any = None) -> frozenset[str] | None:
    """Return the read permissions an interface's implementors imply.

    The answer is the union (an AND) over the types the interface field can
    return, and WHICH types those are is the whole question. The schema's own
    "get_possible_types" is the exact answer: it enumerates the implementors
    this schema mounts, which is what a query can actually be handed.

    The declaring type's REGISTRY is the fallback, and it is a strict superset:
    a registry is process-wide and populated at class-definition time, while a
    schema mounts whatever subset its roots, relations and "types=" forwards
    happen to reach. Over-requiring never leaks — a caller is never handed a row
    whose read permission it lacks — but it is not free either: a caller holding
    the read permission of EVERY implementor the schema mounts lost the field
    because of one no query could ever reach. That is an availability defect,
    and on a field that was public before the label existed it is a regression,
    not a lesser evil.

    Both readers of this answer take the same schema, which is what makes the
    narrowing safe. The pruner derives a field's label from its output type; its
    caller first intersects the user's permissions with the schema-level
    "gdx_label_set", built by "implicit_label_set" from the SAME schema. Narrow
    one and not the other and the label is stripped before the pruner runs,
    removing the field for everyone — so the two move together or not at all.

    An interface the schema mounts with no possible types is unresolvable rather
    than public, but the registry fallback still answers for it, so the
    conservative label survives the case where the schema cannot speak.

    Args:
        gtype: The "GraphQLInterfaceType" whose implementors are wanted.
        gdx: The compiled "extensions[gdx]" payload of that interface, or None
            when the type was not built by the native pipeline.
        schema: The built "GraphQLSchema" to scope the implementors to, or None
            to fall back to the declaring type's registry.

    Returns:
        The union of every reachable implementor's read permissions, or None
        when the interface has no model-backed implementor to gate (nothing it
        can return, so nothing it can leak).
    """
    perms: set[str] = set()
    if schema is not None:
        for member in schema.get_possible_types(gtype):
            member_perms = implicit_perms_for_type(member, schema)
            if member_perms:
                perms.update(member_perms)
        if perms:
            return frozenset(perms)

    declared = getattr(getattr(gdx, "_meta", None), "graphene_type", None)
    registry = getattr(declared, "_dgx_registry", None)
    if registry is None:
        return None
    for model in registry.get_member_models(declared):
        perms.update(required_perms_for(model, "retrieve"))
    return frozenset(perms) or None


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
        perms = implicit_perms_for_type(gtype, schema)
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
