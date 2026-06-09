"""List manipulation GraphQL directives."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from graphql import GraphQLArgument, GraphQLInt, GraphQLNonNull

from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = (
    "ShuffleGraphQLDirective",
    "SampleGraphQLDirective",
    "UniqueGraphQLDirective",
)


class ShuffleGraphQLDirective(BaseExtraGraphQLDirective):
    """Shuffle the list into a random order."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the shuffle directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            A new list with the items in random order, or the value when
            it is empty.
        """
        if not value:
            return value
        # Copy first: never mutate a queryset result cache / shared list in place.
        items = list(value)
        random.shuffle(items)
        return items


class SampleGraphQLDirective(BaseExtraGraphQLDirective):
    """Sample k random elements from a list."""

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the sample directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "k": GraphQLArgument(
                GraphQLNonNull(GraphQLInt), description="Number of elements to sample"
            )
        }

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the sample directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            A list of "k" randomly sampled items, or the value when empty.
        """
        if not value:
            return value
        items = list(value)
        k = max(0, min(int(args.get("k") or 0), len(items)))  # clamp to [0, len]
        return random.sample(items, k)


class UniqueGraphQLDirective(BaseExtraGraphQLDirective):
    """De-duplicate a list, preserving the original order."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the unique directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            A list with duplicates removed, or the value when it is empty.
        """
        if not value:
            return value
        seen = set()
        result = []
        for item in value:
            try:
                key = item
                if key in seen:
                    continue
                seen.add(key)
            except TypeError:  # unhashable -> fall back to identity/equality
                if item in result:
                    continue
            result.append(item)
        return result
