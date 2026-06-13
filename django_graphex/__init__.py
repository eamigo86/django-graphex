"""django-graphex - A toolkit for building GraphQL APIs with Django and graphene."""

from importlib.metadata import PackageNotFoundError, version

from .cost import CostLimitValidationRule, CostReport, analyze_cost
from .directives import all_directives
from .filtering.filter_field import filter_field
from .fields import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoNestedListObjectField,
    DjangoObjectField,
)
from .middleware import GraphQLDirectiveMiddleware
from .mutation import DjangoModelMutation
from .paginations import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from .permissions import (
    AllowAny,
    BasePermission,
    IsAdmin,
    IsAdminOrReadOnly,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from .registry import Registry
from .schema import DenyAllRegistry, DjangoGraphQLSchema, collect_field_names
from .security import (
    AuthenticatedFieldsMiddleware,
    DisableIntrospectionMiddleware,
)
from .types import (
    DjangoInputObjectType,
    DjangoInterfaceType,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
    DjangoUnionType,
)
from .validation import DepthLimitValidationRule
from .views import AuthenticatedGraphQLView, BaseGraphQLView, GraphQLView


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

__all__ = (
    "__version__",
    # FIELDS
    "AnnotatedField",
    "DjangoFilterListField",
    "DjangoFilterPaginateListField",
    "DjangoListObjectField",
    "DjangoNestedListObjectField",
    "DjangoObjectField",
    # MUTATIONS
    "DjangoModelMutation",
    # PAGINATION
    "LimitOffsetGraphqlPagination",
    "PageGraphqlPagination",
    "CursorGraphqlPagination",
    # TYPES
    "DjangoObjectType",
    "DjangoListObjectType",
    "DjangoInputObjectType",
    "DjangoModelType",
    "DjangoUnionType",
    "DjangoInterfaceType",
    # PERMISSIONS
    "BasePermission",
    "AllowAny",
    "IsAuthenticated",
    "IsAdmin",
    "IsAuthenticatedOrReadOnly",
    "IsAdminOrReadOnly",
    # SECURITY
    "DisableIntrospectionMiddleware",
    "AuthenticatedFieldsMiddleware",
    "DepthLimitValidationRule",
    "CostLimitValidationRule",
    "analyze_cost",
    "CostReport",
    "DjangoGraphQLSchema",
    "collect_field_names",
    "DenyAllRegistry",
    # FILTERING
    "filter_field",
    # REGISTRY
    "Registry",
    # DIRECTIVES
    "all_directives",
    "GraphQLDirectiveMiddleware",
    # VIEWS
    "BaseGraphQLView",
    "GraphQLView",
    "AuthenticatedGraphQLView",
)
