"""GraphQL middleware for processing custom directives."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generator

from graphql import GraphQLError
from graphql.execution.values import get_directive_values
from graphql.pyutils import is_awaitable
from graphql.type.directives import GraphQLIncludeDirective, GraphQLSkipDirective

from .registry import get_global_registry
from .settings import graphql_api_settings

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo


class _DirectiveAwaitable:
    """Defer coroutine creation until native GraphQL execution awaits it."""

    def __init__(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        """Retain the coroutine factory without starting or allocating work.

        Args:
            factory: Creates the directive-processing coroutine on demand.
        """
        self._factory = factory

    def __await__(self) -> Generator[Any, Any, Any]:
        """Create the coroutine only when native execution awaits this value.

        Returns:
            An iterator yielding the resolved and transformed field value.
        """
        return self._factory().__await__()


#: Private attribute on the request context holding the per-execution counters.
_BUDGET_ATTR = "_graphex_directive_output"

#: Most executions tracked per table; the oldest entry is dropped beyond this.
_BUDGET_TABLE_SIZE = 64

#: Counters for contexts that cannot take attributes (a dict or None).
_FALLBACK_TABLE: OrderedDict[tuple[int, int], list[Any]] = OrderedDict()

_BUDGET_LOCK = threading.Lock()


def _charge(info: GraphQLResolveInfo, grown: int, directive_name: str) -> None:
    """Charge text grown by a directive against the per-request output budget.

    The counter never lives in anything the client controls. It is kept in a
    small table on the request context (or, for a context that cannot take
    attributes, a bounded module table) keyed by the identity of the
    execution's variable values and root value. Entries hold both objects, so
    an identity can only match while its execution is alive. Subscription
    events share their variable values but each has its own root value, so the
    counter restarts per event.

    Args:
        info: The GraphQL resolve info for the field.
        grown: Characters the directive added to the value (0 only checks).
        directive_name: Directive name, used in the error message.

    Raises:
        GraphQLError: When the request has produced more directive text than
            "MAX_DIRECTIVE_OUTPUT_TOTAL" allows.
    """
    maximum = graphql_api_settings.MAX_DIRECTIVE_OUTPUT_TOTAL
    if maximum is None:
        return
    variables, root = info.variable_values, info.root_value
    key = (id(variables), id(root))
    with _BUDGET_LOCK:
        table = getattr(info.context, _BUDGET_ATTR, None)
        if table is None:
            table = OrderedDict()
            try:
                setattr(info.context, _BUDGET_ATTR, table)
            except (AttributeError, TypeError):
                table = _FALLBACK_TABLE
        entry = table.get(key)
        if entry is None or entry[0] is not variables or entry[1] is not root:
            entry = table[key] = [variables, root, 0]
            while len(table) > _BUDGET_TABLE_SIZE:
                table.popitem(last=False)
        table.move_to_end(key)
        entry[2] += grown
        used = entry[2]
    if used > maximum:
        raise GraphQLError(
            f"@{directive_name} output exceeds the request budget "
            f"MAX_DIRECTIVE_OUTPUT_TOTAL={maximum}."
        )


class GraphQLDirectiveMiddleware:
    """Middleware that processes custom GraphQL directives during execution.

    Wraps each field resolver so that any custom directive registered on the
    field (via the global registry) is applied to the resolved value, in field
    declaration order. The built-in "@skip" / "@include" directives are left to
    graphql-core and ignored here.
    """

    def resolve(
        self,
        next: Callable[..., Any],
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Process field resolution with directive handling.

        Args:
            next: The next resolver in the middleware chain.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: The field arguments forwarded to the next resolver.

        Returns:
            The field value after applying any custom directives.
        """
        result = next(root, info, **kwargs)
        return self.__process_value(result, root, info, **kwargs)

    def __process_value(
        self,
        value: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Apply each custom directive on the field to the resolved value.

        Args:
            value: The resolved field value.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: The field arguments forwarded to each directive.

        Returns:
            The value after every registered directive has been applied.
        """
        registry = get_global_registry()
        field = info.field_nodes[0]
        if not field.directives:
            return value

        if is_awaitable(value):

            async def resolve_awaitable() -> Any:
                """Apply field directives after native async resolution.

                Returns:
                    The resolved value after its directives are applied.
                """
                resolved = await value
                return self.__process_value(resolved, root, info, **kwargs)

            return _DirectiveAwaitable(resolve_awaitable)

        new_value = value
        for directive in field.directives:
            name = directive.name.value
            if name in (GraphQLIncludeDirective.name, GraphQLSkipDirective.name):
                continue

            directive_class = registry.get_directive(name)
            if directive_class is None:
                # Standard or third-party directive not handled here.
                continue
            # Refuse before producing more text once the budget is spent.
            _charge(info, 0, name)

            # Coerce the directive arguments once (resolves variables, applies
            # coercion and default values) instead of parsing the AST by hand.
            args = (
                get_directive_values(directive_class, field, info.variable_values) or {}
            )
            before = len(new_value) if isinstance(new_value, str) else 0
            new_value = directive_class.resolve(
                new_value, args, directive, root, info, **kwargs
            )
            if isinstance(new_value, str) and len(new_value) > before:
                _charge(info, len(new_value) - before, name)

        return new_value
