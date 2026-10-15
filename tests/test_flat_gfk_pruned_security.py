"""Permission-pruned flat GenericForeignKey target and cache boundaries."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache as django_cache
from django.db import connection
from django.db.models import QuerySet
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_schema,
)

from django_graphex.core import ObjectType, field
from django_graphex.core import permission_signature_cache as psc
from django_graphex.core.permission_signature_cache import _SignatureSchemaCache
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.views import AuthenticatedGraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Track2Account, Track2GfkComment, Track2Invoice, Track2Order

_SOURCE = "tests.view_track2gfkcomment"
_TARGET = "tests.view_track2account"
_QUERY = "{ comment { body target { appLabel modelName id } } }"


class _User:
    """Supply stable permission grants to the schema-cache contract."""

    is_active = True
    is_superuser = False

    def __init__(self, grants: frozenset[str]) -> None:
        """Store this request's grants.

        Args:
            grants: Django permission codenames held by this user.
        """
        self.grants = grants

    def get_all_permissions(self) -> frozenset[str]:
        """Return the user's current permission codenames.

        Returns:
            This user's permission grants.
        """
        return self.grants


def _schema(
    comment: Track2GfkComment, *, register_target: bool, scope: str = "default"
) -> GraphQLSchema:
    """Build a private schema with a flat GFK and optional public target type.

    Args:
        comment: Owner row returned by the query root.
        register_target: Whether the target model has a public output type.
        scope: Default, visible, or hidden target hook behavior.

    Returns:
        The executable full schema.
    """
    reg = Registry()

    if register_target and scope == "inherit":

        class TargetType(DjangoObjectType):
            """Public target with the inherited no-op row hook."""

            class Meta:
                """Bind the target to this schema's registry."""

                model = Track2Account
                registry = reg

    elif register_target:

        class TargetType(DjangoObjectType):
            """Optional public type for the GFK target."""

            class Meta:
                """Bind the target to this schema's registry."""

                model = Track2Account
                registry = reg

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Apply the requested target row scope.

                Args:
                    queryset: Unscoped target rows.
                    info: Request resolve info carrying allowed target IDs.

                Returns:
                    The scoped rows for this request.
                """
                if scope == "default":
                    return queryset
                if scope == "hidden":
                    return queryset.none()
                if scope == "wrong_model":
                    return Track2Invoice.objects.all()
                if scope == "not_queryset":
                    return []  # type: ignore[return-value]
                if scope == "duplicate":
                    return queryset.filter(orders__total__gte=0)
                if scope == "slice":
                    return queryset.order_by("pk")[:1]
                return queryset.filter(pk__in=info.context.allowed_ids)

    class CommentType(DjangoObjectType):
        """Owner type exposing its default flat GFK field."""

        class Meta:
            """Bind the owner to this schema's registry."""

            model = Track2GfkComment
            registry = reg
            only_fields = ("id", "body", "target")

    class Query(ObjectType):
        """Expose the owner without publishing the target root."""

        comment = field(
            CommentType,
            required_perms=(_SOURCE,),
            resolver=lambda root, info: comment,
        )

    return DjangoGraphQLSchema(
        query=Query, registries=isolated_pair(reg)
    ).graphql_schema


