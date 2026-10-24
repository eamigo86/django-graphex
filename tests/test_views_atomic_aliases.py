"""Transaction rollback across database aliases for GraphQL execution errors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.db import connection, connections
from django.test import Client, override_settings
from django.urls import path
from graphql import GraphQLError, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Tag
from tests.test_mutations import _RMUT, TestQuery

pytestmark = pytest.mark.django_db(transaction=True)


class _Mutation(ObjectType):
    """Write to the "other" alias, then succeed or fail."""

    write_other = field(GraphQLString)
    write_other_then_fail = field(GraphQLString)

    def resolve_write_other(root: Any, info: Any) -> str:
        """Create a tag on the other alias.

        Args:
            root: Unused mutation root.
            info: Unused GraphQL resolve information.

        Returns:
            A marker string.
        """
        Tag.objects.using("other").create(label="other-ok")
        return "ok"

    def resolve_write_other_then_fail(root: Any, info: Any) -> str:
        """Create a tag on the other alias, then raise.

        Args:
            root: Unused mutation root.
            info: Unused GraphQL resolve information.

        Raises:
            GraphQLError: Always, after the write.
        """
        Tag.objects.using("other").create(label="other-fail")
        raise GraphQLError("boom-other")


_SCHEMA = DjangoGraphQLSchema(
    query=TestQuery, mutation=_Mutation, registries=isolated_pair(_RMUT)
)


@pytest.fixture
def other_db(
    django_db_setup: Any, django_db_blocker: Any, tmp_path: Any
) -> Iterator[None]:
    """Provide a second, file-backed SQLite alias with the Tag table.

    Args:
        django_db_setup: pytest-django database setup fixture.
        django_db_blocker: pytest-django database blocker.
        tmp_path: Per-test temporary directory.

    Yields:
        Control to the test with the "other" alias configured.
    """
    settings.DATABASES["other"] = {
        **settings.DATABASES["default"],
        "NAME": str(tmp_path / "other.sqlite3"),
    }
    with django_db_blocker.unblock():
        with connections["other"].schema_editor() as editor:
            editor.create_model(Tag)
        yield
        connections["other"].close()
    del connections._connections.other
    del settings.DATABASES["other"]


def _post(
    body: Any,
    *,
    atomic_mutations: bool = False,
    other_atomic_mutations: bool = False,
    atomic_requests: bool = False,
    batch: bool = False,
) -> Any:
    """POST a GraphQL body with the given transaction configuration.

    Args:
        body: A query string, or a list of operations when batching.
        atomic_mutations: The global "ATOMIC_MUTATIONS" setting.
        other_atomic_mutations: "ATOMIC_MUTATIONS" on the other alias only.
        atomic_requests: "ATOMIC_REQUESTS" on both aliases.
        batch: Whether the view accepts batches.

    Returns:
        The decoded JSON response.
    """
    urlconf = type("U", (), {})
    urlconf.urlpatterns = [
        path("graphql/", GraphQLView.as_view(schema=_SCHEMA, batch=batch))
    ]
    default_settings = connection.settings_dict
    other_settings = connections["other"].settings_dict
    saved = (
        default_settings.get("ATOMIC_REQUESTS", False),
        other_settings.get("ATOMIC_REQUESTS", False),
        other_settings.get("ATOMIC_MUTATIONS", False),
    )
    default_settings["ATOMIC_REQUESTS"] = atomic_requests
    other_settings["ATOMIC_REQUESTS"] = atomic_requests
    other_settings["ATOMIC_MUTATIONS"] = other_atomic_mutations
    try:
        with override_settings(
            ROOT_URLCONF=urlconf,
            DJANGO_GRAPHEX={
                "SCHEMA": None,
                "ATOMIC_MUTATIONS": atomic_mutations,
                "CACHE_ACTIVE": False,
            },
        ):
            data = body if batch else {"query": body}
            response = Client().post("/graphql/", data, content_type="application/json")
    finally:
        (
            default_settings["ATOMIC_REQUESTS"],
            other_settings["ATOMIC_REQUESTS"],
            other_settings["ATOMIC_MUTATIONS"],
        ) = saved
    return response.json()


def _count(label: str) -> int:
    """Count tags with a label on the other alias.

    Args:
        label: The tag label.

    Returns:
        The number of persisted rows.
    """
    return Tag.objects.using("other").filter(label=label).count()


def test_single_request_error_rolls_back_other_alias(other_db: None) -> None:
    """ATOMIC_REQUESTS on the other alias rolls back its write on an error.

    Args:
        other_db: Fixture providing the second database alias.
    """
    payload = _post("mutation { writeOtherThenFail }", atomic_requests=True)
    assert payload["errors"][0]["message"] == "boom-other"
    assert _count("other-fail") == 0


def test_single_request_success_keeps_other_alias_write(other_db: None) -> None:
    """A successful operation still commits the other alias write.

    Args:
        other_db: Fixture providing the second database alias.
    """
    payload = _post("mutation { writeOther }", atomic_requests=True)
    assert payload["data"] == {"writeOther": "ok"}
    assert _count("other-ok") == 1


def test_non_atomic_other_alias_is_untouched(other_db: None) -> None:
    """Without any atomic block the other alias write persists, as before.

    Args:
        other_db: Fixture providing the second database alias.
    """
    _post("mutation { writeOtherThenFail }")
    assert _count("other-fail") == 1


def test_batch_item_error_rolls_back_only_that_item(other_db: None) -> None:
    """A failing batch item rolls back its other-alias write; siblings commit.

    Args:
        other_db: Fixture providing the second database alias.
    """
    payloads = _post(
        [
            {"query": "mutation { writeOtherThenFail }"},
            {"query": "mutation { writeOther }"},
        ],
        atomic_requests=True,
        batch=True,
    )
    assert payloads[0]["errors"][0]["message"] == "boom-other"
    assert payloads[1]["data"] == {"writeOther": "ok"}
    assert _count("other-fail") == 0
    assert _count("other-ok") == 1


def test_per_alias_atomic_mutations_rolls_back_other_alias(other_db: None) -> None:
    """DATABASES[alias]['ATOMIC_MUTATIONS'] wraps and rolls back that alias.

    Args:
        other_db: Fixture providing the second database alias.
    """
    payload = _post("mutation { writeOtherThenFail }", other_atomic_mutations=True)
    assert payload["errors"][0]["message"] == "boom-other"
    assert _count("other-fail") == 0


def test_per_alias_atomic_mutations_commits_on_success(other_db: None) -> None:
    """The per-alias atomic block commits when the operation succeeds.

    Args:
        other_db: Fixture providing the second database alias.
    """
    payload = _post("mutation { writeOther }", other_atomic_mutations=True)
    assert payload["data"] == {"writeOther": "ok"}
    assert _count("other-ok") == 1


def test_global_atomic_mutations_does_not_wrap_other_alias(other_db: None) -> None:
    """The global setting keeps covering only the default alias.

    Args:
        other_db: Fixture providing the second database alias.
    """
    _post("mutation { writeOtherThenFail }", atomic_mutations=True)
    assert _count("other-fail") == 1
