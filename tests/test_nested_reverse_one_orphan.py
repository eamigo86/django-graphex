"""Adopting an existing reverse-OneToOne orphan by ID needs a child update host."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from django.test import RequestFactory
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from tests._schema_isolation import isolated_default_pair, isolated_pair


class O2OParent(models.Model):
    """Parent owning at most one child through a reverse OneToOne.

    It isolates the public mutation contract from application fixtures.
    """

    name = models.CharField(max_length=32)

    class Meta:
        """Keep the dynamic parent in the tests app.

        The fixed table name makes test database setup deterministic.
        """

        app_label = "tests"
        db_table = "test_nested_o2o_orphan_parent"


class O2OChild(models.Model):
    """Child with a nullable OneToOne to the parent and its own tenant.

    An empty parent is the adoption candidate.
    """

    tenant = models.CharField(max_length=16)
    label = models.CharField(max_length=32)
    parent = models.OneToOneField(
        O2OParent, related_name="child", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        """Keep the dynamic child in the tests app.

        The fixed table name makes test database setup deterministic.
        """

        app_label = "tests"
        db_table = "test_nested_o2o_orphan_child"


def _schema(with_host: bool) -> DjangoGraphQLSchema:
    """Build the parent update mutation, optionally with a child update host.

    Args:
        with_host: Whether a tenant-scoped child update host is registered.

    Returns:
        The executable schema.
    """
    if with_host:

        class ChildHost(DjangoModelMutation):
            """Serve child updates for the request tenant only."""

            class Meta:
                """Serve the update operation only.

                Create and delete are left to other hosts.
                """

                model = O2OChild
                model_operations = ("update",)

            @classmethod
            def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
                """Limit child writes to tenant A.

                Args:
                    qs: Base child queryset.
                    info: GraphQL resolve info.
                    **kwargs: Unused filtering options.

                Returns:
                    Queryset restricted to tenant A.
                """
                return qs.filter(tenant="A")

        assert ChildHost._meta.model is O2OChild

    class ParentMutation(DjangoModelMutation):
        """Expose the generated parent mutations with a nested child."""

        class Meta:
            """Bind the parent and its reverse OneToOne child.

            The nested field name is the reverse accessor.
            """

            model = O2OParent
            nested_fields = {"child": O2OChild}

    create, _delete, update = ParentMutation.MutationFields()

    class Query(ObjectType):
        """Provide the required query root."""

        ready = BooleanField()

    class Mutation(ObjectType):
        """Expose the generated roots."""

        parent_create = create
        parent_update = update

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    )


def _run(schema: DjangoGraphQLSchema, query: str) -> dict[str, Any]:
    """Execute one mutation and return its payload.

    Args:
        schema: Schema under test.
        query: Mutation document.

    Returns:
        The payload of the only root field.
    """
    result = graphql_sync(
        schema.graphql_schema,
        query,
        context_value=RequestFactory().post("/graphql/"),
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    return next(iter(result.data.values()))


def _adopt(schema: DjangoGraphQLSchema, parent: O2OParent, child_id: int) -> Any:
    """Try to adopt a child by ID through the parent update.

    Args:
        schema: Schema under test.
        parent: Parent being updated.
        child_id: Child pk named in the nested payload.

    Returns:
        The mutation payload.
    """
    return _run(
        schema,
        f'mutation {{ parentUpdate(newO2oparent: {{id: "{parent.pk}", name: "after", '
        f'child: {{id: "{child_id}", label: "adopted"}}}}) '
        "{ ok errors { field messages } } }",
    )


@pytest.mark.django_db
def test_orphan_adoption_without_update_host_is_refused() -> None:
    """Refuse adoption when no child update host is registered.

    Nothing could authorize the write, so the parent is not saved either.
    """
    parent = O2OParent.objects.create(name="before")
    orphan = O2OChild.objects.create(tenant="B", label="before")
    with isolated_default_pair():
        payload = _adopt(_schema(with_host=False), parent, orphan.pk)

    assert payload["ok"] is False
    assert payload["errors"][0]["field"] == "child"
    assert "update host" in payload["errors"][0]["messages"][0]
    orphan.refresh_from_db()
    parent.refresh_from_db()
    assert (orphan.parent_id, orphan.label) == (None, "before")
    assert parent.name == "before"


@pytest.mark.django_db
def test_orphan_adoption_follows_the_child_host_scope() -> None:
    """Adopt a visible orphan and refuse a hidden one.

    The hidden orphan and its parent link stay untouched.
    """
    first = O2OParent.objects.create(name="first")
    second = O2OParent.objects.create(name="second")
    visible = O2OChild.objects.create(tenant="A", label="visible")
    hidden = O2OChild.objects.create(tenant="B", label="hidden")
    with isolated_default_pair():
        schema = _schema(with_host=True)
        denied = _adopt(schema, first, hidden.pk)
        allowed = _adopt(schema, second, visible.pk)

    assert denied["ok"] is False
    assert allowed["ok"] is True, allowed
    hidden.refresh_from_db()
    visible.refresh_from_db()
    assert (hidden.parent_id, hidden.label) == (None, "hidden")
    assert (visible.parent_id, visible.label) == (second.pk, "adopted")


@pytest.mark.django_db
def test_child_of_another_parent_still_cannot_be_taken() -> None:
    """Keep the ownership guard for rows owned by someone else.

    The row keeps its owner and its values.
    """
    owner = O2OParent.objects.create(name="owner")
    thief = O2OParent.objects.create(name="thief")
    child = O2OChild.objects.create(tenant="A", label="owned", parent=owner)
    with isolated_default_pair():
        payload = _adopt(_schema(with_host=True), thief, child.pk)

    assert payload["ok"] is False
    child.refresh_from_db()
    assert (child.parent_id, child.label) == (owner.pk, "owned")


@pytest.mark.django_db
def test_own_child_updates_and_new_child_creates_without_a_host() -> None:
    """Update the parent's own child or create one without any host.

    Only adoption of an existing orphan needs a host.
    """
    parent = O2OParent.objects.create(name="p")
    own = O2OChild.objects.create(tenant="A", label="own", parent=parent)
    fresh = O2OParent.objects.create(name="fresh")
    with isolated_default_pair():
        schema = _schema(with_host=False)
        updated = _adopt(schema, parent, own.pk)
        created = _run(
            schema,
            f'mutation {{ parentUpdate(newO2oparent: {{id: "{fresh.pk}", '
            'child: {tenant: "A", label: "new"}}) { ok errors { field messages } } }',
        )

    assert updated["ok"] is True, updated
    assert created["ok"] is True, created
    own.refresh_from_db()
    assert own.label == "adopted"
    assert O2OChild.objects.get(parent=fresh).label == "new"
