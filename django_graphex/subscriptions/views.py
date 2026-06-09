"""Provide an HTTP view resolving a subscription into a one-shot confirmation.

The package's :class:`BaseGraphQLView` refuses subscription operations
(graphql-core routes them through "subscribe" rather than "execute"). This view
drives the async iterator returned by "subscribe" for exactly one value -- the
join/leave confirmation produced by the "Subscription._subscribe" method.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from django.views.decorators.csrf import csrf_exempt
from graphql import ExecutionResult, OperationType, parse, subscribe, validate
from graphql.utilities import get_operation_ast

from .._graphene_settings import graphene_settings
from ..views import BaseGraphQLView

if TYPE_CHECKING:
    from typing import Callable

    from django.http import HttpRequest
    from graphql import DocumentNode, GraphQLSchema


class SubscriptionGraphQLView(BaseGraphQLView):
    """Execute the preserved one-shot subscriptions over HTTP."""

    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Callable[..., Any]:
        """Expose the view CSRF-exempt, like the other extras GraphQL views.

        Returns:
            The CSRF-exempt view callable.
        """
        view = super().as_view(*args, **kwargs)
        return csrf_exempt(view)

    def execute_graphql_request(
        self,
        request: HttpRequest,
        data: dict[str, Any],
        query: str | None,
        variables: dict[str, Any] | None,
        operation_name: str | None,
        show_graphiql: bool = False,
    ) -> ExecutionResult | None:
        """Route subscription operations through subscribe; delegate the rest.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.
            query: The GraphQL query string.
            variables: The query variable values.
            operation_name: The operation name to execute.
            show_graphiql: Whether the GraphiQL interface is being shown.

        Returns:
            The execution result, or whatever the base view returns for
            non-subscription operations.
        """
        if not query:
            return super().execute_graphql_request(
                request, data, query, variables, operation_name, show_graphiql
            )

        schema = self.schema.graphql_schema

        try:
            document = parse(query)
        except Exception as exc:  # invalid syntax -> let the base view format it
            return ExecutionResult(errors=[exc])

        operation_ast = get_operation_ast(document, operation_name)
        if (
            operation_ast is None
            or operation_ast.operation != OperationType.SUBSCRIPTION
        ):
            return super().execute_graphql_request(
                request, data, query, variables, operation_name, show_graphiql
            )

        validation_errors = validate(
            schema,
            document,
            self.validation_rules,
            graphene_settings.MAX_VALIDATION_ERRORS,
        )
        if validation_errors:
            return ExecutionResult(data=None, errors=validation_errors)

        try:
            return async_to_sync(self._subscribe_once)(
                schema,
                document,
                root_value=self.get_root_value(request),
                context_value=self.get_context(request),
                variable_values=variables,
                operation_name=operation_name,
            )
        except Exception as exc:  # noqa: BLE001 - returned to the client as errors
            return ExecutionResult(errors=[exc])

    @staticmethod
    async def _subscribe_once(
        schema: GraphQLSchema,
        document: DocumentNode,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Await subscribe and return its first execution result only.

        Args:
            schema: The GraphQL schema to subscribe against.
            document: The parsed subscription document.
            **kwargs: Additional arguments forwarded to "subscribe".

        Returns:
            The first "ExecutionResult" yielded by the subscription.
        """
        result = subscribe(schema, document, **kwargs)
        if inspect.isawaitable(result):
            result = await result

        # On a subscribe-time error graphql-core returns an ExecutionResult.
        if isinstance(result, ExecutionResult):
            return result

        try:
            return await result.__anext__()
        except StopAsyncIteration:
            return ExecutionResult(data=None, errors=None)
        finally:
            aclose = getattr(result, "aclose", None)
            if aclose is not None:
                await aclose()


__all__ = ["SubscriptionGraphQLView"]
