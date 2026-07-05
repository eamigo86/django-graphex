# -*- coding: utf-8 -*-
""" "PERMISSION_SCOPED_SCHEMA" — per-request pruned schema in the view (P2).

When "DJANGO_GRAPHEX['PERMISSION_SCOPED_SCHEMA']" is True (read PER-REQUEST),
"AuthenticatedGraphQLView" validates AND executes each request against the
pruned schema for the caller's permission signature. Invariants:

- A field the caller lacks perms for is ABSENT from their schema, so selecting it
  yields a native "Cannot query field" validation error (a not-found, NOT an
  authz error, no existence leak).
- An ACTIVE superuser always gets the FULL schema and NO signature is computed.
- A non-superuser whose pruned Query root is EMPTY gets the endpoint's existing
  generic 403 (byte-identical message), raised BEFORE validate/execute.
- The public "GraphQLView" is NEVER pruned, regardless of the flag.
- With the flag False (default) behavior is byte-identical to today.
- The flag is read per-request (toggle between two requests, no restart).
"""

import json
from collections.abc import Sequence
from typing import Any

from django.contrib.auth.models import AnonymousUser, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core import permission_signature_cache as psc
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView

#: The exact generic message the view returns for any permission failure — the
#: empty-root case must reuse it verbatim so it never leaks that a field existed.
_FORBIDDEN_MESSAGE = "You do not have permission to access this endpoint."

_ON = {"PERMISSION_SCOPED_SCHEMA": True}
_OFF = {"PERMISSION_SCOPED_SCHEMA": False}


# --------------------------------------------------------------------------- #
# Labeled schema: "public" is untagged (visible to all); "secret" requires
# "auth.view_permission" (a real Django perm we can grant/withhold in tests).
# --------------------------------------------------------------------------- #
_SECRET_PERM = "auth.view_permission"


class _Query(ObjectType):
    public = field(GraphQLString)
    secret = field(GraphQLString, required_perms=[_SECRET_PERM])

    def resolve_public(root: Any, info: Any) -> str:
        """Resolve the "public" field, visible to every caller.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            data: The fixed string "public-data".
        """
        return "public-data"

    def resolve_secret(root: Any, info: Any) -> str:
        """Resolve the "secret" field, gated by "_SECRET_PERM".

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            data: The fixed string "secret-data".
        """
        return "secret-data"


_schema = DjangoGraphQLSchema(query=_Query)


# --------------------------------------------------------------------------- #
# A schema whose ONLY Query field is perm-gated: a user lacking the perm has an
# EMPTY pruned Query root -> the empty-root 403 path.
# --------------------------------------------------------------------------- #
class _GatedOnlyQuery(ObjectType):
    secret = field(GraphQLString, required_perms=[_SECRET_PERM])

    def resolve_secret(root: Any, info: Any) -> str:
        """Resolve the "secret" field, the only field on this query root.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            data: The fixed string "secret-data".
        """
        return "secret-data"


_gated_only_schema = DjangoGraphQLSchema(query=_GatedOnlyQuery)


def _post(query: str, user: Any = None) -> HttpRequest:
    """Build a POST request against the GraphQL endpoint for view tests.

    Args:
        query: The raw GraphQL query text.
        user: When given, attached to the request as "request.user".

    Returns:
        request: A POST request carrying the given query.
    """
    request = RequestFactory().post(
        "/graphql/", {"query": query}, content_type="application/json"
    )
    if user is not None:
        request.user = user
    return request


