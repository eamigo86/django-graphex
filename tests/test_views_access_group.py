# -*- coding: utf-8 -*-
""" "API_ACCESS_GROUP" — settings-driven endpoint access-group gate.

The gate lives inside "AuthenticatedGraphQLView.dispatch" (after the
"permission_classes" loop, before the request is handled). When
"DJANGO_GRAPHEX['API_ACCESS_GROUP']" is a non-empty string, only members of
that Django auth "Group" (plus any active superuser) may reach the endpoint;
everyone else gets a generic 403 before GraphQL parsing/execution. The
public "GraphQLView" is never affected.
"""

import json
from typing import Any

from django.contrib.auth.models import AnonymousUser, Group, User
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView

#: The exact generic message the view returns for any permission failure. The
#: gate must reuse it verbatim so it never leaks the group name / requirement.
_FORBIDDEN_MESSAGE = "You do not have permission to access this endpoint."


class _Query(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve the "hello" field to a fixed greeting for test schemas.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            greeting: The fixed string "world".
        """
        return "world"


_schema = DjangoGraphQLSchema(query=_Query)


def _post(user: Any = None) -> HttpRequest:
    """Build a POST request against the GraphQL endpoint for view tests.

    Args:
        user: When given, attached to the request as "request.user".

    Returns:
        request: A POST request carrying a fixed "{ hello }" query.
    """
    request = RequestFactory().post(
        "/graphql/", {"query": "{ hello }"}, content_type="application/json"
    )
    if user is not None:
        request.user = user
    return request


class ApiAccessGroupTest(TestCase):
    """Behavior of the "API_ACCESS_GROUP" setting-driven endpoint gate.

    Covers the inert default, member/non-member/anonymous outcomes, the
    superuser bypass, and that the public view and error body are unaffected.
    """

    def setUp(self) -> None:
        """Create the "api-users" group shared by every test in this class.

        Individual tests then add members, non-members, or superusers as
        needed via the helper methods below.
        """
        self.group = Group.objects.create(name="api-users")

    def _member(self) -> User:
        """Create a user that belongs to the "api-users" group.

        Returns:
            user: A persisted user who is a member of "self.group".
        """
        user = User.objects.create_user(username="member", password="x")
        user.groups.add(self.group)
        return user

    def _non_member(self) -> User:
        """Create a user that does not belong to the "api-users" group.

        Returns:
            user: A persisted user with no group memberships.
        """
        return User.objects.create_user(username="outsider", password="x")

    def _superuser(self) -> User:
        """Create an active superuser deliberately outside the group.

        Returns:
            user: A persisted superuser not in "self.group".
        """
        # Active superuser, deliberately NOT in the group.
        return User.objects.create_superuser(
            username="root", email="root@example.com", password="x"
        )

    # 1. Default ("") — behavior EXACTLY as today: an authenticated non-member
    #    passes straight through (the gate is inert).
    def test_default_empty_setting_is_inert(self) -> None:
        """Ship-broken contract: with no API_ACCESS_GROUP configured, the gate
        must be inert and let any authenticated non-member through.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=self._non_member()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    # 2. Non-empty setting, authenticated NON-member -> 403, generic message,
    #    and NO GraphQL execution (no "data" key in the body).
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_non_member_is_forbidden(self) -> None:
        """Ship-broken contract: an authenticated non-member must get a 403
        with the generic message and no GraphQL execution must have occurred.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=self._non_member()))
        self.assertEqual(response.status_code, 403)
        body = json.loads(response.content)
        self.assertEqual(body["errors"][0]["message"], _FORBIDDEN_MESSAGE)
        # The gate must fire BEFORE GraphQL execution: no resolver ran.
        self.assertNotIn("data", body)

    # 3. Non-empty setting, authenticated member -> passes (200, GraphQL data).
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_member_passes_through(self) -> None:
        """Ship-broken contract: an authenticated member of the configured
        group must pass through and receive the resolved GraphQL data.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=self._member()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    # 4. Non-empty setting, anonymous -> 403 (fail-closed, gate self-sufficient).
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_anonymous_is_forbidden(self) -> None:
        """Ship-broken contract: an anonymous request must fail closed with a
        403 when an access group is configured.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=AnonymousUser()))
        self.assertEqual(response.status_code, 403)

    # 5. Non-empty setting, ACTIVE superuser NOT in the group -> passes
    #    (hardcoded bypass invariant).
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_active_superuser_bypasses_group(self) -> None:
        """Ship-broken contract: an active superuser must bypass the group
        gate even when not a member of the configured group.
        """
        superuser = self._superuser()
        self.assertFalse(superuser.groups.filter(name="api-users").exists())
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=superuser))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    # 6. The PUBLIC GraphQLView is unaffected: an anonymous request still serves.
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_public_view_unaffected(self) -> None:
        """Ship-broken contract: the public GraphQLView must remain
        unaffected by API_ACCESS_GROUP, serving anonymous requests as usual.
        """
        view = GraphQLView.as_view(schema=_schema)
        response = view(_post(user=AnonymousUser()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    # 7. The 403 must NOT leak the group name — the body equals the generic
    #    permission message exactly.
    @override_settings(DJANGO_GRAPHEX={"API_ACCESS_GROUP": "api-users"})
    def test_forbidden_body_does_not_mention_group(self) -> None:
        """Ship-broken contract: the 403 error body must never leak the
        configured group name, exposing only the generic permission message.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=self._non_member()))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"api-users", response.content)
        self.assertEqual(
            json.loads(response.content),
            {"errors": [{"message": _FORBIDDEN_MESSAGE}]},
        )
