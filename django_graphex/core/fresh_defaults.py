"""Argument class that never shares a mutable default between executions.

graphql-core hands the SAME default object to every execution: the legacy
"default_value" is returned as is, so a resolver that mutates a list or dict
default changes what the next request sees. "FreshArgument" keeps a private
pristine copy and returns a new deep copy on each read. Immutable defaults never
use it, so they cost nothing. Input-object field defaults are isolated by the
input type's out_type callback instead (see "input_compiler").
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from graphql import GraphQLArgument, Undefined
from pydantic import BaseModel


def is_mutable_default(value: Any) -> bool:
    """Report whether a default can be changed in place by a resolver.

    Args:
        value: The default value declared for an argument or input field.

    Returns:
        True for lists, dicts, sets, byte arrays, model instances and tuples
        that hold any of them.
    """
    if isinstance(value, (list, dict, set, bytearray, BaseModel)):
        return True
    if isinstance(value, (tuple, frozenset)):
        return any(is_mutable_default(item) for item in value)
    return False


class FreshArgument(GraphQLArgument):
    """A "GraphQLArgument" whose mutable default is fresh for every execution.

    The default is copied on each read, so no two executions share it.
    """

    _pristine: Any = Undefined
    _copy_on_read: bool = False

    @property
    def default_value(self) -> Any:
        """Return the default, copied when it is mutable.

        Returns:
            A fresh copy for a mutable default, otherwise the stored value.
        """
        return deepcopy(self._pristine) if self._copy_on_read else self._pristine

    @default_value.setter
    def default_value(self, value: Any) -> None:
        """Store a pristine copy of the default.

        Args:
            value: The default value to keep.
        """
        self._copy_on_read = is_mutable_default(value)
        self._pristine = deepcopy(value) if self._copy_on_read else value


def graphql_argument(*args: Any, **kwargs: Any) -> GraphQLArgument:
    """Build a "GraphQLArgument", isolating a mutable default.

    Args:
        *args: Positional arguments of "GraphQLArgument".
        **kwargs: Keyword arguments of "GraphQLArgument".

    Returns:
        A "FreshArgument" when "default_value" is mutable, else a plain one.
    """
    if is_mutable_default(kwargs.get("default_value", Undefined)):
        return FreshArgument(*args, **kwargs)
    return GraphQLArgument(*args, **kwargs)
