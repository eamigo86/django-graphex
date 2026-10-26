"""Public regressions for automatic M2M output visibility and counts."""

import json
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection, connections
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from graphql import get_named_type, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from tests._schema_isolation import isolated_pair
from tests.test_and_many_filtering import AndManyPost, AndManyTag
from tests.test_sd2_m2m_filter_scope import (
    THROUGH_SCHEMA,
    ThroughLink,
    ThroughPost,
    ThroughTag,
)


def _scope(queryset: Any, info: Any) -> Any:
    """Record the current request and restrict each model's visible rows.

    Args:
        queryset: Candidate rows from the public resolver.
        info: Current GraphQL resolve information.

    Returns:
        The unchanged or restricted lazy queryset.
    """
    info.context.calls.append(
        {
            "model": queryset.model.__name__,
            "alias": queryset.db,
            "request": info.context.token,
            "allow_hidden": info.context.allow_hidden,
        }
    )
    if getattr(info.context, "preload_unscoped", False):
        if queryset.model is AndManyPost:
            queryset = queryset.prefetch_related("tags")
        else:
            queryset = queryset.prefetch_related("posts")
    if info.context.allow_hidden or (
        getattr(info.context, "restrict_on_alias", None)
        and queryset.db != info.context.restrict_on_alias
    ):
        return queryset
    if queryset.model is AndManyTag:
        return queryset.filter(color="visible")
    return queryset.exclude(title__startswith="private-")


def _schema(scoped: bool, *, alias: str | None = None) -> DjangoGraphQLSchema:
    """Compile both automatic M2M directions in a private schema registry.

    Args:
        scoped: Whether both destination types declare a row hook.
        alias: Optional root queryset database alias.

    Returns:
        The actual public GraphQL schema.
    """
    local_registry = Registry()

    class M2MTagType(DjangoObjectType):
        """Expose tags and their automatic reverse post relation."""

        class Meta:
            """Bind the tag projection without exposing its visibility field."""

            model = AndManyTag
            registry = local_registry
            only_fields = ("id", "label", "posts")

        if scoped:

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Apply the current tag policy.

                Args:
                    queryset: Candidate tag rows.
                    info: Active request information.

                Returns:
                    The current lazy row scope.
                """
                return _scope(queryset, info)

    class M2MPostType(DjangoObjectType):
        """Expose posts and their automatic declared tag relation."""

        class Meta:
            """Bind the post projection and its model-declared M2M."""

            model = AndManyPost
            registry = local_registry
            only_fields = ("id", "title", "tags")

        if scoped:

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Apply the current post policy.

                Args:
                    queryset: Candidate post rows.
                    info: Active request information.

                Returns:
                    The current lazy row scope.
                """
                return _scope(queryset, info)

    class M2MPostList(DjangoListObjectType):
        """Publish posts with the registered object projection."""

        class Meta:
            """Bind the root and automatically reused nested post container."""

            model = AndManyPost
            registry = local_registry
            if alias is not None:
                queryset = AndManyPost.objects.using(alias).all()

    class M2MTagList(DjangoListObjectType):
        """Publish tags with the registered object projection."""

        class Meta:
            """Bind the root and automatically reused nested tag container."""

            model = AndManyTag
            registry = local_registry
            if alias is not None:
                queryset = AndManyTag.objects.using(alias).all()

    class Query(ObjectType):
        """Publish both roots without custom relation resolvers."""

        posts = DjangoListObjectField(M2MPostList)
        tags = DjangoListObjectField(M2MTagList)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    for type_name, accessor in (("M2MPostType", "tags"), ("M2MTagType", "posts")):
        field = schema.graphql_schema.get_type(type_name).fields[accessor]
        resolver = field.resolve
        assert isinstance(resolver, partial)
        assert resolver.func.__qualname__ == "DjangoNestedListObjectField.list_resolver"
        mounted = resolver.func.__self__
        assert isinstance(mounted, DjangoNestedListObjectField)
        assert mounted.accessor == accessor and mounted.resolver is None
        container = get_named_type(field.type)
        assert {"results", "totalCount"}.issubset(container.fields)
        print(
            "M2M_OUTPUT_PROJECTION "
            + json.dumps(
                {
                    "field": type_name + "." + accessor,
                    "sdl_type": str(field.type),
                    "resolver": resolver.func.__qualname__,
                    "automatic_accessor": mounted.accessor,
                    "explicit_resolver": False,
                },
                sort_keys=True,
            )
        )
    return schema


