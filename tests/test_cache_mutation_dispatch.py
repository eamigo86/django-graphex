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


class _FailingMutation(Mutation):
    """A non-atomic mutation that fails after execution starts.

    The resolver models a failure that may happen after an earlier durable write.
    """

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: object, info: GraphQLResolveInfo) -> "_FailingMutation":
        """Raise after mutation execution has begun.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution context.

        Raises:
            RuntimeError: Always, to model a late resolver failure.
        """
        raise RuntimeError("resolver failed after a possible durable write")


class _RejectedMutationRoot(ObjectType):
    """Expose the rejected mutation used by rollback tests.

    This root isolates the rollback behavior from the shared cache schema.
    """

    rejected = _RejectedMutation.Field()
    fails = _FailingMutation.Field()


_rollback_schema = DjangoGraphQLSchema(
    query=minimal_cache_schema.query,
    mutation=_RejectedMutationRoot,
)


@override_settings(**CACHE_ON)
class MutationDispatchInvalidationTest(TestCase):
    """Verify that only potentially durable mutations invalidate responses.

    Rejections before execution and atomic rollbacks preserve cached queries.
    """

    def setUp(self) -> None:
        """Create an isolated request factory for every cache scenario.

        Each test constructs its own request so dispatch state cannot leak.
        """
        self.factory = RequestFactory()

    def _assert_bumps(
        self, request, *, schema=minimal_cache_schema, batch=False
    ) -> tuple[int, int]:
        """Dispatch a request and count cache-version increments.

        Args:
            request: The Django request to dispatch.
            schema: The GraphQL schema used by the view.
            batch: Whether the view accepts a JSON batch.

        Returns:
            The HTTP status and cache-version increment count.
        """
        view = GraphQLView.as_view(schema=schema, batch=batch)
        with patch.object(GraphQLView, "_bump_cache_version") as bump:
            response = view(request)
        return response.status_code, bump.call_count

    def test_get_mutation_rejected_with_405_does_not_invalidate(self) -> None:
        """Keep the cache version stable when GET rejects a mutation.

        A method rejection happens before any resolver can persist data.
        """
        request = self.factory.get(
            "/graphql/", {"query": "mutation { doThing { ok } }"}
        )
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 405)
        self.assertEqual(bump_count, 0)

    def test_validation_rejected_mutation_does_not_invalidate(self) -> None:
        """Keep the cache version stable when mutation validation fails.

        Invalid operations never reach mutation execution.
        """
        request = graphql_post(self.factory, "mutation { fieldThatDoesNotExist }")

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 400)
        self.assertEqual(bump_count, 0)

    def test_executed_mutation_invalidates(self) -> None:
        """Invalidate cached queries after a mutation executes.

        Resolver execution may have durably changed query-visible state.
        """
        request = graphql_post(self.factory, "mutation { doThing { ok } }")

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)

    def test_non_atomic_mutation_error_still_invalidates(self) -> None:
        """Invalidate after a non-atomic resolver reaches execution and fails.

        A write completed by an earlier resolver may already be durable.
        """
        request = graphql_post(self.factory, "mutation { fails { ok } }")

        status, bump_count = self._assert_bumps(request, schema=_rollback_schema)

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
        """Keep cached queries when an atomic mutation rolls back.

        The rejected mutation marks its transaction as non-durable.
        """
        request = graphql_post(self.factory, "mutation { rejected { ok } }")

        status, bump_count = self._assert_bumps(request, schema=_rollback_schema)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 0)

    def test_batch_with_executed_mutation_invalidates_once(self) -> None:
        """Invalidate once when a JSON batch executes a mutation.

        Query operations in the same batch do not add extra increments.
        """
        body = json.dumps(
            [
                {"query": "{ hello }"},
                {"query": "mutation { doThing { ok } }"},
            ]
        )
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request, batch=True)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)

    def test_multipart_with_executed_mutation_invalidates(self) -> None:
        """Invalidate when a multipart request executes a mutation.

        Multipart dispatch follows the same durable-execution contract.
        """
        request = self.factory.post(
            "/graphql/",
            data={"query": "mutation { doThing { ok } }"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()

        status, bump_count = self._assert_bumps(request)

        self.assertEqual(status, 200)
        self.assertEqual(bump_count, 1)
