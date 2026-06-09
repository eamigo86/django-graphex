# -*- coding: utf-8 -*-
"""A minimal subscription schema used by the subscription test-suite."""

import graphene
from django.contrib.auth.models import User

from django_graphex.subscriptions import (
    GraphqlAPIDemultiplexer,
    Subscription,
)


class UserSubscription(Subscription):
    class Meta:
        model = User
        stream = "users"
        description = "User Subscription"
        # Full payload so the projection / fields-enum / e2e tests exercise the
        # `data` argument. The id-only default and the override are covered on
        # BasicModel in test_payload.py (a separate model, no binding clash).
        serialize_data = True


class AppDemultiplexer(GraphqlAPIDemultiplexer):
    subscriptions = {"users": UserSubscription}


class SubscriptionRoot(graphene.ObjectType):
    user_subscription = UserSubscription.Field()


class Query(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(self, info):
        return "world"


schema = graphene.Schema(query=Query, subscription=SubscriptionRoot)
