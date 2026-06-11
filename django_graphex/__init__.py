"""django-graphex - A toolkit for building GraphQL APIs with Django and graphene."""

from graphene.pyutils.version import get_version

from .cost import CostLimitValidationRule, CostReport, analyze_cost
from .directives import all_directives
from .fields import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
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
from .schema import DenyAllRegistry, DjangoGraphQLSchema, collect_field_names
from .security import (
    AuthenticatedFieldsMiddleware,
    DisableIntrospectionMiddleware,
)
from .types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)
from .validation import DepthLimitValidationRule
from .views import AuthenticatedGraphQLView, BaseGraphQLView, GraphQLView

VERSION = (1, 0, 0, "final", "")

__version__ = get_version(VERSION)

__all__ = (
    "__version__",
    # FIELDS
    "AnnotatedField",
    "DjangoObjectField",
    "DjangoFilterListField",
    "DjangoFilterPaginateListField",
    "DjangoListObjectField",
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
    # DIRECTIVES
    "all_directives",
    "GraphQLDirectiveMiddleware",
    # VIEWS
    "BaseGraphQLView",
    "GraphQLView",
    "AuthenticatedGraphQLView",
)
