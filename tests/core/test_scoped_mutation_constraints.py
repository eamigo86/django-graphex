"""SQLite mutation checks must be scoped to rows written by that mutation."""

import uuid
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, connections, models, transaction
from django.test.utils import CaptureQueriesContext, isolate_apps

from django_graphex.core.backend import (
    PydanticBackend,
    _check_sqlite_written_relations,
)
from tests.models import Author, Post, Tag


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


class CompositeChild(models.Model):
    """Exercise the explicit fallback for a composite primary key.

    Its row cannot be addressed through a single database column.
    """

    first = models.IntegerField()
    second = models.IntegerField()
    pk = models.CompositePrimaryKey("first", "second")
    target = models.ForeignKey(ScopedTarget, to_field="code", on_delete=models.CASCADE)

    class Meta:
        """Keep the composite-key table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class InheritedTarget(models.Model):
    """Provide a referenced key for inherited parent rows.

    The FK belongs physically to the concrete parent table.
    """

    label = models.CharField(max_length=32)

    class Meta:
        """Keep the target table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class InheritedParent(models.Model):
    """Own a nullable constrained FK inherited by a concrete child.

    Django stores this field only in the parent table.
    """

    target = models.ForeignKey(InheritedTarget, null=True, on_delete=models.CASCADE)

    class Meta:
        """Keep the parent table in the disposable fixture app.

        The test owns its schema lifecycle.
        """

        app_label = "scoped_constraint_fixture"


class InheritedChild(InheritedParent):
    """Write a child row and its parent-owned FK in one mutation.

    The automatic parent link is stored in the child table.
    """

    extra = models.CharField(max_length=32)

    class Meta:
        """Keep the child table in the disposable fixture app.

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

    The checker uses one key-filtered statement independent of table size.
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
    scoped_checks = [sql for sql in statements if "SELECT CASE" in sql]
    assert len(scoped_checks) == 1, statements
    assert 'WHERE CHILD."ID" =' in scoped_checks[0]
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
            with CaptureQueriesContext(connection) as captured:
                _check_sqlite_written_relations(first, {"targets"}, "default")
            link_checks = [
                item["sql"]
                for item in captured
                if f'FROM "{ScopedLink._meta.db_table}" AS child' in item["sql"]
            ]
            assert link_checks
            assert all('child."owner_id" =' in sql for sql in link_checks)
            assert all(" OR " not in sql for sql in link_checks)
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


@pytest.mark.django_db(transaction=True)
def test_composite_key_retains_table_constraint_fallback() -> None:
    """Composite keys retain database checks rather than skipping them.

    The fallback is explicitly table-scoped, not claimed to be constant work.
    """
    with connection.schema_editor() as editor:
        editor.create_model(ScopedTarget)
        editor.create_model(CompositeChild)
    try:
        target = ScopedTarget.objects.create(code="valid")
        with transaction.atomic():
            child = CompositeChild.objects.create(
                first=1, second=2, target_id=target.code
            )
            _check_sqlite_written_relations(child, set(), "default")
            CompositeChild.objects.filter(first=1, second=2).update(target_id="bad")
            with pytest.raises(IntegrityError):
                _check_sqlite_written_relations(child, set(), "default")
            transaction.set_rollback(True)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(CompositeChild)
            editor.delete_model(ScopedTarget)


@pytest.mark.django_db(transaction=True)
def test_non_sqlite_path_retains_existing_table_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-SQLite branch still invokes the existing table check.

    A SQLite connection stands in only to check branch routing; this is not
    a substitute for actual PostgreSQL integration testing.

    Args:
        monkeypatch: Fixture temporarily selecting the non-SQLite branch.
    """
    author = Author.objects.create(name="Owner")
    tag = Tag.objects.create(label="tag")
    backend = PydanticBackend(Post)
    database = connections["default"]
    checked_tables: list[list[str]] = []

    def record_tables(*, table_names: list[str]) -> None:
        """Record the tables passed to the existing check.

        Args:
            table_names: Tables the backend asks the database to check.
        """
        checked_tables.append(table_names)

    with monkeypatch.context() as patch:
        patch.setattr(database, "vendor", "other")
        patch.setattr(database, "check_constraints", record_tables)
        with transaction.atomic():
            ok, result = backend.save_object(
                None,
                None,
                _info(),
                {"title": "Valid", "author": author.pk, "body": "", "tags": [tag.pk]},
            )
            assert ok, result
    assert checked_tables == [[Post._meta.db_table, Post.tags.through._meta.db_table]]


