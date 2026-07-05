# -*- coding: utf-8 -*-
"""Tests for DjangoModelType permission_classes (piece C)."""

from __future__ import annotations

import types as _types
from typing import TYPE_CHECKING, Any

from graphql import ExecutionResult, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.permissions import (
    AllowAny,
    BasePermission,
    IsAdminOrReadOnly,
    IsAuthenticated,
)
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from .models import HookModel

if TYPE_CHECKING:
    from django.contrib.auth.models import Permission, User
    from pytest import MonkeyPatch


# Local DjangoModelType (native). Defined here rather than imported from
# ``test_serializer_queryset_hooks`` so this module's coverage of
# ``permission_classes`` does not depend on that sibling's module-level schema.
class HookType(DjangoModelType):
    """Model type under test.

    Exposes "permission_classes" so tests can monkeypatch it and assert
    the resulting access control.
    """

    class Meta:
        """Configuration for "HookType".

        Declares the backing model and the fields exposed to native filtering.
        """

        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


class _Query(ObjectType):
    hook = HookType.RetrieveField()
    hooks = HookType.ListField()


class _Mutation(ObjectType):
    create_hook = HookType.CreateField()


_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)


def _execute(query: str, context: Any) -> ExecutionResult:
    """Run "query" against the native graphql-core schema with "context".

    Args:
        query: The GraphQL query or mutation document to execute.
        context: The context value exposed as "info.context" to resolvers.

    Returns:
        result: The execution result returned by "graphql_sync".
    """
    return graphql_sync(_schema.graphql_schema, query, context_value=context)


_CREATE = 'mutation { createHook(newHookmodel: {text: "y"}) { ok } }'
_LIST = "{ hooks { totalCount } }"


def _ctx(user: Any) -> _types.SimpleNamespace:
    """Build a minimal request-context stand-in carrying "user".

    Args:
        user: The user object (real or duck-typed) to expose as
            "context.user".

    Returns:
        context: A namespace shaped like the subset of Django's request
            object the view layer reads (user, META, FILES).
    """
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


def _denied(result: ExecutionResult) -> bool:
    """Report whether an execution result is a PERMISSION_DENIED error.

    Args:
        result: The execution result to inspect.

    Returns:
        denied: True when the result carries errors and the first error's
            "code" extension is "PERMISSION_DENIED".
    """
    return bool(result.errors) and result.errors[0].extensions.get("code") == (
        "PERMISSION_DENIED"
    )


# -- AC1: no permission_classes -> everything allowed ------------------------ #
def test_no_permissions_allows_anonymous(db: None) -> None:
    """Assert an anonymous caller can list rows when no permission_classes are set.

    If this fails, a model type with no explicit permission configuration
    would wrongly deny access instead of defaulting to open.

    Args:
        db: The pytest-django fixture that grants database access for the test.
    """
    HookModel.objects.create(text="x")
    res = _execute(_LIST, _ctx(_anon))
    assert res.errors is None and res.data["hooks"]["totalCount"] == 1


# -- AC2: IsAuthenticated ---------------------------------------------------- #
def test_is_authenticated(db: None, monkeypatch: MonkeyPatch) -> None:
    """Assert "IsAuthenticated" denies anonymous callers and allows authenticated ones.

    If this fails, the "IsAuthenticated" permission class would not
    actually gate list and create actions behind authentication.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    monkeypatch.setattr(HookType, "permission_classes", [IsAuthenticated])
    HookModel.objects.create(text="x")

    assert _denied(_execute(_LIST, _ctx(_anon)))
    assert _denied(_execute(_CREATE, _ctx(_anon)))

    ok = _execute(_LIST, _ctx(_authed))
    assert ok.errors is None and ok.data["hooks"]["totalCount"] == 1


# -- AC3: IsAdminOrReadOnly -------------------------------------------------- #
def test_is_admin_or_read_only(db: None, monkeypatch: MonkeyPatch) -> None:
    """Assert "IsAdminOrReadOnly" allows anonymous reads but only admin writes.

    If this fails, anonymous callers could either be blocked from
    reading, or could write despite not being an admin.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    monkeypatch.setattr(HookType, "permission_classes", [IsAdminOrReadOnly])
    HookModel.objects.create(text="x")

    # anonymous can read, cannot write
    assert _execute(_LIST, _ctx(_anon)).errors is None
    assert _denied(_execute(_CREATE, _ctx(_anon)))

    # admin can write
    admin_create = _execute(_CREATE, _ctx(_admin))
    assert admin_create.errors is None and admin_create.data["createHook"]["ok"] is True


