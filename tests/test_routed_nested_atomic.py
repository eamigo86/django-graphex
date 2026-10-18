"""Keep generated nested mutations atomic on their parent write alias."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.db import connections, models, router
from django.test import RequestFactory
from graphql import ExecutionResult, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.schema import DjangoGraphQLSchema


class RoutedNestedParent(models.Model):
    """Own a table created only for the routed nested-write regression.

    Its rows are isolated from the repository's shared test models.
    """

    name = models.CharField(max_length=30)

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
        nested_fields = {"children": RoutedNestedChild}


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
        return self.alias if model in (RoutedNestedParent, RoutedNestedChild) else None

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Choose the same alias for writes to either owned model.

        Args:
            model: Model being written.
            **hints: Optional Django routing context.

        Returns:
            The selected alias for owned models, otherwise no preference.
        """
        return self.alias if model in (RoutedNestedParent, RoutedNestedChild) else None


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


def _execute(name: str, data: dict[str, Any]) -> ExecutionResult:
    """Execute a generated public mutation with its compiled input type.

    Args:
        name: Mutation root field name.
        data: Variable payload for the generated model input.

    Returns:
        The real graphql-core execution result.
    """
    mutation = SCHEMA.mutation_type.fields[name]
    ((argument_name, argument),) = mutation.args.items()
    document = (
        f"mutation($data: {argument.type}) {{ {name}({argument_name}: $data) "
        "{ ok errors { field messages } } }"
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    return graphql_sync(
        SCHEMA, document, variable_values={"data": data}, context_value=request
    )


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
