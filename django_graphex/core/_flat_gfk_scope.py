"""Internal schema markers for permission-pruned flat GFK targets."""

from __future__ import annotations

from typing import Any

FLAT_GFK_FALLBACK_EXT = "gdx_flat_gfk_fallback"
EFFECTIVE_GRANTS_EXT = "gdx_effective_grants"


def has_flat_gfk_fallback(schema: Any) -> bool:
    """Report whether the schema actually exposes a marked flat GFK type.

    Args:
        schema: The executable GraphQL schema to inspect.

    Returns:
        True only for the library's native flat GFK fallback type.
    """
    return any(
        (getattr(gql_type, "extensions", None) or {}).get(FLAT_GFK_FALLBACK_EXT) is True
        for gql_type in schema.type_map.values()
    )


def signature_grants(
    schema: Any, granted: frozenset[str], label_set: frozenset[str]
) -> frozenset[str]:
    """Select grants relevant to a schema and its flat GFK fallback.

    Args:
        schema: Full schema whose reachable type map determines the key policy.
        granted: The caller's complete live permission grants.
        label_set: Statically labeled schema permissions.

    Returns:
        All grants for a flat GFK fallback, otherwise labeled grants only.
    """
    return granted if has_flat_gfk_fallback(schema) else granted & label_set
