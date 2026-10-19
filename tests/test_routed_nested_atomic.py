"""Exercise generated nested mutations under stable database routing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.db import connections, models, router, transaction
from django.db.models.signals import post_save
from django.test import RequestFactory
from graphql import ExecutionResult, GraphQLSchema, GraphQLString, graphql_sync

import django_graphex.nested as nested_module
from django_graphex.core import ObjectType, field
from django_graphex.core.backend import PydanticBackend
from django_graphex.mutation import DjangoModelMutation
from django_graphex.nested import NestedFieldsMixin
from django_graphex.schema import DjangoGraphQLSchema


class RoutedNestedTag(models.Model):
    """Own a test-only row used by routed nested writes.

    Both forward and many-to-many relations exercise the selected alias.
    """

    label = models.CharField(max_length=10)

    class Meta:
        """Keep the routed tag outside normal migrations.

        The module fixture creates its table on disposable aliases.
        """

        app_label = "tests"
        db_table = "tests_routed_nested_tag"
        managed = False


class RoutedNestedParent(models.Model):
    """Own a table created only for the routed nested-write regression.

    Its rows are isolated from the repository's shared test models.
    """

    name = models.CharField(max_length=30)
    primary_tag = models.ForeignKey(
        RoutedNestedTag,
        null=True,
        on_delete=models.SET_NULL,
        related_name="featured_by",
    )
    tags = models.ManyToManyField(RoutedNestedTag, related_name="parents")

    class Meta:
        """Keep the test-owned parent outside normal migrations.

        The module fixture creates it on both disposable and default aliases.
        """

        app_label = "tests"
        db_table = "tests_routed_nested_parent"
        managed = False


class RoutedNestedChild(models.Model):
    """Provide a reverse-FK child whose late validation can fail.

    A valid sibling can persist before this child produces an error.
    """

    parent = models.ForeignKey(
        RoutedNestedParent, on_delete=models.CASCADE, related_name="children"
    )
    title = models.CharField(max_length=10)

    class Meta:
        """Keep the test-owned child outside normal migrations.

        The module fixture creates it after its parent on each alias.
        """

        app_label = "tests"
        db_table = "tests_routed_nested_child"
        managed = False


class RoutedNestedMutation(DjangoModelMutation):
    """Expose real generated create and update fields for this parent.

    The model is intentionally distinct from shared suite fixtures.
    """

    class Meta:
        """Bind the nested reverse-FK input to the test-owned models.

        Both generated operations exercise the same relation mapping.
        """

        model = RoutedNestedParent
        model_operations = ("create", "update")
        nested_fields = {
            "primary_tag": RoutedNestedTag,
            "tags": RoutedNestedTag,
            "children": RoutedNestedChild,
        }


class RoutedTagMutation(DjangoModelMutation):
    """Expose the reverse M2M nested CREATE path over GraphQL.

    The generated field exercises the public reverse relation input.
    """

    class Meta:
        """Bind the reverse parent relation to the tag create input.

        This host uses the same included Django backend as the parent host.
        """

        model = RoutedNestedTag
        model_operations = ("create",)
        nested_fields = {"parents": RoutedNestedParent}


class _Query(ObjectType):
    """Provide the query root required by a native GraphQL schema.

    The tests execute only the generated mutation fields.
    """

    hello = field(GraphQLString)


class _Mutation(ObjectType):
    """Expose the public generated mutation fields over the wire.

    Both create and update use the same routed parent model.
    """

    routed_nested_create = RoutedNestedMutation.CreateField()
    routed_nested_update = RoutedNestedMutation.UpdateField()
    routed_tag_create = RoutedTagMutation.CreateField()


SCHEMA = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema


class _NestedRouter:
    """Route only this module's parent and child to the selected alias."""

    def __init__(self, alias: str) -> None:
        """Store the alias selected by the fixture.

        Args:
            alias: Database alias for the parent and child.
        """
        self.alias = alias

    def db_for_read(self, model: type[Any], **hints: Any) -> str | None:
        """Choose the test alias for either owned model.

        Args:
            model: Model being read.
            **hints: Optional Django routing context.

        Returns:
            The selected alias for owned models, otherwise no preference.
        """
        return (
            self.alias
            if model in (RoutedNestedParent, RoutedNestedChild, RoutedNestedTag)
            else None
        )

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Choose the same alias for writes to either owned model.

        Args:
            model: Model being written.
            **hints: Optional Django routing context.

        Returns:
            The selected alias for owned models, otherwise no preference.
        """
        return (
            self.alias
            if model in (RoutedNestedParent, RoutedNestedChild, RoutedNestedTag)
            else None
        )


class _InstanceRouter:
    """Route populated east parents away from the child model's default alias."""

    def db_for_read(self, model: type[Any], **hints: Any) -> str | None:
        """Leave reads to their explicit database managers.

        Args:
            model: Model being read.
            **hints: Optional Django routing context.

        Returns:
            No preferred alias.
        """
        return None

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Choose a secondary alias only for a populated parent hint.

        Args:
            model: Model being written.
            **hints: Optional Django routing context.

        Returns:
            The parent's selected alias or the default alias.
        """
        instance = hints.get("instance")
        if model is RoutedNestedParent and getattr(instance, "name", None) == "east":
            return "routed_nested"
        if model in (RoutedNestedParent, RoutedNestedChild, RoutedNestedTag):
            return "default"
        return None


class _DivergentThroughRouter(_InstanceRouter):
    """Route the M2M through table away from its populated parent."""

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Select a different alias only for the nested through table.

        Args:
            model: Model being written.
            **hints: Optional Django routing context.

        Returns:
            The divergent alias for through writes or the inherited choice.
        """
        if model is RoutedNestedParent.tags.through:
            return "default"
        if (
            model is RoutedNestedTag
            and getattr(hints.get("instance"), "label", None) == "east"
        ):
            return "routed_nested"
        return super().db_for_write(model, **hints)


