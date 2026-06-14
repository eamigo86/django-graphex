"""String conversion utilities for django-graphex.

Stdlib-only implementation of the helpers previously imported from graphene:
  - to_camel_case  (graphene.utils.str_converters)
  - to_snake_case  (graphene.utils.str_converters)
  - props          (graphene.utils.props)
  - warn_deprecation (graphene.utils.deprecated)

Zero graphene imports.  Safe to use in the native write-path (GDX_BACKEND=native)
and in any stdlib-only context.
"""

from __future__ import annotations

import re
import warnings


# ---------------------------------------------------------------------------
# to_camel_case
# ---------------------------------------------------------------------------

_UNDERSCORE_RE = re.compile(r"_([a-zA-Z0-9])")


def to_camel_case(value: str) -> str:
    """Convert a snake_case string to camelCase.

    Examples::

        to_camel_case("created_at")  # "createdAt"
        to_camel_case("name")        # "name"

    Args:
        value: A snake_case string.

    Returns:
        The camelCase equivalent.
    """
    return _UNDERSCORE_RE.sub(lambda m: m.group(1).upper(), value)


# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])([A-Z])|(?<=[A-Z])([A-Z])(?=[a-z])")


def to_snake_case(value: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case.

    Examples::

        to_snake_case("createdAt")    # "created_at"
        to_snake_case("name")         # "name"
        to_snake_case("firstNameLast") # "first_name_last"

    Args:
        value: A camelCase or PascalCase string.

    Returns:
        The snake_case equivalent (all lower-case).
    """
    # Insert underscore before uppercase letters that follow a lowercase letter
    # or digit, or before sequences like "AB" in "ABCFoo" → "abc_foo".
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    result = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", result)
    return result.lower()


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------


def props(cls: type) -> dict[str, object]:
    """Return only the non-underscore attributes of *cls*.

    Equivalent to graphene's ``props`` helper::

        {k: v for k, v in vars(cls).items() if not k.startswith("_")}

    Args:
        cls: Any class object.

    Returns:
        A dict of ``{attr_name: attr_value}`` for attrs whose name does NOT
        start with ``"_"``.
    """
    return {k: v for k, v in vars(cls).items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# warn_deprecation
# ---------------------------------------------------------------------------


def warn_deprecation(message: str) -> None:
    """Emit a ``DeprecationWarning`` with the given *message*.

    Equivalent to graphene's ``warn_deprecation`` helper.

    Args:
        message: Human-readable deprecation message.
    """
    warnings.warn(message, DeprecationWarning, stacklevel=2)