class PermissionScopedSchemaViewTest(TestCase):
    """Behavior of the "PERMISSION_SCOPED_SCHEMA" per-request pruning flag.

    Covers pruned-field rejection, untouched public fields, the superuser
    full-schema bypass, the empty-root 403 path, the public view's immunity
    to pruning, the flag-off baseline, per-request flag reads, and the
    anonymous-user rejection ordering.
    """

    def setUp(self) -> None:
        """Reset the permission-signature cache and load the shared test permission.

        Clearing the process-wide LRU stops cross-test schema instances from
        leaking between tests in this class.
        """
        # Clear the process-wide LRU so cross-test schema instances never leak.
        psc._CACHE.clear()
        self.secret_perm = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Permission),
            codename="view_permission",
        )

    def _user_without_secret(self) -> User:
        """Create a plain authenticated user lacking the secret permission.

        Returns:
            user: A persisted user with no extra permissions.
        """
        return User.objects.create_user(username="plain", password="x")

    def _user_with_secret(self) -> User:
        """Create a user granted the secret permission.

        Returns:
            user: A persisted user holding "self.secret_perm".
        """
        user = User.objects.create_user(username="privileged", password="x")
        user.user_permissions.add(self.secret_perm)
        return user

    def _superuser(self) -> User:
        """Create an active superuser.

        Returns:
            user: A persisted superuser.
        """
        return User.objects.create_superuser(
            username="root", email="root@example.com", password="x"
        )

    # 1. Flag ON: a user WITHOUT the perm cannot even SELECT ``secret`` — it is
    #    absent from their schema, so validation reports "Cannot query field".
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_pruned_field_is_not_found_not_authz(self) -> None:
        """Ship-broken contract: a user lacking the required permission must
        get a "Cannot query field" validation error for the gated field, not
        an authorization error, and no "data" key must be present.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post("{ secret }", user=self._user_without_secret()))
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertIn("Cannot query field", body["errors"][0]["message"])
        self.assertNotIn("data", body)

    # 2. Flag ON: the SAME user CAN still query the untagged ``public`` field
    #    (pruning removes only what they lack, not the whole schema).
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_public_field_still_served_under_pruning(self) -> None:
        """Ship-broken contract: pruning must remove only the fields the
        caller lacks permission for, leaving untagged fields queryable.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post("{ public }", user=self._user_without_secret()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["public"], "public-data")

    # 3. Flag ON: a user WITH the perm sees ``secret`` and gets its data (the
    #    field survives pruning for that signature and executes).
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_permitted_user_queries_gated_field(self) -> None:
        """Ship-broken contract: a user holding the required permission must
        see the gated field survive pruning and receive its resolved data.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post("{ secret }", user=self._user_with_secret()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["secret"], "secret-data")

    # 4. Flag ON + ACTIVE superuser -> FULL schema, and NO signature computed.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_superuser_gets_full_schema_without_signature(self) -> None:
        """Ship-broken contract: an active superuser must receive the full,
        unpruned schema, and the permission-signature function must never be
        invoked for that request.
        """
        calls: list[Sequence[str]] = []
        original = psc.permission_signature

        def spy(perms: Sequence[str], label_set: Any) -> Any:
            """Record signature-computation calls before delegating to the original.

            Args:
                perms: The permission codenames being signed.
                label_set: The schema label set being signed against.

            Returns:
                signature: Whatever "original" returns for the same arguments.
            """
            calls.append(perms)
            return original(perms, label_set)

        psc.permission_signature = spy
        try:
            view = AuthenticatedGraphQLView.as_view(schema=_schema)
            response = view(_post("{ secret }", user=self._superuser()))
        finally:
            psc.permission_signature = original
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["secret"], "secret-data")
        self.assertEqual(calls, [])  # no signature was ever computed

    # 5. Flag ON + a user whose ENTIRE pruned Query root is empty -> the
    #    endpoint's existing generic 403 (byte-identical), before execution.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_empty_pruned_root_returns_generic_403(self) -> None:
        """Ship-broken contract: a user whose pruned Query root becomes
        entirely empty must get the endpoint's existing generic 403 message,
        raised before validation/execution.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_gated_only_schema)
        response = view(_post("{ secret }", user=self._user_without_secret()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content),
            {"errors": [{"message": _FORBIDDEN_MESSAGE}]},
        )

    # 6. Flag ON + empty pruned root: the superuser bypass means a superuser
    #    still queries the gated-only schema (full schema, root intact).
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_superuser_bypasses_empty_root_403(self) -> None:
        """Ship-broken contract: the superuser full-schema bypass must apply
        even when non-superusers would hit the empty-root 403 on this schema.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_gated_only_schema)
        response = view(_post("{ secret }", user=self._superuser()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["secret"], "secret-data")

    # 7. Flag ON: the PUBLIC GraphQLView is NEVER pruned — ``secret`` is still
    #    queryable there even for a user without the perm.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_public_view_never_pruned(self) -> None:
        """Ship-broken contract: the public "GraphQLView" must never apply
        schema pruning, regardless of PERMISSION_SCOPED_SCHEMA.
        """
        view = GraphQLView.as_view(schema=_schema)
        response = view(_post("{ secret }", user=self._user_without_secret()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["secret"], "secret-data")

    # 8. Flag OFF (default): behavior is byte-identical to today — a user without
    #    the perm can STILL select ``secret`` (no pruning happens at all).
    @override_settings(DJANGO_GRAPHEX=_OFF)
    def test_flag_off_is_byte_identical(self) -> None:
        """Ship-broken contract: with the flag off, behavior must match the
        pre-pruning baseline exactly — a user without the perm can still
        select the gated field.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post("{ secret }", user=self._user_without_secret()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["secret"], "secret-data")

    # 9. The flag is read PER-REQUEST: the same view/user gets pruned behavior
    #    under ON and full behavior under OFF, with no restart.
    def test_flag_read_per_request(self) -> None:
        """Ship-broken contract: the flag must be read per-request, so the
        same view and user switch between pruned and full behavior across
        two requests without a process restart.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        user = self._user_without_secret()
        with override_settings(DJANGO_GRAPHEX=_ON):
            pruned = view(_post("{ secret }", user=user))
        with override_settings(DJANGO_GRAPHEX=_OFF):
            full = view(_post("{ secret }", user=user))
        self.assertEqual(pruned.status_code, 400)  # secret pruned away
        self.assertEqual(full.status_code, 200)  # secret visible
        self.assertEqual(json.loads(full.content)["data"]["secret"], "secret-data")

    # 10. Flag ON, anonymous user: IsAuthenticated already rejects at dispatch
    #     (403) BEFORE any schema selection — pruning never sees an anon user.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_anonymous_rejected_before_pruning(self) -> None:
        """Ship-broken contract: an anonymous user must be rejected by the
        authentication gate before schema pruning ever runs, receiving the
        generic 403 message.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post("{ public }", user=AnonymousUser()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content),
            {"errors": [{"message": _FORBIDDEN_MESSAGE}]},
        )
