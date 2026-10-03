"""Adapt caller-owned variable mappings to GraphQL-core's native values API."""

from __future__ import annotations

from typing import Any

from graphql.execution import values as graphql_values


def native_variable_values(variable_values: Any) -> Any:
    """Pass native variables through and wrap legacy mappings on core 3.3.

    Args:
        variable_values: Bound variables from a resolver or an internal walker.

    Returns:
        The input unchanged on core 3.2 or when already native; otherwise a
        core 3.3 value object retaining the supplied coerced mapping.
    """
    native_type = getattr(graphql_values, "VariableValues", None)
    if native_type is not None and isinstance(variable_values, dict):
        return native_type(sources={}, coerced=variable_values)
    return variable_values
