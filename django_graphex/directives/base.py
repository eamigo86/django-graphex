"""Base classes for GraphQL directives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from graphql import DirectiveLocation, GraphQLDirective

from django_graphex._strconv import to_snake_case

from ..registry import get_global_registry

if TYPE_CHECKING:
    from graphql import GraphQLArgument


class BaseExtraGraphQLDirective(GraphQLDirective):
    """Base class for the library's custom GraphQL directives.

    Subclasses declare their arguments through "get_args" and their runtime
    behaviour through a "resolve" static method. The name is derived from the
    class name (minus the "GraphQLDirective" suffix) and snake_cased.
    """

    def __init__(self) -> None:
        """Build the directive and register it on the global registry.

        The directive is placed on "FIELD", "FRAGMENT_SPREAD" and
        "INLINE_FRAGMENT" locations, uses the class docstring as its GraphQL
        description, and registers itself under its snake_cased name so the
        execution layer can look it up.
        """
        registry = get_global_registry()
        super().__init__(
            name=self.get_name(),
            description=self.__doc__,
            args=self.get_args(),
            locations=[
                DirectiveLocation.FIELD,
                DirectiveLocation.FRAGMENT_SPREAD,
                DirectiveLocation.INLINE_FRAGMENT,
            ],
        )
        registry.register_directive(self.get_name(), self)

    @classmethod
    def get_name(cls) -> str:
        """Get the directive name from the class name.

        Returns:
            The snake_cased directive name derived from the class name.
        """
        return to_snake_case(cls.__name__.replace("GraphQLDirective", ""))

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get the arguments for the directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {}
