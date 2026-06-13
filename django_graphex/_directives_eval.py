"""Shared helper for evaluating @skip / @include directives.

This module provides a single public function, ``is_selection_skipped``, used
by the cost analyser (``cost.py``), the depth-limit rule (``validation.py``) and
the query-optimizer walkers (``utils.py``) to decide whether a selection should
be excluded from counting or fetch planning.

Conservative policy
-------------------
``@skip`` and ``@include`` accept a Boolean argument ``if`` that may be either a
literal (``true``/``false``) or a variable reference (``$flag``).

* **Literal** – the result is exact.
* **Variable with a bound value** – the result is exact (the caller must pass
  the current ``variable_values`` mapping).
* **Variable with no bound value** – the selection is treated as *included*
  (``is_selection_skipped`` returns ``False``).  This is the conservative,
  never-under-count policy used by validation rules that run before variable
  binding; it avoids false-negative rejections (a query that might be cheap when
  ``$flag=true`` is not wrongly allowed through when the variable is unknown).

Note on output-formatting directives
-------------------------------------
Custom application-level directives such as ``@date`` and ``@number`` are
*output-formatting* directives: they transform the value of a field that is
already being fetched.  They have **no effect on whether a field is fetched**,
and therefore do **not** affect query cost, depth, or the optimizer's
select/prefetch/only planning.  Only the built-in ``@skip`` and ``@include``
directives control selection inclusion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graphql import GraphQLError
from graphql.execution.values import get_directive_values
from graphql.type.directives import GraphQLIncludeDirective, GraphQLSkipDirective

if TYPE_CHECKING:  # pragma: no cover
    from graphql.language.ast import (
        FieldNode,
        FragmentSpreadNode,
        InlineFragmentNode,
    )

    _SelectionNode = FieldNode | FragmentSpreadNode | InlineFragmentNode

__all__ = ("is_selection_skipped",)


def _safe_get_directive_values(
    directive_def: Any,
    node: Any,
    variable_values: dict[str, Any],
) -> dict[str, Any] | None:
    """Wrap ``get_directive_values`` with conservative error handling.

    When a directive argument is a variable that has no bound value,
    ``get_directive_values`` raises ``GraphQLError`` (required argument not
    provided).  We catch that and return ``None`` so the caller treats the
    directive as absent → conservative policy (never skip on uncertainty).

    Args:
        directive_def: The ``GraphQLDirective`` to look for.
        node: The AST node to inspect.
        variable_values: The currently bound variable values.

    Returns:
        The resolved argument dict when the directive is present and all
        arguments are resolvable, or ``None`` otherwise.
    """
    try:
        return get_directive_values(
            directive_def,
            node,
            variable_values,  # type: ignore[arg-type]
        )
    except GraphQLError:
        # Unresolvable variable reference → conservative: treat as absent.
        return None


def is_selection_skipped(
    node: _SelectionNode,
    variable_values: dict[str, Any],
) -> bool:
    """Return ``True`` when the selection should be excluded from processing.

    Evaluates the ``@skip`` and ``@include`` directives on *node* using
    *variable_values* (which may be empty for validation-time calls).

    Args:
        node: A ``FieldNode``, ``InlineFragmentNode``, or ``FragmentSpreadNode``
            whose directives should be evaluated.
        variable_values: The currently bound variable values.  Pass ``{}`` when
            variables are not available (e.g. inside a validation rule); the
            function falls back to the conservative policy (never skip).

    Returns:
        ``True`` if the selection is provably skipped and should be excluded.
        ``False`` in all other cases, including when the outcome is uncertain
        due to an unresolved variable (conservative policy).
    """
    if not node.directives:
        return False

    # --- @skip(if: <value>) --------------------------------------------------
    # _safe_get_directive_values returns None when the directive is not present
    # on the node OR when the argument cannot be resolved (unbound variable).
    # We only act when the resolved ``if`` value is a concrete True boolean —
    # anything else (None, False, missing, or unresolvable variable) keeps the
    # field selected.
    skip_args = _safe_get_directive_values(GraphQLSkipDirective, node, variable_values)
    if skip_args is not None and skip_args.get("if") is True:
        return True

    # --- @include(if: <value>) -----------------------------------------------
    # When @include is present AND its ``if`` is a concrete False, the selection
    # is excluded.  If ``if`` is True, missing, or unresolvable the selection is
    # kept (conservative).
    include_args = _safe_get_directive_values(
        GraphQLIncludeDirective, node, variable_values
    )
    if include_args is not None and include_args.get("if") is False:
        return True

    return False
