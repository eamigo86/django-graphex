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


def to_camel_case(value: str) -> str:
    """Convert a snake_case string to camelCase.

    Byte-for-byte equivalent to ``graphene.utils.str_converters.to_camel_case``:
    the FIRST underscore-separated component is kept verbatim and every later
    component is ``str.capitalize()``-d (first letter upper, REST lower-cased),
    with empty components (from doubled underscores) rendered as ``"_"``.  This
    exact behavior matters: type / enum NAMES are built from values that may
    already contain internal capitals (e.g. ``tests_SeedArticle_status_Enum``),
    and ``str.capitalize()`` lower-cases the remainder
    (``"SeedArticle" -> "Seedarticle"``).  A naive "uppercase the char after
    each underscore" implementation would PRESERVE those capitals and silently
    diverge from the graphene-built names used elsewhere (filter-input enum
    lookups, native schema/type naming) — producing missed registry lookups and
    SDL-parity breaks.

    Examples::

        to_camel_case("created_at")                    # "createdAt"
        to_camel_case("name")                          # "name"
        to_camel_case("tests_SeedArticle_status_Enum") # "testsSeedarticleStatusEnum"

    Args:
        value: A snake_case string.

    Returns:
        The camelCase equivalent.
    """
    components = value.split("_")
    return components[0] + "".join(
        x.capitalize() if x else "_" for x in components[1:]
    )


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
