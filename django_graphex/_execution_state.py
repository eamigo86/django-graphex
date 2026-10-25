"""Budget state shared by the middleware and the optimizer.

Two scopes exist, and they differ on purpose:

* "per execution": one GraphQL operation execution (a subscription event is its
  own execution). The state lives in a weak table keyed by the graphql-core
  executor of the execution, so it lasts exactly as long as the execution. The
  events of one subscription share their stream's executor but run one after
  the other, so that entry also remembers the root value of the current event
  and starts a fresh state when another one arrives. An info without an
  executor uses a bounded table keyed by the identity of the variable values
  and root value instead. This is what the optimizer work budget uses, and the
  fallback of the directive output budget.
* "per request": every execution of one HTTP request, so all items of a batch
  share one budget. The view binds a RequestBudget to the request
  context; the directive output budget prefers it when it is present.
"""

from __future__ import annotations

import threading
import weakref
from collections import OrderedDict
from collections.abc import MutableMapping
from typing import Any, Callable

from graphql import OperationType

#: Private attribute on a context holding its request-wide budget.
REQUEST_BUDGET_ATTR = "_graphex_request_budget"

#: Most executor-less infos (test doubles) tracked by identity; the least
#: recently used entry is dropped beyond this. Real executions never use this
#: table, so nothing can evict one that is still running.
EXECUTION_TABLE_SIZE = 1024


class RequestBudget:
    """Counter shared by every execution of one HTTP request.

    Attributes:
        used: Characters charged so far.
    """

    __slots__ = ("used",)

    def __init__(self) -> None:
        """Start with nothing used.

        The counter begins at zero and only grows.
        """
        self.used = 0


class ExecutionStates:
    """Table of per-execution state, keyed by execution identity.

    An execution is identified by its graphql-core executor, held weakly so the
    state dies with it and nothing can evict a live one. A subscription event
    shares the executor of its source stream; the events of a stream run
    sequentially, so the entry also holds the root value of the current event
    and a different root value starts a fresh state. An info without an
    executor (a test double) falls back to a bounded table keyed by the variable
    values and the root value. Its entries hold both objects, so an identity can
    only match while its execution is alive.
    """

    def __init__(self, size: int = EXECUTION_TABLE_SIZE) -> None:
        """Create an empty table.

        Args:
            size: Most fallback entries kept before the least recently used is
                dropped.
        """
        self.size = size
        self.lock = threading.Lock()
        self._by_executor: weakref.WeakKeyDictionary[Any, Any] = (
            weakref.WeakKeyDictionary()
        )
        self._table: OrderedDict[tuple[int, int], list[Any]] = OrderedDict()

    def __len__(self) -> int:
        """Count the tracked executions.

        Returns:
            The number of entries.
        """
        return len(self._table) + len(self._by_executor)

    def get(self, info: Any, factory: Callable[[], Any]) -> Any:
        """Return the state of the execution "info" belongs to.

        The caller must hold "self.lock" while it reads or updates the state.

        Args:
            info: Resolve info of any field of the execution.
            factory: Builds the state of a new execution.

        Returns:
            The execution's state object.
        """
        executor = getattr(
            getattr(getattr(info, "async_helpers", None), "track", None),
            "__self__",
            None,
        )
        if executor is not None:
            root = getattr(info, "root_value", None)
            try:
                entry = self._by_executor.get(executor)
                if entry is None or (is_subscription(info) and entry[0] is not root):
                    entry = self._by_executor[executor] = [root, factory()]
                return entry[1]
            except TypeError:  # not hashable or not weak-referenceable
                pass
        variables = getattr(info, "variable_values", None)
        root = getattr(info, "root_value", None)
        key = (id(variables), id(root))
        entry = self._table.get(key)
        if entry is None or entry[0] is not variables or entry[1] is not root:
            entry = self._table[key] = [variables, root, factory()]
            while len(self._table) > self.size:
                self._table.popitem(last=False)
        self._table.move_to_end(key)
        return entry[2]


def request_budget_of(context: Any) -> RequestBudget | None:
    """Return the request budget bound to a context, if any.

    The lookup reads the instance "__dict__" directly: "getattr" would trust a
    context whose "__getattr__" invents values (a mock). A mutable mapping (a
    dict context) carries the budget under the same private key; None has
    nothing to read.

    Args:
        context: The execution context value.

    Returns:
        The bound budget, or None.
    """
    try:
        carrier = vars(context)
    except TypeError:
        if not isinstance(context, MutableMapping):
            return None
        carrier = context
    found = carrier.get(REQUEST_BUDGET_ATTR)
    return found if isinstance(found, RequestBudget) else None


def bind_request_budget(request: Any, context: Any) -> None:
    """Share one budget across every execution of an HTTP request.

    The budget lives on the request; a context that is a different object (a
    custom "get_context") is bound to the same budget. A mutable mapping
    carries it under the private key; None, an immutable mapping or a
    "__slots__" object keeps the per-execution budget.

    Args:
        request: The incoming HTTP request.
        context: The execution context built for one execution of the request.
    """
    try:
        shared = request_budget_of(request) or RequestBudget()
        vars(request)[REQUEST_BUDGET_ATTR] = shared
        if context is request:
            return
        try:
            vars(context)[REQUEST_BUDGET_ATTR] = shared
        except TypeError:
            if isinstance(context, MutableMapping):
                context[REQUEST_BUDGET_ATTR] = shared
    except TypeError:
        return


def is_subscription(info: Any) -> bool:
    """Tell whether the execution is a subscription event.

    Args:
        info: Resolve info of any field of the execution.

    Returns:
        True for a subscription operation.
    """
    operation = getattr(getattr(info, "operation", None), "operation", None)
    return operation is OperationType.SUBSCRIPTION
