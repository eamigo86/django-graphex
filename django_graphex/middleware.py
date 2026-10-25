"""GraphQL middleware for processing custom directives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generator

from graphql import GraphQLError
from graphql.execution.values import get_directive_values
from graphql.pyutils import is_awaitable
from graphql.type.directives import GraphQLIncludeDirective, GraphQLSkipDirective

from ._execution_state import (
    ExecutionStates,
    RequestBudget,
    is_subscription,
    request_budget_of,
)
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


#: Counters of executions that carry no request budget (anything not run by the
#: GraphQL view: subscription events, transports, direct "execute" calls).
_EXECUTIONS = ExecutionStates()


def _charge(info: GraphQLResolveInfo, grown: int, directive_name: str) -> None:
    """Charge text grown by a directive against the output budget.

    The counter never lives in anything the client controls. An execution run
    by the GraphQL view shares the budget of its whole HTTP request, so every
    item of a batch draws from the same "MAX_DIRECTIVE_OUTPUT_TOTAL". Anything
    else (a subscription event, a transport, a direct "execute" call) is its own
    scope: the counter is kept per execution in a table keyed by the
    graphql-core executor, so it lasts as long as the execution. Subscription
    events share the executor of their source stream and run one after the
    other, so the entry also tracks the current event's root value and restarts
    when a new one arrives. An info without an executor falls back to a bounded
    table keyed by the identity of the variable values and root value. Entries
    hold both objects, so an identity can only match while its execution is
    alive. Events share their variable values but each has its own root value,
    so the counter restarts per event, even over a request context.

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
    shared = None if is_subscription(info) else request_budget_of(info.context)
    with _EXECUTIONS.lock:
        if shared is None:
            counter = _EXECUTIONS.get(info, RequestBudget)
        else:
            counter = shared
        counter.used += grown
        used = counter.used
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
