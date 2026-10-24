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
fragment spreads (cyclic documents are rejected up front) -- a fragment cannot be used to bypass it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from graphql import GraphQLError, OperationType, get_named_type
from graphql.language import (
    DocumentNode,
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
)
from graphql.validation import ValidationRule

from . import settings as _settings
from ._directives_eval import is_selection_skipped
from ._fragment_cycles import find_fragment_cycle
from .core.compat import _gdx_meta as _native_gdx_meta

if TYPE_CHECKING:
    from graphql import GraphQLNamedType, OperationDefinitionNode, SelectionSetNode
    from graphql.validation import ValidationContext

#: Hard ceiling on nested object levels, applied even when MAX_QUERY_DEPTH is
#: None or larger. Python's stack cannot execute deeper documents: graphql-core
#: completes each level through several nested frames, and with real (cyclic)
#: data a request under pytest's deeper stack fails with an internal error from
#: about 130 levels (127 ran cleanly, 130 failed); its parser gives up on
#: inline documents at about 232. Fragments hide depth from the parser, so the
#: rule enforces this value for them too. 100 leaves a safety margin below the
#: measured execution failure point.
_MAX_STRUCTURAL_DEPTH = 100

__all__ = ("DepthLimitValidationRule", "run_validation")


def run_validation(
    validate_fn: Callable[..., Any], *args: Any, **kwargs: Any
) -> list[GraphQLError]:
    """Run graphql-core validation, answering stack exhaustion as a client error.

    graphql-core's own rules (for example "NoFragmentCycles") recurse once per
    fragment link, so a long but acyclic fragment chain can exhaust the Python
    stack inside the library, before or beside this module's iterative rules.
    Such a document is the client's fault, not a server fault, so it becomes a
    depth error instead of an HTTP 500. Only validation is guarded: errors raised
    while resolving fields are never routed through here.

    Args:
        validate_fn: The validate callable (graphql-core's "validate").
        *args: Positional arguments forwarded to it.
        **kwargs: Keyword arguments forwarded to it.

    Returns:
        The validation errors, or one depth error when the stack ran out.
    """
    try:
        return list(validate_fn(*args, **kwargs))
    except RecursionError:
        return [
            GraphQLError(
                "Query is nested too deeply to be validated.",
                extensions={"code": "QUERY_TOO_DEEP"},
            )
        ]


class _Constraint(NamedTuple):
    """Represent an active depth budget below its origin."""

    limit: int
    origin: int
    label: str


