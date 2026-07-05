# -*- coding: utf-8 -*-
""" "PERMISSION_SCOPED_SCHEMA" — response-cache signature isolation (P4).

When "CACHE_ACTIVE" AND "PERMISSION_SCOPED_SCHEMA" are both True, the
"AuthenticatedGraphQLView" response-cache key MUST incorporate the
caller's permission signature so a low-permission user can never read a
high-permission user's cached response body for the SAME query body.

Invariants under test (spec P4 — Response-Cache Signature Isolation, design D7):

- Flag OFF: the composed cache key is byte-identical to today (no signature
  folded), so the P4 change is inert when the feature is disabled.
- Flag ON: the key folds the signature; two users with DIFFERENT relevant perms
  produce DIFFERENT cache keys for the SAME query body.
- The DISCRIMINATING case: user A (high perms) populates the cache with a query
  body; user B (low perms) issuing the IDENTICAL body is NOT served A's cached
  response — B's own resolver runs.
- An active superuser folds no signature (they always get the full schema).
"""

import json
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core import permission_signature_cache as psc
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView

_SECRET_PERM = "auth.view_permission"

#: CACHE_ACTIVE + PERMISSION_SCOPED_SCHEMA both on.
_CACHE_AND_SCOPED = {
    "DJANGO_GRAPHEX": {
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "PERMISSION_SCOPED_SCHEMA": True,
    }
}
#: CACHE_ACTIVE on, scoped-schema OFF (the key must stay byte-identical to today).
_CACHE_ONLY = {
    "DJANGO_GRAPHEX": {
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "PERMISSION_SCOPED_SCHEMA": False,
    }
}


# --------------------------------------------------------------------------- #
# A schema whose ``public`` field is untagged (visible to everyone) and whose
# ``secret`` field needs a real Django perm. Both a high- and a low-perm user
# have a NON-EMPTY pruned Query root (``public`` survives for both), so neither
# hits the empty-root 403 — the ONLY difference between them is their signature,
# which is exactly what the cache key must fold in.
# --------------------------------------------------------------------------- #
class _Query(ObjectType):
    public = field(GraphQLString)
    secret = field(GraphQLString, required_perms=[_SECRET_PERM])

    def resolve_public(root: Any, info: Any) -> str:  # noqa: N805
        """Resolve the "public" field, echoing the caller for leak detection.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info, used to read the caller's username.

        Returns:
            data: The string "public-for-{username}".
        """
        # Echo the caller so a leaked cache body is detectable in the response.
        return f"public-for-{info.context.user.username}"

    def resolve_secret(root: Any, info: Any) -> str:  # noqa: N805
        """Resolve the "secret" field, gated by "_SECRET_PERM".

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            data: The fixed string "secret-data".
        """
        return "secret-data"


_schema = DjangoGraphQLSchema(query=_Query)


class _SharedIdentityView(AuthenticatedGraphQLView):
    """View that maps EVERY caller to one cache identity partition.

    Collapsing the identity prefix isolates the permission SIGNATURE as the only
    thing that can distinguish two users' cache keys: if the signature were not
    folded in, a low-perm user WOULD read a high-perm user's cached body. This is
    the discriminating harness for spec P4 (Response-Cache Signature Isolation).
    """

    @staticmethod
    def cache_key_prefix(request: HttpRequest) -> str:  # noqa: D401 — see class docstring
        """Collapse every caller into the single "shared" cache identity.

        Args:
            request: The incoming request (unused; every request maps to the
                same partition).

        Returns:
            identity: The fixed string "shared".
        """
        return "shared"


def _post(query: str, user: User) -> HttpRequest:
    """Build a POST request against the GraphQL endpoint for a given user.

    Args:
        query: The raw GraphQL query text.
        user: The Django user to attach to the request.

    Returns:
        request: A POST request carrying the given query, with "user" set.
    """
    body = json.dumps({"query": query})
    req = RequestFactory().post("/graphql/", body, content_type="application/json")
    req.user = user
    return req