@pytest.fixture
def rows(db: None) -> None:
    """Create mixed, hidden-only and empty relations in the disposable database.

    Args:
        db: Pytest-Django's disposable database fixture.
    """
    tags = {
        name: AndManyTag.objects.create(label=name, color=color)
        for name, color in (
            ("visible-tag", "visible"),
            ("hidden-tag", "hidden"),
            ("hidden-only-tag", "visible"),
            ("empty-tag", "visible"),
        )
    }
    posts = {
        name: AndManyPost.objects.create(title=name)
        for name in (
            "mixed-post",
            "hidden-only-post",
            "empty-post",
            "private-post",
        )
    }
    posts["mixed-post"].tags.add(tags["visible-tag"], tags["hidden-tag"])
    posts["hidden-only-post"].tags.add(tags["hidden-tag"])
    posts["private-post"].tags.add(tags["visible-tag"], tags["hidden-only-tag"])


@pytest.fixture
def alias_rows(django_db_blocker: Any) -> None:
    """Create only disposable in-memory rows on a nondefault database alias.

    Args:
        django_db_blocker: Pytest-Django database access control.

    Yields:
        Access to disposable rows on the nondefault alias.
    """
    assert "m2m_scope" not in connections.databases
    config = deepcopy(connections.databases["default"])
    config["NAME"] = ":memory:"
    connections.databases["m2m_scope"] = config
    with django_db_blocker.unblock():
        alias_connection = connections["m2m_scope"]
        assert alias_connection.settings_dict["NAME"] == ":memory:"
        try:
            with alias_connection.schema_editor() as editor:
                editor.create_model(AndManyTag)
                editor.create_model(AndManyPost)
            visible = AndManyTag.objects.using("m2m_scope").create(
                label="visible-tag", color="visible"
            )
            hidden = AndManyTag.objects.using("m2m_scope").create(
                label="hidden-tag", color="hidden"
            )
            public = AndManyPost.objects.using("m2m_scope").create(title="public-post")
            private = AndManyPost.objects.using("m2m_scope").create(
                title="private-post"
            )
            public.tags.add(visible, hidden)
            private.tags.add(visible)
            yield
        finally:
            alias_connection.close()
            del connections["m2m_scope"]
            del connections.databases["m2m_scope"]


@pytest.mark.parametrize("root", ["posts", "tags"])
@pytest.mark.parametrize("count_only", [True, False])
def test_optimized_m2m_scope_uses_source_database_alias(
    alias_rows: None, root: str, count_only: bool
) -> None:
    """Scope automatic M2M members or count before a cross-alias hook runs.

    Args:
        alias_rows: Disposable nondefault-alias rows.
        root: Declared or reverse automatic relation root.
        count_only: Whether to query only the nested count.
    """
    schema = _schema(True, alias="m2m_scope")
    child = "tags" if root == "posts" else "posts"
    root_field = "title" if root == "posts" else "label"
    child_field = "label" if root == "posts" else "title"
    nested = "totalCount" if count_only else f"totalCount results{{{child_field}}}"
    query = f"{{{root}{{totalCount results{{{root_field} {child}{{{nested}}}}}}}}}"
    context = SimpleNamespace(
        token=f"alias-{root}-{count_only}",
        allow_hidden=False,
        restrict_on_alias="m2m_scope",
        calls=[],
    )
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": True}):
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, result.errors
    expected_child = {"totalCount": 1}
    if not count_only:
        expected_child["results"] = [
            {child_field: "visible-tag" if root == "posts" else "public-post"}
        ]
    expected_root = "public-post" if root == "posts" else "visible-tag"
    assert result.data == {
        root: {
            "totalCount": 1,
            "results": [{root_field: expected_root, child: expected_child}],
        }
    }
    assert context.calls
    assert all(call["alias"] == "m2m_scope" for call in context.calls)


def _observe(
    schema: DjangoGraphQLSchema,
    root: str,
    token: str,
    allowed: bool,
    *,
    preload_unscoped: bool = False,
) -> dict:
    """Observe actual nested data, counts and hook invocations.

    Args:
        schema: Public compiled schema.
        root: Root list field to select.
        token: Current request identity.
        allowed: Whether the policy permits hidden rows.
        preload_unscoped: Whether the root deliberately caches unscoped children.

    Returns:
        Exact request and response evidence.
    """
    selection = (
        "title tags { totalCount results { label } }"
        if root == "posts"
        else "label posts { totalCount results { title } }"
    )
    query = "{ " + root + " { totalCount results { " + selection + " } } }"
    context = SimpleNamespace(
        token=token,
        allow_hidden=allowed,
        preload_unscoped=preload_unscoped,
        calls=[],
    )
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    record = {
        "token": token,
        "query": query,
        "data": result.data,
        "errors": [str(error) for error in result.errors or ()],
        "calls": context.calls,
        "query_count": len(captured),
    }
    print("M2M_OUTPUT_OBSERVATION " + json.dumps(record, sort_keys=True))
    assert result.errors is None, record
    assert all(
        call["request"] == token and call["alias"] == "default"
        for call in context.calls
    )
    return record


