"""django-graphex - A toolkit for building GraphQL APIs with Django and graphene."""

from importlib.metadata import PackageNotFoundError, version

from .cost import CostLimitValidationRule, CostReport, analyze_cost
from .directives import all_directives
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

VERSION = (1, 2, 1, "final", "")

try:
    __version__ = version("django-graphex")
except PackageNotFoundError:  # pragma: no cover
    # Fallback for editable / source installs not yet installed via pip.
    # This path is unreachable in the test environment where the package is
    # installed, but is essential for source checkouts that skip pip install.
    from graphene.pyutils.version import get_version

    __version__ = get_version(VERSION)

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
