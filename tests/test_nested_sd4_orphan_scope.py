"""Public GraphQL contract for adopting an existing reverse-FK orphan by ID."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.permissions import BasePermission
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType


class SD4Parent(models.Model):
    """Parent with an explicit tenant marker for the adoption regression.

    This model isolates the public mutation contract from application fixtures.
    """

    tenant = models.CharField(max_length=16)
    name = models.CharField(max_length=32)

    class Meta:
        """Keep the dynamic parent in the tests app.

        The fixed table name makes the test database setup deterministic.
        """

        app_label = "tests"
        db_table = "test_nested_sd4_parent"


class SD4Child(models.Model):
    """Child with an independently owned tenant and nullable reverse FK.

    The empty parent relation represents the adoption candidate.
    """

    tenant = models.CharField(max_length=16)
    label = models.CharField(max_length=32)
    parent = models.ForeignKey(
        SD4Parent, related_name="children", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        """Keep the dynamic child in the tests app.

        The fixed table name makes the test database setup deterministic.
        """

        app_label = "tests"
        db_table = "test_nested_sd4_child"


class _ChildPermission(BasePermission):
    """Request-controlled permission used to prove host authorization."""

    def has_permission(self, info: Any, action: str, model: Any, **kwargs: Any) -> bool:
        """Return the request's child-write decision.

        Args:
            info: GraphQL resolve info.
            action: Requested model action.
            model: Child model class.
            **kwargs: Action-specific context.

        Returns:
            Whether child writes are allowed.
        """
        return bool(info.context.get("allow_child_write", True))


class SD4ChildWriteType(DjangoModelType):
    """Child UPDATE host with tenant scope and permission checks.

    It is included only by tests that explicitly select this host.
    """

    permission_classes = (_ChildPermission,)

    class Meta:
        """Serve child updates and no other model operations.

        The host's filter and permission checks apply to that operation.
        """

        model = SD4Child
        model_operations = ("update",)

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Limit child writes to the request tenant.

        Args:
            qs: Base child queryset.
            info: GraphQL resolve info.
            **kwargs: Unused filtering options.

        Returns:
            Queryset for the request tenant.
        """
        return qs.filter(tenant=info.context["tenant"])


class SD4ChildCreateOnly(DjangoModelMutation):
    """Create-only host that cannot authorize adopting an existing child.

    Tests can temporarily add UPDATE to verify mutation-host eligibility.
    """

    class Meta:
        """Expose only child creation by default.

        Tests may temporarily add the update operation.
        """

        model = SD4Child
        model_operations = ("create",)


class SD4ParentType(DjangoModelType):
    """Generated model-type update frontend.

    The nested child field exercises reverse-FK writes.
    """

    class Meta:
        """Bind the parent model and its nested reverse child.

        This is the model-type generated mutation frontend.
        """

        model = SD4Parent
        nested_fields = {"children": SD4Child}


class SD4ParentMutation(DjangoModelMutation):
    """Generated mutation-class update frontend.

    It verifies parity with the model-type frontend.
    """

    class Meta:
        """Bind the parent model and its nested reverse child.

        This is the mutation-class generated frontend.
        """

        model = SD4Parent
        nested_fields = {"children": SD4Child}


class _Query(ObjectType):
    """Minimal valid query root."""

    ping = field(GraphQLString)

    def resolve_ping(root: Any, info: Any) -> str:
        """Return a constant query result.

        Args:
            root: Root object.
            info: GraphQL resolve info.

        Returns:
            A constant value.
        """
        return "ok"


