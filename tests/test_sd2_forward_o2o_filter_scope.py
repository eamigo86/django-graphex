"""Verify public forward OneToOne destination-field filter scoping."""

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import models
from graphql import get_named_type, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from tests._schema_isolation import isolated_pair


class ProbeUser(models.Model):
    """Represent a user whose visibility is controlled by the request.

    The user can be present in the database but hidden from a filter branch.
    """

    name = models.CharField(max_length=60)
    visible = models.BooleanField(default=True)

    class Meta:
        """Keep this model in the disposable test database.

        The table is unique to the forward OneToOne filter witness.
        """

        app_label = "tests"
        db_table = "independent_o2o_user"


class ProbeProfile(models.Model):
    """Publish a nullable forward relation and its real reverse accessor.

    A missing user remains distinct from a hidden linked user.
    """

    label = models.CharField(max_length=60)
    visible = models.BooleanField(default=True)
    user = models.OneToOneField(
        ProbeUser, null=True, on_delete=models.CASCADE, related_name="profile"
    )

    class Meta:
        """Keep this model in the disposable test database.

        This table supports both forward and reverse traversal controls.
        """

        app_label = "tests"
        db_table = "independent_o2o_profile"


def _scope(queryset: Any, info: Any) -> Any:
    """Record request identity and return a lazy destination policy.

    Args:
        queryset: Rows offered by the public resolver or filter compiler.
        info: Active GraphQL request.

    Returns:
        The request's visible row universe.
    """
    info.context.calls.append(
        {
            "model": queryset.model.__name__,
            "alias": queryset.db,
            "request": info.context.token,
            "allow_hidden": info.context.allow_hidden,
        }
    )
    if queryset.model is ProbeUser and getattr(info.context, "fail_scope", False):
        raise RuntimeError("destination scope failed")
    if queryset.model is ProbeUser and getattr(info.context, "wrong_alias", False):
        return queryset.using("unconfigured")
    return queryset if info.context.allow_hidden else queryset.filter(visible=True)


def _schema(
    scoped: bool, direct: bool = False, chain: bool = False
) -> DjangoGraphQLSchema:
    """Compile real public OneToOne output and input projections.

    Args:
        scoped: Whether both object types declare the visibility hook.
        direct: Whether the forward input uses source-column IDs instead.
        chain: Whether to publish the reverse-to-forward nested filter.

    Returns:
        A compiled schema with its own registry.
    """
    local_registry = Registry()

    class O2OUserType(DjangoObjectType):
        """Publish a user and its automatic reverse profile."""

        class Meta:
            """Bind the public user projection."""

            model = ProbeUser
            registry = local_registry
            only_fields = ("id", "name", "profile")

        if scoped:

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Apply this request's user policy.

                Args:
                    queryset: Candidate user rows.
                    info: Active GraphQL request.

                Returns:
                    The lazy user scope.
                """
                return _scope(queryset, info)

    class O2OProfileType(DjangoObjectType):
        """Publish a profile and its automatic forward user."""

        class Meta:
            """Bind the public profile projection."""

            model = ProbeProfile
            registry = local_registry
            only_fields = ("id", "label", "user")

        if scoped:

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Apply this request's profile policy.

                Args:
                    queryset: Candidate profile rows.
                    info: Active GraphQL request.

                Returns:
                    The lazy profile scope.
                """
                return _scope(queryset, info)

    class O2OUserList(DjangoListObjectType):
        """Expose a nested reverse profile predicate."""

        class Meta:
            """Declare only the bounded public filter paths."""

            model = ProbeUser
            registry = local_registry
            filter_fields = {
                "name": ("exact",),
                "profile__label": ("exact",),
                **({"profile__user__name": ("exact",)} if chain else {}),
            }

    class O2OProfileList(DjangoListObjectType):
        """Expose a nested forward user or direct source-column predicate."""

        class Meta:
            """Keep direct IDs distinct from destination-field traversal."""

            model = ProbeProfile
            registry = local_registry
            filter_fields = {
                "label": ("exact",),
                ("user" if direct else "user__name"): ("exact", "in"),
            }

    class Query(ObjectType):
        """Serve both sides through the normal public list resolver."""

        users = DjangoListObjectField(O2OUserList)
        profiles = DjangoListObjectField(O2OProfileList)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    compiled = schema.graphql_schema
    assert "profile" in compiled.get_type("O2OUserType").fields
    assert "user" in compiled.get_type("O2OProfileType").fields
    for field, relation in (("users", "profile"), ("profiles", "user")):
        filter_type = get_named_type(
            compiled.query_type.fields[field].args["filter"].type
        )
        assert relation in filter_type.fields
        if not (direct and field == "profiles"):
            child = get_named_type(filter_type.fields[relation].type)
            assert ("label" if field == "users" else "name") in child.fields
    return schema


