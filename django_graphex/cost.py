"""Query cost analysis via a graphql-core validation rule.

Cost analysis estimates how much work a query asks for *before* execution and
rejects queries over a budget. Unlike depth limiting it captures *width × depth ×
page size* in a single number:

    cost(field) = own_cost + multiplier * sum(cost(child) for child in children)

* ``own_cost`` -- ``0`` for scalar leaves, ``1`` for object/list fields, or a
  type's ``Meta.complexity`` when declared.
* ``multiplier`` -- a list field's page size (the ``limit`` / ``page_size`` /
  ``first`` / ``last`` argument), capped at ``MAX_PAGE_SIZE``; ``1`` otherwise.

The estimate seeds enforcement (``MAX_QUERY_COST`` via
:class:`CostLimitValidationRule`) and optional reporting (``EXPOSE_QUERY_COST``
adds ``extensions.cost`` to responses, wired in ``GraphQLView``). The walk
resolves field types from the schema and follows inline + named fragments
(cycle-guarded), so fragments cannot be used to under-count.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

from graphql import GraphQLError, GraphQLList, OperationType, get_named_type
from graphql.language import (
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    IntValueNode,
    VariableNode,
)
from graphql.validation import ValidationRule

from . import settings as _settings

if TYPE_CHECKING:
    from graphql import (
        DocumentNode,
        FragmentDefinitionNode,
        GraphQLNamedType,
        GraphQLSchema,
        OperationDefinitionNode,
        SelectionSetNode,
    )

__all__ = ("CostReport", "analyze_cost", "CostLimitValidationRule")

#: Emit the "unbounded list" warning at most once per process.
_unbounded_warned = False


class CostReport(NamedTuple):
    """The estimated cost of an operation and the configured budget."""

    total: int
    max_cost: int | None


def _settings_value(name: str) -> Any:
    """Read a settings value through the module so overrides are honored."""
    return getattr(_settings.graphql_api_settings, name)


def _type_complexity(named_type: GraphQLNamedType) -> int | None:
    """Return a type's declared ``Meta.complexity``, or ``None``."""
    meta = getattr(getattr(named_type, "graphene_type", None), "_meta", None)
    value = getattr(meta, "complexity", None)
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class _CostAnalyzer:
    """Recursively estimates the cost of an operation's selection tree."""

    def __init__(
        self,
        schema: GraphQLSchema,
        get_fragment: Callable[[str], FragmentDefinitionNode | None],
        variable_values: dict[str, Any],
        variable_defaults: dict[str, Any],
    ) -> None:
        """Capture the schema, fragment resolver and variable context.

        Args:
            schema: The graphql-core schema (for type resolution).
            get_fragment: Resolves a fragment definition by name.
            variable_values: Bound variable values (empty during validation).
            variable_defaults: Default value nodes from the operation's variable
                definitions, keyed by variable name.
        """
        self._schema = schema
        self._get_fragment = get_fragment
        self._variable_values = variable_values
        self._variable_defaults = variable_defaults
        self._pagination_args = tuple(_settings_value("COST_PAGINATION_ARGS") or ())

    # -- public ----------------------------------------------------------------

    def operation_cost(self, node: OperationDefinitionNode) -> int:
        """Return the estimated cost of a single operation."""
        root_type = {
            OperationType.QUERY: self._schema.query_type,
            OperationType.MUTATION: self._schema.mutation_type,
            OperationType.SUBSCRIPTION: self._schema.subscription_type,
        }.get(node.operation)
        if root_type is None:
            return 0
        return self._selection_set_cost(node.selection_set, root_type, frozenset())

    # -- internals -------------------------------------------------------------

    def _selection_set_cost(
        self,
        selection_set: SelectionSetNode,
        parent_type: GraphQLNamedType,
        seen_fragments: frozenset[str],
    ) -> int:
        """Sum the cost of every selection at one level."""
        fields = getattr(parent_type, "fields", None)
        total = 0

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                if selection.name.value.startswith("__"):
                    continue  # introspection meta-fields are free
                if not fields or selection.name.value not in fields:
                    continue
                field_def = fields[selection.name.value]
                field_type = get_named_type(field_def.type)
                has_children = selection.selection_set is not None
                own = self._own_cost(field_type, has_children)
                if not has_children:
                    total += own
                    continue
                multiplier = self._list_multiplier(selection, field_def)
                children = self._selection_set_cost(
                    selection.selection_set, field_type, seen_fragments
                )
                total += own + multiplier * children

            elif isinstance(selection, InlineFragmentNode):
                frag_type = parent_type
                if selection.type_condition is not None:
                    frag_type = (
                        self._schema.get_type(selection.type_condition.name.value)
                        or parent_type
                    )
                total += self._selection_set_cost(
                    selection.selection_set, frag_type, seen_fragments
                )

            elif isinstance(selection, FragmentSpreadNode):
                name = selection.name.value
                if name in seen_fragments:
                    continue
                fragment = self._get_fragment(name)
                if fragment is None:
                    continue
                frag_type = (
                    self._schema.get_type(fragment.type_condition.name.value)
                    or parent_type
                )
                total += self._selection_set_cost(
                    fragment.selection_set, frag_type, seen_fragments | {name}
                )

        return total

    @staticmethod
    def _own_cost(field_type: GraphQLNamedType, has_children: bool) -> int:
        """Return a field's own weight (type complexity, or 0/1 by kind)."""
        declared = _type_complexity(field_type)
        if declared is not None:
            return declared
        return 1 if has_children else 0

    def _list_multiplier(self, node: FieldNode, field_def: Any) -> int:
        """Return the page-size multiplier for a (possibly list) field."""
        max_page_size = _settings_value("MAX_PAGE_SIZE")

        size = self._page_size_argument(node)
        if size is not None:
            return min(size, max_page_size) if max_page_size else size

        if not self._is_list_field(field_def):
            return 1

        if max_page_size:
            return int(max_page_size)
        default_page_size = _settings_value("DEFAULT_PAGE_SIZE")
        if default_page_size:
            return int(default_page_size)
        self._warn_unbounded()
        return int(_settings_value("DEFAULT_LIST_MULTIPLIER") or 1)

    def _page_size_argument(self, node: FieldNode) -> int | None:
        """Resolve the page-size argument value from the query, if present."""
        for argument in node.arguments:
            if argument.name.value not in self._pagination_args:
                continue
            value = argument.value
            if isinstance(value, IntValueNode):
                return int(value.value)
            if isinstance(value, VariableNode):
                name = value.name.value
                if name in self._variable_values:
                    try:
                        return int(self._variable_values[name])
                    except (TypeError, ValueError):
                        return None
                default = self._variable_defaults.get(name)
                if isinstance(default, IntValueNode):
                    return int(default.value)
            return None
        return None

    def _is_list_field(self, field_def: Any) -> bool:
        """Whether a field returns a list (plain list or paginated wrapper)."""
        node_type = field_def.type
        while hasattr(node_type, "of_type"):
            if isinstance(node_type, GraphQLList):
                return True
            node_type = node_type.of_type
        if isinstance(node_type, GraphQLList):
            return True
        # Library list wrappers aren't GraphQLList but expose a page-size arg.
        args = getattr(field_def, "args", None) or {}
        return any(name in args for name in self._pagination_args)

    @staticmethod
    def _warn_unbounded() -> None:
        """Warn once that costing an unbounded list relies on a soft default."""
        global _unbounded_warned
        if _unbounded_warned:
            return
        _unbounded_warned = True
        warnings.warn(
            "Query cost analysis is active but MAX_PAGE_SIZE is None: list fields "
            "without a page size are costed with DEFAULT_LIST_MULTIPLIER, so the "
            "estimate is unreliable. Set MAX_PAGE_SIZE for accurate costs.",
            RuntimeWarning,
            stacklevel=2,
        )


