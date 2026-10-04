"""Keep scoped SQLite mutation SQL values separate from declared identifiers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import IntegrityError, connection, models, transaction

from django_graphex.core.backend import PydanticBackend, _check_sqlite_written_relations
from tests.models import Author, Post


class SecurityTarget(models.Model):
    """Provide a constrained relation target in the disposable test schema.

    The table name is a SQL keyword so identifier quoting is observable.
    """

    code = models.CharField(max_length=80, unique=True)

    class Meta:
        """Use a SQL keyword to require identifier quoting.

        The fixture is local to this test module.
        """

        app_label = "scoped_security_fixture"
        db_table = "select"


class SecurityOwner(models.Model):
    """Use a caller-provided string primary key for through-row selection.

    The SQL-looking key must stay in the parameter sequence.
    """

    code = models.CharField(max_length=80, primary_key=True)
    targets = models.ManyToManyField(SecurityTarget, through="SecurityLink")

    class Meta:
        """Keep the owner table inside the disposable fixture app.

        Its SQL-keyword name tests quoting in the FK checker.
        """

        app_label = "scoped_security_fixture"
        db_table = "group"


class SecurityLink(models.Model):
    """Hold the directly written constrained relation row.

    The checker selects this row by the owner key.
    """

    owner = models.ForeignKey(SecurityOwner, on_delete=models.CASCADE)
    target = models.ForeignKey(
        SecurityTarget, to_field="code", on_delete=models.CASCADE
    )

    class Meta:
        """Use another SQL keyword to require declared-table quoting.

        Only Django-declared metadata may enter SQL text.
        """

        app_label = "scoped_security_fixture"
        db_table = "order"


def _info() -> SimpleNamespace:
    """Provide the mutation backend's minimal request context.

    Returns:
        Resolver-shaped context without files or metadata.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


@pytest.mark.django_db(transaction=True)
def test_scoped_queries_bind_hostile_owner_keys_and_quote_declared_names() -> None:
    """Bind a SQL-looking owner key without changing unrelated target rows.

    Raises:
        AssertionError: If caller bytes enter SQL text or bypass FK validation.
    """
    with connection.schema_editor() as editor:
        for model in (SecurityTarget, SecurityOwner, SecurityLink):
            editor.create_model(model)
    try:
        target = SecurityTarget.objects.create(code="safe")
        author = Author.objects.create(name="Unrelated")
        hostile = "x' OR 1=1; DROP TABLE order; --"
        observed: list[tuple[str, tuple[Any, ...]]] = []

        def record(
            execute: Any, sql: str, params: Any, many: bool, context: Any
        ) -> Any:
            """Capture pre-interpolation SQL and bound parameters.

            Args:
                execute: Django's next database execute callback.
                sql: Statement before adapter parameter interpolation.
                params: Separate bound values.
                many: Whether Django requested bulk execution.
                context: Django execution metadata.

            Returns:
                The database execution result.
            """
            if "AS child" in sql and "NOT EXISTS" in sql:
                observed.append((sql, tuple(params or ())))
            return execute(sql, params, many, context)

        backend = PydanticBackend(Post)
        with connection.execute_wrapper(record), transaction.atomic():
            ok, post = backend.save_object(
                None,
                None,
                _info(),
                {"title": hostile, "author": author.pk, "body": ""},
            )
            assert ok, post
            owner = SecurityOwner.objects.create(code=hostile)
            SecurityLink.objects.create(owner=owner, target_id=target.code)
            _check_sqlite_written_relations(owner, {"targets"}, "default")
        assert observed
        assert any(hostile in params for _, params in observed), observed
        assert all(hostile not in sql for sql, _ in observed)
        assert any('FROM "order" AS child' in sql for sql, _ in observed)
        assert any('FROM "select" AS parent' in sql for sql, _ in observed)
        assert SecurityTarget.objects.filter(pk=target.pk).exists()
        assert Post.objects.filter(pk=post.pk, title=hostile).exists()

        with transaction.atomic():
            with pytest.raises(IntegrityError, match="target"):
                with transaction.atomic():
                    SecurityLink.objects.create(owner=owner, target_id="missing")
                    _check_sqlite_written_relations(owner, {"targets"}, "default")
            assert SecurityTarget.objects.filter(pk=target.pk).exists()
            assert SecurityLink.objects.filter(owner=owner).count() == 1
    finally:
        with connection.schema_editor() as editor:
            for model in (SecurityLink, SecurityOwner, SecurityTarget):
                editor.delete_model(model)
