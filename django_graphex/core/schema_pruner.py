"""Permission-scoped schema prune transform (P1).

"prune_schema(full, granted)" rebuilds the reachable-from-roots closure of a
LABELED graphql-core schema, OMITTING any field whose
"extensions[gdx_required_perms]" (stamped by P0) are not all held by the
caller's "granted" permission set. The result is a SEPARATE, distinct
"GraphQLSchema" — the transform is PURE and never mutates or shares type
identity with the source (the FULL schema is a process singleton).

Design (SDD "permission-scoped-schema" D2):

- A field survives iff its "gdx_required_perms" (a "frozenset") is a subset of
  "granted". An UNTAGGED field falls back to the IMPLICIT label of its output
  type (the target model's read permission, via
  "perm_labels.implicit_perms_for_type") — this is what gates RELATION and
  NESTED-LIST fields, which are built with no permission context and would
  otherwise be "untagged == public" and let a caller read a model through a
  relation after its own roots were pruned away. An untagged field whose output
  type is not a generated model-backed type is PUBLIC and always survives.
- A subscription field carries a per-action "dict{action: frozenset}" instead.
  Its "action" enum is rebuilt per signature: an action-value survives iff its
  perms are held; "ALL_ACTIONS" survives only when every write verb is held.
  If NO action survives, the whole subscription field is removed.
- Removal is TRANSITIVE: a type reachable only via omitted fields disappears, and
  a type left with ZERO fields is dropped, cascading to a fixpoint (its
  referencing fields / union members are removed too, which can empty and drop
  further types — including a root type, which becomes "None").
- Interfaces, unions and their membership are recomputed against the survivors.
- The pruned schema passes graphql-core "validate_schema" (no dangling refs),
  except when a ROOT type is fully pruned; that empty-root case is the caller's
  (the view's) 403 responsibility, not a dangling reference.

The algorithm is two-phase over the type graph (O(V+E) plus a bounded cascade
fixpoint):

1. Survivor fixpoint — starting from the root object types, decide which named
   types survive. An object / interface survives iff it retains at least one
   field after per-field perm filtering AND after dropping fields whose (named)
   output type did not survive. A union survives iff at least one member
   survives. Iterate until the survivor set is stable.
2. Clone-on-write rebuild — clone each surviving type via "to_kwargs()",
   remapping every referenced type to its cloned survivor and dropping fields /
   members / interfaces that reference a non-survivor. Scalars and named enums
   are threaded through unchanged; the per-signature subscription action enum is
   rebuilt inline on its field argument.

"GraphQLSchema" recomputes its "type_map" from the rebuilt roots, so unreachable
types fall away automatically.
"""

from __future__ import annotations

from typing import Any

from graphql import (
    GraphQLEnumType,
    GraphQLField,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLUnionType,
    get_named_type,
    is_enum_type,
    is_input_object_type,
    is_interface_type,
    is_object_type,
    is_union_type,
)

from django_graphex.core.perm_labels import implicit_perms_for_type

__all__ = ("prune_schema",)

# The subscribe action-value whose perms span every write verb. ``all_actions``
# is retained only when every per-action value also survives.
_ALL_ACTIONS_KEY = "all_actions"

# Suffix of the per-model subscription action enum (``{Model}SubscriptionAction``)
# whose values are pruned per signature.
_ACTION_ENUM_SUFFIX = "SubscriptionAction"


