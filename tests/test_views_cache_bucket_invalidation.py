# -*- coding: utf-8 -*-
"""Version-counter bucketing costs invalidation locality, never isolation.

"GraphQLView._cache_version_identity" maps every identity an UNAUTHENTICATED
caller can vary onto one of "_CACHE_VERSION_BUCKETS" fixed namespaces, so that a
caller cannot mint unbounded permanent version-counter keys by rotating its
"Authorization" header. Two credentials can therefore land in the same bucket and
share a version counter.

That trade has to be stated precisely, because the caching guide previously
promised the opposite:

- SPENT — invalidation locality. A mutation from one bucket member advances the
  counter its bucket-mates read, so their cached entries go unreachable. The
  counter only ever moves forward, so this can only turn a HIT into a MISS: the
  next read re-executes against current data. Nothing stale is resurrected and
  nothing is served that was not just computed for that caller.
- KEPT — isolation. The response entry is keyed by the FULL identity, not by the
  bucket, so bucket-mates never share a response slot.

Invariants asserted here:

- A mutation from a bucket-mate invalidates the other member's cached read
  (the documented behaviour change).
- A mutation does NOT invalidate a caller in a different bucket, so bucketing
  costs locality inside a bucket rather than degrading to a global flush.
- Across that invalidation, a caller is still answered with its OWN data. The
  performance regression must not become a leak.
- An UNAUTHENTICATED caller can reach a bucket it does not belong to, by hashing
  candidate credentials until one collides. That is stated rather than closed
  (see "GraphQLView._cache_version_identity"): the namespace is small by
  construction, so a caller that cannot aim can still cover it by volume. The
  test below is the honest record of the exposure and of its ceiling -- eviction
  yes, cross-caller bodies never.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLBoolean, GraphQLResolveInfo, GraphQLString

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_CACHE_ON = {
    "DJANGO_GRAPHEX": {
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "CACHE_INVALIDATION_SCOPE": "identity",
    }
}

#: How many candidate credentials to hash while looking for a bucket collision.
#: Only has to comfortably exceed "_CACHE_VERSION_BUCKETS" for the birthday
#: bound to make a collision certain in practice.
_CANDIDATES = 200

#: Counts resolver invocations, so a cache HIT (resolver not called) can be told
#: apart from a MISS. Reset in "setUp"; a module global rather than an attribute
#: because the resolver is a plain function on the schema, not a bound method.
_RESOLVER_CALLS: dict[str, int] = {}


class _EchoQuery(ObjectType):
    """Query root echoing the caller's credential and counting executions.

    A constant answer could not distinguish "served from cache" from "served
    from the wrong caller's cache": both would return identical bytes. Echoing
    the credential makes a cross-identity hit visible, and counting the calls
    makes the HIT/MISS the bucketing actually changes visible too.
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
        token = info.context.META.get("HTTP_AUTHORIZATION", "none")
        _RESOLVER_CALLS[token] = _RESOLVER_CALLS.get(token, 0) + 1
        return token