class _Context(dict[str, Any]):
    """Request-like mapping used by the native mutation backend."""

    META: dict[str, Any] = {}
    FILES: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        """Expose mapping entries as request attributes.

        Args:
            name: Attribute name.

        Returns:
            The corresponding mapping value.

        Raises:
            AttributeError: If the mapping has no such entry.
        """
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@pytest.fixture
def child_hosts(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Select child hosts locally without leaking into other test schemas.

    Args:
        monkeypatch: Restores the registry and class metadata after each test.

    Yields:
        A function selecting the currently visible child hosts.
    """
    registry = get_global_registry()
    original = tuple(registry.nested_hosts.get(SD4Child, ()))
    original_ops = SD4ChildWriteType._meta.model_operations

    def select(*hosts: Any, read_only: bool = False) -> None:
        """Set the child hosts for one test case.

        Args:
            *hosts: Child host classes to make visible.
            read_only: Whether to narrow the write type to read-only operations.
        """
        monkeypatch.setitem(registry.nested_hosts, SD4Child, list(hosts))
        if read_only:
            monkeypatch.setattr(
                SD4ChildWriteType._meta,
                "model_operations",
                ("list", "retrieve"),
            )
        else:
            monkeypatch.setattr(
                SD4ChildWriteType._meta, "model_operations", original_ops
            )

    yield select
    if original:
        registry.nested_hosts[SD4Child] = list(original)
    else:
        registry.nested_hosts.pop(SD4Child, None)


def _named_type(value: Any) -> Any:
    """Return the named GraphQL type under list or non-null wrappers.

    Args:
        value: Wrapped GraphQL type.

    Returns:
        The named type.
    """
    while hasattr(value, "of_type"):
        value = value.of_type
    return value


def _execute(
    frontend: type[Any],
    payload: dict[str, Any],
    *,
    tenant: str = "A",
    allow: bool = True,
) -> Any:
    """Execute one generated public update mutation.

    Args:
        frontend: Generated mutation frontend.
        payload: Update input data.
        tenant: Request tenant.
        allow: Child permission decision.

    Returns:
        Native GraphQL execution result.
    """

    class Mutation(ObjectType):
        update_parent = frontend.UpdateField()

    schema = DjangoGraphQLSchema(query=_Query, mutation=Mutation).graphql_schema
    gql_field = schema.mutation_type.fields["updateParent"]
    ((arg_name, argument),) = gql_field.args.items()
    input_type = _named_type(argument.type)
    query = (
        f"mutation($payload: {input_type.name}!) {{ updateParent"
        f"({arg_name}: $payload) {{ ok errors {{ field messages }} }} }}"
    )
    return graphql_sync(
        schema,
        query,
        variable_values={"payload": payload},
        context_value=_Context(tenant=tenant, allow_child_write=allow),
    )


def _execute_create(frontend: type[Any], payload: dict[str, Any]) -> Any:
    """Execute a generated parent create with nested child input.

    Args:
        frontend: Generated mutation frontend.
        payload: Create input data.

    Returns:
        Native GraphQL execution result.
    """

    class Mutation(ObjectType):
        create_parent = frontend.CreateField()

    schema = DjangoGraphQLSchema(query=_Query, mutation=Mutation).graphql_schema
    gql_field = schema.mutation_type.fields["createParent"]
    ((arg_name, argument),) = gql_field.args.items()
    input_type = _named_type(argument.type)
    query = (
        f"mutation($payload: {input_type.name}!) {{ createParent"
        f"({arg_name}: $payload) {{ ok errors {{ field messages }} }} }}"
    )
    return graphql_sync(
        schema,
        query,
        variable_values={"payload": payload},
        context_value=_Context(tenant="A", allow_child_write=True),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
@pytest.mark.parametrize("host_mode", ["none", "create_only", "read_only"])
def test_existing_orphan_requires_child_update_host(
    frontend: type[Any], host_mode: str, child_hosts: Any
) -> None:
    """Reject cross-tenant orphan adoption before any child or parent update.

    Args:
        frontend: Public update frontend.
        host_mode: Non-update child host configuration.
        child_hosts: Test-local host selector.
    """
    if host_mode == "create_only":
        child_hosts(SD4ChildCreateOnly)
    elif host_mode == "read_only":
        child_hosts(SD4ChildWriteType, read_only=True)
    else:
        child_hosts()

    parent = SD4Parent.objects.create(tenant="A", name="before")
    orphan = SD4Child.objects.create(tenant="B", label="before", parent=None)
    result = _execute(
        frontend,
        {
            "id": str(parent.pk),
            "name": "after",
            "children": [{"id": str(orphan.pk), "label": "after"}],
        },
    )

    parent.refresh_from_db()
    orphan.refresh_from_db()
    assert result.errors is None
    assert result.data["updateParent"]["ok"] is False
    assert result.data["updateParent"]["errors"][0]["field"] == "children"
    assert orphan.parent_id is None
    assert orphan.label == "before"
    assert parent.name == "before"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_update_host_preserves_scope_and_child_permission(
    frontend: type[Any], child_hosts: Any
) -> None:
    """Admit visible orphans and preserve hidden-row and permission denials.

    Args:
        frontend: Public update frontend.
        child_hosts: Test-local host selector.
    """
    child_hosts(SD4ChildWriteType)
    parent = SD4Parent.objects.create(tenant="A", name="parent")
    visible = SD4Child.objects.create(tenant="A", label="before", parent=None)
    hidden = SD4Child.objects.create(tenant="B", label="before", parent=None)

    allowed = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": str(visible.pk), "label": "after"}]},
    )
    visible.refresh_from_db()
    assert allowed.errors is None
    assert allowed.data["updateParent"]["ok"] is True
    assert (visible.parent_id, visible.label) == (parent.pk, "after")

    denied_scope = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": str(hidden.pk), "label": "after"}]},
    )
    hidden.refresh_from_db()
    assert denied_scope.errors is None
    assert denied_scope.data["updateParent"]["ok"] is False
    assert (
        "does not exist"
        in denied_scope.data["updateParent"]["errors"][0]["messages"][0]
    )
    assert (hidden.parent_id, hidden.label) == (None, "before")

    refused = SD4Child.objects.create(tenant="A", label="before", parent=None)
    denied_permission = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": str(refused.pk), "label": "after"}]},
        allow=False,
    )
    refused.refresh_from_db()
    assert denied_permission.errors
    assert denied_permission.errors[0].extensions["code"] == "PERMISSION_DENIED"
    assert (refused.parent_id, refused.label) == (None, "before")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_existing_owned_and_new_children_keep_prior_paths(
    frontend: type[Any], child_hosts: Any
) -> None:
    """Keep owned updates, new children and different-parent denial unchanged.

    Args:
        frontend: Public update frontend.
        child_hosts: Test-local host selector.
    """
    child_hosts()
    parent = SD4Parent.objects.create(tenant="A", name="parent")
    other = SD4Parent.objects.create(tenant="B", name="other")
    owned = SD4Child.objects.create(tenant="A", label="before", parent=parent)
    elsewhere = SD4Child.objects.create(tenant="B", label="before", parent=other)

    updated = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": str(owned.pk), "label": "after"}]},
    )
    owned.refresh_from_db()
    assert updated.errors is None
    assert updated.data["updateParent"]["ok"] is True
    assert owned.label == "after"

    created = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"tenant": "A", "label": "new"}]},
    )
    assert created.errors is None
    assert created.data["updateParent"]["ok"] is True
    assert SD4Child.objects.filter(parent=parent, label="new", tenant="A").exists()

    rejected = _execute(
        frontend,
        {
            "id": str(parent.pk),
            "children": [{"id": str(elsewhere.pk), "label": "after"}],
        },
    )
    elsewhere.refresh_from_db()
    assert rejected.errors is None
    assert rejected.data["updateParent"]["ok"] is False
    assert (
        "does not belong" in rejected.data["updateParent"]["errors"][0]["messages"][0]
    )
    assert (elsewhere.parent_id, elsewhere.label) == (other.pk, "before")

    count = SD4Child.objects.count()
    missing = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": "900001", "label": "after"}]},
    )
    assert missing.errors is None
    assert missing.data["updateParent"]["ok"] is False
    assert missing.data["updateParent"]["errors"] == [
        {
            "field": "children.id",
            "messages": ["SD4Child with id 900001 does not exist."],
        }
    ]
    assert SD4Child.objects.count() == count


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_later_orphan_denial_rolls_back_earlier_sibling_write(
    frontend: type[Any], child_hosts: Any
) -> None:
    """Roll back the parent and an earlier child when adoption is denied.

    Args:
        frontend: Public update frontend.
        child_hosts: Test-local host selector.
    """
    child_hosts()
    parent = SD4Parent.objects.create(tenant="A", name="before")
    owned = SD4Child.objects.create(tenant="A", label="before", parent=parent)
    orphan = SD4Child.objects.create(tenant="B", label="before", parent=None)

    result = _execute(
        frontend,
        {
            "id": str(parent.pk),
            "name": "after",
            "children": [
                {"id": str(owned.pk), "label": "after"},
                {"id": str(orphan.pk), "label": "after"},
            ],
        },
    )

    parent.refresh_from_db()
    owned.refresh_from_db()
    orphan.refresh_from_db()
    assert result.errors is None
    assert result.data["updateParent"]["ok"] is False
    assert (parent.name, owned.label, orphan.label, orphan.parent_id) == (
        "before",
        "before",
        "before",
        None,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_update_serving_mutation_host_admits_visible_orphan(
    frontend: type[Any], child_hosts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept a mutation host only when it serves child UPDATE.

    Args:
        frontend: Public update frontend.
        child_hosts: Test-local host selector.
        monkeypatch: Restores mutation operation metadata after the test.
    """
    monkeypatch.setattr(
        SD4ChildCreateOnly._meta, "model_operations", ("create", "update")
    )
    child_hosts(SD4ChildCreateOnly)
    parent = SD4Parent.objects.create(tenant="A", name="before")
    orphan = SD4Child.objects.create(tenant="A", label="before", parent=None)

    result = _execute(
        frontend,
        {"id": str(parent.pk), "children": [{"id": str(orphan.pk), "label": "after"}]},
    )

    orphan.refresh_from_db()
    assert result.errors is None
    assert result.data["updateParent"]["ok"] is True
    assert (orphan.parent_id, orphan.label) == (parent.pk, "after")


@pytest.mark.django_db(transaction=True)
def test_unrelated_registry_cannot_supply_child_update_host(
    child_hosts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignore a host registered only in an unrelated private Registry.

    Args:
        child_hosts: Test-local global-host selector.
        monkeypatch: Restores mutation host operations after the test.
    """
    child_hosts()
    parent_registry = Registry()
    unrelated_registry = Registry()
    monkeypatch.setattr(
        SD4ChildCreateOnly._meta, "model_operations", ("create", "update")
    )
    unrelated_registry.nested_hosts[SD4Child] = [SD4ChildCreateOnly]

    class PrivateParentMutation(DjangoModelMutation):
        """Parent mutation bound only to its own private Registry."""

        class Meta:
            model = SD4Parent
            registry = parent_registry
            nested_fields = {"children": SD4Child}

    parent = SD4Parent.objects.create(tenant="A", name="before")
    orphan = SD4Child.objects.create(tenant="A", label="before", parent=None)
    result = _execute(
        PrivateParentMutation,
        {"id": str(parent.pk), "children": [{"id": str(orphan.pk), "label": "after"}]},
    )

    orphan.refresh_from_db()
    assert result.errors is None
    assert result.data["updateParent"]["ok"] is False
    assert orphan.parent_id is None

    child_hosts(SD4ChildWriteType)
    admitted = _execute(
        PrivateParentMutation,
        {"id": str(parent.pk), "children": [{"id": str(orphan.pk), "label": "after"}]},
    )
    orphan.refresh_from_db()
    assert admitted.errors is None
    assert admitted.data["updateParent"]["ok"] is True
    assert (orphan.parent_id, orphan.label) == (parent.pk, "after")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_parent_create_keeps_new_child_path(
    frontend: type[Any], child_hosts: Any
) -> None:
    """Leave ordinary nested creation available without a child update host.

    Args:
        frontend: Public create frontend.
        child_hosts: Test-local host selector.
    """
    child_hosts()
    created = _execute_create(
        frontend,
        {"tenant": "A", "name": "new", "children": [{"tenant": "A", "label": "new"}]},
    )
    assert created.errors is None
    assert created.data["createParent"]["ok"] is True
    assert SD4Parent.objects.filter(name="new").count() == 1
    assert SD4Child.objects.filter(label="new", parent__name="new").count() == 1
