# -*- coding: utf-8 -*-
"""Response-cache invalidation follows durable mutation execution."""

import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLBoolean, GraphQLResolveInfo

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import MUTATION_ERRORS_FLAG, GraphQLView
from tests.cache_helpers import CACHE_ON, graphql_post, minimal_cache_schema


class _RejectedMutation(Mutation):
    """A mutation that asks the atomic executor to roll its work back."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: object, info: GraphQLResolveInfo) -> "_RejectedMutation":
        """Mark the mutation transaction for rollback."""
        setattr(info.context, MUTATION_ERRORS_FLAG, True)
        return cls(ok=False)


class _RejectedMutationRoot(ObjectType):
    rejected = _RejectedMutation.Field()


_rollback_schema = DjangoGraphQLSchema(
    query=minimal_cache_schema.query,
    mutation=_RejectedMutationRoot,
)


@override_settings(**CACHE_ON)
class MutationDispatchInvalidationTest(TestCase):
    """Only a mutation whose execution may be durable invalidates responses."""

    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _assert_bumps(
        self, request, *, schema=minimal_cache_schema, batch=False
    ) -> tuple[int, int]:
        view = GraphQLView.as_view(schema=schema, batch=batch)
        with patch.object(GraphQLView, "_bump_cache_version") as bump:
            response = view(request)
        return response.status_code, bump.call_count

    def test_get_mutation_rejected_with_405_does_not_invalidate(self) -> None:
        request = self.factory.get(
            "/graphql/", {"query": "mutation { doThing { ok } }"}
        )
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 405)
        self.assertEqual(bump_count, 0)

    def test_validation_rejected_mutation_does_not_invalidate(self) -> None:
        request = graphql_post(self.factory, "mutation { fieldThatDoesNotExist }")

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 400)
        self.assertEqual(bump_count, 0)

    def test_executed_mutation_invalidates(self) -> None:
        request = graphql_post(self.factory, "mutation { doThing { ok } }")

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)

    @override_settings(
        DJANGO_GRAPHEX={
            "CACHE_ACTIVE": True,
            "CACHE_TIMEOUT": 60,
            "ATOMIC_MUTATIONS": True,
        }
    )
    def test_rolled_back_atomic_mutation_does_not_invalidate(self) -> None:
        request = graphql_post(self.factory, "mutation { rejected { ok } }")

        status, bump_count = self._assert_bumps(request, schema=_rollback_schema)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 0)

    def test_batch_with_executed_mutation_invalidates_once(self) -> None:
        body = json.dumps(
            [
                {"query": "{ hello }"},
                {"query": "mutation { doThing { ok } }"},
            ]
        )
        request = self.factory.post(
            "/graphql/", body, content_type="application/json"
        )
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request, batch=True)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)

    def test_multipart_with_executed_mutation_invalidates(self) -> None:
        request = self.factory.post(
            "/graphql/",
            data={"query": "mutation { doThing { ok } }"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)