@pytest.mark.django_db(transaction=True)
def test_inherited_parent_fk_uses_its_physical_table() -> None:
    """A valid inherited FK checks parent and child rows by their own keys.

    The checker must not read a parent-owned column from the child table.
    """
    with connection.schema_editor() as editor:
        for model in (InheritedTarget, InheritedParent, InheritedChild):
            editor.create_model(model)
    try:
        target = InheritedTarget.objects.create(label="valid")
        backend = PydanticBackend(InheritedChild)
        with transaction.atomic():
            with CaptureQueriesContext(connection) as captured:
                ok, child = backend.save_object(
                    None,
                    None,
                    _info(),
                    {"target": target.pk, "extra": "valid"},
                )
            assert ok, child
            assert InheritedParent.objects.filter(pk=child.pk).exists()
            assert InheritedChild.objects.filter(pk=child.pk).exists()
            checks = [
                item["sql"]
                for item in captured.captured_queries
                if "SELECT CASE" in item["sql"]
            ]
            assert len(checks) == 2, checks
            assert any(
                f'FROM "{InheritedParent._meta.db_table}"' in sql for sql in checks
            )
            assert any(
                f'FROM "{InheritedChild._meta.db_table}"' in sql for sql in checks
            )
            assert not any(
                "FOREIGN_KEY_CHECK" in item["sql"].upper() for item in captured
            )
            transaction.set_rollback(True)
        assert InheritedParent.objects.count() == 0
        assert InheritedChild.objects.count() == 0
        assert InheritedTarget.objects.filter(pk=target.pk).exists()
    finally:
        with connection.schema_editor() as editor:
            for model in (InheritedChild, InheritedParent, InheritedTarget):
                editor.delete_model(model)


@pytest.mark.django_db(transaction=True)
def test_inherited_parent_fk_failure_rolls_back_and_keeps_connection() -> None:
    """An invalid parent-owned FK fails without leaving a partial child row.

    The enclosing transaction remains usable after the inner savepoint rolls back.
    """
    with connection.schema_editor() as editor:
        for model in (InheritedTarget, InheritedParent, InheritedChild):
            editor.create_model(model)
    try:
        InheritedTarget.objects.create(label="valid")
        backend = PydanticBackend(InheritedChild)
        with transaction.atomic():
            ok, errors = backend.save_object(
                None,
                None,
                _info(),
                {"target": 999999, "extra": "invalid"},
            )
            assert ok is False
            assert {item.field for item in errors} == {"target"}
            assert InheritedParent.objects.count() == 0
            assert InheritedChild.objects.count() == 0
            ok, child = backend.save_object(
                None,
                None,
                _info(),
                {"target": None, "extra": "nullable"},
            )
            assert ok, child
            assert InheritedParent.objects.filter(pk=child.pk, target_id=None).exists()
            ok, errors = backend.save_object(
                None,
                None,
                _info(),
                {"target": 999999},
                instance=child,
                partial=True,
            )
            assert ok is False
            assert {item.field for item in errors} == {"target"}
            assert InheritedParent.objects.get(pk=child.pk).target_id is None
            transaction.set_rollback(True)
        assert InheritedParent.objects.count() == 0
        assert InheritedChild.objects.count() == 0
    finally:
        with connection.schema_editor() as editor:
            for model in (InheritedChild, InheritedParent, InheritedTarget):
                editor.delete_model(model)


