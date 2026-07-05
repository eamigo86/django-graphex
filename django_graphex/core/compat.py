"""Native backend read-site helpers.

Read-sites recover the source class for a compiled "GraphQLObjectType" from
"t.extensions["gdx"]._meta.graphene_type" (the source DjangoObjectType / root
ObjectType carried on "GdxMeta" at native compile time). These helpers
centralise that lookup so callers can read "_meta" and the source class
uniformly.

"_gdx_meta(t)":
    Returns the "_meta"-like object for "t" — either "t.graphene_type._meta"
    when a direct back-reference is present, or "t.extensions['gdx']._meta" for
    native types.

    This single function replaces the repeated pattern
    "t.graphene_type._meta.max_depth" with "_gdx_meta(t).max_depth".

    Used at: validation.py, cost.py, utils.py, fields.py, filtering/*.py.

"NativeTypeAliasMixin" — exposes a "graphene_type" property alias on native
    output types so read-sites that access "type.graphene_type" recover the
    "GdxPayload" carried on "extensions['gdx']".
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# _gdx_meta — read-site _meta helper
# ---------------------------------------------------------------------------


def _gdx_meta(t: Any) -> Any:
    """Return the ``_meta``-like object for ``t``.

    Direct back-reference: ``t.graphene_type._meta`` when present.
    Native:               ``t.extensions["gdx"]._meta`` (GdxPayload._meta → _MetaView).

    The direct back-reference is tried first as a fast path; native types fall
    through to the ``extensions["gdx"]`` lookup.

    Args:
        t: A ``GraphQLObjectType`` (or similar) with either ``graphene_type``
           or ``extensions["gdx"]`` populated.

    Returns:
        The ``_meta`` proxy object (``_MetaView`` over ``GdxMeta``).

    Raises:
        AttributeError: if neither path is available.
    """
    # Fast path: try t.graphene_type._meta
    graphene_type = None
    try:
        graphene_type = t.graphene_type
    except AttributeError:
        pass

    if graphene_type is not None:
        return graphene_type._meta

    # Native: t.extensions["gdx"]._meta
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
# _gdx_graphene_type — source-class recovery helper
# ---------------------------------------------------------------------------


def _gdx_graphene_type(t: Any) -> Any:
    """Return the source class for ``t``, or ``None``.

    Direct back-reference: ``t.graphene_type`` when present.
    Native:               ``t.extensions["gdx"]._meta.graphene_type`` (the source
        class — root ObjectType or DjangoObjectType — carried on ``GdxMeta`` at
        native compile time).

    The direct back-reference is tried first as a fast path. Returns ``None``
    (never raises) when no source class is recoverable, so callers can treat
    "no custom resolver / hook declared" uniformly.

    Args:
        t: A ``GraphQLObjectType`` — typically ``info.parent_type`` at a
           read-site.

    Returns:
        The source class (root ObjectType or DjangoObjectType), or ``None`` when
        none is carried.
    """
    # Fast path: a direct graphene_type back-reference.
    graphene_type = getattr(t, "graphene_type", None)
    if graphene_type is not None:
        return graphene_type

    # Native: t.extensions["gdx"]._meta.graphene_type.
    extensions = getattr(t, "extensions", None)
    if extensions is not None:
        gdx = extensions.get("gdx")
        if gdx is not None:
            try:
                return gdx._meta.graphene_type
            except AttributeError:
                return None
    return None


# ---------------------------------------------------------------------------
# NativeTypeAliasMixin — graphene_type property alias for native types
# ---------------------------------------------------------------------------


class NativeTypeAliasMixin:
    """Mixin that provides a "graphene_type" property alias for native types.

    Native output "GraphQLObjectType" instances (built via the native compile
    path) carry their source class on "extensions['gdx']" rather than as a
    direct "graphene_type" back-reference.

    Read-sites in validation.py, cost.py, utils.py, fields.py, and filtering/
    may access ".graphene_type" directly; this mixin returns the
    "GdxPayload" as the alias value so the subsequent "._meta" access still
    works.

    NOTE: This mixin is on the INSTANCE (the "GraphQLObjectType" wrapper or
    the DjangoObjectType subclass), not on the "GraphQLObjectType" itself.
    """

    @property
    def graphene_type(self) -> Any:
        """Return the "GdxPayload" from "extensions['gdx']" as a graphene_type.

        Acts as a drop-in "graphene_type" alias.

        Returns:
            The "GdxPayload" carried on "extensions['gdx']", or None when
            "extensions['gdx']" is not set.
        """
        extensions = getattr(self, "extensions", None)
        if extensions is not None:
            return extensions.get("gdx")
        return None