class _PostIdDivergentThroughRouter(_InstanceRouter):
    """Choose a foreign through alias only after a generated parent ID exists."""

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Defer the through route until Django has saved its source instance.

        Args:
            model: Model being written.
            **hints: Optional Django routing context.

        Returns:
            A divergent alias for a saved through-source, otherwise no choice.
        """
        if model is RoutedNestedParent.tags.through:
            instance = hints.get("instance")
            return "default" if getattr(instance, "pk", None) is not None else None
        if (
            model is RoutedNestedTag
            and getattr(hints.get("instance"), "label", None) == "east"
        ):
            return "routed_nested"
        return super().db_for_write(model, **hints)


@pytest.fixture(scope="module", autouse=True)
def _install_test_tables(
    django_db_setup: None,
    django_db_blocker: Any,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Create only this module's tables on default and disposable SQLite.

    Args:
        django_db_setup: Initializes the test database before schema edits.
        django_db_blocker: Permits explicit setup and teardown database access.
        tmp_path_factory: Creates the secondary SQLite file outside the checkout.

    Yields:
        None while both test-owned schemas are installed.
    """
    alias = "routed_nested"
    assert alias not in connections.databases
    location = tmp_path_factory.mktemp("routed-nested-db") / "routed.sqlite3"
    settings.DATABASES[alias] = {
        **settings.DATABASES["default"],
        "NAME": str(location),
    }
    secondary = connections[alias]
    with django_db_blocker.unblock():
        for name in ("default", alias):
            with connections[name].schema_editor() as editor:
                editor.create_model(RoutedNestedTag)
                editor.create_model(RoutedNestedParent)
                editor.create_model(RoutedNestedChild)
    try:
        yield
    finally:
        with django_db_blocker.unblock():
            for name in (alias, "default"):
                with connections[name].schema_editor() as editor:
                    editor.delete_model(RoutedNestedChild)
                    editor.delete_model(RoutedNestedParent)
                    editor.delete_model(RoutedNestedTag)
        secondary.close()
        del connections._connections.routed_nested
        del settings.DATABASES[alias]