def _type_max_depth(named_type: GraphQLNamedType) -> int | None:
    """Return the maximum depth declared on a type, when configured.

    Reads it via the internal metadata shim, which tries the Graphene metadata
    first and falls back to the native extension metadata. This ensures both backends
    work through a single read-site.

    Args:
        named_type: The unwrapped (named) graphql-core type.

    Returns:
        The non-negative depth limit, or None when not configured or invalid.
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
        #: (fragment, parent type, remaining budget) triples already proven
        #: violation-free, so a re-spread can be skipped instead of re-walked.
        self._clean_spreads: set[tuple[str, str, int | None]] = set()
        #: Counts cycle-guard short-circuits so truncated walks are not cached.
        self._cycle_cuts = 0
        self._cyclic_fragments = False

    def enter_document(self, node: DocumentNode, *_args: Any) -> None:
        """Check the fragment graph before any operation's depth expansion.

        Args:
            node: The document definition root.
            *_args: Additional visitor arguments supplied by graphql-core.
        """
        self._cyclic_fragments = find_fragment_cycle(node) is not None

    def enter_operation_definition(
        self, node: OperationDefinitionNode, *_args: Any
    ) -> None:
        """Analyze a single operation's selection tree for depth violations.

        Args:
            node: The operation definition AST node.
            *_args: Additional visitor arguments supplied by graphql-core.
        """
        if self._cyclic_fragments:
            return
        schema = self.context.schema
        root_type = {
            OperationType.QUERY: schema.query_type,
            OperationType.MUTATION: schema.mutation_type,
            OperationType.SUBSCRIPTION: schema.subscription_type,
        }.get(node.operation)
        if root_type is None:
            return

        constraints: list[_Constraint] = []
        # Read via the module so `override_settings` (which rebuilds the cached
        # settings object) is honored.
        global_max = _settings.graphql_api_settings.MAX_QUERY_DEPTH
        # None is the ONLY disabling value: a limit of 0 means "allow nothing",
        # and the settings reader refuses it rather than let it read as falsy
        # here and silently switch the guard off.
        if global_max is not None:
            # Label the budget with the operation the client actually sent.
            # Both subscription transports now validate with the shared rule
            # tuple, so a hardcoded "query" would refuse a subscription for an
            # operation it never wrote.
            constraints.append(_Constraint(int(global_max), 0, node.operation.value))
        # Last, so a stricter configured limit is the one reported.
        constraints.append(_Constraint(_MAX_STRUCTURAL_DEPTH, 0, node.operation.value))

        self._walk(node.selection_set, root_type, 0, constraints)

    def _walk(
        self,
        selection_set: SelectionSetNode,
        parent_type: GraphQLNamedType,
        depth: int,
        constraints: list[_Constraint],
    ) -> None:
        """Walk a selection tree, counting object nesting against budgets.

        The walk keeps an explicit stack of selection iterators instead of
        recursing, so neither a long fragment chain nor deep inline nesting can
        exhaust the Python stack. Fragment cycles are rejected up front; the
        path guard is a defense for callers that reach this walker directly.

        Args:
            selection_set: The selection set to walk.
            parent_type: The (named) type the selections are resolved against.
            depth: The object-nesting depth of the selection set from the root.
            constraints: The active depth budgets.
        """
        schema = self.context.schema
        #: (selections, parent type, depth, constraints, memo key or None, cycle
        #: cuts when the spread was entered)
        stack: list[tuple[Any, GraphQLNamedType, int, list[_Constraint], Any, int]] = [
            (iter(selection_set.selections), parent_type, depth, constraints, None, 0)
        ]
        #: Fragment names on the current path (the cycle guard).
        active: set[str] = set()
        while stack:
            selections, parent_type, depth, constraints, key, cuts_before = stack[-1]
            fields = getattr(parent_type, "fields", None)
            for selection in selections:
                # Honor @skip / @include directives.  Validation rules run
                # before variable binding, so variable_values is always empty
                # here — the conservative policy applies (unresolvable
                # variable conditions are never skipped).
                if is_selection_skipped(selection, {}):
                    continue

                if isinstance(selection, FieldNode):
                    if (
                        selection.selection_set is None
                        or selection.name.value.startswith("__")
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
                    stack.append(
                        (
                            iter(selection.selection_set.selections),
                            field_type,
                            child_depth,
                            child_constraints,
                            None,
                            0,
                        )
                    )
                    break

                if isinstance(selection, InlineFragmentNode):
                    # A type condition narrows the type but adds no nesting level.
                    frag_type = parent_type
                    if selection.type_condition is not None:
                        frag_type = (
                            schema.get_type(selection.type_condition.name.value)
                            or parent_type
                        )
                    stack.append(
                        (
                            iter(selection.selection_set.selections),
                            frag_type,
                            depth,
                            constraints,
                            None,
                            0,
                        )
                    )
                    break

                if isinstance(selection, FragmentSpreadNode):
                    name = selection.name.value
                    if name in active:
                        self._cycle_cuts += 1
                        continue  # cyclic spread; the schema rejects it separately
                    fragment = self.context.get_fragment(name)
                    if fragment is None:
                        continue
                    frag_type = (
                        schema.get_type(fragment.type_condition.name.value)
                        or parent_type
                    )
                    # Only the tightest inherited budget decides whether this
                    # subtree can violate anything: every constraint is checked
                    # against the same depth, and constraints created inside
                    # the subtree depend on its shape alone.  So the walk's
                    # verdict is a function of (fragment, parent type, tightest
                    # budget) -- memoize it, or a fragment reachable by K paths
                    # is walked K times (exponential for a fan-out document).
                    budget = min(
                        (c.limit - (depth - c.origin) for c in constraints),
                        default=None,
                    )
                    spread_key = (name, frag_type.name, budget)
                    if spread_key in self._clean_spreads:
                        continue
                    active.add(name)
                    stack.append(
                        (
                            iter(fragment.selection_set.selections),
                            frag_type,
                            depth,
                            constraints,
                            spread_key,
                            self._cycle_cuts,
                        )
                    )
                    break
            else:
                # Exhausted without a violation (a violation returns above), so
                # a finished spread frame is proven clean.
                stack.pop()
                if key is not None:
                    active.discard(key[0])
                    if cuts_before == self._cycle_cuts:
                        # A walk truncated by the cycle guard is path-dependent,
                        # so only untruncated clean walks may be cached.
                        self._clean_spreads.add(key)

    def _report(self, constraint: _Constraint, node: FieldNode) -> None:
        """Record a single depth-limit error for the operation.

        Args:
            constraint: The budget that was exceeded.
            node: The field node at which the limit was exceeded.
        """
        self.report_error(
            GraphQLError(
                "Query exceeds the maximum nesting depth of {limit} for "
                "'{label}'.".format(limit=constraint.limit, label=constraint.label),
                node,
                extensions={"code": "QUERY_TOO_DEEP"},
            )
        )
