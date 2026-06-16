# -*- coding: utf-8 -*-
"""Tests for DjangoModelType permission_classes (piece C)."""

import types as _types

import graphene
from graphql import graphql_sync

from django_graphex import (
    AllowAny,
    BasePermission,
    DjangoGraphQLSchema,
    DjangoModelType,
    IsAdminOrReadOnly,
    IsAuthenticated,
)

from .models import HookModel


# Local DjangoModelType (native). Defined here rather than imported from
# ``test_serializer_queryset_hooks`` so this module's coverage of
# ``permission_classes`` does not depend on that sibling's module-level schema.
class HookType(DjangoModelType):
    class Meta:
        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


class _Query(graphene.ObjectType):
    hook = HookType.RetrieveField()
    hooks = HookType.ListField()


class _Mutation(graphene.ObjectType):
    create_hook = HookType.CreateField()


_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)


def _execute(query, context):
    """Run ``query`` against the native graphql-core schema with ``context``."""
    return graphql_sync(_schema.graphql_schema, query, context_value=context)


_CREATE = 'mutation { createHook(newHookmodel: {text: "y"}) { ok } }'
_LIST = "{ hooks { totalCount } }"


def _ctx(user):
    return _types.SimpleNamespace(user=user, META={}, FILES={})


_anon = _types.SimpleNamespace(
    is_authenticated=False, is_active=False, is_staff=False, is_superuser=False
)
_authed = _types.SimpleNamespace(
    is_authenticated=True, is_active=True, is_staff=False, is_superuser=False
)
_admin = _types.SimpleNamespace(
    is_authenticated=True, is_active=True, is_staff=True, is_superuser=True
)


def _denied(result):
    return bool(result.errors) and result.errors[0].extensions.get("code") == (
        "PERMISSION_DENIED"
    )


# -- AC1: no permission_classes -> everything allowed ------------------------ #
def test_no_permissions_allows_anonymous(db):
    HookModel.objects.create(text="x")
    res = _execute(_LIST, _ctx(_anon))
    assert res.errors is None and res.data["hooks"]["totalCount"] == 1


# -- AC2: IsAuthenticated ---------------------------------------------------- #
def test_is_authenticated(db, monkeypatch):
    monkeypatch.setattr(HookType, "permission_classes", [IsAuthenticated])
    HookModel.objects.create(text="x")

    assert _denied(_execute(_LIST, _ctx(_anon)))
    assert _denied(_execute(_CREATE, _ctx(_anon)))

    ok = _execute(_LIST, _ctx(_authed))
    assert ok.errors is None and ok.data["hooks"]["totalCount"] == 1


# -- AC3: IsAdminOrReadOnly -------------------------------------------------- #
def test_is_admin_or_read_only(db, monkeypatch):
    monkeypatch.setattr(HookType, "permission_classes", [IsAdminOrReadOnly])
    HookModel.objects.create(text="x")

    # anonymous can read, cannot write
    assert _execute(_LIST, _ctx(_anon)).errors is None
    assert _denied(_execute(_CREATE, _ctx(_anon)))

    # admin can write
    admin_create = _execute(_CREATE, _ctx(_admin))
    assert admin_create.errors is None and admin_create.data["createHook"]["ok"] is True


# -- AC5: custom per-action permission --------------------------------------- #
def test_custom_per_action_permission(db, monkeypatch):
    class NoCreate(BasePermission):
        def has_create_permission(self, info, model, **kwargs):
            return False

    monkeypatch.setattr(HookType, "permission_classes", [NoCreate])
    HookModel.objects.create(text="x")

    assert _execute(_LIST, _ctx(_anon)).errors is None  # list allowed
    assert _denied(_execute(_CREATE, _ctx(_anon)))  # create denied


# -- ready-made classes (unit) ----------------------------------------------- #
def test_ready_made_permissions():
    anon = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_anon))
    authed = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_authed))
    admin = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_admin))

    assert IsAuthenticated().has_list_permission(anon, HookModel) is False
    assert IsAuthenticated().has_list_permission(authed, HookModel) is True

    assert IsAdminOrReadOnly().has_list_permission(anon, HookModel) is True
    assert IsAdminOrReadOnly().has_create_permission(anon, HookModel) is False
    assert IsAdminOrReadOnly().has_create_permission(admin, HookModel) is True

    assert AllowAny().has_create_permission(anon, HookModel) is True


def test_all_per_action_methods_delegate_to_has_permission():
    from django_graphex import IsAdmin, IsAuthenticatedOrReadOnly

    anon = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_anon))
    authed = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_authed))
    admin = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_admin))

    # IsAuthenticated gates every action, including the write/read variants.
    p = IsAuthenticated()
    assert p.has_update_permission(authed, HookModel) is True
    assert p.has_delete_permission(anon, HookModel) is False
    assert p.has_retrieve_permission(authed, HookModel) is True
    assert p.has_subscribe_permission(anon, HookModel) is False

    # IsAdmin allows only an active staff superuser.
    admin_perm = IsAdmin()
    assert admin_perm.has_create_permission(admin, HookModel) is True
    assert admin_perm.has_create_permission(authed, HookModel) is False
    assert admin_perm.has_list_permission(anon, HookModel) is False

    # IsAuthenticatedOrReadOnly: reads open, writes require auth.
    ror = IsAuthenticatedOrReadOnly()
    assert ror.has_retrieve_permission(anon, HookModel) is True
    assert ror.has_list_permission(anon, HookModel) is True
    assert ror.has_subscribe_permission(anon, HookModel) is True
    assert ror.has_create_permission(anon, HookModel) is False
    assert ror.has_update_permission(authed, HookModel) is True
    assert ror.has_delete_permission(anon, HookModel) is False

    # IsAdminOrReadOnly write path uses the admin check.
    assert IsAdminOrReadOnly().has_update_permission(admin, HookModel) is True
    assert IsAdminOrReadOnly().has_delete_permission(authed, HookModel) is False
    assert IsAdminOrReadOnly().has_retrieve_permission(anon, HookModel) is True
