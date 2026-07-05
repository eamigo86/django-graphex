# -*- coding: utf-8 -*-
"""A minimal subscription type shared by the subscription test-suite.

After the WU11 lockstep cutover the bespoke transport ("GraphqlAPIDemultiplexer"
+ the graphene confirmation "Schema") is gone. The kept engine/binding tests
only need a concrete "Subscription" subclass with a wired signal binding, so
this module exposes just "UserSubscription". Transport-level tests
("test_transport_sse"/"test_transport_ws"/"test_capability_parity") build
their own native "DjangoGraphQLSchema" from local roots.
"""

from django.contrib.auth.models import User

from django_graphex.subscriptions import Subscription


class UserSubscription(Subscription):
    """Subscription over the built-in Django "User" model.

    Uses full-payload serialization so the serialize-once / binding tests can
    exercise the serialized data. The id-only default and payload overrides
    are covered on other models in the transport-agnostic suites.
    """

    class Meta:
        """Configuration for "UserSubscription".

        Declares the backing model, the broadcast stream name, and the
        payload mode used when serializing broadcasts.
        """

        model = User
        stream = "users"
        description = "User Subscription"
        # Full payload so the serialize-once / binding tests exercise the
        # serialized data. The id-only default and the override are covered on
        # other models in the transport-agnostic suites.
        payload_mode = "full"
