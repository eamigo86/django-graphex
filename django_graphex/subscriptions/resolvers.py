"""Snake-closure resolver factory for subscription output fields.

graphql-core's "default_field_resolver" keys by "info.field_name", which is
the camelCase WIRE name (e.g. "isActive"). The serialized subscription payload
produced by "native/backend.py:to_representation" uses SNAKE keys (e.g.
"is_active"). This mismatch produces a SILENT NULL for every multi-word field —
the blocking correctness issue documented in design section 6.

"make_snake_resolver" closes over the snake-case key and reads it directly from
the source dict, bypassing the camelCase wire name entirely.

The returned closure is tagged with "_gdx_pure_projection = True" so that:
  (a) COND-B ("guard.py") can whitelist it at schema build time, and
  (b) COND-B can reject hand-written/live/computed resolvers that lack the
      sentinel, even if they are otherwise structurally correct.

No Django, graphene, or channels imports — this module is pure Python and may
be imported safely in any context.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ["make_snake_resolver"]


def make_snake_resolver(snake: str) -> Callable[..., Any]:
    """Return a resolver closure that reads "snake" from a flat snake-keyed dict.

    Args:
        snake: The snake_case field name as it appears in the serialized
            subscription payload (e.g. "is_active", "date_joined").

    Returns:
        A two-argument resolver "(root, info) -> value" compatible with the
        graphql-core field resolver protocol. The closure reads "root[snake]"
        when "root" is a "dict" (the common production path — the flat serialized
        dict from "native/backend.py:to_representation" never touches the ORM),
        and falls back to "getattr(root, snake, None)" for non-dict roots (direct
        object access in tests or non-serialized usage).
    """
    resolver = lambda root, _info, *, _name=snake: (  # noqa: E731
        root.get(_name) if isinstance(root, dict) else getattr(root, _name, None)
    )
    resolver._gdx_pure_projection = True  # type: ignore[attr-defined]
    return resolver
