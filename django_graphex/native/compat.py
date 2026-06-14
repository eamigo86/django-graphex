"""Native backend compatibility shims.

Provides a bridge between the graphene ``graphene_type._meta`` read pattern
and the native ``extensions["gdx"]._meta`` pattern.

``_gdx_meta(t)`` — graphene-first helper:
    Tries ``t.graphene_type._meta`` first (for the graphene path and any
    type that carries the graphene alias); falls back to
    ``t.extensions["gdx"]._meta`` (for native-only types).

    This single function replaces the repeated pattern:
        ``t.graphene_type._meta.max_deep``
    with:
        ``_gdx_meta(t).max_deep``

    Used at: validation.py, cost.py, utils.py, fields.py, filtering/*.py
    (Phase 3 WU-B read-site migration; not done in WU-A).

``NativeTypeAliasMixin`` — provides a ``graphene_type`` property alias
    on native output types so that any read-site that still accesses
    ``type.graphene_type`` before the WU-B migration continues to work.
    Valid for one major version; removed in Phase 7.

No imports from ``graphene``.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# _gdx_meta — graphene-first read-site helper
# ---------------------------------------------------------------------------


def _gdx_meta(t: Any) -> Any:
    """Return the ``_meta``-like object for either backend.

    Graphene path: ``t.graphene_type._meta`` (graphene ObjectType extension).
    Native path:   ``t.extensions["gdx"]._meta`` (GdxPayload._meta → _MetaView).

    The graphene path is tried first so the graphene baseline (1617 tests)
    is unaffected: existing read-sites calling ``_gdx_meta`` on a graphene
    type still hit the fast path.

    Args:
        t: A ``GraphQLObjectType`` (or similar) with either ``graphene_type``
           or ``extensions["gdx"]`` populated.

    Returns:
        The ``_meta`` proxy object (graphene ``ObjectTypeOptions`` or
        ``_MetaView`` over ``GdxMeta``).

    Raises:
        AttributeError: if neither path is available.
    """
    # Graphene-first: try t.graphene_type._meta
    graphene_type = None
    try:
        graphene_type = t.graphene_type
    except AttributeError:
        pass

    if graphene_type is not None:
        return graphene_type._meta

    # Native fallback: t.extensions["gdx"]._meta
    extensions = getattr(t, "extensions", None)
    if extensions is not None:
        gdx = extensions.get("gdx")
        if gdx is not None:
            return gdx._meta

    raise AttributeError(
        f"_gdx_meta: type {t!r} has neither 'graphene_type' nor "
        f"'extensions[\"gdx\"]'. Cannot read _meta."
    )


# ---------------------------------------------------------------------------
# NativeTypeAliasMixin — graphene_type property alias for native types
# ---------------------------------------------------------------------------


class NativeTypeAliasMixin:
    """Mixin that provides a ``graphene_type`` property alias for native types.

    Native output ``GraphQLObjectType`` instances (built via the native compile
    path) do NOT carry a real graphene ``graphene_type`` extension — they use
    ``extensions["gdx"]`` instead.

    During the WU-B read-site migration (~52 sites in validation.py, cost.py,
    utils.py, fields.py, filtering/), some callers may still access
    ``.graphene_type`` before their call-site is migrated to ``_gdx_meta``.
    This mixin returns the ``GdxPayload`` as the alias value so the subsequent
    ``._meta`` access still works.

    NOTE: This mixin is on the INSTANCE (the ``GraphQLObjectType`` wrapper or
    the DjangoObjectType subclass), not on the ``GraphQLObjectType`` itself.
    Phase 7 removes this mixin.
    """

    @property
    def graphene_type(self) -> Any:
        """Return the ``GdxPayload`` from ``extensions["gdx"]`` as a drop-in
        graphene_type alias.

        Returns None if ``extensions["gdx"]`` is not set.
        """
        extensions = getattr(self, "extensions", None)
        if extensions is not None:
            return extensions.get("gdx")
        return None
