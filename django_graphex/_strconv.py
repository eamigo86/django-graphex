"""String conversion utilities for django-graphex.

Stdlib-only implementation of the helpers previously imported from graphene:
  - to_camel_case  (graphene.utils.str_converters)
  - to_snake_case  (graphene.utils.str_converters)
  - props          (graphene.utils.props)
  - warn_deprecation (graphene.utils.deprecated)

Zero graphene imports.  Safe to use in the native write-path and in any
stdlib-only context.
"""

from __future__ import annotations

import re
import warnings

# ---------------------------------------------------------------------------
# to_camel_case
# ---------------------------------------------------------------------------


def to_camel_case(value: str) -> str:
    """Convert a snake_case string to camelCase.

    Byte-for-byte equivalent to "graphene.utils.str_converters.to_camel_case":
    the FIRST underscore-separated component is kept verbatim and every later
    component is "str.capitalize()"-d (first letter upper, REST lower-cased),
    with empty components (from doubled underscores) rendered as "_". This
    exact behavior matters: type / enum NAMES are built from values that may
    already contain internal capitals (e.g. "tests_SeedArticle_status_Enum"),
    and "str.capitalize()" lower-cases the remainder
    ("SeedArticle" becomes "Seedarticle"). A naive "uppercase the char after
    each underscore" implementation would PRESERVE those capitals and silently
    diverge from the graphene-built names used elsewhere (filter-input enum
    lookups, native schema/type naming), producing missed registry lookups and
    SDL-parity breaks.

    Examples:
        to_camel_case("created_at")                    -> "createdAt"
        to_camel_case("name")                          -> "name"
        to_camel_case("tests_SeedArticle_status_Enum") -> "testsSeedarticleStatusEnum"

    Args:
        value: A snake_case string.

    Returns:
        camel: The camelCase equivalent.
    """
    components = value.split("_")
    return components[0] + "".join(x.capitalize() if x else "_" for x in components[1:])


# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------


def to_snake_case(value: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case.

    Examples:
        to_snake_case("createdAt")     -> "created_at"
        to_snake_case("name")          -> "name"
        to_snake_case("firstNameLast") -> "first_name_last"

    Args:
        value: A camelCase or PascalCase string.

    Returns:
        snake: The snake_case equivalent (all lower-case).
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
    """Return the non-underscore attributes of "cls", INHERITED ones included.

    Like graphene's "props" helper, the whole class hierarchy is read, not just
    the class body: graphene resolves attributes through "dir(cls)". A
    "vars(cls)"-only comprehension SILENTLY drops every inherited attribute, so
    factoring shared mutation arguments into a base class
    ("class Arguments(CommonArgs)") shipped a schema missing them, with no error
    anywhere.

    The MRO is walked in reverse (base classes first) rather than through
    "dir(cls)" so declaration order survives and the most-derived class wins on
    a name collision; "dir" sorts alphabetically, which would reshuffle the
    compiled argument order in the SDL.

    Args:
        cls: Any class object.

    Returns:
        attrs: A dict of "{attr_name: attr_value}" for every attribute of the
            class and its bases whose name does NOT start with "_".
    """
    attrs: dict[str, object] = {}
    for klass in reversed(cls.__mro__):
        attrs.update((k, v) for k, v in vars(klass).items() if not k.startswith("_"))
    return attrs


# ---------------------------------------------------------------------------
# warn_deprecation
# ---------------------------------------------------------------------------


def warn_deprecation(message: str) -> None:
    """Emit a "DeprecationWarning" with the given "message".

    Equivalent to graphene's "warn_deprecation" helper.

    Args:
        message: Human-readable deprecation message.
    """
    warnings.warn(message, DeprecationWarning, stacklevel=2)
