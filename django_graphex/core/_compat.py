"""self-to-root adapter shim for native mutation resolvers.

Provides "_adapt_self(fn, owner=None)":
  - If "fn"'s first parameter is named "self" AND "fn" is NOT a bound
    method ("inspect.ismethod(fn)" is False), wrap it in a shim that
    calls it as "fn(root, info, **kw)" and emits one "DeprecationWarning"
    per call.
  - Otherwise return "fn" unmodified (identity passthrough).

Rationale:
  graphql-core's "default_field_resolver" calls resolvers as
  "(root, info, **kwargs)" — not "(self, info, **kwargs)". Hand-written
  mutations often have "def mutate(self, info, ...)" because they were
  originally graphene Mutation subclasses. The shim is the safety net that
  makes them callable under the native runtime without a code change, while the
  deprecation warning prompts migration.

  Bound classmethods ("inspect.ismethod" is True) are called correctly as
  "(cls, root, info, **kw)" by graphql-core's resolver protocol, so they
  need no shim.

Zero graphene imports.
"""

from __future__ import annotations

import inspect
import warnings
from typing import Any, Callable


def _adapt_self(
    fn: Callable[..., Any],
    owner: type | None = None,  # reserved for future use (logging, context)
) -> Callable[..., Any]:
    """Adapt a self-first callable to the (root, info, **kw) protocol.

    Inspection rules:
    1. If fn is a bound method (inspect.ismethod(fn) is True),
       return it **unmodified** — classmethods are already correct.
    2. Examine the first positional parameter via inspect.signature(fn).
       If it is named "self", wrap fn in a shim that:
       - Calls the underlying function as fn(root, info, **kw) so existing
         behaviour is preserved under the native runtime.
       - Emits DeprecationWarning on every call to prompt migration.
    3. In all other cases, return fn unmodified.

    Args:
        fn: The callable to inspect and optionally wrap.
        owner: The class that owns the callable (reserved; currently unused).

    Returns:
        The original fn or a shim that wraps it.
    """
    # Rule 1: bound classmethods — always passthrough
    if inspect.ismethod(fn):
        return fn

    # Rule 2: inspect first param name
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
    except (ValueError, TypeError):
        # Un-inspectable callables (built-ins, etc.) — passthrough
        return fn

    if not params:
        return fn

    first_param = params[0]
    if first_param.name != "self":
        return fn

    # Rule 2 applies: wrap with shim + DeprecationWarning
    def _shim(root: Any, info: Any, **kw: Any) -> Any:
        warnings.warn(
            f"Resolver {fn.__qualname__!r} uses 'self' as the first parameter. "
            "Under the native backend resolvers are called as (root, info, **kw). "
            "Rename 'self' to 'root' to silence this warning. "
            "This shim will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return fn(root, info, **kw)

    # Preserve identity attributes for introspection
    _shim.__name__ = fn.__name__
    _shim.__qualname__ = fn.__qualname__
    _shim.__doc__ = fn.__doc__
    _shim.__wrapped__ = fn  # type: ignore[attr-defined]

    return _shim