def _query(
    schema: DjangoGraphQLSchema,
    field: str,
    predicate: str,
    token: str,
    allow_hidden: bool = False,
) -> tuple[list[str], list[dict]]:
    """Capture exact public data and request-scoped hook calls.

    Args:
        schema: Actual compiled schema under investigation.
        field: Public list field.
        predicate: Fixed filter literal.
        token: Unique request identity.
        allow_hidden: Whether this request can see all destination rows.

    Returns:
        Sorted result labels and recorded hook invocations.
    """
    selected = "name" if field == "users" else "label"
    query = (
        "{ "
        + field
        + "(filter: "
        + predicate
        + ") { results { "
        + selected
        + " } totalCount } }"
    )
    context = SimpleNamespace(token=token, allow_hidden=allow_hidden, calls=[])
    result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, str(result.errors)
    assert all(
        call["request"] == token and call["alias"] == "default"
        for call in context.calls
    )
    assert result.data[field]["totalCount"] == len(result.data[field]["results"])
    return sorted(row[selected] for row in result.data[field]["results"]), context.calls


@pytest.fixture
def rows(db: None) -> dict[str, Any]:
    """Create visible, hidden and absent OneToOne destinations.

    Args:
        db: Disposable test database fixture.

    Returns:
        Named objects needed for the direct-ID control.
    """
    visible = ProbeUser.objects.create(name="visible-user")
    hidden = ProbeUser.objects.create(name="hidden-user", visible=False)
    public = ProbeUser.objects.create(name="public-user-hidden-profile")
    ProbeUser.objects.create(name="no-profile")
    ProbeProfile.objects.create(label="visible-profile", user=visible)
    ProbeProfile.objects.create(label="public-profile-hidden-user", user=hidden)
    ProbeProfile.objects.create(label="hidden-profile", user=public, visible=False)
    ProbeProfile.objects.create(label="orphan-profile")
    return {"hidden_user": hidden}


def test_forward_and_reverse_destination_policies(rows: dict[str, Any]) -> None:
    """Scope forward traversal while retaining existing reverse behavior.

    Args:
        rows: Disposable model rows.
    """
    scoped = _schema(True)
    plain = _schema(False)
    forward = '{ user: { name: { exact: "hidden-user" } } }'
    reverse = '{ profile: { label: { exact: "hidden-profile" } } }'
    for schema, label in ((plain, "plain"), (scoped, "scoped")):
        found, calls = _query(schema, "profiles", forward, label + "-forward")
        assert found == (["public-profile-hidden-user"] if schema is plain else [])
        assert [call["model"] for call in calls] == (
            [] if schema is plain else ["ProbeProfile", "ProbeUser"]
        )
        found, calls = _query(schema, "users", reverse, label + "-reverse")
        assert found == (["public-user-hidden-profile"] if schema is plain else [])
        assert [call["model"] for call in calls] == (
            [] if schema is plain else ["ProbeUser", "ProbeProfile"]
        )
    found, calls = _query(
        scoped,
        "profiles",
        '{ user: { name: { exact: "visible-user" } } }',
        "positive-forward",
    )
    assert found == ["visible-profile"]
    assert [call["model"] for call in calls] == ["ProbeProfile", "ProbeUser"]
    found, calls = _query(
        scoped,
        "users",
        '{ profile: { label: { exact: "visible-profile" } } }',
        "positive-reverse",
    )
    assert found == ["visible-user"]
    assert [call["model"] for call in calls] == ["ProbeUser", "ProbeProfile"]
    for allowed, label in ((True, "privileged"), (False, "restricted-again")):
        found, calls = _query(scoped, "users", reverse, label, allowed)
        assert found == (["public-user-hidden-profile"] if allowed else [])
        assert [call["model"] for call in calls] == ["ProbeUser", "ProbeProfile"]
        found, calls = _query(scoped, "profiles", forward, label + "-forward", allowed)
        assert found == (["public-profile-hidden-user"] if allowed else [])
        assert [call["model"] for call in calls] == ["ProbeProfile", "ProbeUser"]