@pytest.mark.parametrize("optimize", [True, False])
def test_declared_m2m_members_follow_destination_scope(
    rows: None, optimize: bool
) -> None:
    """Exclude hidden tags from automatic declared M2M results.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    schema = _schema(True)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        record = _observe(schema, "posts", f"declared-members-{optimize}", False)
    posts = {row["title"]: row["tags"] for row in record["data"]["posts"]["results"]}
    assert posts["mixed-post"]["results"] == [{"label": "visible-tag"}]
    assert posts["hidden-only-post"]["results"] == []
    assert posts["empty-post"]["results"] == []
    assert any(call["model"] == "AndManyTag" for call in record["calls"])


@pytest.mark.parametrize("optimize", [True, False])
def test_reverse_m2m_members_follow_destination_scope(
    rows: None, optimize: bool
) -> None:
    """Exclude hidden posts from automatic reverse M2M results.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    schema = _schema(True)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        record = _observe(schema, "tags", f"reverse-members-{optimize}", False)
    tags = {row["label"]: row["posts"] for row in record["data"]["tags"]["results"]}
    assert tags["visible-tag"]["results"] == [{"title": "mixed-post"}]
    assert tags["hidden-only-tag"]["results"] == []
    assert tags["empty-tag"]["results"] == []
    assert any(call["model"] == "AndManyPost" for call in record["calls"])


@pytest.mark.parametrize("optimize", [True, False])
def test_declared_m2m_count_only_is_scoped(rows: None, optimize: bool) -> None:
    """Scope a declared relation count even without selecting member results.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    schema = _schema(True)
    query = "{posts{results{title tags{totalCount}}}}"
    context = SimpleNamespace(
        token=f"declared-count-{optimize}", allow_hidden=False, calls=[]
    )
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, result.errors
    posts = {
        row["title"]: row["tags"]["totalCount"]
        for row in result.data["posts"]["results"]
    }
    assert posts == {"mixed-post": 1, "hidden-only-post": 0, "empty-post": 0}
    assert any(call["model"] == "AndManyTag" for call in context.calls)


@pytest.mark.parametrize("optimize", [True, False])
def test_reverse_m2m_count_only_is_scoped(rows: None, optimize: bool) -> None:
    """Scope a reverse relation count even without selecting member results.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    schema = _schema(True)
    query = "{tags{results{label posts{totalCount}}}}"
    context = SimpleNamespace(
        token=f"reverse-count-{optimize}", allow_hidden=False, calls=[]
    )
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, result.errors
    tags = {
        row["label"]: row["posts"]["totalCount"]
        for row in result.data["tags"]["results"]
    }
    assert tags == {"visible-tag": 1, "hidden-only-tag": 0, "empty-tag": 0}
    assert any(call["model"] == "AndManyPost" for call in context.calls)