# -- AC5: custom per-action permission --------------------------------------- #
def test_custom_per_action_permission(db: None, monkeypatch: MonkeyPatch) -> None:
    """Assert a custom per-action override gates only its specific action.

    If this fails, overriding a single "has_<action>_permission" method
    would either fail to deny that action, or would unintentionally deny
    unrelated actions too.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """

    class NoCreate(BasePermission):
        def has_create_permission(self, info: Any, model: Any, **kwargs: Any) -> bool:
            return False

    monkeypatch.setattr(HookType, "permission_classes", [NoCreate])
    HookModel.objects.create(text="x")

    assert _execute(_LIST, _ctx(_anon)).errors is None  # list allowed
    assert _denied(_execute(_CREATE, _ctx(_anon)))  # create denied


# -- ready-made classes (unit) ----------------------------------------------- #
def test_ready_made_permissions() -> None:
    """Assert the built-in permission classes gate list/create as documented.

    If this fails, one of the ready-made permission classes
    ("IsAuthenticated", "IsAdminOrReadOnly", "AllowAny") would diverge
    from its documented list/create behavior.
    """
    anon = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_anon))
    authed = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_authed))
    admin = _types.SimpleNamespace(context=_types.SimpleNamespace(user=_admin))

    assert IsAuthenticated().has_list_permission(anon, HookModel) is False
    assert IsAuthenticated().has_list_permission(authed, HookModel) is True

    assert IsAdminOrReadOnly().has_list_permission(anon, HookModel) is True
    assert IsAdminOrReadOnly().has_create_permission(anon, HookModel) is False
    assert IsAdminOrReadOnly().has_create_permission(admin, HookModel) is True

    assert AllowAny().has_create_permission(anon, HookModel) is True


def test_all_per_action_methods_delegate_to_has_permission() -> None:
    """Assert every has_<action>_permission method reflects its class's policy.

    If this fails, one of the per-action convenience methods on
    "IsAuthenticated", "IsAdmin", "IsAuthenticatedOrReadOnly", or
    "IsAdminOrReadOnly" would not consistently delegate to the class's
    overall permission policy.
    """
    from django_graphex.permissions import IsAdmin, IsAuthenticatedOrReadOnly

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


# --------------------------------------------------------------------------- #
# DjangoModelPermissions (DRF-style mapping to Django model permissions)
# --------------------------------------------------------------------------- #
import pytest  # noqa: E402

_ALL_ACTIONS = ("create", "update", "delete", "retrieve", "list", "subscribe")

#: action -> expected codenames for HookModel (app_label "tests"). Composite
#: (P0): write verbs ALSO require ``view`` because a mutation payload returns
#: instance data. retrieve/list/subscribe stay view-only.
_EXPECTED_CODENAMES = {
    "create": {"tests.add_hookmodel", "tests.view_hookmodel"},
    "update": {"tests.change_hookmodel", "tests.view_hookmodel"},
    "delete": {"tests.delete_hookmodel", "tests.view_hookmodel"},
    "retrieve": {"tests.view_hookmodel"},
    "list": {"tests.view_hookmodel"},
    "subscribe": {"tests.view_hookmodel"},
}


def _fake_user(*, authenticated: bool, has_perms: Any) -> _types.SimpleNamespace:
    """Build a SimpleNamespace user with a fake "has_perms" callable.

    Args:
        authenticated: The value exposed as "is_authenticated".
        has_perms: A callable stand-in for Django's "has_perms" method.

    Returns:
        user: A duck-typed user object with "is_authenticated" and
            "has_perms".
    """
    return _types.SimpleNamespace(is_authenticated=authenticated, has_perms=has_perms)


