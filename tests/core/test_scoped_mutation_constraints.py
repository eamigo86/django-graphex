"""SQLite mutation checks must be scoped to rows written by that mutation."""

import uuid
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, models, transaction
from django.test.utils import CaptureQueriesContext

from django_graphex.core.backend import (
    PydanticBackend,
    _check_sqlite_written_relations,
)
from tests.models import Author, Post


class ScopedTarget(models.Model):
    """Provide a non-primary referenced key for direct-write checks.

    The code field is the actual foreign-key target in fixture models.
    """

    code = models.CharField(max_length=32, unique=True)

    class Meta:
        """Keep disposable schema outside the installed test app.

        Each fixture table is created and removed by its owning test.
        """

        app_label = "scoped_constraint_fixture"


class ScopedChild(models.Model):
    """Exercise persisted constrained and unconstrained foreign keys.

    The optional and unchecked fields distinguish database constraints.
    """

    target = models.ForeignKey(ScopedTarget, to_field="code", on_delete=models.CASCADE)
    optional = models.ForeignKey(
        ScopedTarget,
        to_field="code",
        null=True,
        on_delete=models.CASCADE,
        related_name="optional_children",
    )
    unchecked = models.ForeignKey(
        ScopedTarget,
        to_field="code",
        db_constraint=False,
        on_delete=models.CASCADE,
        related_name="unchecked_children",
    )

    class Meta:
        """Keep disposable schema outside the installed test app.

        Each fixture table is created and removed by its owning test.
        """

        app_label = "scoped_constraint_fixture"


class ScopedOwner(models.Model):
    """Own a custom relation table checked only for this owner's links.

    A second owner provides unrelated invalid-link coverage.
    """

    targets = models.ManyToManyField(ScopedTarget, through="ScopedLink")

    class Meta:
        """Keep disposable schema outside the installed test app.

        Each fixture table is created and removed by its owning test.
        """

        app_label = "scoped_constraint_fixture"


class ScopedLink(models.Model):
    """Store custom through rows with a non-primary target field.

    The relation is explicit rather than Django's auto-created table.
    """

    owner = models.ForeignKey(ScopedOwner, on_delete=models.CASCADE)
    target = models.ForeignKey(ScopedTarget, to_field="code", on_delete=models.CASCADE)

    class Meta:
        """Keep disposable schema outside the installed test app.

        Each fixture table is created and removed by its owning test.
        """

        app_label = "scoped_constraint_fixture"


class UuidTarget(models.Model):
    """Provide a UUID primary key for SQLite value adaptation.

    The key is stored as a backend-specific database representation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        """Keep the UUID table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class UuidChild(models.Model):
    """Reference a UUID target from a directly written row.

    The saved row exercises bound primary and foreign keys.
    """

    target = models.ForeignKey(UuidTarget, on_delete=models.CASCADE)

    class Meta:
        """Keep the UUID child table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class UuidOwner(models.Model):
    """Own relation rows selected by a UUID source key.

    The link query must bind that key in its stored representation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    targets = models.ManyToManyField(UuidTarget, through="UuidLink")

    class Meta:
        """Keep the UUID owner table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class UuidLink(models.Model):
    """Link UUID owners and targets through constrained foreign keys.

    The relation is checked only for the selected owner.
    """

    owner = models.ForeignKey(UuidOwner, on_delete=models.CASCADE)
    target = models.ForeignKey(UuidTarget, on_delete=models.CASCADE)

    class Meta:
        """Keep the UUID link table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