def prune_schema(full: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
    """Return a permission-scoped clone of the schema for the granted perm set.

    Args:
        full: The labeled FULL "GraphQLSchema" (P0 stamped
            "extensions[gdx_required_perms]" on generated fields).
        granted: The permission codenames the caller holds. Extra perms outside
            the schema label-set are harmless.

    Returns:
        A distinct "GraphQLSchema" whose reachable closure omits every field the
        caller may not see. The source "full" schema is never mutated.
    """
    return _Pruner(full, granted).run()


class _Pruner:
    """Stateful single-shot pruner (one instance per built variant)."""

    def __init__(self, full: GraphQLSchema, granted: frozenset[str]) -> None:
        self._full = full
        self._granted = granted
        # Named object / interface type -> its field map AFTER per-field perm
        # filtering (before the survivor fixpoint drops dangling-type fields).
        self._filtered_fields: dict[str, dict[str, GraphQLField]] = {}
        # Named input object type -> its field map after the same filtering.
        self._filtered_input_fields: dict[str, dict[str, Any]] = {}
        # Named types that survive the fixpoint.
        self._survivors: set[str] = set()
        # Memoized clones, keyed by type name, so shared references stay shared
        # within the pruned universe (and self-references resolve).
        self._clones: dict[str, Any] = {}
        # Memoized implicit (output-type-derived) perms, keyed by type name.
        self._implicit: dict[str, frozenset[str] | None] = {}
        # Memoized pruned NODE clones per Django model, so a filter input can
        # be measured against the very types the clone serves its rows with.
        self._serving: dict[Any, list[Any]] = {}

    # -- entry point -------------------------------------------------------- #
    def run(self) -> GraphQLSchema:
        """Build and return the pruned schema.

        ``GraphQLSchema`` keeps only root-reachable types plus whatever is
        forwarded via ``types=``. A surviving object type that implements a
        surviving interface but is never returned DIRECTLY by any field (only
        via the interface) would otherwise fall out of the pruned ``type_map``,
        leaving ``possible_types`` empty and breaking inline-fragment queries.
        We forward the CLONES (not the source instances — identity must stay
        within the pruned universe) of those implementers via ``types=``, so the
        interface keeps its implementers exactly like the FULL schema does.
        """
        self._compute_filtered_fields()
        self._compute_survivors()
        query = self._clone_root(self._full.query_type)
        mutation = self._clone_root(self._full.mutation_type)
        subscription = self._clone_root(self._full.subscription_type)
        # Roots are cloned first so ``_clones`` reflects everything reachable
        # through fields; the implementer forward then only needs to add the
        # interface-only-reachable object clones.
        implementer_types = self._forwarded_implementer_clones()
        return GraphQLSchema(
            query=query,
            mutation=mutation,
            subscription=subscription,
            types=implementer_types or None,
            directives=self._full.directives,
            extensions=dict(self._full.extensions or {}),
        )

    def _forwarded_implementer_clones(self) -> list[GraphQLObjectType]:
        """Return the surviving object-type clones to force into the schema.

        Mirrors ``DjangoGraphQLSchema._native_types_for_forwarding``: an object
        type that implements a SURVIVING interface must stay in the type map
        even when no surviving field returns it directly. Only SURVIVORS are
        forwarded (the survivor set is the source of truth) — a type the
        fixpoint dropped is never resurrected. Cloning is idempotent and
        memoized, so a type already cloned via a field ride-through is returned
        as the SAME instance (no duplicate-name).
        """
        # Single-level-interface assumption: this only checks the DIRECT
        # interfaces of an object type (gtype.interfaces), not any interfaces
        # THOSE interfaces might themselves implement. This library only
        # generates "object type implements interface" — it never generates
        # interface-implementing-interface hierarchies — so there is no deeper
        # level to walk here. If that ever changes, this forwarding check would
        # need to walk the interface chain transitively.
        forwarded: list[GraphQLObjectType] = []
        for name in self._survivors:
            gtype = self._full.type_map[name]
            if not is_object_type(gtype):
                continue
            if any(iface.name in self._survivors for iface in gtype.interfaces):
                forwarded.append(self._clone_named(gtype))
        return forwarded

    # -- phase 1a: per-field perm filtering --------------------------------- #
    def _compute_filtered_fields(self) -> None:
        """Compute, per object / interface type, the fields clearing the perms."""
        for name, gtype in self._full.type_map.items():
            if name.startswith("__"):
                continue
            if is_object_type(gtype) or is_interface_type(gtype):
                self._filtered_fields[name] = {
                    field_name: gql_field
                    for field_name, gql_field in gtype.fields.items()
                    if self._field_permitted(gql_field)
                }
            elif is_input_object_type(gtype):
                self._filtered_input_fields[name] = {
                    field_name: ifield
                    for field_name, ifield in gtype.fields.items()
                    if self._input_field_permitted(ifield)
                }

    def _field_permitted(self, gql_field: GraphQLField) -> bool:
        """Return whether *gql_field* clears the caller's permissions.

        An explicit ``gdx_required_perms`` stamp always wins: a plain
        ``frozenset`` must be a subset of *granted*, and a subscription
        per-action ``dict`` is permitted iff at least one action-value survives.

        An UNTAGGED field falls back to the IMPLICIT label of its output type
        (:func:`~django_graphex.core.perm_labels.implicit_perms_for_type`). Only
        the generated CRUD / mutation / subscription ROOT fields are stamped at
        compile time; relation and nested-list fields are built deep inside the
        output compiler with no permission context, so without this fallback
        they would be "untagged == public" and a caller whose direct roots for
        the TARGET model were pruned away could still read its rows by
        traversing the relation. A field returning anything that is not a
        generated model-backed type (a scalar, an enum, a plain object) implies
        nothing and stays public, exactly as before.
        """
        perms = (gql_field.extensions or {}).get("gdx_required_perms")
        if perms is None:
            implicit = self._implicit_perms(gql_field.type)
            return implicit is None or implicit <= self._granted
        if isinstance(perms, dict):
            return bool(self._surviving_actions(perms))
        return frozenset(perms) <= self._granted

    def _implicit_perms(self, gtype: Any) -> frozenset[str] | None:
        """Return the output type's implicit read perms, memoized by type name.

        The FULL schema is handed along so an interface's label is the union
        over the implementors this schema mounts rather than over every one
        registered in the process. It must be the same schema
        ``perm_labels.implicit_label_set`` was built from — the caller
        intersects the granted permissions with that label set before this runs,
        so a label the two disagree about is stripped and the field disappears
        for everyone.

        Args:
            gtype: The field's (possibly list- / non-null-wrapped) output type.

        Returns:
            The target model's read permissions, or ``None`` when the output
            type is not a generated model-backed type.
        """
        named = get_named_type(gtype)
        name = named.name
        if name not in self._implicit:
            self._implicit[name] = implicit_perms_for_type(named, self._full)
        return self._implicit[name]

    def _surviving_actions(self, perms: dict[str, Any]) -> set[str]:
        """Return the subscribe action-values whose perms the caller holds.

        ``all_actions`` survives only when every single action-value survives.
        """
        singles = {
            action
            for action, action_perms in perms.items()
            if action != _ALL_ACTIONS_KEY and frozenset(action_perms) <= self._granted
        }
        all_singles = {a for a in perms if a != _ALL_ACTIONS_KEY}
        surviving = set(singles)
        if (
            _ALL_ACTIONS_KEY in perms
            and all_singles
            and singles == all_singles
            and frozenset(perms[_ALL_ACTIONS_KEY]) <= self._granted
        ):
            surviving.add(_ALL_ACTIONS_KEY)
        return surviving

    # -- phase 1b: survivor fixpoint ---------------------------------------- #
    def _compute_survivors(self) -> None:
        """Fixpoint the survivor set until no type is left empty.

        A named object / interface survives iff it retains at least one field
        once fields referencing non-survivors are dropped; a union survives iff
        at least one member survives.
        """
        candidates = {name for name in self._full.type_map if not name.startswith("__")}
        changed = True
        while changed:
            changed = False
            for name in list(candidates):
                if self._is_empty(name, candidates):
                    candidates.discard(name)
                    changed = True
        self._survivors = candidates

    def _is_empty(self, name: str, candidates: set[str]) -> bool:
        """Return whether the named type is empty relative to *candidates*."""
        gtype = self._full.type_map[name]
        if is_object_type(gtype) or is_interface_type(gtype):
            return not any(
                self._field_survives(gql_field, candidates)
                for gql_field in self._filtered_fields[name].values()
            )
        if is_union_type(gtype):
            return not any(m.name in candidates for m in gtype.types)
        if is_input_object_type(gtype):
            return not any(
                self._input_survives(ifield.type, candidates)
                for ifield in self._filtered_input_fields[name].values()
            )
        return False

    def _field_survives(self, gql_field: GraphQLField, candidates: set[str]) -> bool:
        """Return whether a permitted field is still usable at all.

        A field needs BOTH a surviving output type and surviving ARGUMENT types.
        The argument half is what propagates an emptied input object upward: an
        input the caller may not fill a single field of cannot be emitted (a
        zero-field input object is an invalid schema), so the field that takes
        it goes instead — the mutation root disappears exactly as it would had
        its own stamp been unheld.
        """
        return self._output_survives(gql_field.type, candidates) and all(
            self._input_survives(arg.type, candidates)
            for arg in gql_field.args.values()
        )

    def _input_survives(self, gtype: Any, candidates: set[str]) -> bool:
        """Return whether an input position's unwrapped type is still a candidate.

        Scalars and enums are always live; only input OBJECT types can be pruned
        to empty.
        """
        named = get_named_type(gtype)
        return named.name in candidates if is_input_object_type(named) else True

    def _output_survives(self, gtype: Any, candidates: set[str]) -> bool:
        """Return whether a field's unwrapped output type is still a candidate.

        Leaf types (scalars / enums) are always live — only composite object /
        interface / union types can be pruned to empty in an OUTPUT position
        (the input side has its own emptiness rule, ``_input_survives``). A
        field's output type is always a named (possibly wrapped) type, so
        ``get_named_type`` never yields ``None`` here.
        """
        named = get_named_type(gtype)
        if is_object_type(named) or is_interface_type(named) or is_union_type(named):
            return named.name in candidates
        return True

    # -- phase 2: clone-on-write rebuild ------------------------------------ #
    def _clone_root(self, root: Any) -> GraphQLObjectType | None:
        """Clone a root type, or return ``None`` when it did not survive."""
        if root is None or root.name not in self._survivors:
            return None
        return self._clone_named(root)

    def _clone_named(self, gtype: Any) -> Any:
        """Return the pruned clone of a named type, memoized by name."""
        name = gtype.name
        cached = self._clones.get(name)
        if cached is not None:
            return cached
        if is_object_type(gtype):
            clone: Any = self._clone_composite(gtype, GraphQLObjectType)
        elif is_interface_type(gtype):
            clone = self._clone_composite(gtype, GraphQLInterfaceType)
        elif is_union_type(gtype):
            clone = self._clone_union(gtype)
        elif is_enum_type(gtype):
            clone = GraphQLEnumType(**gtype.to_kwargs())
        elif is_input_object_type(gtype):
            clone = self._clone_input(gtype)
        else:
            # Scalars (and any other leaf) carry no perm-gated members and can be
            # shared identity-safe across the pruned universe.
            clone = gtype
        self._clones[name] = clone
        return clone

    def _clone_composite(self, gtype: Any, cls: type) -> Any:
        """Clone an object / interface, thunking its field / interface maps.

        Thunks defer resolution until after the clone is memoized so
        self-references and cycles resolve against the pruned universe.
        """
        kwargs = gtype.to_kwargs()
        kwargs["fields"] = lambda g=gtype: self._rebuild_fields(g.name)
        kwargs["interfaces"] = lambda g=gtype: self._rebuild_interfaces(g)
        return cls(**kwargs)

    def _clone_union(self, gtype: GraphQLUnionType) -> GraphQLUnionType:
        """Clone a union, keeping only its surviving member types."""
        # graphql-core accepts a thunk for ``types`` at runtime; cast to a plain
        # dict so the assignment does not clash with the narrower TypedDict.
        kwargs: dict[str, Any] = dict(gtype.to_kwargs())
        kwargs["types"] = lambda g=gtype: [
            self._clone_named(m) for m in g.types if m.name in self._survivors
        ]
        return GraphQLUnionType(**kwargs)

    def _clone_input(self, gtype: Any) -> Any:
        """Clone an input object type, dropping the fields the caller may not use.

        Only NESTED-object input fields carry an explicit
        ``gdx_required_perms`` stamp, so every input field that exists today is
        unaffected. Dropping one is safe: a nested input field is never NonNull
        at the parent level.

        A type that loses EVERY field is not cloned at all — the fixpoint has
        already dropped it from the survivors, and ``_field_survives`` has
        already removed the argument (and with it the root field) that referenced
        it. This method is therefore only ever reached for a type with at least
        one surviving field, and it needs no per-field survivor filter of its
        own: the only stamped input fields are the nested-child ones, and a
        nested child input is built with ``nested_fields={}``, so it carries no
        stamp and can never itself be pruned to empty. No input object in the
        generated universe references an emptied input object.
        """
        kwargs = gtype.to_kwargs()
        kwargs["fields"] = lambda g=gtype: {
            fname: self._clone_input_field(ifield)
            for fname, ifield in self._filtered_input_fields[g.name].items()
            if self._filter_key_survives(g, ifield)
        }
        return type(gtype)(**kwargs)

    def _filter_key_survives(self, gtype: Any, ifield: Any) -> bool:
        """Return whether a filter input's key still names something the clone serves.

        The projection boundary is not only ``Meta.only_fields`` -- a PRUNE
        publishes less than the schema it clones, and the ordering axis already
        re-derives its allowlist against the clone
        (:func:`_rescope_paginated_resolver`). The filter argument rode through
        verbatim, so a caller who lost the ``author`` relation kept
        ``filter: {author: {name: {icontains: ...}}}``: a prefix oracle over a
        model the pruned SDL does not mount.

        Only a generated ``<Model>FilterInput`` carries a model on its ``gdx``
        payload; every other input object (the per-field ``<Field>Lookups``, the
        mutation inputs) has no column to measure and rides through untouched.

        Evaluated INSIDE the input clone's field thunk, which is what lets it
        read the pruned node clones: they are memoized by name before their own
        field thunks run, so forcing one from here resolves against the pruned
        universe without re-entering this thunk (an argument's input type is
        remapped to the memoized clone, never forced).

        Args:
            gtype: The SOURCE input object type being cloned.
            ifield: One of its permitted input fields.

        Returns:
            True when the key survives into the pruned schema.
        """
        model = getattr((gtype.extensions or {}).get("gdx"), "model", None)
        if model is None:
            return True
        from django_graphex.filtering.native_schema import filter_key_is_published

        return filter_key_is_published(
            model, getattr(ifield, "out_name", None), self._serving_clones(model)
        )

    def _serving_clones(self, model: Any) -> list[Any]:
        """Return the pruned NODE clones that serve a model's rows.

        A ``<Model>ListType`` container carries the same model on its payload
        but publishes only ``results`` and a count, so the projection boundary
        is measured on the node it paginates and containers are skipped here.

        More than one node type per model is normal (two ``DjangoObjectType``s
        over one model share the single ``<Model>FilterInput`` name), so the key
        has to clear ALL of them -- the same union rule the build-time guard
        applies.

        Args:
            model: The Django model whose serving types are wanted.

        Returns:
            The memoized clones, in a stable order.
        """
        clones = self._serving.get(model)
        if clones is None:
            clones = [
                self._clone_named(self._full.type_map[name])
                for name in sorted(self._survivors)
                if self._is_node_type_for(self._full.type_map[name], model)
            ]
            self._serving[model] = clones
        return clones

    @staticmethod
    def _is_node_type_for(gtype: Any, model: Any) -> bool:
        """Return whether a type is a generated NODE type over *model*.

        Args:
            gtype: A named type from the full schema.
            model: The Django model to match.

        Returns:
            True for a model-backed object type that is not a list container.
        """
        if not is_object_type(gtype):
            return False
        meta = getattr((gtype.extensions or {}).get("gdx"), "_meta", None)
        return (
            getattr(meta, "model", None) is model
            and getattr(meta, "results_field_name", None) is None
        )

    def _input_field_permitted(self, ifield: Any) -> bool:
        """Return whether an input field clears the caller's permissions.

        Only the EXPLICIT stamp is tested -- never the output-type implicit
        fallback ``_field_permitted`` applies -- so an unlabeled input field
        stays exactly as public as it is today.

        Args:
            ifield: The input field to test.

        Returns:
            True when the field carries no stamp or the caller holds it.
        """
        perms = (ifield.extensions or {}).get("gdx_required_perms")
        return perms is None or frozenset(perms) <= self._granted

    def _clone_input_field(self, ifield: Any) -> Any:
        """Clone a single input field, remapping its type."""
        kwargs = ifield.to_kwargs()
        kwargs["type_"] = self._remap_type(ifield.type)
        return type(ifield)(**kwargs)

    def _rebuild_fields(self, type_name: str) -> dict[str, GraphQLField]:
        """Return the surviving, type-remapped field map for a cloned type."""
        return {
            fname: self._rebuild_field(gql_field)
            for fname, gql_field in self._filtered_fields[type_name].items()
            if self._field_survives(gql_field, self._survivors)
        }

    def _rebuild_field(self, gql_field: GraphQLField) -> GraphQLField:
        """Clone a field, remapping its output type and pruning its action enum.

        ``subscribe`` / ``deprecation_reason`` / ``description`` / ``extensions``
        ride through ``to_kwargs()`` verbatim. So did ``resolve`` — and a
        paginating results resolver carries the FULL schema's ordering allowlist
        inside it, which is a pre-prune answer to a post-prune question; see
        ``_rescope_paginated_resolver``.
        """
        kwargs = gql_field.to_kwargs()
        kwargs["type_"] = self._remap_type(gql_field.type)
        rescoped = _rescope_paginated_resolver(
            kwargs.get("resolve"), kwargs["type_"], self._remap_type
        )
        if rescoped is not None:
            kwargs["resolve"] = rescoped
        args = kwargs.get("args")
        if args:
            perms = (gql_field.extensions or {}).get("gdx_required_perms")
            surviving = (
                self._surviving_actions(perms) if isinstance(perms, dict) else None
            )
            kwargs["args"] = {
                aname: self._rebuild_arg(aname, arg, surviving)
                for aname, arg in args.items()
            }
        return GraphQLField(**kwargs)

    def _rebuild_arg(
        self, name: str, arg: Any, surviving_actions: set[str] | None
    ) -> Any:
        """Clone an argument, remapping its type and pruning the action enum.

        The subscription ``action`` argument's enum is rebuilt to keep only the
        surviving action-values; every other argument type is remapped verbatim.
        """
        kwargs = arg.to_kwargs()
        if (
            surviving_actions is not None
            and name == "action"
            and _is_action_enum(arg.type)
        ):
            kwargs["type_"] = self._prune_action_enum(arg.type, surviving_actions)
        else:
            kwargs["type_"] = self._remap_type(arg.type)
        return type(arg)(**kwargs)

    def _prune_action_enum(self, gtype: Any, surviving_actions: set[str]) -> Any:
        """Rebuild the action enum keeping only surviving values (wrap preserved)."""
        wrap_nonnull = isinstance(gtype, GraphQLNonNull)
        enum = get_named_type(gtype)
        enum_kwargs = enum.to_kwargs()
        enum_kwargs["values"] = {
            key: value
            for key, value in enum.values.items()
            if value.value in surviving_actions
        }
        pruned_enum = GraphQLEnumType(**enum_kwargs)
        return GraphQLNonNull(pruned_enum) if wrap_nonnull else pruned_enum

    def _rebuild_interfaces(self, gtype: Any) -> list[GraphQLInterfaceType]:
        """Return the surviving interfaces a cloned type implements."""
        return [
            self._clone_named(iface)
            for iface in gtype.interfaces
            if iface.name in self._survivors
        ]

    def _remap_type(self, gtype: Any) -> Any:
        """Return *gtype* with its named type replaced by its pruned clone.

        List / NonNull wrappers are preserved around the remapped named type.
        """
        if isinstance(gtype, GraphQLNonNull):
            return GraphQLNonNull(self._remap_type(gtype.of_type))
        if isinstance(gtype, GraphQLList):
            return GraphQLList(self._remap_type(gtype.of_type))
        return self._clone_named(gtype)


def _rescope_paginated_resolver(resolve: Any, pruned_type: Any, remap: Any) -> Any:
    """Return a results resolver whose ordering allowlist answers for the PRUNE.

    Which columns "ordering" may name is derived from the node type serving the
    rows, and it is stamped on the paginator when the list container is built --
    once, against the FULL schema's node type. Cloning the field carries that
    resolver through verbatim, so the pruned schema asked the full schema's
    question: a caller who lost the "author" relation (and with it the whole
    author type) kept "ordering: -authorId", ranking the rows by a foreign key
    the pruned SDL denies exists.

    The paginator instance cannot simply be re-stamped: one instance backs the
    full schema and every pruned variant, so writing on it would let the last
    prune decide every other caller's allowlist -- the same reason the container
    stamps a COPY. This stamps another copy, per clone, and rebuilds the results
    resolver around it.

    The stamp is a THUNK here, unlike the list container's, which is a plain
    value. This runs from INSIDE "_rebuild_fields", and "pruned_type" is a clone
    whose own field map is a thunk back into that same walk; the clone graph is
    cyclic (a node reaches its own list container through any relation) and
    graphql-core caches "fields" only once a thunk RETURNS. Reading the pruned
    fields here is therefore re-entrant by construction. The models this suite
    ships cannot close the loop through a second paginated field, so the guard
    is structural rather than a reproduction -- do not make it eager to match
    the container without adding a self-referential fixture first.

    Both paginating shapes are covered, because both are reachable from a root
    and both hold the allowlist the same way -- the two shapes
    "utils._resolve_results_paginator" already enumerates for the optimizer:

    - the list container's results field, a closure over a
      "NativePaginationField", rebuilt around the rescoped copy;
    - a flat "DjangoFilterPaginateListField", a partial bound to the graphene
      field that paginates in its own resolver, rebound to a copy of that field.

    A THIRD field on the same container needs the same answer and cannot be
    recognised the same way: "pageInfo". Its output type is the shared
    "CursorPageInfo", which names no model, so "pruned_type" says nothing about
    whose columns it may page by -- and it is the field where the allowlist
    matters MOST, because a keyset cursor prints the ordering value and the row
    key into "startCursor" / "endCursor" rather than merely ranking by them.
    Leaving it on the pre-prune paginator gave one container two answers, and
    the cursor was the one that spelled the value out. So the paginator stamps
    the node it pages onto that resolver ("get_native_page_info_field") and the
    node is remapped to THIS clone here.

    Anything else -- a plain field, a custom resolver that owns its own scoping
    -- returns "None" and rides through unchanged.

    Args:
        resolve: The source field's resolver, or "None".
        pruned_type: The field's already-remapped output type.
        remap: The pruner's type remapper, used to reach the pruned clone of a
            node type that the field's own output type cannot name.

    Returns:
        A replacement resolver, or "None" to keep the original.
    """
    from copy import copy
    from functools import partial

    from graphql import default_field_resolver

    from django_graphex.paginations.pagination import (
        BaseDjangoGraphqlPagination,
        projected_ordering_attnames,
    )
    from django_graphex.paginations.utils import NativePaginationField

    stamped_node = getattr(resolve, "page_info_node_type", None)
    node = get_named_type(pruned_type if stamped_node is None else remap(stamped_node))
    gdx = (getattr(node, "extensions", None) or {}).get("gdx")
    model = getattr(getattr(gdx, "_meta", None), "model", None)
    if model is None:
        return None

    def _rescoped(paginator: Any) -> Any:
        scoped = copy(paginator)
        scoped.ordering_allowed_attnames = lambda: projected_ordering_attnames(
            model, node
        )
        return scoped

    paginator = getattr(resolve, "page_info_paginator", None)
    if isinstance(paginator, BaseDjangoGraphqlPagination):
        return _rescoped(paginator).get_native_page_info_field(node).resolve

    paginator = getattr(resolve, "paginator_instance", None)
    if isinstance(paginator, BaseDjangoGraphqlPagination):
        return NativePaginationField(
            type=node, paginator=_rescoped(paginator)
        ).wrap_resolve(default_field_resolver)

    func = getattr(resolve, "func", None)
    bound = getattr(func, "__self__", None)
    paginator = getattr(bound, "pagination", None)
    if isinstance(paginator, BaseDjangoGraphqlPagination):
        field_clone = copy(bound)
        field_clone.pagination = _rescoped(paginator)
        return partial(
            getattr(field_clone, func.__name__), *resolve.args, **resolve.keywords
        )
    return None


def _is_action_enum(gtype: Any) -> bool:
    """Return whether *gtype* (possibly wrapped) is a subscription action enum."""
    named = get_named_type(gtype)
    return is_enum_type(named) and named.name.endswith(_ACTION_ENUM_SUFFIX)