def _info_for(user: Any) -> _types.SimpleNamespace:
    """Wrap "user" in an info-like object (info.context.user).

    Args:
        user: The user object to expose via "context.user".

    Returns:
        info: A namespace shaped like the subset of GraphQL resolver info
            "DjangoModelPermissions" reads.
    """
    return _types.SimpleNamespace(context=_types.SimpleNamespace(user=user))


def test_django_model_permissions_anonymous_denied_every_action() -> None:
    """Assert an anonymous user is denied every CRUD/subscribe action.

    If this fails, "DjangoModelPermissions" would grant some action to an
    unauthenticated caller instead of failing closed.
    """
    from django_graphex.permissions import DjangoModelPermissions

    info = _info_for(_anon)
    perm = DjangoModelPermissions()
    for action in _ALL_ACTIONS:
        assert perm.has_permission(info, action, HookModel) is False


@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_django_model_permissions_authed_without_perm_denied(action: str) -> None:
    """Assert an authenticated user without the required perm is denied.

    Args:
        action: The CRUD/subscribe action under test, parametrized over
            "_ALL_ACTIONS".

    If this fails, "DjangoModelPermissions" would grant an action to a
    user lacking the Django model permission it maps to.
    """
    from django_graphex.permissions import DjangoModelPermissions

    user = _fake_user(authenticated=True, has_perms=lambda perms: False)
    info = _info_for(user)
    assert DjangoModelPermissions().has_permission(info, action, HookModel) is False


@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_django_model_permissions_authed_with_perm_allowed(action: str) -> None:
    """Assert an authenticated user holding the required perm is allowed.

    Args:
        action: The CRUD/subscribe action under test, parametrized over
            "_ALL_ACTIONS".

    If this fails, "DjangoModelPermissions" would deny an action to a
    user who actually holds the mapped Django model permission(s).
    """
    from django_graphex.permissions import DjangoModelPermissions

    user = _fake_user(authenticated=True, has_perms=lambda perms: True)
    info = _info_for(user)
    assert DjangoModelPermissions().has_permission(info, action, HookModel) is True


@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_django_model_permissions_get_required_permissions(action: str) -> None:
    """Assert "get_required_permissions" returns the documented codename set.

    Args:
        action: The CRUD/subscribe action under test, parametrized over
            "_ALL_ACTIONS".

    If this fails, the mapping from action to required Django permission
    codenames would drift from the documented composite table.
    """
    from django_graphex.permissions import DjangoModelPermissions

    perms = DjangoModelPermissions().get_required_permissions(action, HookModel)
    assert set(perms) == _EXPECTED_CODENAMES[action]


def test_django_model_permissions_write_requires_view_composite() -> None:
    """P0: write verbs (create/update/delete) MUST ALSO require "view".

    If this fails, a write mutation could execute for a user who cannot
    view the resulting instance data, violating the composite permission
    requirement.
    """
    from django_graphex.permissions import DjangoModelPermissions

    perm = DjangoModelPermissions()
    for action, write_codename in (
        ("create", "tests.add_hookmodel"),
        ("update", "tests.change_hookmodel"),
        ("delete", "tests.delete_hookmodel"),
    ):
        perms = perm.get_required_permissions(action, HookModel)
        assert write_codename in perms
        assert "tests.view_hookmodel" in perms


def test_django_model_permissions_update_requires_change_and_view() -> None:
    """Spec scenario: get_required_permissions("update", Thing) includes change and view.

    If this fails, updating a model would not require both the change
    permission and the view permission.
    """
    from django_graphex.permissions import DjangoModelPermissions

    perms = DjangoModelPermissions().get_required_permissions("update", HookModel)
    assert "tests.change_hookmodel" in perms
    assert "tests.view_hookmodel" in perms


