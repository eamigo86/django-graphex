"""GraphQL middleware for processing custom directives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generator

from graphql.execution.values import get_directive_values
from graphql.pyutils import is_awaitable
from graphql.type.directives import GraphQLIncludeDirective, GraphQLSkipDirective

from .registry import get_global_registry

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

            # Coerce the directive arguments once (resolves variables, applies
            # coercion and default values) instead of parsing the AST by hand.
            args = (
                get_directive_values(directive_class, field, info.variable_values) or {}
            )
            new_value = directive_class.resolve(
                new_value, args, directive, root, info, **kwargs
            )

        return new_value
