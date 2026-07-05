"""django-graphex - A toolkit for building GraphQL APIs with Django.

Public API surface (v2.0+): the package root intentionally exposes ONLY
"__version__". Every class, function and middleware is imported from its
own submodule, mirroring Django REST Framework's layout:

    from django_graphex.views import AuthenticatedGraphQLView, GraphQLView
    from django_graphex.permissions import IsAdmin, IsAuthenticated
    from django_graphex.types import DjangoObjectType
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.core import ObjectType, field, Mutation
    from django_graphex.schema import DjangoGraphQLSchema

This keeps the root namespace lean and makes every import's provenance
explicit. Settings-string references to the bundled middleware use the same
submodule paths, e.g. "django_graphex.middleware.GraphQLDirectiveMiddleware"
and "django_graphex.security.DisableIntrospectionMiddleware".
"""

from importlib.metadata import PackageNotFoundError, version


def _version_from_pyproject() -> str:
    """Read the project version straight from ``pyproject.toml``.

    Used only as a fallback for source checkouts that were never installed via
    pip (build metadata absent, but ``pyproject.toml`` present in the tree).
    Never used for an installed package — ``pyproject.toml`` is not shipped in
    the wheel.
    """
    import pathlib
    import tomllib

    pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


try:
    # Single source of truth: the installed package metadata, which the build
    # backend (hatchling) generates from ``pyproject.toml``.
    __version__ = version("django-graphex")
except PackageNotFoundError:  # pragma: no cover - source checkout, not installed
    try:
        __version__ = _version_from_pyproject()
    except Exception:  # noqa: BLE001 - last-resort dev fallback
        __version__ = "0.0.0"

# The package root deliberately exports ONLY ``__version__``. Everything else
# lives in its submodule (see the module docstring). Do NOT re-add re-exports
# here — that is the v2.0 public-API contract.
__all__ = ("__version__",)
