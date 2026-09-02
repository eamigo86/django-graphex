# -*- coding: utf-8 -*-
"""Permanent cache keys must not be mintable by an unauthenticated caller.

"GraphQLView.cache_key_prefix" partitions the response cache by
"request.user.pk" when the request is authenticated and, when it is NOT, by a
hash of the caller-supplied "Authorization" header. That header is
UNAUTHENTICATED input: an anonymous client can vary it per request and mint a
fresh identity every time.

Each identity seeds its own namespace version counter, and that counter is
stored with "timeout=None" so it NEVER expires (issue #60b — the counter has to
outlive the response entries it namespaces). Combined, an anonymous caller could
plant an unbounded number of PERMANENT cache entries.

Invariants asserted here:

- The number of permanent version-counter keys an unauthenticated caller can
  create is bounded by a fixed constant, no matter how many distinct
  "Authorization" headers it sends.
- The authenticated and the fully-anonymous partitions keep their exact,
  un-bucketed version namespace (bounded by the real user table / a single key).
- Bounding the counter does NOT weaken isolation: two callers holding different
  credentials still never read each other's cached response body.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLResolveInfo, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_CACHE_ON = {
    "DJANGO_GRAPHEX": {
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "CACHE_INVALIDATION_SCOPE": "identity",
    }
}

#: How many distinct "Authorization" headers the bound test sends. It only has
#: to exceed "_CACHE_VERSION_BUCKETS" by enough that an unbucketed
#: implementation (one key per header) is unmistakably over the bound.
_DISTINCT_TOKENS = 200


class _EchoQuery(ObjectType):
    """Query root whose only field echoes the caller's credential.

    A constant resolver cannot prove cache isolation — every caller would get
    the same bytes whether or not the cache leaked. Echoing the credential makes
    a cross-identity hit visible in the response body.
    """

    who = field(GraphQLString)

    def resolve_who(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Resolve "who" to the request's raw Authorization header.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info, used to read the request headers.

        Returns:
            The Authorization header value, or "none" when absent.
        """
        return info.context.META.get("HTTP_AUTHORIZATION", "none")


_schema = DjangoGraphQLSchema(query=_EchoQuery)


def _request(token: str | None = None, user: Any = None) -> Any:
    """Build a JSON GraphQL POST, optionally carrying an Authorization header.

    Args:
        token: The raw Authorization header value, or None to omit it.
        user: The user to attach; defaults to an unauthenticated user.

    Returns:
        A request ready to be dispatched to the view.
    """
    extra = {"HTTP_AUTHORIZATION": token} if token is not None else {}
    body = json.dumps({"query": "{ who }"})
    req = RequestFactory().post(
        "/graphql/", body, content_type="application/json", **extra
    )
    req.user = user if user is not None else AnonymousUser()
    return req


def _version_keys_written(view: Any, requests: list[Any]) -> set[str]:
    """Dispatch every request and return the version-counter keys written.

    Counting the keys the view WRITES (rather than reading the backend) keeps
    the assertion independent of backend eviction: culling can drop a key and
    force a re-seed, which repeats a key but never invents a new one.

    Args:
        view: The view callable to dispatch each request through.
        requests: The requests to dispatch, in order.

    Returns:
        The distinct namespace version-counter keys passed to "cache.set".
    """
    seen: set[str] = set()
    original_set = cache.set

    def capturing_set(key: str, *args: Any, **kwargs: Any) -> Any:
        if key.startswith("_graphql_cacheversion_"):
            seen.add(key)
        return original_set(key, *args, **kwargs)

    with patch.object(cache, "set", side_effect=capturing_set):
        for req in requests:
            view(req)
    return seen