def _variable_defaults(node: OperationDefinitionNode) -> dict[str, Any]:
    """Map variable name -> default value node for an operation."""
    return {
        definition.variable.name.value: definition.default_value
        for definition in (node.variable_definitions or ())
    }


def analyze_cost(
    schema: GraphQLSchema,
    document: DocumentNode,
    operation_name: str | None = None,
    variable_values: dict[str, Any] | None = None,
) -> CostReport:
    """Estimate the cost of an operation in ``document``.

    Args:
        schema: The graphql-core schema.
        document: The parsed query document.
        operation_name: Which operation to cost (required when the document has
            several); the sole/first operation is used otherwise.
        variable_values: Bound variables, so variabled page sizes are exact.

    Returns:
        A :class:`CostReport` with the estimated total and the configured budget.
    """
    from graphql.language import FragmentDefinitionNode, OperationDefinitionNode

    fragments: dict[str, FragmentDefinitionNode] = {}
    operations: list[OperationDefinitionNode] = []
    for definition in document.definitions:
        if isinstance(definition, FragmentDefinitionNode):
            fragments[definition.name.value] = definition
        elif isinstance(definition, OperationDefinitionNode):
            operations.append(definition)

    operation = None
    if operation_name is not None:
        operation = next(
            (o for o in operations if o.name and o.name.value == operation_name), None
        )
    elif operations:
        operation = operations[0]

    max_cost = _settings_value("MAX_QUERY_COST")
    if operation is None:
        return CostReport(0, max_cost)

    analyzer = _CostAnalyzer(
        schema,
        fragments.get,
        variable_values or {},
        _variable_defaults(operation),
    )
    return CostReport(analyzer.operation_cost(operation), max_cost)


class CostLimitValidationRule(ValidationRule):
    """Reject queries whose estimated cost exceeds ``MAX_QUERY_COST``.

    A no-op unless ``MAX_QUERY_COST`` is set. Added to ``GraphQLView`` by
    default. Variables aren't bound during validation, so page sizes fall back to
    variable defaults and the ``MAX_PAGE_SIZE`` cap (a conservative estimate).
    """

    def enter_operation_definition(
        self, node: OperationDefinitionNode, *_args: Any
    ) -> None:
        """Cost a single operation and report when it is over budget.

        Args:
            node: The operation definition AST node.
        """
        max_cost = _settings_value("MAX_QUERY_COST")
        if not max_cost:
            return
        analyzer = _CostAnalyzer(
            self.context.schema,
            self.context.get_fragment,
            {},
            _variable_defaults(node),
        )
        total = analyzer.operation_cost(node)
        if total > max_cost:
            self.report_error(
                GraphQLError(
                    "Query cost {total} exceeds the maximum of {limit}.".format(
                        total=total, limit=max_cost
                    ),
                    node,
                    extensions={"code": "QUERY_TOO_COMPLEX"},
                )
            )
