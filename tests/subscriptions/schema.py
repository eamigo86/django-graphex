# -*- coding: utf-8 -*-
"""A minimal subscription type shared by the subscription test-suite.

After the WU11 lockstep cutover the bespoke transport (``GraphqlAPIDemultiplexer``
+ the graphene confirmation ``Schema``) is gone. The kept engine/binding tests
only need a concrete ``Subscription`` subclass with a wired signal binding, so
this module exposes just ``UserSubscription``. Transport-level tests
(``test_transport_sse``/``test_transport_ws``/``test_capability_parity``) build
their own native ``DjangoGraphQLSchema`` from local roots.
"""

from django.contrib.auth.models import User

from django_graphex.subscriptions import Subscription


class UserSubscription(Subscription):
    class Meta:
        model = User
        stream = "users"
        description = "User Subscription"
        # Full payload so the serialize-once / binding tests exercise the
        # serialized data. The id-only default and the override are covered on
        # other models in the transport-agnostic suites.
        serialize_data = True