def test_django_model_permissions_retrieve_view_only() -> None:
    """Spec scenario: get_required_permissions("retrieve", Thing) is view-only.

    If this fails, retrieving a single object would require permissions
    beyond the view permission.
    """
    from django_graphex.permissions import DjangoModelPermissions

    perms = DjangoModelPermissions().get_required_permissions("retrieve", HookModel)
    assert set(perms) == {"tests.view_hookmodel"}


def test_django_model_permissions_write_only_inbox_override() -> None:
    """Spec scenario: a subclass overriding create to write-only skips view.

    If this fails, a subclass could not opt out of the composite
    add+view requirement for a specific action via its own "perms_map".
    """
    from django_graphex.permissions import DjangoModelPermissions

    class WriteOnlyInbox(DjangoModelPermissions):
        perms_map = {
            **DjangoModelPermissions.perms_map,
            "create": ("{app_label}.add_{model_name}",),
        }

    perms = WriteOnlyInbox().get_required_permissions("create", HookModel)
    assert set(perms) == {"tests.add_hookmodel"}
    assert "tests.view_hookmodel" not in perms


def test_django_model_permissions_model_none_denied() -> None:
    """Assert a None model (no model context) fails closed.

    If this fails, the view-level "list" check with no model context to
    map would wrongly allow the action instead of denying it.
    """
    from django_graphex.permissions import DjangoModelPermissions

    user = _fake_user(authenticated=True, has_perms=lambda perms: True)
    info = _info_for(user)
    # Fail-closed: no model context to map (the view-level "view" case).
    assert DjangoModelPermissions().has_permission(info, "list", None) is False


def test_django_model_permissions_unknown_action_denied() -> None:
    """Assert an unrecognized action name is denied and maps to no permissions.

    If this fails, an unknown action would either be allowed or would
    return a non-None permission set instead of signaling "unmapped".
    """
    from django_graphex.permissions import DjangoModelPermissions

    user = _fake_user(authenticated=True, has_perms=lambda perms: True)
    info = _info_for(user)
    assert DjangoModelPermissions().has_permission(info, "view", HookModel) is False
    # get_required_permissions returns None for an unknown action.
    assert DjangoModelPermissions().get_required_permissions("view", HookModel) is None


def test_django_model_permissions_perms_map_subclass_override() -> None:
    """Assert a subclass's "perms_map" override replaces the base mapping.

    If this fails, a subclass overriding a single action's permission
    codenames would still use the base class's mapping for that action.
    """
    from django_graphex.permissions import DjangoModelPermissions

    class CustomModelPermissions(DjangoModelPermissions):
        perms_map = {
            **DjangoModelPermissions.perms_map,
            "create": ("{app_label}.publish_{model_name}",),
        }

    perms = CustomModelPermissions().get_required_permissions("create", HookModel)
    assert perms == ["tests.publish_hookmodel"]


# -- Integration with real Django permissions -------------------------------- #
def _get_perm(codename: str, name: str) -> Permission:
    """Fetch-or-create a Permission on HookModel's ContentType.

    Args:
        codename: The permission codename (without the app_label prefix).
        name: The human-readable permission name used if it must be created.

    Returns:
        permission: The fetched or newly created "Permission" instance.
    """
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(HookModel)
    perm, _ = Permission.objects.get_or_create(
        codename=codename, content_type=ct, defaults={"name": name}
    )
    return perm


def _grant(user: User, codename: str, name: str) -> User:
    """Grant "codename" to "user" and re-fetch (has_perm caches).

    Args:
        user: The user to grant the permission to.
        codename: The permission codename (without the app_label prefix).
        name: The human-readable permission name used if it must be created.

    Returns:
        user: A freshly re-fetched user instance reflecting the new grant.
    """
    from django.contrib.auth.models import User

    user.user_permissions.add(_get_perm(codename, name))
    return User.objects.get(pk=user.pk)