def _data(
    schema: GraphQLSchema, *, allowed_ids: tuple[int, ...] = ()
) -> dict[str, Any]:
    """Execute the same public GraphQL selection against a schema variant.

    Args:
        schema: Full or permission-pruned executable schema.
        allowed_ids: Rows admitted by an optional target scope hook.

    Returns:
        The response data after asserting no GraphQL errors.
    """
    result = graphql_sync(
        schema,
        _QUERY,
        context_value=SimpleNamespace(
            allowed_ids=allowed_ids, user=_User(frozenset({_SOURCE, _TARGET}))
        ),
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    return result.data


@pytest.fixture
def owner() -> Track2GfkComment:
    """Persist an owner and target so the GFK resolves through the ORM.

    Returns:
        A saved owner referencing a saved target.
    """
    target = Track2Account.objects.create(balance=10, label="private")
    return Track2GfkComment.objects.create(body="public", target=target)


@pytest.mark.django_db
def test_flat_target_denied_by_actual_model_permission(owner: Track2GfkComment) -> None:
    """A source-only clone must null the whole target without changing SDL.

    Args:
        owner: Persisted GFK owner and target.
    """
    full = _schema(owner, register_target=False)
    denied = prune_schema(full, frozenset({_SOURCE}))
    allowed = prune_schema(full, frozenset({_SOURCE, _TARGET}))
    assert print_schema(denied) == print_schema(allowed)
    assert _data(denied) == {"comment": {"body": "public", "target": None}}
    assert _data(allowed)["comment"]["target"]["id"] == str(owner.target_id)
    assert _data(full)["comment"]["target"]["id"] == str(owner.target_id)


@pytest.mark.django_db
def test_missing_flat_target_stays_null(owner: Track2GfkComment) -> None:
    """A stale GFK reference remains null even with target read permission.

    Args:
        owner: Persisted GFK owner and target.
    """
    Track2Account.objects.filter(pk=owner.target_id).delete()
    reloaded = Track2GfkComment.objects.get(pk=owner.pk)
    pruned = prune_schema(
        _schema(reloaded, register_target=False), frozenset({_SOURCE, _TARGET})
    )
    assert _data(pruned)["comment"]["target"] is None


@pytest.mark.django_db
def test_flat_target_uses_registered_scope_per_request(owner: Track2GfkComment) -> None:
    """A target hook denies hidden rows and admits visible rows afresh.

    Args:
        owner: Persisted GFK owner and target.
    """
    full = _schema(owner, register_target=True, scope="visible")
    cache = _SignatureSchemaCache(maxsize=2)
    user = _User(frozenset({_SOURCE, _TARGET}))
    pruned = cache.pruned_schema_for(user, full)
    assert cache.pruned_schema_for(user, full) is pruned
    assert _data(pruned)["comment"]["target"] is None
    assert _data(pruned, allowed_ids=(owner.target_id,))["comment"]["target"][
        "id"
    ] == str(owner.target_id)


@pytest.mark.django_db
def test_registered_default_hook_adds_no_membership_query(
    owner: Track2GfkComment,
) -> None:
    """The inherited row hook requires no second lookup after GFK resolution.

    Args:
        owner: Persisted GFK owner and target.
    """
    full = _schema(owner, register_target=True, scope="inherit")
    pruned = prune_schema(full, frozenset({_SOURCE, _TARGET}))
    with CaptureQueriesContext(connection) as queries:
        assert _data(pruned)["comment"]["target"]["id"] == str(owner.target_id)
    assert len(queries) == 0


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ("not_queryset", "wrong_model"))
def test_invalid_registered_scope_fails_closed(
    owner: Track2GfkComment, scope: str
) -> None:
    """An invalid row hook cannot return flat target metadata.

    Args:
        owner: Persisted GFK owner and target.
        scope: Invalid hook result to exercise.
    """
    pruned = prune_schema(
        _schema(owner, register_target=True, scope=scope),
        frozenset({_SOURCE, _TARGET}),
    )
    result = graphql_sync(pruned, _QUERY)
    assert result.data == {"comment": {"body": "public", "target": None}}
    assert result.errors and "get_queryset" in result.errors[0].message


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ("duplicate", "slice"))
def test_registered_scope_preserves_join_and_slice_membership(
    owner: Track2GfkComment, scope: str
) -> None:
    """Membership accepts duplicate JOIN rows and an in-window slice.

    Args:
        owner: Persisted GFK owner and target.
        scope: Duplicate-JOIN or sliced queryset hook behavior.
    """
    if scope == "duplicate":
        for total in (1, 2):
            Track2Order.objects.create(customer=owner.target, total=total)
    pruned = prune_schema(
        _schema(owner, register_target=True, scope=scope),
        frozenset({_SOURCE, _TARGET}),
    )
    assert _data(pruned)["comment"]["target"]["id"] == str(owner.target_id)
    if scope == "slice":
        earlier = Track2Account.objects.create(balance=0, label="earlier")
        assert earlier.pk > owner.target_id
        late = Track2Account.objects.create(balance=0, label="late")
        other = Track2GfkComment.objects.create(body="other", target=late)
        excluded = prune_schema(
            _schema(other, register_target=True, scope=scope),
            frozenset({_SOURCE, _TARGET}),
        )
        assert _data(excluded)["comment"]["target"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("grant_first", (False, True))
def test_flat_cache_keys_unregistered_target_grants(
    owner: Track2GfkComment, grant_first: bool
) -> None:
    """Irrelevant-to-SDL target grants must still separate flat-GFK variants.

    Args:
        owner: Persisted owner and target.
        grant_first: Whether the permitted caller populates the cache first.
    """
    full = _schema(owner, register_target=False)
    cache = _SignatureSchemaCache(maxsize=4)
    order = (True, False) if grant_first else (False, True)
    variants = [
        cache.pruned_schema_for(
            _User(
                frozenset({_SOURCE, _TARGET}) if has_target else frozenset({_SOURCE})
            ),
            full,
        )
        for has_target in order
    ]
    assert variants[0] is not variants[1]
    for has_target, variant in zip(order, variants, strict=True):
        assert (_data(variant)["comment"]["target"] is not None) is has_target


@pytest.mark.django_db
def test_explicit_prune_grants_never_widen_from_context_or_reprune(
    owner: Track2GfkComment,
) -> None:
    """Only explicit grants, never a privileged context, authorize metadata.

    Args:
        owner: Persisted GFK owner and target.
    """
    full = _schema(owner, register_target=False)
    first = prune_schema(full, frozenset({_SOURCE}))
    second = prune_schema(first, frozenset({_SOURCE, _TARGET}))
    assert _data(first)["comment"]["target"] is None
    assert _data(second)["comment"]["target"] is None
    assert (
        _data(prune_schema(full, frozenset({_SOURCE, _TARGET})))["comment"]["target"]
        is not None
    )
    assert "gdx_effective_grants" not in (full.extensions or {})
    assert (
        prune_schema(full, frozenset()).extensions["gdx_effective_grants"]
        == frozenset()
    )


def test_unmarked_schema_keeps_projected_signature() -> None:
    """A same-name custom GraphQL type does not trigger all-grant keys.

    Its type name alone is not the native fallback marker.
    """
    flat_named_custom = GraphQLObjectType(
        "GenericForeignKeyType", {"id": GraphQLField(GraphQLString)}
    )
    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"target": GraphQLField(flat_named_custom)}),
        extensions={"gdx_label_set": frozenset({"app.view_source"})},
    )
    cache = _SignatureSchemaCache(maxsize=2)
    first = cache.pruned_schema_for(_User(frozenset({"app.view_source"})), schema)
    second = cache.pruned_schema_for(
        _User(frozenset({"app.view_source", "other.view_target"})), schema
    )
    assert second is first
    assert second.extensions["gdx_effective_grants"] == frozenset({"app.view_source"})


