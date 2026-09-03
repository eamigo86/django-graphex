"""PostgreSQL-only transaction contracts for django-graphex write paths."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import connection, transaction

from django_graphex.core.backend import PydanticBackend
from tests.core.test_savepoint_only_when_needed import AuthorWithProfileType, _create
from tests.models import Author, AuthorProfile, Post, Tag

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="requires GDX_TEST_DATABASE=postgres",
    ),
]


def _info() -> SimpleNamespace:
    """Return the resolver context needed by the backend."""
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


@pytest.fixture(autouse=True)
def _assert_postgresql_vendor() -> None:
    """Prevent this integration contract from ever reporting success on SQLite."""
    assert connection.vendor == "postgresql"


@pytest.mark.django_db(transaction=True)
def test_bad_fk_inside_atomic_rolls_back_and_keeps_connection_usable() -> None:
    """A failed FK insert rolls back to the inner savepoint before diagnostics.

    This test protects the corresponding regression contract.
    """
    backend = PydanticBackend(Post)
    with transaction.atomic():
        ok, errors = backend.save_object(
            None,
            None,
            _info(),
            {"title": "bad", "author": 999999, "body": ""},
        )
        assert ok is False
        assert {error.field for error in errors} == {"author"}
        assert Post.objects.count() == 0
        assert Author.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_bad_m2m_rolls_back_the_parent_row() -> None:
    """A missing tag cannot leave the preceding parent INSERT behind.

    This test protects the corresponding regression contract.
    """
    author = Author.objects.create(name="author")
    backend = PydanticBackend(Post)
    ok, errors = backend.save_object(
        None,
        None,
        _info(),
        {"title": "bad m2m", "author": author.pk, "body": "", "tags": [999999]},
    )
    assert ok is False
    assert {error.field for error in errors} == {"tags"}
    assert Post.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_nested_failure_rolls_back_parent_and_child() -> None:
    """A rejected reverse one-to-one list persists neither object.

    This test protects the corresponding regression contract.
    """
    result = _create(
        AuthorWithProfileType,
        {"name": "writer", "author_profile": [{"bio": "a"}, {"bio": "b"}]},
    )
    assert result.ok is False
    assert Author.objects.count() == 0
    assert AuthorProfile.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_valid_autocommit_write_persists_relations() -> None:
    """The PostgreSQL happy path persists a valid FK and M2M relation.

    This test protects the corresponding regression contract.
    """
    author = Author.objects.create(name="author")
    tag = Tag.objects.create(label="tag")
    backend = PydanticBackend(Post)
    ok, post = backend.save_object(
        None,
        None,
        _info(),
        {"title": "valid", "author": author.pk, "body": "", "tags": [tag.pk]},
    )
    assert ok is True
    assert Post.objects.get(pk=post.pk).tags.get() == tag


@pytest.mark.django_db(transaction=True)
def test_connection_is_reused_after_recovered_integrity_error() -> None:
    """Failure diagnostics leave the existing DB-API connection reusable.

    This test protects the corresponding regression contract.
    """
    connection.ensure_connection()
    raw_connection = connection.connection
    backend = PydanticBackend(Post)

    with transaction.atomic():
        ok, _ = backend.save_object(
            None,
            None,
            _info(),
            {"title": "bad", "author": 999999, "body": ""},
        )
        assert ok is False
        assert Author.objects.create(name="still usable").pk is not None

    assert connection.connection is raw_connection