def test_django_model_permissions_real_user_with_view_perm(db: None) -> None:
    """Assert a real user holding "view_hookmodel" can list but not create.

    If this fails, integration with real Django's permission storage
    (rather than a stubbed "has_perms") would not enforce the expected
    view-only access.

    Args:
        db: The pytest-django fixture that grants database access for the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    user = User.objects.create_user(username="viewer", password="x")
    user = _grant(user, "view_hookmodel", "Can view hook model")
    info = _info_for(user)
    assert DjangoModelPermissions().has_permission(info, "list", HookModel) is True
    # No add perm -> create denied.
    assert DjangoModelPermissions().has_permission(info, "create", HookModel) is False


def test_django_model_permissions_real_user_without_perms(db: None) -> None:
    """Assert a real user with no granted permissions cannot list.

    If this fails, a user with no Django model permissions would still
    be allowed to list rows.

    Args:
        db: The pytest-django fixture that grants database access for the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    user = User.objects.create_user(username="nobody", password="x")
    info = _info_for(user)
    assert DjangoModelPermissions().has_permission(info, "list", HookModel) is False


def test_django_model_permissions_schema_list_with_view_perm(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert a schema-level list query succeeds for a user with view perm.

    If this fails, wiring "DjangoModelPermissions" onto a model type's
    "permission_classes" would not actually grant list access to a
    correctly permissioned real user.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))
    HookModel.objects.create(text="x")

    user = User.objects.create_user(username="viewer2", password="x")
    user = _grant(user, "view_hookmodel", "Can view hook model")
    res = _execute(_LIST, _ctx(user))
    assert res.errors is None and res.data["hooks"]["totalCount"] == 1


def test_django_model_permissions_schema_list_without_perms_denied(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert a schema-level list query is denied for a user with no perms.

    If this fails, wiring "DjangoModelPermissions" onto a model type's
    "permission_classes" would not actually deny list access to an
    unpermissioned real user.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))
    HookModel.objects.create(text="x")

    user = User.objects.create_user(username="nobody2", password="x")
    assert _denied(_execute(_LIST, _ctx(user)))


def test_django_model_permissions_schema_create_with_only_view_denied(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert create is denied for a user holding only the view permission.

    If this fails, a user without the add permission could still create
    rows through the schema-level mutation.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))

    user = User.objects.create_user(username="viewer3", password="x")
    user = _grant(user, "view_hookmodel", "Can view hook model")
    assert _denied(_execute(_CREATE, _ctx(user)))


def test_django_model_permissions_schema_create_with_add_only_denied(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """P0 composite: "add" alone is no longer enough — create also needs view.

    If this fails, a user holding only the add permission (without view)
    could still create rows, violating the composite requirement.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))

    user = User.objects.create_user(username="adder", password="x")
    user = _grant(user, "add_hookmodel", "Can add hook model")
    # add-only user: composite perms_map now also requires view -> denied.
    assert _denied(_execute(_CREATE, _ctx(user)))


def test_django_model_permissions_schema_create_with_add_and_view(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert create succeeds for a user holding both add and view permissions.

    If this fails, the composite add+view requirement would reject a
    user who actually holds both required permissions.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))

    user = User.objects.create_user(username="adder2", password="x")
    user = _grant(user, "add_hookmodel", "Can add hook model")
    user = _grant(user, "view_hookmodel", "Can view hook model")
    res = _execute(_CREATE, _ctx(user))
    assert res.errors is None and res.data["createHook"]["ok"] is True


def test_django_model_permissions_schema_superuser_passes(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert a superuser can list and create with no explicit permission grants.

    If this fails, Django's ModelBackend superuser bypass would not
    propagate through "DjangoModelPermissions" to the schema layer.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.permission_classes" for the
            duration of the test.
    """
    from django.contrib.auth.models import User

    from django_graphex.permissions import DjangoModelPermissions

    monkeypatch.setattr(HookType, "permission_classes", (DjangoModelPermissions,))
    HookModel.objects.create(text="x")

    user = User.objects.create_superuser(username="root", email="r@e.co", password="x")
    # ModelBackend grants all perms to a superuser with no explicit perms.
    assert _execute(_LIST, _ctx(user)).errors is None
    create = _execute(_CREATE, _ctx(user))
    assert create.errors is None and create.data["createHook"]["ok"] is True
