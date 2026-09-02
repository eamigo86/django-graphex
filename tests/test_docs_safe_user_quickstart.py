"""Executable security contract for the user-account quick start."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from graphql import get_named_type, graphql_sync

from django_graphex.core import BooleanField, CharField, Field, Mutation, ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import AuthenticatedGraphQLView

ROOT = Path(__file__).resolve().parents[1]
USER_FIELDS = ("id", "username", "first_name", "last_name")
User = get_user_model()


@pytest.fixture
def safe_contract() -> Iterator[SimpleNamespace]:
    """Build the executable docs schema without changing global type slots.

    This test protects the corresponding regression contract.

    Yields:
        result: The isolated executable documentation contract.
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        default_schema_registries,
        get_shared_output_registry,
    )

    shared = get_shared_output_registry()
    default_registries = default_schema_registries()
    entries_before = list(_gdx_output_registry)
    compiled_before = dict(shared._compiled)
    cache_names = (
        "plain_object_cache",
        "union_cache",
        "interface_cache",
        "filter_input_cache",
    )
    caches_before = {
        name: dict(getattr(default_registries, name)) for name in cache_names
    }
    contract_registry = Registry()

    class SafeUserType(DjangoObjectType):
        """Read-only account projection copied by the quick start."""

        class Meta:
            model = User
            registry = contract_registry
            only_fields = USER_FIELDS
            filter_fields = {"username": ("exact", "icontains")}

    class SafeUserListType(DjangoListObjectType):
        """Paginated container for the safe account projection."""

        class Meta:
            model = User
            registry = contract_registry
            pagination = LimitOffsetGraphqlPagination(default_limit=25)

    class RegisterUser(Mutation):
        """Purpose-built account registration that hashes the password."""

        ok = BooleanField()
        user = Field(SafeUserType)

        class Arguments:
            username = CharField(required=True)
            password = CharField(required=True)

        @classmethod
        def mutate(cls, root, info, username, password):
            user = User.objects.create_user(username=username, password=password)
            return cls(ok=True, user=user)

    class SafeQuery(ObjectType):
        user = DjangoObjectField(SafeUserType)
        users = DjangoListObjectField(SafeUserListType)

    class SafeMutation(ObjectType):
        register_user = RegisterUser.Field()

    try:
        yield SimpleNamespace(
            schema=DjangoGraphQLSchema(query=SafeQuery, mutation=SafeMutation),
        )
    finally:
        _gdx_output_registry[:] = entries_before
        shared._compiled.clear()
        shared._compiled.update(compiled_before)
        for name, before in caches_before.items():
            cache = getattr(default_registries, name)
            cache.clear()
            cache.update(before)


def test_quick_start_docs_do_not_generate_auth_user_crud() -> None:
    """The first copied example must not publish Django's privileged columns.

    This test protects the corresponding regression contract.
    """
    for relative in ("README.md",):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "AuthenticatedGraphQLView" in text, relative
        assert "'CACHE_ACTIVE': False" in text or '"CACHE_ACTIVE": False' in text
        assert "class UserMutation(DjangoModelMutation)" not in text, relative
        assert "class UserModelType(DjangoModelType)" not in text, relative
        assert "get_user_model" in text, relative
        assert ".objects.create_user(" in text, relative
        assert "only_fields" in text and all(name in text for name in USER_FIELDS)


def test_safe_user_sdl_has_no_sensitive_fields_or_generic_crud(
    safe_contract: SimpleNamespace,
) -> None:
    """The documented shape publishes four read fields and one custom write.

    This test protects the corresponding regression contract.

    Args:
        safe_contract: The isolated executable quickstart contract.
    """
    schema = safe_contract.schema.graphql_schema
    user_type = get_named_type(schema.query_type.fields["user"].type)
    assert set(user_type.fields) == {"id", "username", "firstName", "lastName"}
    assert set(schema.mutation_type.fields) == {"registerUser"}
    assert set(schema.mutation_type.fields["registerUser"].args) == {
        "username",
        "password",
    }
    sdl = str(schema)
    for forbidden in ("isStaff", "isSuperuser", "groups", "userPermissions"):
        assert forbidden not in sdl


@pytest.mark.django_db
def test_registration_hashes_password_without_granting_privileges(
    safe_contract: SimpleNamespace,
) -> None:
    """The custom registration path uses Django's user manager safely.

    This test protects the corresponding regression contract.

    Args:
        safe_contract: The isolated executable quickstart contract.
    """
    result = graphql_sync(
        safe_contract.schema.graphql_schema,
        'mutation { registerUser(username: "ada", password: "s3cret!") '
        "{ ok user { id username firstName lastName } } }",
    )
    assert result.errors is None, result.errors
    user = User.objects.get(username="ada")
    assert user.check_password("s3cret!") is True
    assert user.is_staff is False
    assert user.is_superuser is False


def test_anonymous_request_is_rejected_before_execution(
    safe_contract: SimpleNamespace,
) -> None:
    """The documented endpoint must use the authenticated view.

    This test protects the corresponding regression contract.

    Args:
        safe_contract: The isolated executable quickstart contract.
    """
    request = RequestFactory().post(
        "/graphql/",
        {"query": "{ users { totalCount } }"},
        content_type="application/json",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    response = AuthenticatedGraphQLView.as_view(schema=safe_contract.schema)(request)
    assert response.status_code == 403
    assert "errors" in json.loads(response.content)
