"""HTTP contracts for blocked generated deletes."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
from typing import Any

import graphql
import pytest
from django.db import IntegrityError, models
from django.test import RequestFactory, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from django_graphex.views import GraphQLView
from tests.models import Category


class A9ProtectChild(models.Model):
    """Dependent row that prevents category deletion with PROTECT.

    This definition is local to the generated-delete regression schema.
    """

    category = models.ForeignKey(Category, on_delete=models.PROTECT)

    class Meta:
        """Keep the regression table inside the test application.

        This definition is local to the generated-delete regression schema.
        """

        app_label = "tests"
        db_table = "test_a9_protect_child"


class A9RestrictChild(models.Model):
    """Dependent row that prevents category deletion with RESTRICT.

    This definition is local to the generated-delete regression schema.
    """

    category = models.ForeignKey(Category, on_delete=models.RESTRICT)

    class Meta:
        """Keep the regression table inside the test application.

        This definition is local to the generated-delete regression schema.
        """

        app_label = "tests"
        db_table = "test_a9_restrict_child"


class A9Query(ObjectType):
    """Minimal query root for the generated mutations.

    This definition is local to the generated-delete regression schema.
    """

    ping = field(GraphQLString)


class A9MutationHost(DjangoModelMutation):
    """Expose the generated mutation-host delete field.

    This definition is local to the generated-delete regression schema.
    """

    class Meta:
        """Bind the generated mutation to Category.

        This definition is local to the generated-delete regression schema.
        """

        model = Category


class A9TypeHost(DjangoModelType):
    """Expose the generated model-type delete field.

    This definition is local to the generated-delete regression schema.
    """

    class Meta:
        """Bind the generated type to Category.

        This definition is local to the generated-delete regression schema.
        """

        model = Category


class A9MutationRoot(ObjectType):
    """Mutation root for the mutation-host delete field.

    This definition is local to the generated-delete regression schema.
    """

    delete_category = A9MutationHost.DeleteField()


class A9TypeRoot(ObjectType):
    """Mutation root for the model-type delete field.

    This definition is local to the generated-delete regression schema.
    """

    delete_category = A9TypeHost.DeleteField()


def _sibling_write(root: Any, info: Any) -> str:
    """Persist an earlier sibling mutation before a blocked delete.

    Args:
        root: The root resolver value.
        info: GraphQL execution information.

    Returns:
        The successful sibling field value.
    """
    Category.objects.create(title="a9-sibling-marker")
    return "written"


def _fail_delete(self: Category, *args: Any, **kwargs: Any) -> None:
    """Raise a non-collector database error from deletion.

    Args:
        self: The model instance being deleted.
        *args: Unused positional deletion options.
        **kwargs: Unused keyword deletion options.

    Raises:
        IntegrityError: Always, to verify the narrow exception boundary.
    """
    raise IntegrityError("a9-unrelated-db-error")


class A9AtomicRoot(ObjectType):
    """Expose a sibling write before the generated delete.

    This definition is local to the generated-delete regression schema.
    """

    sibling_write = field(GraphQLString, resolver=_sibling_write)
    delete_category = A9MutationHost.DeleteField()


SCHEMAS = (
    DjangoGraphQLSchema(query=A9Query, mutation=A9MutationRoot),
    DjangoGraphQLSchema(query=A9Query, mutation=A9TypeRoot),
)
ATOMIC_SCHEMA = DjangoGraphQLSchema(query=A9Query, mutation=A9AtomicRoot)
DELETE_QUERY = """mutation DeleteCategory($id: ID!) {
    deleteCategory(id: $id) { ok errors { field messages } }
}"""
GENERIC_ERROR = "Deletion blocked by related objects."


def _assert_runtime_identity() -> None:
    """Require supported graphql-core and this repository's package.

    This definition is local to the generated-delete regression schema.
    """
    import django_graphex

    assert importlib.metadata.version("graphql-core") == "3.3.0"
    assert graphql.__file__ is not None
    assert "/core330-overlay/" in str(Path(graphql.__file__).resolve())
    assert "/django-graphex/django_graphex/__init__.py" in str(
        Path(django_graphex.__file__).resolve()
    )


def _post(schema: DjangoGraphQLSchema, query: str, variables: dict[str, Any]) -> Any:
    """Execute a JSON request through the real GraphQL view.

    Args:
        schema: Compiled schema exposing the generated delete field.
        query: GraphQL operation to execute.
        variables: Variables for the operation.

    Returns:
        The Django HTTP response.
    """
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query, "variables": variables}),
        content_type="application/json",
    )
    return GraphQLView.as_view(schema=schema)(request)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("child_model", [A9ProtectChild, A9RestrictChild])
@override_settings(DEBUG=False, DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": False})
def test_blocked_generated_delete_hides_collector_details(
    schema: DjangoGraphQLSchema, child_model: type[models.Model]
) -> None:
    """Return only the approved generic GraphQL execution error.

    Args:
        schema: One of the two generated-delete frontends.
        child_model: Dependent relation using PROTECT or RESTRICT.
    """
    _assert_runtime_identity()
    category = Category.objects.create(title="a9-private-category")
    child_model.objects.create(category=category)

    response = _post(schema, DELETE_QUERY, {"id": str(category.pk)})
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["data"] == {"deleteCategory": None}
    assert len(payload["errors"]) == 1
    error = payload["errors"][0]
    assert error["message"] == GENERIC_ERROR
    assert error["path"] == ["deleteCategory"]
    assert error["locations"] == [{"line": 2, "column": 5}]
    assert "extensions" not in error
    assert Category.objects.filter(pk=category.pk).exists()
    assert child_model.objects.filter(category_id=category.pk).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("child_model", [A9ProtectChild, A9RestrictChild])
@pytest.mark.parametrize("atomic", [False, True])
@override_settings(DEBUG=False)
def test_blocked_delete_preserves_sibling_rollback(
    child_model: type[models.Model], atomic: bool
) -> None:
    """Preserve the existing GraphQL-error transaction boundary.

    Args:
        child_model: Dependent relation using PROTECT or RESTRICT.
        atomic: Whether to wrap the whole mutation operation atomically.
    """
    _assert_runtime_identity()
    category = Category.objects.create(title="a9-blocked")
    child_model.objects.create(category=category)
    marker_before = Category.objects.filter(title="a9-sibling-marker").count()
    with override_settings(DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": atomic}):
        response = _post(
            ATOMIC_SCHEMA,
            """mutation DeleteCategory($id: ID!) {
                siblingWrite
                deleteCategory(id: $id) { ok errors { field messages } }
            }""",
            {"id": str(category.pk)},
        )
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["data"] == {
        "siblingWrite": "written",
        "deleteCategory": None,
    }
    assert payload["errors"][0]["message"] == GENERIC_ERROR
    assert Category.objects.filter(title="a9-sibling-marker").count() == (
        marker_before + (0 if atomic else 1)
    )
    assert Category.objects.filter(pk=category.pk).exists()
    assert child_model.objects.filter(category_id=category.pk).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
@override_settings(DEBUG=False, DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": False})
def test_generated_delete_keeps_success_and_not_found_contract(
    schema: DjangoGraphQLSchema,
) -> None:
    """Keep ordinary delete success and structured missing-row errors.

    Args:
        schema: One of the two generated-delete frontends.
    """
    _assert_runtime_identity()
    category = Category.objects.create(title="a9-removable")
    success = json.loads(_post(schema, DELETE_QUERY, {"id": str(category.pk)}).content)
    assert success["data"]["deleteCategory"]["ok"] is True
    assert "errors" not in success
    assert not Category.objects.filter(pk=category.pk).exists()

    missing = json.loads(_post(schema, DELETE_QUERY, {"id": str(category.pk)}).content)
    assert missing["data"]["deleteCategory"]["ok"] is False
    assert missing["data"]["deleteCategory"]["errors"]
    assert "errors" not in missing


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
@override_settings(DEBUG=False, DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": False})
def test_unrelated_database_error_is_not_generic(
    schema: DjangoGraphQLSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not widen collector handling to arbitrary persistence errors.

    Args:
        schema: One of the two generated-delete frontends.
        monkeypatch: Scoped replacement for the model's delete method.
    """
    _assert_runtime_identity()
    category = Category.objects.create(title="a9-unchanged")

    monkeypatch.setattr(Category, "delete", _fail_delete)
    payload = json.loads(_post(schema, DELETE_QUERY, {"id": str(category.pk)}).content)
    assert payload["data"] == {"deleteCategory": None}
    assert payload["errors"][0]["message"] == "a9-unrelated-db-error"
    assert Category.objects.filter(pk=category.pk).exists()
