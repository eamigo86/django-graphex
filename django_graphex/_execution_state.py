"""Budget state shared by the middleware and the optimizer.

Two scopes exist, and they differ on purpose:

* "per execution": one GraphQL operation execution (a subscription event is its
  own execution). The state lives in a weak table keyed by the graphql-core
  executor of the execution, so it lasts exactly as long as the execution. The
  events of one subscription share their stream's executor but run one after
  the other, so that entry also remembers the root response path of the current
  event (graphql-core makes a new one per event execution, so equal payload
  objects do not matter) and starts a fresh state when another one arrives.
  The entry never holds the root value, which may reference the executor. An
  info without an executor uses a bounded table keyed by the identity of the variable values
  and root value instead. This is what the optimizer work budget uses, and the
  fallback of the directive output budget.
* "per request": every execution of one HTTP request, so all items of a batch
  share one budget. The view opens a request_budget_scope around the whole
  request; the budget travels in a context variable, so the user's context
  value is never touched and any context type works. The directive output
  budget prefers it when it is present (and the execution is not a
  subscription event).
"""

from __future__ import annotations

import threading
import weakref
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

from graphql import OperationType

#: Request-wide budget of the HTTP request being served in this context.
_REQUEST_BUDGET: ContextVar[RequestBudget | None] = ContextVar(
    "graphex_request_budget", default=None
)

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
    sequentially, so the entry also holds the root response path of the current
    event and a different path starts a fresh state. The entry never holds the
    root value (it may reference the executor, which would keep the entry
    alive forever). An info without an
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
            event = _root_path(info) if is_subscription(info) else None
            try:
                entry = self._by_executor.get(executor)
                if entry is None or entry[0] is not event:
                    entry = self._by_executor[executor] = [event, factory()]
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


@contextmanager
def request_budget_scope() -> Iterator[RequestBudget]:
    """Share one fresh budget across everything run inside the block.

    The budget is carried by a context variable, never by the user's context
    value, so any context type (and a context object shared between requests)
    works and concurrent requests stay apart. The variable is reset on exit.

    Yields:
        The budget of this scope.
    """
    budget = RequestBudget()
    token = _REQUEST_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _REQUEST_BUDGET.reset(token)


def current_request_budget() -> RequestBudget | None:
    """Return the budget of the enclosing request scope, if any.

    Returns:
        The budget set by "request_budget_scope", or None outside one.
    """
    return _REQUEST_BUDGET.get()


def _root_path(info: Any) -> Any:
    """Return the outermost response path of a field.

    graphql-core builds a new root path object for the root field every time it
    executes the operation, so for a subscription this identifies one event. It
    references only response keys and type names, never the executor or a
    payload.

    Args:
        info: Resolve info of any field of the execution.

    Returns:
        The root Path object, or None when the info carries no path.
    """
    path = getattr(info, "path", None)
    while getattr(path, "prev", None) is not None:
        path = path.prev
    return path


def is_subscription(info: Any) -> bool:
    """Tell whether the execution is a subscription event.

    Args:
        info: Resolve info of any field of the execution.

    Returns:
        True for a subscription operation.
    """
    operation = getattr(getattr(info, "operation", None), "operation", None)
    return operation is OperationType.SUBSCRIPTION
