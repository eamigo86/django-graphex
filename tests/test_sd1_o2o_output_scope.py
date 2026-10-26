"""Verify automatic OneToOne outputs honor destination row scopes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection, models
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync, is_non_null_type

from django_graphex.core import Field, ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_pair
from tests.test_sd2_forward_o2o_filter_scope import (
    ProbeProfile,
    ProbeUser,
    _schema,
    _scope,
)
from tests.test_sd2_forward_o2o_filter_scope import (
    rows as rows,
)


class DefaultOwner(models.Model):
    """Own a reverse OneToOne relation with Django's default accessor.

    The public output field is derived rather than declared by the test type.
    """

    name = models.CharField(max_length=40)

    class Meta:
        """Bind the witness table to the disposable tests application.

        The table name avoids collisions with other relation probes.
        """

        app_label = "tests"
        db_table = "sd1_o2o_default_owner"


class DefaultBadge(models.Model):
    """Provide a scoped default-accessor destination.

    The hidden row must resolve as null on its otherwise visible owner.
    """

    owner = models.OneToOneField(DefaultOwner, on_delete=models.CASCADE)
    label = models.CharField(max_length=40)
    visible = models.BooleanField(default=True)

    class Meta:
        """Bind the witness table to the disposable tests application.

        It is created only inside the project's test database.
        """

        app_label = "tests"
        db_table = "sd1_o2o_default_badge"


def _read(
    schema: Any, field: str, token: str, allow_hidden: bool
) -> tuple[dict, list, int]:
    """Run a public list query and return its rows with hook observations.

    Args:
        schema: Independently compiled public schema.
        field: Root list field name.
        token: Identity of the current request.
        allow_hidden: Whether this request permits hidden destinations.

    Returns:
        The returned rows, hook observations and executed SQL count.
    """
    selection = (
        "label user { name }" if field == "profiles" else "name profile { label }"
    )
    query = "{ " + field + " { results { " + selection + " } } }"
    context = SimpleNamespace(token=token, allow_hidden=allow_hidden, calls=[])
    with CaptureQueriesContext(connection) as queries:
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert all(
        call["request"] == token and call["alias"] == "default"
        for call in context.calls
    )
    key = "label" if field == "profiles" else "name"
    returned = {item[key]: item for item in result.data[field]["results"]}
    return returned, context.calls, len(queries)


@pytest.mark.parametrize("optimize", [True, False])
def test_automatic_o2o_outputs_hide_only_destinations(
    rows: dict[str, Any], optimize: bool
) -> None:
    """Keep visible parents while replacing hidden to-one children with null.

    Args:
        rows: Disposable public OneToOne model fixture.
        optimize: Whether queryset optimization is enabled.
    """
    scoped = _schema(True)
    plain = _schema(False)
    for schema in (scoped, plain):
        for name, relation in (("O2OProfileType", "user"), ("O2OUserType", "profile")):
            assert not is_non_null_type(
                schema.graphql_schema.get_type(name).fields[relation].type
            )

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        for schema, label, allowed in (
            (plain, "plain", False),
            (scoped, "restricted", False),
            (scoped, "permitted", True),
            (scoped, "restricted-again", False),
        ):
            profiles, profile_calls, profile_queries = _read(
                schema, "profiles", f"{optimize}-{label}-profiles", allowed
            )
            users, user_calls, user_queries = _read(
                schema, "users", f"{optimize}-{label}-users", allowed
            )
            assert profiles["visible-profile"]["user"] == {"name": "visible-user"}
            assert users["visible-user"]["profile"] == {"label": "visible-profile"}
            assert profiles["orphan-profile"]["user"] is None
            assert users["no-profile"]["profile"] is None
            expected_hidden = schema is plain or allowed
            assert profiles["public-profile-hidden-user"]["user"] == (
                {"name": "hidden-user"} if expected_hidden else None
            )
            assert users["public-user-hidden-profile"]["profile"] == (
                {"label": "hidden-profile"} if expected_hidden else None
            )
            assert ("hidden-profile" in profiles) is expected_hidden
            assert ("hidden-user" in users) is expected_hidden
            assert [call["model"] for call in profile_calls] == (
                [] if schema is plain else ["ProbeProfile", "ProbeUser"]
            )
            assert [call["model"] for call in user_calls] == (
                [] if schema is plain else ["ProbeUser", "ProbeProfile"]
            )
            if schema is scoped:
                assert profile_queries <= 4
                assert user_queries <= 4


@pytest.mark.parametrize("optimize", [True, False])
def test_reverse_o2o_destination_scope_reaches_hidden_child_assertion(
    rows: dict[str, Any], optimize: bool
) -> None:
    """Hide a reverse child without selecting the forward output path.

    Args:
        rows: Disposable public OneToOne model fixture.
        optimize: Whether queryset optimization is enabled.
    """
    schema = _schema(True)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        users, calls, queries = _read(
            schema, "users", f"reverse-only-{optimize}", False
        )
    assert users["visible-user"]["profile"] == {"label": "visible-profile"}
    assert users["no-profile"]["profile"] is None
    assert users["public-user-hidden-profile"]["profile"] is None
    assert "hidden-user" not in users
    assert [call["model"] for call in calls] == ["ProbeUser", "ProbeProfile"]
    assert queries <= 4


@pytest.mark.parametrize("optimize", [True, False])
def test_cached_o2o_values_are_not_visibility_evidence(
    rows: dict[str, Any], optimize: bool
) -> None:
    """Check automatic child resolvers even when a root preloads the relation.

    Args:
        rows: Disposable public OneToOne model fixture.
        optimize: Whether queryset optimization is enabled.
    """
    local_registry = Registry()

    class UserType(DjangoObjectType):
        """Expose the request-scoped user and its automatic reverse profile."""

        class Meta:
            """Bind the user to this isolated public registry."""

            model = ProbeUser
            registry = local_registry
            only_fields = ("id", "name", "profile")

        @classmethod
        def get_queryset(cls, queryset: Any, info: Any) -> Any:
            """Apply the request's user visibility.

            Args:
                queryset: Candidate user rows.
                info: Current GraphQL request.

            Returns:
                Visible user rows.
            """
            return _scope(queryset, info)

    class ProfileType(DjangoObjectType):
        """Expose the request-scoped profile and its automatic forward user."""

        class Meta:
            """Bind the profile to this isolated public registry."""

            model = ProbeProfile
            registry = local_registry
            only_fields = ("id", "label", "user")

        @classmethod
        def get_queryset(cls, queryset: Any, info: Any) -> Any:
            """Apply the request's profile visibility.

            Args:
                queryset: Candidate profile rows.
                info: Current GraphQL request.

            Returns:
                Visible profile rows.
            """
            return _scope(queryset, info)

    class Query(ObjectType):
        """Return cached roots while retaining automatic nested relations."""

        profile = Field(ProfileType)
        user = Field(UserType)

        def resolve_profile(self, info: Any) -> ProbeProfile:
            """Return a profile with its forward relation already selected.

            Args:
                info: Current GraphQL request.

            Returns:
                The visible parent profile with a cached hidden user.
            """
            return ProbeProfile.objects.select_related("user").get(
                label="public-profile-hidden-user"
            )

        def resolve_user(self, info: Any) -> ProbeUser:
            """Return a user with its reverse relation already selected.

            Args:
                info: Current GraphQL request.

            Returns:
                The visible parent user with a cached hidden profile.
            """
            return ProbeUser.objects.select_related("profile").get(
                name="public-user-hidden-profile"
            )

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    context = SimpleNamespace(token="cached", allow_hidden=False, calls=[])
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(
            schema.graphql_schema,
            "{ profile { label user { name } } user { name profile { label } } }",
            context_value=context,
        )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data == {
        "profile": {"label": "public-profile-hidden-user", "user": None},
        "user": {"name": "public-user-hidden-profile", "profile": None},
    }
    assert sorted(call["model"] for call in context.calls) == [
        "ProbeProfile",
        "ProbeUser",
    ]


def test_nested_o2o_outputs_scope_each_hop(rows: dict[str, Any]) -> None:
    """Apply each automatic destination hook in a reverse-to-forward chain.

    Args:
        rows: Disposable public OneToOne model fixture.
    """
    schema = _schema(True)
    context = SimpleNamespace(token="chain", allow_hidden=False, calls=[])
    result = graphql_sync(
        schema.graphql_schema,
        "{ users { results { name profile { label user { name } } } } }",
        context_value=context,
    )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    users = {item["name"]: item["profile"] for item in result.data["users"]["results"]}
    assert users["visible-user"] == {
        "label": "visible-profile",
        "user": {"name": "visible-user"},
    }
    assert users["public-user-hidden-profile"] is None
    assert users["no-profile"] is None
    assert "hidden-user" not in users
    assert [call["model"] for call in context.calls].count("ProbeProfile") >= 1


@pytest.mark.parametrize("failure", ["fail_scope", "wrong_alias"])
def test_o2o_output_hook_failure_does_not_serve_hidden_child(
    rows: dict[str, Any], failure: str
) -> None:
    """Reject a failing or cross-database destination hook without fallback.

    Args:
        rows: Disposable public OneToOne model fixture.
        failure: Hook failure mode to activate.
    """
    schema = _schema(True)
    context = SimpleNamespace(token="failure", allow_hidden=False, calls=[])
    setattr(context, failure, True)
    result = graphql_sync(
        schema.graphql_schema,
        "{ profiles { results { label user { name } } } }",
        context_value=context,
    )
    assert result.errors
    assert "hidden-user" not in str(result.data)


@pytest.mark.django_db
@pytest.mark.parametrize("optimize", [True, False])
def test_default_reverse_o2o_accessor_uses_destination_scope(optimize: bool) -> None:
    """Resolve the actual default accessor instead of the ORM query name.

    Args:
        optimize: Whether queryset optimization is enabled.
    """
    hidden = DefaultOwner.objects.create(name="hidden-badge-owner")
    visible = DefaultOwner.objects.create(name="visible-badge-owner")
    DefaultOwner.objects.create(name="without-badge")
    DefaultBadge.objects.create(owner=hidden, label="private", visible=False)
    DefaultBadge.objects.create(owner=visible, label="public")
    local_registry = Registry()

    class BadgeType(DjangoObjectType):
        """Publish only badges visible to the current request."""

        class Meta:
            """Register the default-accessor destination type."""

            model = DefaultBadge
            registry = local_registry
            only_fields = ("id", "label")

        @classmethod
        def get_queryset(cls, queryset: Any, info: Any) -> Any:
            """Hide private badges.

            Args:
                queryset: Candidate badge rows.
                info: Current GraphQL request.

            Returns:
                Only public badge rows.
            """
            info.context.calls.append(queryset.db)
            return queryset.filter(visible=True)

    class OwnerType(DjangoObjectType):
        """Publish the automatic default reverse OneToOne field."""

        class Meta:
            """Register the owner and its default reverse accessor."""

            model = DefaultOwner
            registry = local_registry
            only_fields = ("id", "name", "defaultbadge")

    class Query(ObjectType):
        """Expose the ordinary public owner list."""

        owners = DjangoFilterListField(OwnerType)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    assert "defaultbadge" in schema.graphql_schema.get_type("OwnerType").fields
    context = SimpleNamespace(calls=[])
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(
            schema.graphql_schema,
            "{ owners { name defaultbadge { label } } }",
            context_value=context,
        )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    owners = {item["name"]: item["defaultbadge"] for item in result.data["owners"]}
    assert owners == {
        "hidden-badge-owner": None,
        "visible-badge-owner": {"label": "public"},
        "without-badge": None,
    }
    assert context.calls == ["default"]


def test_explicit_relation_resolver_is_not_reclassified_as_automatic(
    rows: dict[str, Any],
) -> None:
    """Leave an intentionally declared relation resolver under its own policy.

    Args:
        rows: Disposable public OneToOne model fixture.
    """
    local_registry = Registry()

    class UserType(DjangoObjectType):
        """Provide the declared relation's GraphQL destination type."""

        class Meta:
            """Bind the user type to the isolated hatch registry."""

            model = ProbeUser
            registry = local_registry
            only_fields = ("id", "name")

        @classmethod
        def get_queryset(cls, queryset: Any, info: Any) -> Any:
            """Apply a scope to ordinary automatic user reads.

            Args:
                queryset: Candidate user rows.
                info: Current GraphQL request.

            Returns:
                Visible user rows.
            """
            return queryset.filter(visible=True)

    class ProfileType(DjangoObjectType):
        """Deliberately replace the automatic user relation."""

        user = Field(UserType)

        class Meta:
            """Bind the declared relation to the public profile."""

            model = ProbeProfile
            registry = local_registry
            only_fields = ("id", "label", "user")

        def resolve_user(self, info: Any) -> ProbeUser | None:
            """Return the explicitly managed relation without automatic scope.

            Args:
                info: Current GraphQL request.

            Returns:
                The linked user or None for an orphan profile.
            """
            return self.user

    class Query(ObjectType):
        """Expose the declared-hatch profile list."""

        profiles = DjangoFilterListField(ProfileType)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    result = graphql_sync(
        schema.graphql_schema,
        "{ profiles { label user { name } } }",
    )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    profiles = {item["label"]: item["user"] for item in result.data["profiles"]}
    assert profiles["public-profile-hidden-user"] == {"name": "hidden-user"}
