# -*- coding: utf-8 -*-
"""Security regressions for the 2.1.0 "DjangoModelType" CRUD/permission surface.

Three published defects are pinned here:

* the write path ("update"/"delete") resolved its target row from the BARE
  model, so "filter_queryset" scoping protected reads and left writes open;
* "check_permissions" compared the permission result with "is False", so a
  permission returning "None"/0/"" granted the action;
* "only_fields"/"exclude_fields"/"include_fields" were dropped silently when the
  output type came back from the registry, leaving a sensitive column exposed.

Their sibling on the plain "DjangoObjectType" hierarchy is pinned here too:
"get_node" resolved its row on the bare model, skipping the "get_queryset"
choke point every other row-serving path routes through.

Every test builds its own module-level schema over a dedicated model family so
the assertions never depend on a sibling module's registry state.
"""

from __future__ import annotations

import types as _types
from typing import TYPE_CHECKING, Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import ExecutionResult, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.permissions import BasePermission
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType

from .models import (
    CrudFreshDoc,
    CrudLeakDoc,
    CrudNodeDoc,
    CrudPermDoc,
    CrudScopedDoc,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

# --------------------------------------------------------------------------- #
# S1 -- cross-tenant write through the CRUD mutations
# --------------------------------------------------------------------------- #


class ScopedDocType(DjangoModelType):
    """CRUD type scoped to the caller's tenant, exactly as the docs show.

    "filter_queryset" narrows every operation to "info.context.tenant", which is
    the multi-tenant pattern documented in docs/usage/filtering.md.
    """

    class Meta:
        """Configuration for "ScopedDocType".

        Declares the backing model and the single filter field the retrieve
        and list resolvers need.
        """

        model = CrudScopedDoc
        filter_fields = {"id": ("exact",)}

    @classmethod
    def filter_queryset(
        cls, qs: QuerySet[CrudScopedDoc], info: Any, **kwargs: Any
    ) -> QuerySet[CrudScopedDoc]:
        """Restrict the queryset to the calling request's tenant.

        Args:
            qs: Queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra resolver arguments (unused).

        Returns:
            The queryset narrowed to the caller's tenant.
        """
        return qs.filter(tenant=getattr(info.context, "tenant", None))


class _ScopedQuery(ObjectType):
    """Root query exposing the scoped retrieve field."""

    doc = ScopedDocType.RetrieveField()


class _ScopedMutation(ObjectType):
    """Root mutation exposing the scoped update and delete fields."""

    doc_update = ScopedDocType.UpdateField()
    doc_delete = ScopedDocType.DeleteField()


_scoped_schema = DjangoGraphQLSchema(query=_ScopedQuery, mutation=_ScopedMutation)


def _ctx(**attrs: Any) -> _types.SimpleNamespace:
    """Build a minimal request stand-in for the CRUD resolvers.

    Args:
        **attrs: Extra attributes exposed on the fake request (e.g. "tenant").

    Returns:
        A namespace carrying the "META"/"FILES" the mutations read.
    """
    return _types.SimpleNamespace(META={}, FILES={}, **attrs)


def _run(schema: DjangoGraphQLSchema, document: str, context: Any) -> ExecutionResult:
    """Execute "document" against "schema" with "context".

    Args:
        schema: The schema to execute against.
        document: The GraphQL document to run.
        context: The value exposed to resolvers as "info.context".

    Returns:
        The execution result returned by "graphql_sync".
    """
    return graphql_sync(schema.graphql_schema, document, context_value=context)


def _two_tenants() -> tuple[CrudScopedDoc, CrudScopedDoc]:
    """Create one row for tenant "a" and one for tenant "b".

    Returns:
        The caller's own row and the row owned by the other tenant.
    """
    mine = CrudScopedDoc.objects.create(tenant="a", body="mine")
    theirs = CrudScopedDoc.objects.create(tenant="b", body="theirs")
    return mine, theirs


def test_retrieve_denies_other_tenant_row(db: None) -> None:
    """Assert the READ path already refuses a row outside "filter_queryset".

    This is the baseline the write path must match; if it fails, the scoping
    hook itself is broken and the write assertions below prove nothing.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    _mine, theirs = _two_tenants()
    res = _run(_scoped_schema, "{ doc(id: %d) { id } }" % theirs.pk, _ctx(tenant="a"))
    assert res.errors is None, res.errors
    assert res.data["doc"] is None


def test_update_cannot_write_other_tenant_row(db: None) -> None:
    """Ships broken if "update" resolves its target outside "filter_queryset".

    A tenant "a" caller updating a tenant "b" row must get the plain
    "does not exist" payload and leave the row untouched.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    _mine, theirs = _two_tenants()
    document = (
        'mutation { docUpdate(newCrudscopeddoc: {id: %d, tenant: "b", '
        'body: "PWNED"}) { ok errors { field messages } } }' % theirs.pk
    )
    res = _run(_scoped_schema, document, _ctx(tenant="a"))

    assert res.errors is None, res.errors
    payload = res.data["docUpdate"]
    assert payload["ok"] is False, f"cross-tenant update was accepted: {payload}"
    theirs.refresh_from_db()
    assert theirs.body == "theirs", "cross-tenant update overwrote the row"


def test_delete_cannot_remove_other_tenant_row(db: None) -> None:
    """Ships broken if "delete" resolves its target outside "filter_queryset".

    A tenant "a" caller deleting a tenant "b" row must get the plain
    "does not exist" payload and leave the row in place.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    _mine, theirs = _two_tenants()
    document = (
        "mutation { docDelete(id: %d) { ok errors { field messages } } }" % theirs.pk
    )
    res = _run(_scoped_schema, document, _ctx(tenant="a"))

    assert res.errors is None, res.errors
    payload = res.data["docDelete"]
    assert payload["ok"] is False, f"cross-tenant delete was accepted: {payload}"
    assert CrudScopedDoc.objects.filter(pk=theirs.pk).exists(), (
        "cross-tenant delete removed the row"
    )


def test_out_of_scope_write_is_indistinguishable_from_missing(db: None) -> None:
    """Ships broken if an out-of-scope row answers differently than a missing one.

    A distinguishable error would let a caller probe which primary keys exist in
    another tenant.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    _mine, theirs = _two_tenants()
    missing_pk = theirs.pk + 10_000
    document = "mutation { docDelete(id: %d) { ok errors { field messages } } }"

    out_of_scope = _run(_scoped_schema, document % theirs.pk, _ctx(tenant="a"))
    missing = _run(_scoped_schema, document % missing_pk, _ctx(tenant="a"))

    assert out_of_scope.errors is None and missing.errors is None
    scoped_errors = out_of_scope.data["docDelete"]["errors"]
    missing_errors = missing.data["docDelete"]["errors"]
    assert scoped_errors is not None and missing_errors is not None
    assert scoped_errors[0]["field"] == missing_errors[0]["field"]
    # Only the primary key differs between the two messages.
    assert scoped_errors[0]["messages"][0].replace(
        str(theirs.pk), "<pk>"
    ) == missing_errors[0]["messages"][0].replace(str(missing_pk), "<pk>")


def test_update_still_writes_own_tenant_row(db: None) -> None:
    """Assert the scoping fix does not break a legitimate in-scope update.

    Guards against "fixing" the leak by denying every write.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    mine, _theirs = _two_tenants()
    document = (
        'mutation { docUpdate(newCrudscopeddoc: {id: %d, tenant: "a", '
        'body: "edited"}) { ok errors { field messages } } }' % mine.pk
    )
    res = _run(_scoped_schema, document, _ctx(tenant="a"))

    assert res.errors is None, res.errors
    assert res.data["docUpdate"]["ok"] is True, res.data["docUpdate"]["errors"]
    mine.refresh_from_db()
    assert mine.body == "edited"


# --------------------------------------------------------------------------- #
# S2 -- a falsy (but not False) permission result must deny
# --------------------------------------------------------------------------- #


class _FalsyPermission(BasePermission):
    """Permission written with the most idiomatic Python one-liner.

    "user and user.is_staff" evaluates to the falsy USER (or "None") rather than
    to "False" whenever the caller is anonymous, which is exactly the shape the
    identity check used to let through.
    """

    def has_permission(self, info: Any, action: str, model: Any, **kwargs: Any) -> Any:
        """Return the raw "user and user.is_staff" value for any action.

        Args:
            info: GraphQL resolve info carrying the request context.
            action: The CRUD action being checked.
            model: The Django model the action targets.
            **kwargs: Action-specific extras (unused).

        Returns:
            The truthiness of the staff check, unconverted.
        """
        user = getattr(info.context, "user", None)
        return user and user.is_staff


class PermDocType(DjangoModelType):
    """CRUD type guarded by "_FalsyPermission".

    Mounts both a read and a write field so the shared permission choke point is
    proven on each path.
    """

    permission_classes = (_FalsyPermission,)

    class Meta:
        """Configuration for "PermDocType".

        Declares the backing model and the single filter field the retrieve
        resolver needs.
        """

        model = CrudPermDoc
        filter_fields = {"id": ("exact",)}


class _PermQuery(ObjectType):
    """Root query exposing the guarded retrieve field."""

    perm_doc = PermDocType.RetrieveField()


class _PermMutation(ObjectType):
    """Root mutation exposing the guarded delete field."""

    perm_doc_delete = PermDocType.DeleteField()


_perm_schema = DjangoGraphQLSchema(query=_PermQuery, mutation=_PermMutation)

_DENIED = "You do not have permission to perform this action."


@pytest.mark.parametrize("value", [None, 0, ""])
def test_falsy_permission_denies_retrieve(db: None, value: Any) -> None:
    """Ships broken if a falsy non-"False" permission result grants a read.

    Args:
        db: The pytest-django fixture that grants database access.
        value: The falsy value the permission returns.
    """
    row = CrudPermDoc.objects.create(name="x")
    context = _ctx(user=_types.SimpleNamespace(is_staff=value))
    res = _run(_perm_schema, "{ permDoc(id: %d) { id } }" % row.pk, context)

    assert res.errors, f"falsy permission {value!r} granted the read"
    assert _DENIED in str(res.errors[0].message)


@pytest.mark.parametrize("value", [None, 0, ""])
def test_falsy_permission_denies_delete(db: None, value: Any) -> None:
    """Ships broken if a falsy non-"False" permission result grants a delete.

    The write sibling of the read check above: the identity comparison lived in
    one choke point, so both paths must close together.

    Args:
        db: The pytest-django fixture that grants database access.
        value: The falsy value the permission returns.
    """
    row = CrudPermDoc.objects.create(name="x")
    context = _ctx(user=_types.SimpleNamespace(is_staff=value))
    document = "mutation { permDocDelete(id: %d) { ok } }" % row.pk
    res = _run(_perm_schema, document, context)

    assert res.errors, f"falsy permission {value!r} granted the delete"
    assert _DENIED in str(res.errors[0].message)
    assert CrudPermDoc.objects.filter(pk=row.pk).exists()


def test_truthy_permission_still_allows(db: None) -> None:
    """Assert a truthy non-"True" permission result still grants the action.

    Guards against closing the hole by denying everything.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    row = CrudPermDoc.objects.create(name="x")
    context = _ctx(user=_types.SimpleNamespace(is_staff="yes"))
    res = _run(_perm_schema, "{ permDoc(id: %d) { name } }" % row.pk, context)

    assert res.errors is None, res.errors
    assert res.data["permDoc"]["name"] == "x"


# --------------------------------------------------------------------------- #
# S3 -- a dropped projection must not silently expose a column
# --------------------------------------------------------------------------- #


class LeakDocNode(DjangoObjectType):
    """Plain output type registered for "CrudLeakDoc" BEFORE the CRUD type.

    Its presence in the registry is what made the CRUD type's projection
    options a no-op.
    """

    class Meta:
        """Configuration for "LeakDocNode".

        Declares the backing model with no projection, so the registered output
        type carries every column including "secret".
        """

        model = CrudLeakDoc


def test_projection_on_reused_output_type_is_rejected(db: None) -> None:
    """Ships broken if a dropped "exclude_fields" only warns instead of failing.

    Declaring the type must fail closed and name the option, the model and the
    type that already registered the output type; otherwise the schema builds
    with "secret" exposed.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    with pytest.raises(ImproperlyConfigured) as excinfo:

        class LeakDocType(DjangoModelType):
            """CRUD type that tries to hide "secret" on a reused output type."""

            class Meta:
                """Bind "LeakDocType" to "CrudLeakDoc" and hide "secret"."""

                model = CrudLeakDoc
                exclude_fields = ("secret",)

    message = str(excinfo.value)
    assert "exclude_fields" in message, message
    assert "CrudLeakDoc" in message, message
    assert "LeakDocNode" in message, message


def test_projection_is_honored_when_output_type_is_built_fresh(db: None) -> None:
    """Assert the guard only fires on reuse, never on a freshly built type.

    Args:
        db: The pytest-django fixture that grants database access.
    """

    class FreshDocType(DjangoModelType):
        """CRUD type whose output type is built by the type itself."""

        class Meta:
            """Bind "FreshDocType" to a model with no registered output type."""

            model = CrudFreshDoc
            exclude_fields = ("secret",)

    class _FreshQuery(ObjectType):
        """Root query exposing the freshly built output type."""

        fresh = FreshDocType.RetrieveField()

    schema = DjangoGraphQLSchema(query=_FreshQuery)
    row = CrudFreshDoc.objects.create(label="pub", secret="SHHH")
    res = _run(schema, "{ fresh(id: %d) { label } }" % row.pk, _ctx())

    assert res.errors is None, res.errors
    assert res.data["fresh"]["label"] == "pub"
    leak = _run(schema, "{ fresh(id: %d) { secret } }" % row.pk, _ctx())
    assert leak.errors, "excluded field is still queryable on a fresh output type"


# --------------------------------------------------------------------------- #
# Sibling -- DjangoObjectType.get_node bypassed the get_queryset choke point
# --------------------------------------------------------------------------- #


class NodeDocNode(DjangoObjectType):
    """Plain output type whose "get_queryset" hides non-public rows.

    The hook is the documented per-request scoping seam for a
    "DjangoObjectType"; every path that serves rows must honor it.
    """

    class Meta:
        """Configuration for "NodeDocNode".

        Declares the backing model; the scoping lives in the "get_queryset"
        override rather than in a projection.
        """

        model = CrudNodeDoc

    @classmethod
    def get_queryset(cls, queryset: QuerySet[CrudNodeDoc], info: Any) -> Any:
        """Restrict the queryset to public rows.

        Args:
            queryset: Base queryset to scope.
            info: GraphQL resolve info for the current request.

        Returns:
            The queryset narrowed to public rows.
        """
        return queryset.filter(is_public=True)


def test_get_node_honors_the_get_queryset_scope(db: None) -> None:
    """Ships broken if "get_node" resolves its row on the bare model.

    "get_node" takes a primary key straight from the caller, so skipping the
    hook hands back exactly the rows the scope exists to hide.

    Args:
        db: The pytest-django fixture that grants database access.
    """
    public = CrudNodeDoc.objects.create(title="public", is_public=True)
    private = CrudNodeDoc.objects.create(title="private", is_public=False)

    assert NodeDocNode.get_node(None, public.pk) == public
    assert NodeDocNode.get_node(None, private.pk) is None, (
        "get_node returned a row the get_queryset scope excludes"
    )