def _info() -> SimpleNamespace:
    """Return the minimal resolver context required by the backend.

    Returns:
        Resolver context with empty request metadata and files.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


@pytest.mark.django_db(transaction=True)
def test_valid_atomic_write_has_bounded_sql_without_table_check() -> None:
    """A valid write checks its own FK, not all rows in the Post table.

    The request stays within a constant SQL budget independent of table size.
    """
    author = Author.objects.create(name="Owner")
    backend = PydanticBackend(Post)

    with transaction.atomic():
        with CaptureQueriesContext(connection) as captured:
            ok, post = backend.save_object(
                None,
                None,
                _info(),
                {"title": "Valid", "author": author.pk, "body": ""},
            )
        assert ok, post

    statements = [item["sql"].upper() for item in captured.captured_queries]
    assert not any("FOREIGN_KEY_CHECK" in sql for sql in statements)
    assert len(statements) <= 5, statements
    assert Post.objects.filter(pk=post.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_unrelated_deferred_violation_waits_until_outer_commit() -> None:
    """An earlier invalid row cannot make an unrelated valid mutation fail.

    The unresolved violation still fails the outer transaction commit.
    """
    author = Author.objects.create(name="Owner")
    backend = PydanticBackend(Post)
    mutation_succeeded = False

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Post.objects.create(title="Earlier invalid", author_id=999999)
            ok, valid = backend.save_object(
                None,
                None,
                _info(),
                {"title": "Valid", "author": author.pk, "body": ""},
            )
            assert ok, valid
            assert Post.objects.filter(pk=valid.pk).exists()
            mutation_succeeded = True

    assert mutation_succeeded
    assert Post.objects.count() == 0
    assert Author.objects.count() == 1
    assert Author.objects.create(name="Still usable").pk is not None


@pytest.mark.django_db(transaction=True)
def test_persisted_target_field_and_unconstrained_fk() -> None:
    """Validate the stored non-PK target and ignore db_constraint=False.

    Changing only the persisted value must be observed by the checker.
    """
    with connection.schema_editor() as editor:
        editor.create_model(ScopedTarget)
        editor.create_model(ScopedChild)
    try:
        target = ScopedTarget.objects.create(code="valid")
        backend = PydanticBackend(ScopedChild)
        assert backend._db_check_errors({"target": target.code}, None) == {}
        assert backend._db_check_errors({"target": "missing"}, None) == {
            "target": ['Invalid pk "missing" - object does not exist.']
        }
        child = ScopedChild.objects.create(
            target_id=target.code, optional_id=None, unchecked_id="not-present"
        )
        with transaction.atomic():
            _check_sqlite_written_relations(child, set(), "default")
            ScopedChild.objects.filter(pk=child.pk).update(target_id="missing")
            with pytest.raises(IntegrityError, match="target"):
                _check_sqlite_written_relations(child, set(), "default")
            ScopedChild.objects.filter(pk=child.pk).update(target_id=target.code)
        assert ScopedChild.objects.get(pk=child.pk).target_id == "valid"
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(ScopedChild)
            editor.delete_model(ScopedTarget)


@pytest.mark.django_db(transaction=True)
def test_custom_through_checks_only_current_owner_links() -> None:
    """A custom link's invalid FK is caught without scanning other owners.

    Only links associated with the current owner enter the scoped check.
    """
    with connection.schema_editor() as editor:
        editor.create_model(ScopedTarget)
        editor.create_model(ScopedOwner)
        editor.create_model(ScopedLink)
    try:
        target = ScopedTarget.objects.create(code="valid")
        first = ScopedOwner.objects.create()
        other = ScopedOwner.objects.create()
        with transaction.atomic():
            ScopedLink.objects.create(owner=other, target_id="unrelated")
            ScopedLink.objects.create(owner=first, target_id=target.code)
            _check_sqlite_written_relations(first, {"targets"}, "default")
            ScopedLink.objects.create(owner=first, target_id="missing")
            with pytest.raises(IntegrityError, match="target"):
                _check_sqlite_written_relations(first, {"targets"}, "default")
            transaction.set_rollback(True)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(ScopedLink)
            editor.delete_model(ScopedOwner)
            editor.delete_model(ScopedTarget)


@pytest.mark.django_db(transaction=True)
def test_omitted_update_still_checks_persisted_fk() -> None:
    """An update checks the saved row even when its FK was not in the payload.

    The failed update rolls back to its savepoint without changing the row.
    """
    backend = PydanticBackend(Post)
    with transaction.atomic():
        post = Post.objects.create(title="Invalid first", author_id=999999)
        with pytest.raises(IntegrityError, match="author"):
            backend.save_object(
                None,
                None,
                _info(),
                {"title": "Still invalid"},
                instance=post,
                partial=True,
            )
        assert Post.objects.get(pk=post.pk).title == "Invalid first"
        transaction.set_rollback(True)
    assert Post.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_uuid_row_and_relation_keys_are_database_prepared() -> None:
    """A UUID owner and target must still receive scoped FK checks.

    Raw SQL binds must use Django field conversion for each key.
    """
    with connection.schema_editor() as editor:
        for model in (UuidTarget, UuidChild, UuidOwner, UuidLink):
            editor.create_model(model)
    try:
        target = UuidTarget.objects.create()
        child = UuidChild.objects.create(target=target)
        owner = UuidOwner.objects.create()
        with transaction.atomic():
            UuidLink.objects.create(owner=owner, target=target)
            _check_sqlite_written_relations(child, set(), "default")
            _check_sqlite_written_relations(owner, {"targets"}, "default")
            UuidChild.objects.filter(pk=child.pk).update(target_id=uuid.uuid4())
            with pytest.raises(IntegrityError, match="target"):
                _check_sqlite_written_relations(child, set(), "default")
            transaction.set_rollback(True)
    finally:
        with connection.schema_editor() as editor:
            for model in (UuidLink, UuidOwner, UuidChild, UuidTarget):
                editor.delete_model(model)
