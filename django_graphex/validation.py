"""Query depth limiting via a graphql-core validation rule.

Depth limiting rejects abusively nested queries (e.g. "a { b { c { d ... } } }")
*before* execution. The limit is the number of **nested object levels** below a
field; scalar leaves do not count. Two sources combine, most-restrictive wins:

* a global default from the "MAX_QUERY_DEPTH" setting (measured from the query
  root), and
* a per-type "Meta.max_depth" declared on a "DjangoObjectType" /
  "DjangoListObjectType" / "DjangoModelType" (measured from any field
  returning that type).

The rule resolves field types from the schema, so it follows inline and named
fragment spreads (cycles are guarded) -- a fragment cannot be used to bypass it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from graphql import GraphQLError, OperationType, get_named_type
from graphql.language import (
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
)
from graphql.validation import ValidationRule

from . import settings as _settings
from ._directives_eval import is_selection_skipped
from .core.compat import _gdx_meta as _native_gdx_meta

if TYPE_CHECKING:
    from graphql import GraphQLNamedType, OperationDefinitionNode, SelectionSetNode
    from graphql.validation import ValidationContext

__all__ = ("DepthLimitValidationRule",)


class _Constraint(NamedTuple):
    """An active depth budget: ``limit`` levels are allowed below ``origin``."""

    limit: int
    origin: int
    label: str


def _type_max_depth(named_type: GraphQLNamedType) -> int | None:
    """Return the ``max_depth`` declared on a type, or ``None``.

    Reads it via the ``_gdx_meta`` shim, which tries
    ``graphene_type._meta`` first (graphene path) and falls back to
    ``extensions["gdx"]._meta`` (native path).  This ensures both backends
    work through a single read-site.

    Args:
        named_type: The unwrapped (named) graphql-core type.

    Returns:
        The non-negative depth limit, or ``None`` when not configured/invalid.
    """
    try:
        meta = _native_gdx_meta(named_type)
    except AttributeError:
        return None
    value = getattr(meta, "max_depth", None)
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class DepthLimitValidationRule(ValidationRule):
    """Reject queries that nest objects deeper than the configured limit(s).

    Add it to a view's "validation_rules" (the library's "GraphQLView"
    includes it by default). With no global setting and no type declaring
    "max_depth" it is a no-op.
    """

    def __init__(self, context: ValidationContext) -> None:
        """Capture the validation context.

        Args:
            context: The graphql-core validation context.
        """
        super().__init__(context)
        self._errored = False

    def enter_operation_definition(
        self, node: OperationDefinitionNode, *_args: Any
    ) -> None:
        """Analyze a single operation's selection tree for depth violations.

        Args:
            node: The operation definition AST node.
        """
        schema = self.context.schema
        root_type = {
            OperationType.QUERY: schema.query_type,
            OperationType.MUTATION: schema.mutation_type,
            OperationType.SUBSCRIPTION: schema.subscription_type,
        }.get(node.operation)
        if root_type is None:
            return

        self._errored = False
        constraints: list[_Constraint] = []
        # Read via the module so `override_settings` (which rebuilds the cached
        # settings object) is honored.
        global_max = _settings.graphql_api_settings.MAX_QUERY_DEPTH
        if global_max:
            constraints.append(_Constraint(int(global_max), 0, "query"))

        self._walk(node.selection_set, root_type, 0, constraints, frozenset())

    def _walk(
        self,
        selection_set: SelectionSetNode,
        parent_type: GraphQLNamedType,
        depth: int,
        constraints: list[_Constraint],
        seen_fragments: frozenset[str],
    ) -> None:
        """Recurse a selection set, counting object nesting against budgets.

        Args:
            selection_set: The selection set to walk.
            parent_type: The (named) type the selections are resolved against.
            depth: The current object-nesting depth from the operation root.
            constraints: The active depth budgets.
            seen_fragments: Fragment names already entered (cycle guard).
        """
        if self._errored:
            return

        fields = getattr(parent_type, "fields", None)

        for selection in selection_set.selections:
            # Honor @skip / @include directives.  Validation rules run before
            # variable binding, so variable_values is always empty here — the
            # conservative policy applies (unresolvable variable conditions are
            # never skipped).
            if is_selection_skipped(selection, {}):
                continue

            if isinstance(selection, FieldNode):
                if selection.selection_set is None or selection.name.value.startswith(
                    "__"
                ):
                    continue  # scalar leaf or introspection meta-field
                child_depth = depth + 1
                for constraint in constraints:
                    if child_depth - constraint.origin > constraint.limit:
                        self._report(constraint, selection)
                        return
                if not fields or selection.name.value not in fields:
                    continue
                field_type = get_named_type(fields[selection.name.value].type)
                if field_type is None:
                    continue
                child_constraints = constraints
                max_depth = _type_max_depth(field_type)
                if max_depth is not None:
                    child_constraints = [
                        *constraints,
                        _Constraint(max_depth, child_depth, field_type.name),
                    ]
                self._walk(
                    selection.selection_set,
                    field_type,
                    child_depth,
                    child_constraints,
                    seen_fragments,
                )

            elif isinstance(selection, InlineFragmentNode):
                # A type condition narrows the type but adds no nesting level.
                frag_type = parent_type
                if selection.type_condition is not None:
                    frag_type = (
                        self.context.schema.get_type(
                            selection.type_condition.name.value
                        )
                        or parent_type
                    )
                self._walk(
                    selection.selection_set,
                    frag_type,
                    depth,
                    constraints,
                    seen_fragments,
                )

            elif isinstance(selection, FragmentSpreadNode):
                name = selection.name.value
                if name in seen_fragments:
                    continue  # cyclic spread; the schema rejects it separately
                fragment = self.context.get_fragment(name)
                if fragment is None:
                    continue
                frag_type = (
                    self.context.schema.get_type(fragment.type_condition.name.value)
                    or parent_type
                )
                self._walk(
                    fragment.selection_set,
                    frag_type,
                    depth,
                    constraints,
                    seen_fragments | {name},
                )

            if self._errored:
                return

    def _report(self, constraint: _Constraint, node: FieldNode) -> None:
        """Record a single depth-limit error for the operation.

        Args:
            constraint: The budget that was exceeded.
            node: The field node at which the limit was exceeded.
        """
        self._errored = True
        self.report_error(
            GraphQLError(
                "Query exceeds the maximum nesting depth of {limit} for "
                "'{label}'.".format(limit=constraint.limit, label=constraint.label),
                node,
                extensions={"code": "QUERY_TOO_DEEP"},
            )
        )