@pytest.mark.django_db(transaction=True)
@isolate_apps("tests")
@pytest.mark.parametrize("model_kind", ["concrete", "proxy", "inherited"])
def test_symmetric_mirror_default_fk_rolls_back_with_direct_write(
    model_kind: str,
) -> None:
    """Reject an invalid mirror created by a normal symmetric relation set.

    A subsequent valid mutation must work in the same outer transaction,
    including when the relation is inherited or exposed through a proxy.

    Args:
        model_kind: Concrete, proxy, or inherited model used for the write.
    """
    defaults: list[int] = []

    def next_guard() -> int:
        """Supply independently chosen guards for the two direct rows.

        Returns:
            The next configured guard key.
        """
        return defaults.pop(0)

    class SymmetricGuard(models.Model):
        """Provide the extra constrained target on each through row.

        This fixture has no fields beyond the generated primary key.
        """

        class Meta:
            """Register only in this test's isolated app registry.

            Schema creation and removal belong to the test.
            """

            app_label = "tests"

    class SymmetricNode(models.Model):
        """Own a standard symmetric self-relation with a custom through model.

        Adding one friend creates separate forward and mirror rows.
        """

        name = models.CharField(max_length=32)
        friends = models.ManyToManyField(
            "self",
            symmetrical=True,
            through="SymmetricLink",
            through_fields=("source", "target"),
        )

        class Meta:
            """Register only in this test's isolated app registry.

            Schema creation and removal belong to the test.
            """

            app_label = "tests"

    class SymmetricLink(models.Model):
        """Store forward and mirror links with independently defaulted FKs.

        The callable guard default differs for each direct row.
        """

        source = models.ForeignKey(
            SymmetricNode, on_delete=models.CASCADE, related_name="outgoing_links"
        )
        target = models.ForeignKey(
            SymmetricNode, on_delete=models.CASCADE, related_name="incoming_links"
        )
        guard = models.ForeignKey(
            SymmetricGuard, on_delete=models.CASCADE, default=next_guard
        )

        class Meta:
            """Register only in this test's isolated app registry.

            Schema creation and removal belong to the test.
            """

            app_label = "tests"

    class ProxyNode(SymmetricNode):
        """Expose the concrete symmetric relation without another table.

        Django's manager must still write a mirror for this model.
        """

        class Meta:
            """Register an isolated proxy of the symmetric node.

            The proxy has no physical table of its own.
            """

            app_label = "tests"
            proxy = True

    class InheritedNode(SymmetricNode):
        """Access a parent-declared self-relation from a concrete child.

        The child has a separate table linked to its parent row.
        """

        extra = models.CharField(max_length=32)

        class Meta:
            """Register an isolated concrete child of the symmetric node.

            Its parent link is created with the temporary schema.
            """

            app_label = "tests"

    with connection.schema_editor() as editor:
        for model in (SymmetricGuard, SymmetricNode, SymmetricLink):
            editor.create_model(model)
        if model_kind == "inherited":
            editor.create_model(InheritedNode)
    try:
        guard = SymmetricGuard.objects.create()
        peer = SymmetricNode.objects.create(name="peer")
        selected = {
            "concrete": SymmetricNode,
            "proxy": ProxyNode,
            "inherited": InheritedNode,
        }[model_kind]
        backend = PydanticBackend(selected)
        data = {"name": "invalid", "friends": [peer.pk]}
        if model_kind == "inherited":
            data["extra"] = "child"
        assert peer.friends.symmetrical is True
        with transaction.atomic():
            defaults[:] = [guard.pk, 999999]
            with pytest.raises(IntegrityError, match="guard"):
                backend.save_object(
                    None,
                    None,
                    _info(),
                    data,
                )
            assert SymmetricNode.objects.count() == 1
            assert SymmetricLink.objects.count() == 0
            assert SymmetricGuard.objects.filter(pk=guard.pk).exists()

            defaults[:] = [guard.pk, guard.pk]
            data["name"] = "valid"
            ok, node = backend.save_object(
                None,
                None,
                _info(),
                data,
            )
            assert ok, node
            assert set(
                SymmetricLink.objects.values_list("source_id", "target_id", "guard_id")
            ) == {(node.pk, peer.pk, guard.pk), (peer.pk, node.pk, guard.pk)}
    finally:
        defaults.clear()
        with connection.schema_editor() as editor:
            if model_kind == "inherited":
                editor.delete_model(InheritedNode)
            for model in (SymmetricLink, SymmetricNode, SymmetricGuard):
                editor.delete_model(model)