@override_settings(**_CACHE_ON)
class UnauthenticatedIdentityBoundTest(TestCase):
    """An anonymous caller must not be able to plant unbounded permanent keys.

    The version counter never expires, so every namespace an anonymous caller
    can reach is a key that stays in the cache for the life of the process.
    """

    def setUp(self) -> None:
        """Start every test from a cold cache with no seeded version counter.

        A counter left over from a sibling test would be reused rather than
        written, so it would not be counted.
        """
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_authorization_header_cannot_mint_unbounded_version_keys(self) -> None:
        """Ships broken if a varying Authorization header creates one permanent
        version counter per header.

        The counter is stored with timeout=None, so every key an anonymous
        caller mints here stays in the cache forever.
        """
        requests = [_request(f"Bearer attacker-{i}") for i in range(_DISTINCT_TOKENS)]
        keys = _version_keys_written(self.view, requests)

        self.assertLessEqual(
            len(keys),
            GraphQLView._CACHE_VERSION_BUCKETS,
            f"{_DISTINCT_TOKENS} unauthenticated Authorization headers created "
            f"{len(keys)} permanent version keys; the unauthenticated namespace "
            f"must be bounded by {GraphQLView._CACHE_VERSION_BUCKETS}.",
        )

    def test_fully_anonymous_partition_keeps_its_exact_namespace(self) -> None:
        """Ships broken if a credential-free request stops using the single
        shared "anon" version namespace.

        That namespace is already one key for every anonymous caller, so
        bucketing it would buy nothing and would break invalidation locality.
        """
        keys = _version_keys_written(self.view, [_request()])

        self.assertEqual(keys, {"_graphql_cacheversion_anon"})

    def test_authenticated_partition_keeps_its_exact_namespace(self) -> None:
        """Ships broken if an authenticated caller's version namespace is
        bucketed.

        A logged-in caller cannot mint identities: their partition is bounded by
        the real user table, so it keeps precise per-user invalidation.
        """
        user = User.objects.create_user(username="pk-partition", password="x")
        keys = _version_keys_written(self.view, [_request("Bearer ignored", user)])

        self.assertEqual(keys, {f"_graphql_cacheversion_u{user.pk}"})


@override_settings(**_CACHE_ON)
class CredentialIsolationTest(TestCase):
    """Bounding the counter must not let one caller read another's response.

    Isolation is the reason the identity partition exists; the bound is only
    allowed to cost cache misses.
    """

    def setUp(self) -> None:
        """Start every test from a cold cache with no cached response bodies.

        A body warmed by a sibling test would make a leak look like a hit.
        """
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def _who(self, token: str) -> str:
        """Dispatch a query as the given credential and return the echoed value.

        Args:
            token: The raw Authorization header value to send.

        Returns:
            The "who" field of the response, i.e. the credential the SERVER
            answered with — which differs from "token" only on a cache leak.
        """
        response = self.view(_request(token))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)["data"]["who"]

    def test_two_credentials_never_share_a_cached_body(self) -> None:
        """Ships broken if a second credential is served the first one's cached
        response.

        This is the property the identity partition exists for; it must survive
        the version-counter bound.
        """
        self.assertEqual(self._who("Bearer alice"), "Bearer alice")
        self.assertEqual(self._who("Bearer bob"), "Bearer bob")
        # Alice again: her own entry, still hers after Bob warmed the cache.
        self.assertEqual(self._who("Bearer alice"), "Bearer alice")

    def test_credentialled_caller_is_isolated_from_the_anon_partition(self) -> None:
        """Ships broken if a credential-free response is served to a caller that
        presented a credential (or the reverse).
        """
        anon_response = self.view(_request())
        self.assertEqual(json.loads(anon_response.content)["data"]["who"], "none")
        self.assertEqual(self._who("Bearer carol"), "Bearer carol")
        replay = self.view(_request())
        self.assertEqual(json.loads(replay.content)["data"]["who"], "none")

    def test_bucket_collision_never_crosses_response_bodies(self) -> None:
        """Ships broken if two credentials that land in the SAME version bucket
        share a response-cache slot.

        A shared counter may only cost extra cache MISSES; the response key
        still carries the full identity, so the bodies stay separate.
        """
        view_instance = GraphQLView(schema=_schema)
        tokens = [f"Bearer collide-{i}" for i in range(_DISTINCT_TOKENS)]
        buckets: dict[str, list[str]] = {}
        for token in tokens:
            request = _request(token)
            identity = view_instance.cache_key_prefix(request)
            bucket = view_instance._cache_version_identity(request, identity)
            buckets.setdefault(bucket, []).append(token)

        colliding = next(
            (group for group in buckets.values() if len(group) > 1),
            None,
        )
        self.assertIsNotNone(
            colliding,
            f"{_DISTINCT_TOKENS} tokens produced no bucket collision; raise "
            "_DISTINCT_TOKENS so this test exercises what it claims to.",
        )
        assert colliding is not None  # narrowed for mypy
        first, second = colliding[0], colliding[1]
        self.assertEqual(self._who(first), first)
        self.assertEqual(self._who(second), second)
        self.assertEqual(self._who(first), first)
