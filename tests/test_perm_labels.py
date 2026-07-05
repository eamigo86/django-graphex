# -*- coding: utf-8 -*-
"""Tests for "core.perm_labels.required_perms_for" (P0 composite table).

The normative table (spec: Composite Permission Table) maps each CRUD /
subscribe action to the Django permission codenames a caller must hold. Write
verbs are composite ("write + view") because a payload returns instance data.
"""

from __future__ import annotations

import pytest

from .models import HookModel

# HookModel lives under app_label "tests"; codenames follow
# "{app_label}.{verb}_{model_name}".
_ADD = "tests.add_hookmodel"
_CHANGE = "tests.change_hookmodel"
_DELETE = "tests.delete_hookmodel"
_VIEW = "tests.view_hookmodel"


def test_required_perms_for_retrieve_is_view_only() -> None:
    """Assert the "retrieve" action requires only the view permission.

    If this fails, single-object reads would either demand extra
    permissions or fail to demand view access at all.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "retrieve") == frozenset({_VIEW})


def test_required_perms_for_list_is_view_only() -> None:
    """Assert the "list" action requires only the view permission.

    If this fails, list-query reads would either demand extra permissions
    or fail to demand view access at all.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "list") == frozenset({_VIEW})


def test_required_perms_for_create_is_add_and_view() -> None:
    """Spec scenario: create requires add and view.

    If this fails, create mutations would not be gated by the composite
    add+view permission set the spec mandates.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "create") == frozenset({_ADD, _VIEW})


def test_required_perms_for_update_is_change_and_view() -> None:
    """Assert the "update" action requires the change and view permissions.

    If this fails, update mutations would not be gated by the composite
    change+view permission set.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "update") == frozenset({_CHANGE, _VIEW})


def test_required_perms_for_delete_is_delete_and_view() -> None:
    """Assert the "delete" action requires the delete and view permissions.

    If this fails, delete mutations would not be gated by the composite
    delete+view permission set.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "delete") == frozenset({_DELETE, _VIEW})


def test_required_perms_for_returns_frozenset() -> None:
    """Assert "required_perms_for" always returns a frozenset.

    If this fails, callers that rely on set operations (union,
    intersection) over the returned perms would break on a mutable or
    differently-typed collection.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert isinstance(required_perms_for(HookModel, "create"), frozenset)


# -- subscribe: per-action composite ----------------------------------------- #
def test_required_perms_for_subscribe_create() -> None:
    """Assert subscribing to "create" events requires view and add perms.

    If this fails, a subscriber would either be able to receive create
    notifications without add permission, or be wrongly denied.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "subscribe", "create") == frozenset(
        {_VIEW, _ADD}
    )


def test_required_perms_for_subscribe_update() -> None:
    """Assert subscribing to "update" events requires view and change perms.

    If this fails, a subscriber would either be able to receive update
    notifications without change permission, or be wrongly denied.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "subscribe", "update") == frozenset(
        {_VIEW, _CHANGE}
    )


def test_required_perms_for_subscribe_delete() -> None:
    """Assert subscribing to "delete" events requires view and delete perms.

    If this fails, a subscriber would either be able to receive delete
    notifications without delete permission, or be wrongly denied.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "subscribe", "delete") == frozenset(
        {_VIEW, _DELETE}
    )


def test_required_perms_for_subscribe_all_actions_spans_every_verb() -> None:
    """Spec scenario: subscribe ALL_ACTIONS spans all verbs.

    If this fails, subscribing to the catch-all "all_actions" stream would
    not require the union of every per-action permission, letting a caller
    under-provisioned for one verb still receive its notifications.
    """
    from django_graphex.core.perm_labels import required_perms_for

    assert required_perms_for(HookModel, "subscribe", "all_actions") == frozenset(
        {_VIEW, _ADD, _CHANGE, _DELETE}
    )


def test_required_perms_for_unknown_action_raises() -> None:
    """Assert an unrecognized action name raises "KeyError".

    If this fails, a typo'd or unsupported action would silently resolve
    to some default permission set instead of failing loudly.

    Raises:
        KeyError: Not raised by the test itself; asserted via
            "pytest.raises" around the lookup of an unknown action.
    """
    from django_graphex.core.perm_labels import required_perms_for

    with pytest.raises(KeyError):
        required_perms_for(HookModel, "frobnicate")