@pytest.mark.django_db
@override_settings(
    DJANGO_GRAPHEX={
        "PERMISSION_SCOPED_SCHEMA": True,
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "CLEAN_RESPONSE": False,
    }
)
def test_http_cache_rechecks_same_users_target_grant(
    owner: Track2GfkComment,
) -> None:
    """Grant and revoke target permission without reusing stale HTTP data.

    Args:
        owner: Persisted GFK owner and target.
    """
    django_cache.clear()
    psc._CACHE.clear()
    try:
        full = _schema(owner, register_target=False)
        view = AuthenticatedGraphQLView.as_view(
            schema=SimpleNamespace(graphql_schema=full)
        )
        user = User.objects.create_user(username="sd5-reader", password="unused")
        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Track2GfkComment),
                codename="view_track2gfkcomment",
            )
        )

        def request() -> Any:
            """Build a new POST carrying the same principal and query.

            Returns:
                A fresh HTTP request for the same cache identity.
            """
            call = RequestFactory().post(
                "/graphql/",
                {"query": _QUERY},
                content_type="application/json",
            )
            call.user = User.objects.get(pk=user.pk)
            return call

        first = view(request())
        assert first.status_code == 200
        assert json.loads(first.content)["data"]["comment"]["target"] is None

        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Track2Account),
                codename="view_track2account",
            )
        )
        second = view(request())
        assert second.status_code == 200
        assert json.loads(second.content)["data"]["comment"]["target"]["id"] == str(
            owner.target_id
        )

        user.user_permissions.remove(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Track2Account),
                codename="view_track2account",
            )
        )
        third = view(request())
        assert third.status_code == 200
        assert json.loads(third.content)["data"]["comment"]["target"] is None
    finally:
        psc._CACHE.clear()
        django_cache.clear()
