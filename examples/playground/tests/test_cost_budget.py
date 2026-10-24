"""The cost budget the README suggests lets its own examples run.

Uncommenting a "MAX_QUERY_COST" in "config/settings.py" is only useful if the
documented example queries still pass under it. A budget of 200 (the value the
README used to suggest) rejects even "{ posts { results(limit: 1) { id } } }",
because the cost model charges an unspecified nested page at "MAX_PAGE_SIZE".
These tests measure instead of guessing: every plain query the README shows runs
under the suggested budget and reports its cost, while an unbounded nested list
is refused.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.conf import settings
from django.test import override_settings

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.test import Client

pytestmark = pytest.mark.django_db

BUDGET = 10_000_000
DEPTH = 6
_README = Path(__file__).resolve().parent.parent / "README.md"

# 3 levels of unbounded nested lists: 100 * 100 * 100 and beyond.
_ABUSIVE = (
    "{ authors { results { posts { results { comments { results { text } } } } } } }"
)


def _readme_queries() -> list[str]:
    """Collect the read-only example documents the README shows.

    Returns:
        queries: Each fenced "graphql" block that opens with a bare selection set
            and carries no placeholder, in README order.
    """
    blocks = re.findall(r"```graphql\n(.*?)```", _README.read_text(), re.S)
    return [b for b in blocks if b.lstrip().startswith("{") and "…" not in b]


def _run(client: Client, query: str) -> dict[str, Any]:
    """POST a query under the suggested cost settings and return the body.

    Args:
        client: The Django test client issuing the request.
        query: The GraphQL document to execute.

    Returns:
        body: The decoded JSON response body.
    """
    response = client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    return response.json()


@pytest.fixture
def budgeted(client: Client, django_user_model: type[AbstractBaseUser]) -> Client:
    """Log in and apply the settings the README suggests for the cost budget.

    Args:
        client: The Django test client.
        django_user_model: The active user model, used to create the caller.

    Yields:
        client: The logged-in client, with "MAX_QUERY_COST" and
            "EXPOSE_QUERY_COST" active for the duration of the test.
    """
    client.force_login(
        django_user_model.objects.create_superuser("cost", password="pw12345678")
    )
    namespace = dict(settings.DJANGO_GRAPHEX)
    namespace.update(
        MAX_QUERY_COST=BUDGET, MAX_QUERY_DEPTH=DEPTH, EXPOSE_QUERY_COST=True
    )
    with override_settings(DJANGO_GRAPHEX=namespace):
        yield client


def test_the_readme_suggests_exactly_the_measured_settings() -> None:
    """Assert the README and the settings file quote the budget this test uses."""
    settings_text = (_README.parent / "config" / "settings.py").read_text()
    for text in (_README.read_text(), settings_text):
        assert f'"MAX_QUERY_COST": {BUDGET:_}' in text
    assert f'"MAX_QUERY_DEPTH": {DEPTH}' in settings_text


def test_every_readme_query_runs_under_the_suggested_budget(budgeted: Client) -> None:
    """Assert each README example passes validation and reports a cost under budget.

    Args:
        budgeted: The logged-in client with the suggested cost settings applied.
    """
    queries = _readme_queries()
    assert len(queries) >= 8, "the README example extraction found too few queries"

    for query in queries:
        body = _run(budgeted, query)
        assert not body.get("errors"), (query, body["errors"])
        cost = body["extensions"]["cost"]
        assert cost["maxCost"] == BUDGET
        assert 0 <= cost["requestedCost"] <= BUDGET, (query, cost)


def test_an_unbounded_nested_list_is_refused(budgeted: Client) -> None:
    """Assert the suggested budget still stops the abusive shape.

    Args:
        budgeted: The logged-in client with the suggested cost settings applied.
    """
    body = _run(budgeted, _ABUSIVE)

    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX", body
    assert "exceeds the maximum" in body["errors"][0]["message"]


def test_the_old_suggestion_blocked_every_list_query(budgeted: Client) -> None:
    """Assert why 200 was a bad suggestion: it refuses a one-row list query.

    Args:
        budgeted: The logged-in client; the budget is lowered inside the test.
    """
    namespace = dict(settings.DJANGO_GRAPHEX)
    namespace["MAX_QUERY_COST"] = 200
    with override_settings(DJANGO_GRAPHEX=namespace):
        body = _run(budgeted, "{ posts { results(limit: 1) { id } } }")

    assert "exceeds the maximum of 200" in body["errors"][0]["message"], body
