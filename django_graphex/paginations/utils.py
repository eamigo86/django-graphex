"""Utility functions and classes for pagination.

This module provides utility functions for pagination validation and
a generic pagination field class for reusable pagination logic.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

import graphene
from django.db import DatabaseError

from ..base_types import DjangoListObjectBase

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo


class GenericPaginationField(graphene.Field):
    """Generic pagination field with the logic needed to paginate a queryset."""

    def __init__(
        self, _type: Any, paginator_instance: Any, *args: Any, **kwargs: Any
    ) -> None:
        """Initialize the generic pagination field with a paginator instance.

        Args:
            _type: The GraphQL type to paginate.
            paginator_instance: The paginator providing the pagination logic.
            *args: Additional positional arguments for the base field.
            **kwargs: Additional keyword arguments for the base field.
        """
        kwargs.setdefault("args", {})

        self.paginator_instance = paginator_instance

        kwargs.update(self.paginator_instance.to_graphql_fields())
        kwargs.update(
            {
                "description": "{} list, paginated by {}".format(
                    _type._meta.model.__name__, paginator_instance.__name__
                )
            }
        )

        super().__init__(graphene.List(_type), *args, **kwargs)

    @property
    def model(self) -> Any:
        """Get the Django model associated with this pagination field.

        Returns:
            The Django model class backing this field.
        """
        return self.type.of_type._meta.node._meta.model

    def list_resolver(
        self,
        manager: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a paginated list using the configured paginator instance.

        Args:
            manager: The model manager providing the base queryset.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current query.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated results, or "None" when "root" is not a list base.
        """
        if isinstance(root, DjangoListObjectBase):
            return self.paginator_instance.paginate_queryset(root.results, **kwargs)
        return None

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Wrap the resolver with pagination logic.

        Args:
            parent_resolver: The resolver being wrapped.

        Returns:
            A partial that resolves the paginated list.
        """
        return partial(
            self.list_resolver, self.type.of_type._meta.model._default_manager
        )


def _positive_int(
    integer_string: Any, strict: bool = False, cutoff: int | None = None
) -> Any:
    """Cast a string to a strictly positive integer.

    Args:
        integer_string: The value to cast to an integer.
        strict: If "True", treat zero as invalid.
        cutoff: An optional maximum value to clamp the result to.

    Returns:
        The parsed integer, clamped to "cutoff" when provided.

    Raises:
        ValueError: If the value is negative or zero while strict.
    """
    if integer_string:
        ret = int(integer_string)
    else:
        return integer_string
    if ret < 0 or (ret == 0 and strict):
        raise ValueError()
    if cutoff:
        return min(ret, cutoff)
    return ret


def _nonzero_int(
    integer_string: Any, strict: bool = False, cutoff: int | None = None
) -> Any:
    """Cast a string to a strictly non-zero integer.

    Args:
        integer_string: The value to cast to an integer.
        strict: If "True", treat zero as invalid.
        cutoff: An optional maximum value to clamp the result to.

    Returns:
        The parsed integer, clamped to "cutoff" when provided.

    Raises:
        ValueError: If the value is zero while strict.
    """
    if integer_string:
        ret = int(integer_string)
    else:
        return integer_string
    if ret == 0 and strict:
        raise ValueError()
    if cutoff:
        return min(ret, cutoff)
    return ret


def _get_count(queryset: Any) -> int:
    """Determine an object count, supporting either querysets or regular lists.

    Args:
        queryset: A queryset or a regular list-like object to count.

    Returns:
        The number of objects in the given queryset or list.
    """
    try:
        return queryset.count()
    except (AttributeError, TypeError, DatabaseError):
        return len(queryset)
