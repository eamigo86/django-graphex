import datetime
import os

import graphene
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from django_graphex import ObjectType, all_directives, field
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
from django_graphex.native.scalars import GdxDate, GdxDateTime, GdxTime
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

USER_FILTER_FIELDS = {
    "id": ("exact",),
    "first_name": ("icontains", "iexact"),
    "last_name": ("icontains", "iexact"),
    "username": ("icontains", "iexact"),
    "email": ("icontains", "iexact"),
    "is_staff": ("exact",),
}


class UserType(DjangoObjectType):
    class Meta:
        model = User
        description = " Type definition for a single user "
        filter_fields = USER_FILTER_FIELDS


class User1ListType(DjangoListObjectType):
    class Meta:
        description = " Type definition for user list "
        model = User
        filter_fields = USER_FILTER_FIELDS
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25, ordering="-username"
        )


class UserModelType(DjangoModelType):
    class Meta:
        description = " Serializer Type definition for user "
        model = User
        filter_fields = USER_FILTER_FIELDS
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25, ordering="-username"
        )


class Query(ObjectType):
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

    def resolve_datetime_(self, info, *args, **kwargs):
        return datetime.datetime(2020, 12, 31, 10, 21, 30)

    def resolve_date_(self, info, *args, **kwargs):
        return datetime.date(2020, 12, 31)

    def resolve_time_(self, info, *args, **kwargs):
        return datetime.time(10, 21, 30)

    @staticmethod
    def resolve_all_users4(root, info, **kwargs):
        return User.objects.filter(is_staff=True)


# S6b: ``UserType`` / ``User1ListType`` are now NATIVE-only types (re-parented
# off graphene onto the native Pydantic base). graphene's ``Schema(query=Query)``
# can no longer assemble them ("Expected Graphene type, but received: ...").
# Under ``GDX_BACKEND=native`` the consumers build the schema through
# ``DjangoGraphQLSchema`` from ``Query`` directly (see
# tests/native/_sdl_parity_seed.build_full_schema_sdl), so the module only needs
# to register the types at import — NOT build a graphene Schema. Building it under
# native would crash at import (the #1534 risk-7 "import-time crash after a type
# goes native-only" — keep the graphene-only construction behind a backend
# guard; the non-native branch is a clean no-op exposing ``schema = None``).
if os.environ.get("GDX_BACKEND", "graphene") == "native":
    schema = None
else:
    schema = graphene.Schema(query=Query, directives=all_directives)
