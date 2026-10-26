"""Keep the documented introspection switch aligned with HTTP behavior."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import RequestFactory, override_settings
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex.views import BaseGraphQLView

MIDDLEWARE = "django_graphex.security.DisableIntrospectionMiddleware"
SECURITY_GUIDE = Path(__file__).resolve().parents[1] / "docs/usage/security.md"
INTROSPECTION_QUERY = "{ __schema { queryType { name } } }"


def test_security_guide_installs_middleware_before_blocking_introspection() -> None:
    """Require an actionable opt-in configuration in the security guide.

    The setting alone cannot block introspection while the default middleware
    chain is empty.
    """
    section = SECURITY_GUIDE.read_text().split("## Disable introspection", 1)[1]
    example = section.split("```python", 1)[1].split("```", 1)[0]
    assignment = next(
        node
        for node in ast.parse(example).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DJANGO_GRAPHEX"
            for target in node.targets
        )
    )
    configuration = ast.literal_eval(assignment.value)

    assert configuration["ALLOW_INTROSPECTION"] is False
    assert MIDDLEWARE in configuration["MIDDLEWARE"]


@pytest.mark.parametrize(
    ("middleware", "allow_introspection", "blocked"),
    [([], False, False), ([MIDDLEWARE], False, True), ([MIDDLEWARE], True, False)],
)
def test_introspection_setting_requires_installed_middleware(
    middleware: list[str], allow_introspection: bool, blocked: bool
) -> None:
    """Check the HTTP outcomes behind the documented configuration.

    Args:
        middleware: GraphQL execution middleware configured for the request.
        allow_introspection: Whether the introspection override is enabled.
        blocked: Whether the response must reject introspection.
    """
    schema = SimpleNamespace(
        graphql_schema=GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {"ping": GraphQLField(GraphQLString, resolve=lambda *_: "pong")},
            )
        )
    )
    request = RequestFactory().post(
        "/graphql/",
        data=json.dumps({"query": INTROSPECTION_QUERY}),
        content_type="application/json",
    )
    with override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": allow_introspection,
            "INTROSPECTION_ALLOW_SUPERUSER": False,
            "MIDDLEWARE": middleware,
        }
    ):
        response = BaseGraphQLView.as_view(schema=schema)(request)

    payload = json.loads(response.content)
    if blocked:
        assert response.status_code == 200
        assert payload["errors"][0]["message"] == "GraphQL introspection is disabled."
        assert payload["data"] is None
    else:
        assert response.status_code == 200
        assert payload["data"]["__schema"]["queryType"]["name"] == "Query"