def _graphql_body_keys(stored_keys: list[str]) -> list[str]:
    """Return only the response-body cache keys (drop the version-counter keys).

    "dispatch" stores both "_graphql_cacheversion_<identity>" (the namespace
    version counter) and "_graphql_<identity>_<version>_...<body-hash>" (the
    response body). Signature-fold assertions care only about the latter.

    Args:
        stored_keys: The raw sequence of keys observed being written to cache.

    Returns:
        body_keys: The subset of "stored_keys" that are response-body keys.
    """
    return [
        k
        for k in stored_keys
        if k.startswith("_graphql_") and not k.startswith("_graphql_cacheversion_")
    ]


class ResponseCacheSignatureIsolationTest(TestCase):
    """P4 — the response-cache key folds the permission signature (flag ON).

    Covers the discriminating low/high-perm case, distinct signatures never
    sharing a cache slot, same-signature cache reuse, the flag-off baseline
    key shape, and the superuser no-signature bypass.
    """

    def setUp(self) -> None:
        """Reset caches, build a shared-identity view, and load the test permission.

        Runs before each test in this class.
        """
        cache.clear()
        psc._CACHE.clear()
        self.factory = RequestFactory()
        self.secret_perm = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Permission),
            codename="view_permission",
        )
        # Shared-identity view: EVERY caller lands in one cache partition, so the
        # permission signature is the ONLY thing that can keep two users' cache
        # keys apart. Without the P4 fold, low-perm B WOULD read high-perm A's body.
        self.view = _SharedIdentityView.as_view(schema=_schema)

    def _low(self) -> User:
        """Create a plain authenticated user lacking the secret permission.

        Returns:
            user: A persisted user with no extra permissions.
        """
        return User.objects.create_user(username="low", password="x")

    def _high(self) -> User:
        """Create a user granted the secret permission.

        Returns:
            user: A persisted user holding "self.secret_perm".
        """
        user = User.objects.create_user(username="high", password="x")
        user.user_permissions.add(self.secret_perm)
        return user

    # 1. DISCRIMINATING: user A (high perms) seeds the cache with a query body;
    #    user B (low perms) issuing the IDENTICAL body MUST NOT read A's cached
    #    response — the folded signature makes their keys distinct.
    @override_settings(**_CACHE_AND_SCOPED)
    def test_low_perm_user_never_reads_high_perm_cached_body(self) -> None:
        """Ship-broken contract: a low-perm user issuing the identical query
        body as a high-perm user must never be served the high-perm user's
        cached response; the folded signature must keep the keys distinct.
        """
        query = "{ public }"
        high, low = self._high(), self._low()

        resp_high = self.view(_post(query, user=high))
        self.assertEqual(resp_high.status_code, 200)
        self.assertEqual(
            json.loads(resp_high.content)["data"]["public"], "public-for-high"
        )

        resp_low = self.view(_post(query, user=low))
        self.assertEqual(resp_low.status_code, 200)
        self.assertEqual(
            json.loads(resp_low.content)["data"]["public"],
            "public-for-low",
            "Low-perm user was served the high-perm user's cached response "
            "(signature not folded into the cache key)",
        )

    # 2. Two users with DIFFERENT relevant perms compose DIFFERENT cache keys for
    #    the SAME body: the backend runs once per distinct signature (no shared
    #    slot). Same identity is irrelevant here — we key by signature, not pk.
    @override_settings(**_CACHE_AND_SCOPED)
    def test_distinct_signatures_do_not_share_a_cache_slot(self) -> None:
        """Ship-broken contract: two users with different relevant
        permissions must produce distinct cache keys for the same query body,
        so the backend runs once per distinct signature.
        """
        query = "{ public }"
        high, low = self._high(), self._low()

        stored_keys: list[str] = []
        real_cache = cache
        original_set = real_cache.set

        def capturing_set(key: str, value: Any, *args: Any, **kwargs: Any) -> Any:
            """Record the cache key while delegating to the real "set".

            Args:
                key: The cache key being written.
                value: The value being cached.
                args: Additional positional arguments forwarded as-is.
                kwargs: Additional keyword arguments forwarded as-is.

            Returns:
                result: Whatever the original "set" returns.
            """
            stored_keys.append(key)
            return original_set(key, value, *args, **kwargs)

        with patch.object(real_cache, "set", side_effect=capturing_set):
            self.view(_post(query, user=high))
            self.view(_post(query, user=low))

        graphql_keys = _graphql_body_keys(stored_keys)
        self.assertEqual(
            len(set(graphql_keys)),
            2,
            f"Expected two distinct signature-folded keys, got {graphql_keys}",
        )

    # 3. The SAME user (stable signature) MUST still hit the cache on a repeat.
    @override_settings(**_CACHE_AND_SCOPED)
    def test_same_signature_still_hits_cache(self) -> None:
        """Ship-broken contract: the same user (stable signature) must still
        hit the cache on a repeat query, invoking the backend only once.
        """
        query = "{ public }"
        high = self._high()

        call_count = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(
            self_view: GraphQLView, request: HttpRequest, *args: Any, **kwargs: Any
        ) -> Any:
            """Count invocations while delegating to the real super_call.

            Args:
                self_view: The view instance the call is bound to.
                request: The request being dispatched.
                args: Additional positional arguments forwarded as-is.
                kwargs: Additional keyword arguments forwarded as-is.

            Returns:
                response: Whatever the original "super_call" returns.
            """
            call_count["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        with patch.object(GraphQLView, "super_call", counting_super_call):
            self.view(_post(query, user=high))
            self.view(_post(query, user=high))

        self.assertEqual(
            call_count["n"],
            1,
            "Same-signature repeat query missed the cache (backend ran twice)",
        )

    # 4. Flag OFF: the composed cache key MUST be byte-identical to a plain
    #    identity+version+body key (no signature folded) — the P4 change is inert.
    @override_settings(**_CACHE_ONLY)
    def test_flag_off_cache_key_is_byte_identical(self) -> None:
        """Ship-broken contract: with the flag off, the composed cache key
        must be byte-identical to the plain identity+version+body form (no
        signature segment folded in), so the P4 change is inert.
        """
        query = "{ public }"
        high = self._high()

        stored_keys: list[str] = []
        real_cache = cache
        original_set = real_cache.set

        def capturing_set(key: str, value: Any, *args: Any, **kwargs: Any) -> Any:
            """Record the cache key while delegating to the real "set".

            Args:
                key: The cache key being written.
                value: The value being cached.
                args: Additional positional arguments forwarded as-is.
                kwargs: Additional keyword arguments forwarded as-is.

            Returns:
                result: Whatever the original "set" returns.
            """
            stored_keys.append(key)
            return original_set(key, value, *args, **kwargs)

        with patch.object(real_cache, "set", side_effect=capturing_set):
            self.view(_post(query, user=high))

        graphql_keys = _graphql_body_keys(stored_keys)
        self.assertEqual(len(graphql_keys), 1)
        # With the flag OFF the key MUST equal the plain identity+version+body
        # form used by the base view — no signature segment folded in. The
        # shared-identity harness pins the identity to ``shared``.
        parts = graphql_keys[0].split("_")
        # "_graphql_shared_V_HASH" -> ["", "graphql", "shared", "V", "HASH"]
        self.assertEqual(
            parts[:3],
            ["", "graphql", "shared"],
            f"Flag OFF key changed shape: {graphql_keys[0]}",
        )
        self.assertEqual(
            len(parts),
            5,
            f"Flag OFF key gained an extra segment (signature leaked): {graphql_keys[0]}",
        )

    # 5. An active superuser folds NO signature (they always get the full
    #    schema): their key stays the plain identity+version+body form.
    @override_settings(**_CACHE_AND_SCOPED)
    def test_superuser_folds_no_signature(self) -> None:
        """Ship-broken contract: an active superuser must fold no permission
        signature into the cache key, since they always get the full schema.
        """
        root = User.objects.create_superuser(
            username="root", email="root@example.com", password="x"
        )
        query = "{ public }"

        # The signature helper must never be called for an active superuser.
        calls: list[Any] = []
        original = psc.permission_signature

        def spy(perms: Any, label_set: Any) -> Any:
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
            resp = self.view(_post(query, user=root))
        finally:
            psc.permission_signature = original

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, [], "A signature was computed for an active superuser")
