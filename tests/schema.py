import datetime

import graphene
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from django_graphex import all_directives
from django_graphex.base_types import CustomDate, CustomDateTime, CustomTime
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
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


class Query(graphene.ObjectType):
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

    datetime_ = CustomDateTime(name="datetime")
    date_ = CustomDate(name="date")
    time_ = CustomTime(name="time")

    def resolve_datetime_(self, info, *args, **kwargs):
        return datetime.datetime(2020, 12, 31, 10, 21, 30)

    def resolve_date_(self, info, *args, **kwargs):
        return datetime.date(2020, 12, 31)

    def resolve_time_(self, info, *args, **kwargs):
        return datetime.time(10, 21, 30)

    @staticmethod
    def resolve_all_users4(root, info, **kwargs):
        return User.objects.filter(is_staff=True)


schema = graphene.Schema(query=Query, directives=all_directives)