@pytest.mark.parametrize("optimize", [True, False])
def test_m2m_scope_uses_current_request_and_compiled_schema(
    rows: None, optimize: bool
) -> None:
    """Keep unscoped and permitted requests independent of restricted ones.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    scoped = _schema(True)
    no_hook = _schema(False)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        for schema, allowed, label in (
            (scoped, False, "restricted-first"),
            (scoped, True, "permitted"),
            (no_hook, False, "no-hook"),
            (scoped, False, "restricted-repeat"),
        ):
            post_record = _observe(schema, "posts", f"{label}-posts", allowed)
            tag_record = _observe(schema, "tags", f"{label}-tags", allowed)
            posts = {
                row["title"]: row["tags"]
                for row in post_record["data"]["posts"]["results"]
            }
            tags = {
                row["label"]: row["posts"]
                for row in tag_record["data"]["tags"]["results"]
            }
            restricted = schema is scoped and not allowed
            assert post_record["data"]["posts"]["totalCount"] == (
                3 if restricted else 4
            )
            assert tag_record["data"]["tags"]["totalCount"] == (3 if restricted else 4)
            assert posts["mixed-post"]["totalCount"] == (1 if restricted else 2)
            assert tags["visible-tag"]["totalCount"] == (1 if restricted else 2)
            assert posts["empty-post"] == {"totalCount": 0, "results": []}
            assert tags["empty-tag"] == {"totalCount": 0, "results": []}
            assert ("private-post" not in posts) is restricted
            assert ("hidden-tag" not in tags) is restricted
            expected_post_hooks = (
                {"AndManyPost", "AndManyTag"} if schema is scoped else set()
            )
            expected_tag_hooks = (
                {"AndManyTag", "AndManyPost"} if schema is scoped else set()
            )
            assert {
                call["model"] for call in post_record["calls"]
            } == expected_post_hooks
            assert {call["model"] for call in tag_record["calls"]} == expected_tag_hooks


@pytest.mark.parametrize("optimize", [True, False])
def test_m2m_count_precedes_nested_page_limit(rows: None, optimize: bool) -> None:
    """Count all visible linked targets before slicing the nested page.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
    """
    extra = AndManyTag.objects.create(label="second-visible-tag", color="visible")
    AndManyPost.objects.get(title="mixed-post").tags.add(extra)
    schema = _schema(True)
    context = SimpleNamespace(token="pagination", allow_hidden=False, calls=[])
    query = "{posts{results{title tags{totalCount results(limit:1){label}}}}}"
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, result.errors
    posts = {row["title"]: row["tags"] for row in result.data["posts"]["results"]}
    assert posts["mixed-post"]["totalCount"] == 2
    assert len(posts["mixed-post"]["results"]) == 1
    assert posts["hidden-only-post"] == {"totalCount": 0, "results": []}


@pytest.mark.parametrize("optimize", [True, False])
@pytest.mark.parametrize("root", ["posts", "tags"])
def test_unscoped_prefetch_cache_cannot_authorize_m2m_output(
    rows: None, optimize: bool, root: str
) -> None:
    """Ignore an unrelated root prefetch when resolving scoped M2M output.

    Args:
        rows: Disposable parent and target rows.
        optimize: Whether query optimization is active.
        root: Public list direction under test.
    """
    schema = _schema(True)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        record = _observe(
            schema,
            root,
            f"preloaded-{root}-{optimize}",
            False,
            preload_unscoped=True,
        )
    if root == "posts":
        rows_by_name = {
            row["title"]: row["tags"] for row in record["data"][root]["results"]
        }
        assert rows_by_name["mixed-post"] == {
            "totalCount": 1,
            "results": [{"label": "visible-tag"}],
        }
        assert rows_by_name["hidden-only-post"] == {
            "totalCount": 0,
            "results": [],
        }
    else:
        rows_by_name = {
            row["label"]: row["posts"] for row in record["data"][root]["results"]
        }
        assert rows_by_name["visible-tag"] == {
            "totalCount": 1,
            "results": [{"title": "mixed-post"}],
        }
        assert rows_by_name["hidden-only-tag"] == {
            "totalCount": 0,
            "results": [],
        }


@pytest.mark.parametrize("optimize", [True, False])
def test_custom_through_and_reverse_accessor_scope_m2m_output(
    db: None, optimize: bool
) -> None:
    """Use Django's real through links and reverse accessor in both directions.

    Args:
        db: Disposable Django test database.
        optimize: Whether query optimization is active.
    """
    visible = ThroughTag.objects.create(name="visible", visible=True)
    hidden = ThroughTag.objects.create(name="hidden", visible=False)
    public = ThroughPost.objects.create(title="public")
    private = ThroughPost.objects.create(title="private-secret")
    ThroughLink.objects.create(post_ref=public, tag_ref=visible)
    ThroughLink.objects.create(post_ref=public, tag_ref=hidden)
    ThroughLink.objects.create(post_ref=private, tag_ref=visible)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(
            THROUGH_SCHEMA.graphql_schema,
            "{posts{results{title targets{totalCount results{name}}}} "
            "tags{results{name articles{totalCount results{title}}}}}",
        )
    assert result.errors is None, result.errors
    assert result.data == {
        "posts": {
            "results": [
                {
                    "title": "public",
                    "targets": {
                        "totalCount": 1,
                        "results": [{"name": "visible"}],
                    },
                }
            ]
        },
        "tags": {
            "results": [
                {
                    "name": "visible",
                    "articles": {
                        "totalCount": 1,
                        "results": [{"title": "public"}],
                    },
                }
            ]
        },
    }


def test_optimized_scoped_m2m_prefetch_does_not_grow_per_parent(rows: None) -> None:
    """Keep the optimized scoped child query count bounded as parents grow.

    Args:
        rows: Initial disposable parent and target rows.
    """
    schema = _schema(True)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": True}):
        before = _observe(schema, "posts", "query-count-before", False)
        visible = AndManyTag.objects.get(label="visible-tag")
        hidden = AndManyTag.objects.get(label="hidden-tag")
        for index in range(7):
            post = AndManyPost.objects.create(title=f"public-extra-{index}")
            post.tags.add(visible, hidden)
        after = _observe(schema, "posts", "query-count-after", False)
    assert after["query_count"] == before["query_count"]
    posts = {row["title"]: row["tags"] for row in after["data"]["posts"]["results"]}
    for index in range(7):
        assert posts[f"public-extra-{index}"] == {
            "totalCount": 1,
            "results": [{"label": "visible-tag"}],
        }
