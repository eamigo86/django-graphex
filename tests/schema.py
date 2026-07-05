"""The shared native GraphQL schema used across the top-level test suite.

Builds "UserType" / "User1ListType" / "UserModelType" over "django.contrib.auth.models.User"
and assembles them into a single "Query" root with the native (graphene-free)
"django_graphex.core" API, then wraps it in a "DjangoGraphQLSchema". Most
integration tests import "schema" directly instead of building their own.
"""

import datetime
from typing import Any

from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from graphql import GraphQLResolveInfo

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxDate, GdxDateTime, GdxTime
from django_graphex.directives import all_directives
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

#: Filter fields shared by every "User"-backed type in this schema.
USER_FILTER_FIELDS = {
    "id": ("exact",),
    "first_name": ("icontains", "iexact"),
    "last_name": ("icontains", "iexact"),
    "username": ("icontains", "iexact"),
    "email": ("icontains", "iexact"),
    "is_staff": ("exact",),
}


class UserType(DjangoObjectType):
    """GraphQL object type exposing a single "User" record.

    Filterable via "USER_FILTER_FIELDS" and consumed by the "DjangoObjectField"
    / "DjangoFilterListField" query styles on "Query".
    """

    class Meta:
        """Meta configuration for UserType.

        Binds the type to the "User" model, sets its GraphQL description, and
        shares the module-level "USER_FILTER_FIELDS".
        """

        model = User
        description = " Type definition for a single user "
        filter_fields = USER_FILTER_FIELDS


class User1ListType(DjangoListObjectType):
    """GraphQL list-object type exposing paginated, filterable "User" records.

    Backs the "DjangoListObjectField" query style and "User1ListType.RetrieveField"
    on "Query".
    """

    class Meta:
        """Meta configuration for User1ListType.

        Binds the type to the "User" model, sets its GraphQL description,
        shares "USER_FILTER_FIELDS", and configures limit/offset pagination
        ordered by "-username".
        """

        description = " Type definition for user list "
        model = User
        filter_fields = USER_FILTER_FIELDS
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25, ordering="-username"
        )


class UserModelType(DjangoModelType):
    """Serializer-backed GraphQL type exposing "User" query and mutation fields.

    Backs "UserModelType.QueryFields()", the serializer-style alternative to
    the plain object/list-object query fields above.
    """

    class Meta:
        """Meta configuration for UserModelType.

        Binds the type to the "User" model, sets its GraphQL description,
        shares "USER_FILTER_FIELDS", and configures limit/offset pagination
        ordered by "-username".
        """

        description = " Serializer Type definition for user "
        model = User
        filter_fields = USER_FILTER_FIELDS
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25, ordering="-username"
        )


class Query(ObjectType):
    """Root query type combining every "User" query style plus scalar smoke fields.

    Exposes the object/list-object/serializer query styles side by side so
    integration tests can exercise all three against the same underlying model.
    """

    # Possible User list queries definitions
    all_users = DjangoListObjectField(User1ListType, description=_("All Users query"))
    all_users1 = DjangoFilterPaginateListField(
        UserType, pagination=LimitOffsetGraphqlPagination()
    )
    all_users2 = DjangoFilterListField(UserType)
    all_users3 = DjangoListObjectField(User1ListType, description=_("All Users query"))
    all_users4 = DjangoFilterListField(UserType)

    # Defining a query for a single user
    # The DjangoObjectField have a ID type input field,
    # that allow filter by id and is't necessary to define resolve function
    user = DjangoObjectField(UserType, description=_("Single User query"))

    # Another way to define a query to single user
    user1 = User1ListType.RetrieveField(
        description=_("User List with pagination and filtering")
    )

    # Exist two ways to define single or list user queries with DjangoModelType
    user2, users = UserModelType.QueryFields()

    # Custom (non-model) scalar fields — graphene-free public API (decision
    # #1554): ``field()`` carries a graphql-core scalar singleton; ``name=``
    # pins the explicit wire name (dodging the Python-keyword trailing
    # underscore on the attribute). The native ``GdxDateTime`` / ``GdxDate`` /
    # ``GdxTime`` scalars render the SAME GraphQL names (``CustomDateTime`` /
    # ``CustomDate`` / ``CustomTime``, #1508) the old graphene descriptors did,
    # so SDL stays byte-identical.
    datetime_ = field(GdxDateTime, name="datetime")
    date_ = field(GdxDate, name="date")
    time_ = field(GdxTime, name="time")

    def resolve_datetime_(
        self, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
    ) -> datetime.datetime:
        """Resolve the "datetime" field to a fixed constant timestamp.

        Args:
            info: The GraphQL execution info for the current field.
            *args: Unused positional resolver arguments.
            **kwargs: Unused keyword resolver arguments.

        Returns:
            The constant "datetime.datetime(2020, 12, 31, 10, 21, 30)".
        """
        return datetime.datetime(2020, 12, 31, 10, 21, 30)

    def resolve_date_(
        self, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
    ) -> datetime.date:
        """Resolve the "date" field to a fixed constant date.

        Args:
            info: The GraphQL execution info for the current field.
            *args: Unused positional resolver arguments.
            **kwargs: Unused keyword resolver arguments.

        Returns:
            The constant "datetime.date(2020, 12, 31)".
        """
        return datetime.date(2020, 12, 31)

    def resolve_time_(
        self, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
    ) -> datetime.time:
        """Resolve the "time" field to a fixed constant time.

        Args:
            info: The GraphQL execution info for the current field.
            *args: Unused positional resolver arguments.
            **kwargs: Unused keyword resolver arguments.

        Returns:
            The constant "datetime.time(10, 21, 30)".
        """
        return datetime.time(10, 21, 30)

    @staticmethod
    def resolve_all_users4(
        root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> "QuerySet[User]":
        """Resolve "allUsers4" to staff users only.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.
            **kwargs: Unused keyword resolver arguments.

        Returns:
            A queryset of "User" rows filtered to "is_staff=True".
        """
        return User.objects.filter(is_staff=True)


# S7: the suite is native-only. ``UserType`` / ``User1ListType`` are native
# (re-parented off graphene in S6b) and the public roots/fields use the native
# ``ObjectType`` + ``field()`` API (S-ROOTS-f). The shared test schema is now
# built directly with the native ``DjangoGraphQLSchema``.
schema = DjangoGraphQLSchema(query=Query, directives=all_directives)