class _NoOpMutation(Mutation):
    """A no-op mutation, present only to trigger the version-counter bump."""

    class Arguments:
        """No arguments are accepted by this mutation."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: Any, info: GraphQLResolveInfo) -> "_NoOpMutation":
        """Run the no-op mutation, always reporting success.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            A new instance with "ok" set to True.
        """
        return cls(ok=True)


class _MutationRoot(ObjectType):
    """Mutation root exposing the version-bumping no-op."""

    do_thing = _NoOpMutation.Field()


_schema = DjangoGraphQLSchema(query=_EchoQuery, mutation=_MutationRoot)


def _request(token: str, query: str) -> Any:
    """Build a JSON GraphQL POST carrying an Authorization header.

    Args:
        token: The raw Authorization header value the caller presents.
        query: The GraphQL document to send.

    Returns:
        A request ready to be dispatched, with an unauthenticated user attached
        so "_cache_version_identity" takes its bucketing branch.
    """
    req = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query}),
        content_type="application/json",
        HTTP_AUTHORIZATION=token,
    )
    req.user = AnonymousUser()
    return req


def _bucket_of(token: str) -> str:
    """Return the version-counter namespace a credential is bucketed into.

    Args:
        token: The raw Authorization header value.

    Returns:
        The bucket name "_cache_version_identity" maps that credential to.
    """
    view = GraphQLView(schema=_schema)
    request = _request(token, "{ who }")
    return view._cache_version_identity(request, view.cache_key_prefix(request))


def _find_pairs() -> tuple[tuple[str, str], str]:
    """Find two credentials sharing a bucket, plus one in a different bucket.

    Returns:
        A tuple of the colliding pair and an outsider credential whose bucket
        differs from theirs.

    Raises:
        AssertionError: When no collision turns up, which would mean the bucket
            count grew past what this search covers.
    """
    seen: dict[str, str] = {}
    for i in range(_CANDIDATES):
        token = f"Bearer probe-{i}"
        bucket = _bucket_of(token)
        if bucket in seen:
            outsider = next(
                other for other_bucket, other in seen.items() if other_bucket != bucket
            )
            return (seen[bucket], token), outsider
        seen[bucket] = token
    raise AssertionError(
        f"{_CANDIDATES} credentials produced no bucket collision; raise "
        "_CANDIDATES so this module exercises what it claims to."
    )


@override_settings(**_CACHE_ON)
class BucketedInvalidationTest(TestCase):
    """A shared version counter must cost misses and nothing else.

    Each test pairs two credentials the bucketing put in the same namespace, so
    the trade is exercised on the exact case it creates.
    """

    def setUp(self) -> None:
        """Start from a cold cache with no counted resolver calls.

        A response body or version counter warmed by a sibling test would make a
        MISS look like a HIT, which is exactly the signal under test.
        """
        cache.clear()
        _RESOLVER_CALLS.clear()
        self.view = GraphQLView.as_view(schema=_schema)
        (self.alice, self.bob), self.outsider = _find_pairs()

    def _read(self, token: str) -> str:
        """Dispatch "{ who }" as the given credential and return the answer.

        Args:
            token: The raw Authorization header value to present.

        Returns:
            The credential the SERVER answered with, which differs from "token"
            only when a cached body crossed identities.
        """
        response = self.view(_request(token, "{ who }"))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)["data"]["who"]

    def _mutate(self, token: str) -> None:
        """Dispatch the no-op mutation and flush the deferred version bump.

        The bump is scheduled through "transaction.on_commit", which Django's
        "TestCase" never fires inside its wrapping atomic block, so it has to be
        executed explicitly for the invalidation to be observable at all.

        Args:
            token: The raw Authorization header value to present.
        """
        with self.captureOnCommitCallbacks(execute=True):
            response = self.view(_request(token, "mutation { doThing { ok } }"))
        self.assertEqual(response.status_code, 200)

    def test_bucket_mates_share_invalidation(self) -> None:
        """Ships broken if the caching guide's "only the issuing user's
        namespace is invalidated" is still true of bucketed identities.

        It is not, and the guide has to say so: the counter is per BUCKET, so a
        mutation from either member sends the other back to the database.
        """
        self.assertEqual(self._read(self.alice), self.alice)
        self.assertEqual(_RESOLVER_CALLS[self.alice], 1)
        # Warm proof that Alice is genuinely cached before Bob touches anything.
        self.assertEqual(self._read(self.alice), self.alice)
        self.assertEqual(_RESOLVER_CALLS[self.alice], 1)

        self._mutate(self.bob)

        self.assertEqual(self._read(self.alice), self.alice)
        self.assertEqual(
            _RESOLVER_CALLS[self.alice],
            2,
            "A bucket-mate's mutation left the other member's entry reachable; "
            "the shared version counter did not advance and the guide's "
            "documented behaviour change is not what the code does.",
        )

    def test_a_different_bucket_is_not_invalidated(self) -> None:
        """Ships broken if a mutation invalidates callers outside its bucket.

        Bucketing is allowed to widen invalidation to a bucket. Widening it any
        further would make the counter a global flush in all but name.
        """
        self.assertEqual(self._read(self.outsider), self.outsider)
        self.assertEqual(_RESOLVER_CALLS[self.outsider], 1)

        self._mutate(self.alice)

        self.assertEqual(self._read(self.outsider), self.outsider)
        self.assertEqual(
            _RESOLVER_CALLS[self.outsider],
            1,
            "A mutation from another bucket invalidated this caller's entry; "
            "invalidation is no longer scoped to the mutating bucket.",
        )

    def test_an_unauthenticated_caller_can_pick_a_bucket_but_not_a_body(self) -> None:
        """Ships broken if a crafted colliding credential ever reads a victim's body.

        The eviction half is the stated cost: the bucket is a pure function of a
        caller-chosen header, so an attacker hashes candidates offline until one
        collides and then bumps that counter. The half that must NOT be true is
        the read -- the response entry is keyed by the full identity, so the
        attacker is answered with its own credential and nothing else. If this
        assertion ever flips, the cost stopped being a cost and became a leak.
        """
        victim, attacker = self.alice, self.bob
        self.assertEqual(_bucket_of(victim), _bucket_of(attacker))

        self.assertEqual(self._read(victim), victim)
        self.assertEqual(_RESOLVER_CALLS[victim], 1)

        self._mutate(attacker)

        self.assertEqual(self._read(victim), victim)
        self.assertEqual(
            _RESOLVER_CALLS[victim],
            2,
            "A crafted bucket collision no longer evicts; the documented cost "
            "changed and the guide has to change with it.",
        )
        self.assertEqual(self._read(attacker), attacker)

    def test_invalidation_never_crosses_response_bodies(self) -> None:
        """Ships broken if a bucket-mate is ever answered with the other's body.

        Invalidation granularity is a performance property; this one is a
        security property, and the response key carries the FULL identity
        precisely so the first cannot damage the second.
        """
        self.assertEqual(self._read(self.alice), self.alice)
        self.assertEqual(self._read(self.bob), self.bob)

        self._mutate(self.alice)

        # Both re-read after the shared counter moved: each must be recomputed
        # for itself, never handed the bucket-mate's freshly cached body.
        self.assertEqual(self._read(self.bob), self.bob)
        self.assertEqual(self._read(self.alice), self.alice)
        self.assertEqual(self._read(self.bob), self.bob)