@pytest.fixture(params=("routed_nested", "default"))
def routed_database(
    request: pytest.FixtureRequest,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Select one alias and clean up only this fixture's rows and router.

    Args:
        request: Parameterized alias for the test.
        django_db_blocker: Permits real mutation and assertion queries.
        monkeypatch: Restores the previously configured router list.

    Yields:
        Selected database alias with both owned tables available.
    """
    alias = request.param
    monkeypatch.setattr(router, "routers", [_NestedRouter(alias)])
    with django_db_blocker.unblock():
        try:
            yield alias
        finally:
            RoutedNestedChild.objects.using(alias).all().delete()
            RoutedNestedParent.objects.using(alias).all().delete()
            RoutedNestedTag.objects.using(alias).all().delete()


def _execute(
    name: str, data: dict[str, Any], schema: GraphQLSchema = SCHEMA
) -> ExecutionResult:
    """Execute a generated public mutation with its compiled input type.

    Args:
        name: Mutation root field name.
        data: Variable payload for the generated model input.
        schema: Compiled public GraphQL schema.

    Returns:
        The real graphql-core execution result.
    """
    mutation = schema.mutation_type.fields[name]
    ((argument_name, argument),) = mutation.args.items()
    document = (
        f"mutation($data: {argument.type}) {{ {name}({argument_name}: $data) "
        "{ ok errors { field messages } } }"
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    return graphql_sync(
        schema, document, variable_values={"data": data}, context_value=request
    )


def _capture_writes(
    stack: ExitStack, writes: list[tuple[str, str]], aliases: tuple[str, ...]
) -> None:
    """Observe actual database write attempts on selected disposable aliases.

    Args:
        stack: Context stack owning temporary execute wrappers.
        writes: Collection receiving alias and SQL statement pairs.
        aliases: Database aliases to observe.
    """
    for alias in aliases:

        def wrapper(
            execute: Callable[..., Any],
            sql: str,
            params: Any,
            many: bool,
            context: Any,
            *,
            observed_alias: str = alias,
        ) -> Any:
            """Record DML before allowing the database to execute it.

            Args:
                execute: Original database execution callable.
                sql: SQL submitted to the database.
                params: Bound SQL parameters.
                many: Whether this is batched execution.
                context: Django execution metadata.
                observed_alias: Alias associated with this wrapper.

            Returns:
                The database execution result.
            """
            if sql.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                writes.append((observed_alias, sql))
            return execute(sql, params, many, context)

        stack.enter_context(connections[alias].execute_wrapper(wrapper))


@pytest.mark.parametrize("direction", ("declared", "reverse"))
def test_explicit_divergent_through_router_rejects_before_any_write(
    direction: str,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conflicting through route cannot write either database before refusal.

    Args:
        direction: Declared or reverse M2M nested CREATE input.
        django_db_blocker: Allows disposable database access.
        monkeypatch: Restores the original database routers.
    """
    monkeypatch.setattr(router, "routers", [_DivergentThroughRouter()])
    field, payload = (
        ("routedNestedCreate", {"name": "east", "tags": [{"label": "member"}]})
        if direction == "declared"
        else ("routedTagCreate", {"label": "east", "parents": [{"name": "member"}]})
    )
    writes: list[tuple[str, str]] = []
    with django_db_blocker.unblock():
        try:
            with ExitStack() as stack:
                _capture_writes(stack, writes, ("default", "routed_nested"))
                result = _execute(field, payload)
            assert writes == []
            assert result.errors is None, result.errors
            response = result.data[field]
            assert response["ok"] is False
            assert response["errors"]
            assert "database" not in str(response["errors"]).lower()
            for alias in ("default", "routed_nested"):
                assert RoutedNestedParent.objects.using(alias).count() == 0
                assert RoutedNestedTag.objects.using(alias).count() == 0
                assert RoutedNestedParent.tags.through.objects.using(alias).count() == 0
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


@pytest.mark.parametrize("direction", ("declared", "reverse"))
def test_post_id_divergent_through_router_rolls_back_without_foreign_sql(
    direction: str,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generated ID may change the through route but cannot escape atomic.

    Args:
        direction: Declared or reverse M2M nested CREATE input.
        django_db_blocker: Allows disposable database access.
        monkeypatch: Restores the original database routers.
    """
    monkeypatch.setattr(router, "routers", [_PostIdDivergentThroughRouter()])
    field, payload = (
        ("routedNestedCreate", {"name": "east", "tags": [{"label": "member"}]})
        if direction == "declared"
        else ("routedTagCreate", {"label": "east", "parents": [{"name": "member"}]})
    )
    writes: list[tuple[str, str]] = []
    with django_db_blocker.unblock():
        try:
            with ExitStack() as stack:
                _capture_writes(stack, writes, ("default", "routed_nested"))
                result = _execute(field, payload)
            local_dml = [sql for alias, sql in writes if alias == "routed_nested"]
            foreign_dml = [sql for alias, sql in writes if alias == "default"]
            assert any('"tests_routed_nested_' in sql for sql in local_dml)
            assert foreign_dml == []
            assert result.errors is None, result.errors
            response = result.data[field]
            assert response["ok"] is False
            assert response["errors"]
            assert "database" not in str(response["errors"]).lower()
            for alias in ("default", "routed_nested"):
                assert RoutedNestedParent.objects.using(alias).count() == 0
                assert RoutedNestedTag.objects.using(alias).count() == 0
                assert RoutedNestedParent.tags.through.objects.using(alias).count() == 0
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


def test_late_failure_after_real_writes_rolls_back_chosen_alias(
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later invalid child rolls back observed earlier parent and child writes.

    Args:
        django_db_blocker: Allows disposable database access.
        monkeypatch: Restores the original database routers.
    """
    monkeypatch.setattr(router, "routers", [_InstanceRouter()])
    writes: list[tuple[str, str]] = []
    with django_db_blocker.unblock():
        try:
            with ExitStack() as stack:
                _capture_writes(stack, writes, ("default", "routed_nested"))
                result = _execute(
                    "routedNestedCreate",
                    {
                        "name": "east",
                        "children": [
                            {"title": "first"},
                            {"title": "too-long-child-title"},
                        ],
                    },
                )
            assert result.errors is None, result.errors
            assert result.data["routedNestedCreate"]["ok"] is False
            routed_dml = [sql for alias, sql in writes if alias == "routed_nested"]
            assert any('"tests_routed_nested_parent"' in sql for sql in routed_dml)
            assert any('"tests_routed_nested_child"' in sql for sql in routed_dml)
            assert not any(alias == "default" for alias, _ in writes)
            assert RoutedNestedParent.objects.using("routed_nested").count() == 0
            assert RoutedNestedChild.objects.using("routed_nested").count() == 0
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


def test_later_child_failure_rolls_back_create(routed_database: str) -> None:
    """A later invalid child undoes the parent and earlier child on either alias.

    Args:
        routed_database: Default control or test-owned secondary write alias.
    """
    result = _execute(
        "routedNestedCreate",
        {
            "name": "new parent",
            "children": [{"title": "saved"}, {"title": "too-long-child-title"}],
        },
    )
    assert result.errors is None, result.errors
    assert result.data["routedNestedCreate"]["ok"] is False
    assert RoutedNestedParent.objects.using(routed_database).count() == 0
    assert RoutedNestedChild.objects.using(routed_database).count() == 0


def test_later_child_failure_rolls_back_update(routed_database: str) -> None:
    """A later invalid child undoes an earlier parent update on either alias.

    Args:
        routed_database: Default control or test-owned secondary write alias.
    """
    parent = RoutedNestedParent.objects.using(routed_database).create(name="before")
    result = _execute(
        "routedNestedUpdate",
        {
            "id": str(parent.pk),
            "name": "after",
            "children": [{"title": "saved"}, {"title": "too-long-child-title"}],
        },
    )
    assert result.errors is None, result.errors
    assert result.data["routedNestedUpdate"]["ok"] is False
    parent.refresh_from_db(using=routed_database)
    assert parent.name == "before"
    assert RoutedNestedChild.objects.using(routed_database).count() == 0


def test_nested_create_succeeds_on_own_alias(routed_database: str) -> None:
    """The selected alias persists a valid parent and all its children.

    Args:
        routed_database: Default control or test-owned secondary write alias.
    """
    result = _execute(
        "routedNestedCreate",
        {"name": "valid parent", "children": [{"title": "first"}, {"title": "second"}]},
    )
    assert result.errors is None, result.errors
    assert result.data["routedNestedCreate"]["ok"] is True
    assert RoutedNestedParent.objects.using(routed_database).count() == 1
    assert set(
        RoutedNestedChild.objects.using(routed_database).values_list("title", flat=True)
    ) == {"first", "second"}


@pytest.mark.parametrize("late_failure", (False, True))
def test_populated_parent_routes_entire_nested_create_to_one_alias(
    late_failure: bool,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The populated parent selects the alias for itself and every child.

    Args:
        late_failure: Whether the second child must fail after earlier writes.
        django_db_blocker: Allows the test-owned disposable databases.
        monkeypatch: Restores the original router configuration.
    """
    monkeypatch.setattr(router, "routers", [_InstanceRouter()])
    children = [{"title": "first"}]
    if late_failure:
        children.append({"title": "too-long-child-title"})
    with django_db_blocker.unblock():
        try:
            result = _execute(
                "routedNestedCreate", {"name": "east", "children": children}
            )
            assert result.errors is None, result.errors
            assert result.data["routedNestedCreate"]["ok"] is not late_failure
            expected = 0 if late_failure else 1
            assert RoutedNestedParent.objects.using("routed_nested").count() == expected
            assert RoutedNestedChild.objects.using("routed_nested").count() == expected
            assert RoutedNestedParent.objects.using("default").count() == 0
            assert RoutedNestedChild.objects.using("default").count() == 0
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


@pytest.mark.parametrize("late_failure", (False, True))
def test_instance_routed_create_initializes_once_and_commits_only_on_success(
    late_failure: bool,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The native create uses one parent instance and one commit boundary.

    Args:
        late_failure: Whether a later child invalidates the whole transaction.
        django_db_blocker: Allows access to the disposable routed database.
        monkeypatch: Restores constructor and router behavior after the test.
    """
    monkeypatch.setattr(router, "routers", [_InstanceRouter()])
    initialized: list[RoutedNestedParent] = []
    callbacks: list[tuple[str, str]] = []
    original_init = RoutedNestedParent.__init__

    def counting_init(parent: RoutedNestedParent, *args: Any, **kwargs: Any) -> None:
        """Record construction without altering model initialization.

        Args:
            parent: New parent object.
            *args: Positional model fields.
            **kwargs: Named model fields.
        """
        initialized.append(parent)
        original_init(parent, *args, **kwargs)

    def receiver(
        sender: type[models.Model], instance: models.Model, **kwargs: Any
    ) -> None:
        """Defer a record on the same alias as a saved test model.

        Args:
            sender: Model whose save emitted the signal.
            instance: Saved model instance.
            **kwargs: Other signal metadata.
        """
        transaction.on_commit(
            lambda: callbacks.append((sender.__name__, instance._state.db)),
            using=instance._state.db,
        )

    monkeypatch.setattr(RoutedNestedParent, "__init__", counting_init)
    post_save.connect(receiver, sender=RoutedNestedParent, weak=False)
    post_save.connect(receiver, sender=RoutedNestedChild, weak=False)
    children = [{"title": "first"}]
    if late_failure:
        children.append({"title": "too-long-child-title"})
    with django_db_blocker.unblock():
        try:
            result = _execute(
                "routedNestedCreate", {"name": "east", "children": children}
            )
            assert result.errors is None, result.errors
            assert result.data["routedNestedCreate"]["ok"] is not late_failure
            assert len(initialized) == 1
            assert callbacks == (
                []
                if late_failure
                else [
                    ("RoutedNestedParent", "routed_nested"),
                    ("RoutedNestedChild", "routed_nested"),
                ]
            )
        finally:
            post_save.disconnect(receiver, sender=RoutedNestedParent)
            post_save.disconnect(receiver, sender=RoutedNestedChild)
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


@pytest.mark.parametrize("late_failure", (False, True))
def test_instance_routed_forward_and_m2m_writes_share_parent_boundary(
    late_failure: bool,
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward, M2M, and reverse children share the populated parent's alias.

    Args:
        late_failure: Whether the last reverse child must roll back every write.
        django_db_blocker: Allows the disposable test databases.
        monkeypatch: Restores the router after this request.
    """
    monkeypatch.setattr(router, "routers", [_InstanceRouter()])
    children = [{"title": "first"}]
    if late_failure:
        children.append({"title": "too-long-child-title"})
    with django_db_blocker.unblock():
        try:
            result = _execute(
                "routedNestedCreate",
                {
                    "name": "east",
                    "primaryTag": {"label": "featured"},
                    "tags": [{"label": "member"}],
                    "children": children,
                },
            )
            assert result.errors is None, [
                (str(error), repr(error.original_error))
                for error in result.errors or []
            ]
            assert result.data["routedNestedCreate"]["ok"] is not late_failure
            expected = 0 if late_failure else 1
            assert RoutedNestedParent.objects.using("routed_nested").count() == expected
            assert RoutedNestedChild.objects.using("routed_nested").count() == expected
            assert (
                RoutedNestedTag.objects.using("routed_nested").count() == expected * 2
            )
            assert (
                RoutedNestedParent.tags.through.objects.using("routed_nested").count()
                == expected
            )
            for model in (RoutedNestedParent, RoutedNestedChild, RoutedNestedTag):
                assert model.objects.using("default").count() == 0
            assert RoutedNestedParent.tags.through.objects.using("default").count() == 0
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


def test_custom_backend_keeps_existing_create_instance_contract(
    django_db_blocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backend override still receives None for a nested parent create.

    Args:
        django_db_blocker: Allows access to the disposable default database.
        monkeypatch: Restores the backend and router after the request.
    """
    calls: list[tuple[models.Model | None, bool]] = []

    class CustomBackend(PydanticBackend):
        """Record the public save call without changing its behavior."""

        def save_object(
            self,
            host: Any,
            root: Any,
            info: Any,
            data: dict[str, Any],
            *,
            instance: models.Model | None = None,
            partial: bool = False,
            serializer_kwargs: dict[str, Any] | None = None,
            save_kwargs: dict[str, Any] | None = None,
        ) -> tuple[bool, Any]:
            """Record the create arguments before delegating.

            Args:
                host: Mutation host.
                root: GraphQL root value.
                info: GraphQL request information.
                data: Mutation input.
                instance: Parent object passed by the nested writer.
                partial: Whether this is a partial update.
                serializer_kwargs: Optional serializer configuration.
                save_kwargs: Optional injected relation attributes.

            Returns:
                The native backend's save result.
            """
            calls.append((instance, partial))
            return super().save_object(
                host,
                root,
                info,
                data,
                instance=instance,
                partial=partial,
                serializer_kwargs=serializer_kwargs,
                save_kwargs=save_kwargs,
            )

    monkeypatch.setattr(router, "routers", [_InstanceRouter()])
    monkeypatch.setattr(
        RoutedNestedMutation._meta, "backend", CustomBackend(RoutedNestedParent)
    )
    with django_db_blocker.unblock():
        try:
            result = _execute(
                "routedNestedCreate",
                {"name": "west", "children": [{"title": "child"}]},
            )
            assert result.errors is None, result.errors
            assert result.data["routedNestedCreate"]["ok"] is True
            assert calls == [(None, False)]
        finally:
            for alias in ("routed_nested", "default"):
                RoutedNestedChild.objects.using(alias).all().delete()
                RoutedNestedParent.objects.using(alias).all().delete()
                RoutedNestedTag.objects.using(alias).all().delete()


def test_nested_routing_contract_documents_native_instance_create_boundary() -> None:
    """Keep the native routing guarantee and cross-database limit visible.

    Every affected public surface distinguishes native and custom backends.
    """
    root = Path(__file__).resolve().parents[1]
    documents = (
        nested_module.__doc__ or "",
        NestedFieldsMixin.save_with_nested.__doc__ or "",
        (root / "docs/usage/mutations.md").read_text(encoding="utf-8"),
        (root / "CHANGELOG.md").read_text(encoding="utf-8"),
        (root / "docs/changelog.md").read_text(encoding="utf-8"),
    )
    for document in documents:
        normalized = document.casefold()
        assert "populated" in normalized
        assert "alias" in normalized
        assert "custom" in normalized
        assert "cross" in normalized or "different database" in normalized
