"""Pin the documented rule that every empty Boolean construct is a no-op."""

from __future__ import annotations

import pytest

from .test_and_many_filtering import _post, _seed

EVERY_ROW = ["absent", "only-x", "same", "split"]
EMPTY_CONSTRUCTS = [
    "{}",
    "{ and: [] }",
    "{ or: [] }",
    "{ not: {} }",
    "{ not: { and: [] } }",
    "{ not: { or: [] } }",
    "{ tags: {} }",
    "{ tags: { and: [] } }",
    "{ tags: { or: [] } }",
    "{ tags: { not: {} } }",
    "{ and: [{ or: [] }] }",
    "{ or: [{ and: [] }] }",
    "{ title: {} }",
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("construct", EMPTY_CONSTRUCTS)
def test_empty_construct_imposes_no_condition(construct: str) -> None:
    """An empty Boolean construct returns every row, never none.

    Args:
        construct: GraphQL filter value that contains no real condition.
    """
    _seed()
    query = f"{{ posts(filter: {construct}) {{ results {{ title }} }} }}"
    assert _post(query) == EVERY_ROW