def test_null_and_direct_id_controls(rows: dict[str, Any]) -> None:
    """Separate real source NULL and direct IDs from nested visibility.

    Args:
        rows: Disposable model rows.
    """
    scoped = _schema(True)
    plain = _schema(False)
    for schema, label in ((plain, "plain"), (scoped, "scoped")):
        found, _ = _query(
            schema,
            "profiles",
            "{ user: { name: { exact: null } } }",
            label + "-forward-null",
        )
        assert found == ["orphan-profile"]
        found, _ = _query(
            schema,
            "users",
            "{ profile: { label: { exact: null } } }",
            label + "-reverse-null",
        )
        assert found == (
            ["no-profile"]
            if schema is plain
            else ["no-profile", "public-user-hidden-profile"]
        )
    direct = _schema(True, direct=True)
    for operation, value in (
        ("exact", str(rows["hidden_user"].pk)),
        ("in", "[" + str(rows["hidden_user"].pk) + "]"),
    ):
        found, calls = _query(
            direct,
            "profiles",
            "{ user: { " + operation + ": " + value + " } }",
            "direct-id-" + operation,
        )
        assert found == ["public-profile-hidden-user"]
        assert [call["model"] for call in calls] == ["ProbeProfile"]
    found, calls = _query(
        direct, "profiles", "{ user: { exact: null } }", "direct-null"
    )
    assert found == ["orphan-profile"]
    assert [call["model"] for call in calls] == ["ProbeProfile"]


def test_boolean_and_empty_forward_nodes_keep_visible_sources(
    rows: dict[str, Any],
) -> None:
    """A scoped branch does not globally prune unrelated source rows.

    Args:
        rows: Disposable database witnesses.
    """
    schema = _schema(True)
    hidden = '{ user: { name: { exact: "hidden-user" } } }'
    all_labels = ["orphan-profile", "public-profile-hidden-user", "visible-profile"]
    for node in ("{}", "{ user: {} }", "{ user: { or: [] } }", "{ user: { not: {} } }"):
        found, _ = _query(schema, "profiles", node, "empty-forward")
        assert found == all_labels
    found, _ = _query(schema, "profiles", "{ not: " + hidden + " }", "not-hidden")
    assert found == all_labels
    found, _ = _query(
        schema,
        "profiles",
        "{ or: [" + hidden + ', { label: { exact: "orphan-profile" } }] }',
        "or-hidden",
    )
    assert found == ["orphan-profile"]
    found, _ = _query(
        schema,
        "profiles",
        "{ and: [" + hidden + ', { label: { exact: "public-profile-hidden-user" } }] }',
        "and-hidden",
    )
    assert found == []
    found, _ = _query(
        schema,
        "profiles",
        "{ user: { name: { exact: null } } }",
        "real-null",
    )
    assert found == ["orphan-profile"]


def test_reverse_then_forward_one_to_one_scopes_each_destination(
    rows: dict[str, Any],
) -> None:
    """Nested reverse and forward hops retain their respective row scopes.

    Args:
        rows: Disposable database witnesses.
    """
    schema = _schema(True, chain=True)
    found, calls = _query(
        schema,
        "users",
        '{ profile: { user: { name: { exact: "visible-user" } } } }',
        "visible-chain",
    )
    assert found == ["visible-user"]
    assert sorted(call["model"] for call in calls) == [
        "ProbeProfile",
        "ProbeUser",
        "ProbeUser",
    ]
    found, _ = _query(
        schema,
        "users",
        '{ profile: { user: { name: { exact: "public-user-hidden-profile" } } } }',
        "hidden-middle",
    )
    assert found == []


@pytest.mark.parametrize("failure", ["fail_scope", "wrong_alias"])
def test_forward_scope_errors_fail_closed(rows: dict[str, Any], failure: str) -> None:
    """A failing or cross-database destination policy cannot retry unscoped.

    Args:
        rows: Disposable database witnesses.
        failure: Destination policy failure mode.
    """
    schema = _schema(True)
    context = SimpleNamespace(
        token=failure,
        allow_hidden=False,
        calls=[],
        fail_scope=failure == "fail_scope",
        wrong_alias=failure == "wrong_alias",
    )
    result = graphql_sync(
        schema.graphql_schema,
        '{ profiles(filter: { user: { name: { exact: "hidden-user" } } }) '
        "{ results { label } totalCount } }",
        context_value=context,
    )
    assert result.errors
    assert result.data == {"profiles": None}
    assert [call["model"] for call in context.calls] == ["ProbeProfile", "ProbeUser"]
