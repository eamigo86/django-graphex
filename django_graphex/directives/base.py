"""Base classes for GraphQL directives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django_graphex._strconv import to_snake_case
from graphql import DirectiveLocation, GraphQLDirective

from ..registry import get_global_registry

if TYPE_CHECKING:
    from graphql import GraphQLArgument


class BaseExtraGraphQLDirective(GraphQLDirective):
    """Base class for custom GraphQL directives."""

    def __init__(self) -> None:
        """Initialize the directive with registry and configuration."""
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
