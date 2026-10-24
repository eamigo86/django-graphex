"""Public GraphQL regressions for destination-scoped many-to-many filters."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField, DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .test_and_many_filtering import AndManyPost, AndManyTag

REGISTRY = Registry()


class ScopedTagType(DjangoObjectType):
    """Expose tags while restricting rows to the current request's color.

    The visibility discriminator stays private to the output schema.
    """

    class Meta:
        """Bind the tag model and its automatic reverse relation.

        The compiled accessor is needed for reverse traversal filters.
        """

        model = AndManyTag
        registry = REGISTRY
        only_fields = ("id", "label", "color", "posts")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Scope tag rows without changing the model or database alias.

        Args:
            queryset: Candidate tags.
            info: Active request.

        Returns:
            Tags with the request-visible color.
        """
        info.context.tag_aliases.append(queryset.db)
        return queryset.filter(color=info.context.visible_color)


class ScopedPostType(DjangoObjectType):
    """Exclude private posts from reverse M2M destination witnesses.

    The same hook also scopes top-level post rows.
    """

    class Meta:
        """Bind posts and their automatic forward M2M relation.

        The published relation permits target-field filter declarations.
        """

        model = AndManyPost
        registry = REGISTRY
        only_fields = ("id", "title", "tags")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Hide private posts from all source and destination reads.

        Args:
            queryset: Candidate posts.
            info: Active request.

        Returns:
            Public post rows.
        """
        info.context.post_aliases.append(queryset.db)
        return queryset.exclude(title__startswith="private-")


class ScopedPostList(DjangoListObjectType):
    """Publish forward M2M filter paths on posts.

    These paths cover target IDs, scalar predicates and multiple hops.
    """

    class Meta:
        """Declare label predicates over automatic tags.

        Root fields also keep the shared target input shape complete.
        """

        model = AndManyPost
        registry = REGISTRY
        filter_fields = {
            "id": ("exact", "in"),
            "title": ("exact",),
            "tags__id": ("exact", "in"),
            "tags__label": ("exact",),
            "tags__color": ("exact", "isnull"),
            "tags__posts__title": ("exact",),
        }


class ScopedTagList(DjangoListObjectType):
    """Publish reverse M2M filter paths on tags.

    Target post IDs and titles are both exercised through this list.
    """

    class Meta:
        """Declare title predicates over automatic posts.

        The root paths make nested post filters share one complete input.
        """

        model = AndManyTag
        registry = REGISTRY
        filter_fields = {
            "id": ("exact", "in"),
            "label": ("exact",),
            "color": ("exact", "isnull"),
            "posts__id": ("exact", "in"),
            "posts__title": ("exact",),
        }


class Query(ObjectType):
    """Serve both M2M traversal directions through public list resolvers.

    Every assertion runs against this compiled GraphQL surface.
    """

    posts = DjangoListObjectField(ScopedPostList)
    tags = DjangoListObjectField(ScopedTagList)


SCHEMA = DjangoGraphQLSchema(query=Query, registries=isolated_pair(REGISTRY))


DIRECT_REGISTRY = Registry()


class DirectTagType(ScopedTagType):
    """Keep the destination hook in the direct-ID schema.

    Inherited authorization applies to relation-ID witnesses too.
    """

    class Meta:
        """Bind the direct-ID schema's tag output type.

        Its registry is isolated from nested-field tests.
        """

        model = AndManyTag
        registry = DIRECT_REGISTRY
        only_fields = ("id", "label", "color", "posts")


class DirectPostType(ScopedPostType):
    """Keep the source hook in the direct-ID schema.

    Inherited authorization still excludes private source posts.
    """

    class Meta:
        """Bind the direct-ID schema's post output type.

        Its registry is isolated from nested-field tests.
        """

        model = AndManyPost
        registry = DIRECT_REGISTRY
        only_fields = ("id", "title", "tags")


class DirectPostList(DjangoListObjectType):
    """Publish direct forward M2M target-ID lookup inputs.

    This separate schema avoids mixing direct and nested relation shapes.
    """

    class Meta:
        """Declare exact and membership target-ID lookups.

        Both lookups must use visible destination rows.
        """

        model = AndManyPost
        registry = DIRECT_REGISTRY
        filter_fields = {"tags": ("exact", "in"), "title": ("exact",)}


class DirectTagList(DjangoListObjectType):
    """Publish direct reverse M2M target-ID lookup inputs.

    The reverse branch has the same visible-target requirement.
    """

    class Meta:
        """Declare exact and membership target-ID lookups.

        The reverse branch reads IDs through destination rows.
        """

        model = AndManyTag
        registry = DIRECT_REGISTRY
        filter_fields = {"posts": ("exact", "in"), "label": ("exact",)}


class DirectQuery(ObjectType):
    """Serve direct M2M target-ID filters in both directions.

    These public fields retain the normal list resolver behavior.
    """

    posts = DjangoListObjectField(DirectPostList)
    tags = DjangoListObjectField(DirectTagList)


DIRECT_SCHEMA = DjangoGraphQLSchema(
    query=DirectQuery, registries=isolated_pair(DIRECT_REGISTRY)
)


class AliasTag(models.Model):
    """Target of an M2M whose reverse accessor differs from its query name.

    This distinction detects accidental lookup by the output accessor.
    """

    label = models.CharField(max_length=20)

    class Meta:
        """Keep query-name regression tables isolated from application rows.

        The disposable test database owns this fixture table.
        """

        app_label = "tests"
        db_table = "t_sd2_m2m_alias_tag"


class AliasPost(models.Model):
    """Provide a custom reverse M2M query name and a hidden-row predicate.

    The relation publishes entries but filters through entry_lookup.
    """

    title = models.CharField(max_length=40)
    tags = models.ManyToManyField(
        AliasTag, related_name="entries", related_query_name="entry_lookup"
    )

    class Meta:
        """Keep query-name regression tables isolated from application rows.

        The disposable test database owns this fixture table.
        """

        app_label = "tests"
        db_table = "t_sd2_m2m_alias_post"


ALIAS_REGISTRY = Registry()


class AliasPostType(DjangoObjectType):
    """Hide private posts behind a reverse M2M traversal.

    A private post cannot witness a tag predicate.
    """

    class Meta:
        """Publish the post destination type in the alias schema.

        Its compiled projection is the reverse filter's target boundary.
        """

        model = AliasPost
        registry = ALIAS_REGISTRY
        only_fields = ("id", "title", "tags")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Exclude private destinations without evaluating the queryset.

        Args:
            queryset: Candidate posts.
            info: Active request.

        Returns:
            The visible post queryset.
        """
        return queryset.exclude(title__startswith="private-")


class AliasTagType(DjangoObjectType):
    """Publish the automatic reverse accessor named entries.

    The ORM query name remains distinct from this GraphQL field.
    """

    class Meta:
        """Bind the public tag type to the alias schema.

        Only the automatic reverse accessor is traversable.
        """

        model = AliasTag
        registry = ALIAS_REGISTRY
        only_fields = ("id", "label", "entries")


class AliasTagList(DjangoListObjectType):
    """Declare the ORM query-name filter path, not the output accessor.

    Schema compilation resolves this path to the published accessor.
    """

    class Meta:
        """Publish a reverse M2M title predicate.

        The path deliberately uses the ORM's distinct query name.
        """

        model = AliasTag
        registry = ALIAS_REGISTRY
        filter_fields = {"entry_lookup__title": ("exact",)}


class AliasQuery(ObjectType):
    """Serve the custom query-name regression through a public root.

    The root compiles the accessor and its filter declaration together.
    """

    tags = DjangoListObjectField(AliasTagList)


ALIAS_SCHEMA = DjangoGraphQLSchema(
    query=AliasQuery, registries=isolated_pair(ALIAS_REGISTRY)
)


NOHOOK_REGISTRY = Registry()


class NoHookTagType(DjangoObjectType):
    """Publish the same tags without a destination visibility hook.

    This second schema is the control for registry isolation.
    """

    class Meta:
        """Bind the unscoped tag type to another registry.

        It must not inherit the scoped schema's authorization hook.
        """

        model = AndManyTag
        registry = NOHOOK_REGISTRY
        only_fields = ("id", "label", "posts")


class NoHookPostType(DjangoObjectType):
    """Publish the same posts without a source visibility hook.

    The comparison isolates destination scoping from source scoping.
    """

    class Meta:
        """Bind the unscoped post type to another registry.

        The output projection still publishes its automatic M2M relation.
        """

        model = AndManyPost
        registry = NOHOOK_REGISTRY
        only_fields = ("id", "title", "tags")


class NoHookPostList(DjangoListObjectType):
    """Reuse the nested tag declaration in an independent schema.

    Matching hidden tags is expected only in this no-hook control.
    """

    class Meta:
        """Declare the same label predicate without row authorization.

        This makes the two schemas differ only in their output hooks.
        """

        model = AndManyPost
        registry = NOHOOK_REGISTRY
        filter_fields = {"tags__label": ("exact",)}


class NoHookQuery(ObjectType):
    """Serve the other compiled schema for registry-isolation checks.

    A request through this root must use its own type registry.
    """

    posts = DjangoListObjectField(NoHookPostList)


NOHOOK_SCHEMA = DjangoGraphQLSchema(
    query=NoHookQuery, registries=isolated_pair(NOHOOK_REGISTRY)
)


class ThroughTag(models.Model):
    """M2M destination linked through explicitly named foreign keys.

    The visible flag drives target-row authorization in the test.
    """

    name = models.CharField(max_length=20)
    visible = models.BooleanField(default=True)

    class Meta:
        """Isolate the custom-through fixture in the test app.

        It is created only in the disposable test database.
        """

        app_label = "tests"
        db_table = "t_sd2_m2m_through_tag"


class ThroughPost(models.Model):
    """M2M source whose through model does not use conventional FK names.

    Both the reverse query name and accessor are explicitly configured.
    """

    title = models.CharField(max_length=20)
    targets = models.ManyToManyField(
        ThroughTag,
        through="ThroughLink",
        through_fields=("post_ref", "tag_ref"),
        related_name="articles",
        related_query_name="article_link",
    )

    class Meta:
        """Isolate the custom-through fixture in the test app.

        It is created only in the disposable test database.
        """

        app_label = "tests"
        db_table = "t_sd2_m2m_through_post"


class ThroughLink(models.Model):
    """Use custom source and target FK names for the M2M join.

    The ORM must derive correlation from relation metadata, not assumptions.
    """

    post_ref = models.ForeignKey(ThroughPost, on_delete=models.CASCADE)
    tag_ref = models.ForeignKey(ThroughTag, on_delete=models.CASCADE)

    class Meta:
        """Isolate the explicit join table in the test app.

        Its foreign keys use names different from Django's usual convention.
        """

        app_label = "tests"
        db_table = "t_sd2_m2m_through_link"


THROUGH_REGISTRY = Registry()


class ThroughTagType(DjangoObjectType):
    """Scope the custom-through target to visible tag rows.

    Forward M2M predicates must not use hidden tag links.
    """

    class Meta:
        """Publish target fields and the automatic reverse accessor.

        The query-name fallback resolves this accessor during schema build.
        """

        model = ThroughTag
        registry = THROUGH_REGISTRY
        only_fields = ("id", "name", "articles")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict tag witnesses to visible destinations.

        Args:
            queryset: Candidate tag rows.
            info: Current request.

        Returns:
            Tags visible to the caller.
        """
        return queryset.filter(visible=True)


class ThroughPostType(DjangoObjectType):
    """Scope the reverse custom-through destination to public posts.

    Reverse M2M predicates must not use private post links.
    """

    class Meta:
        """Publish post fields and its automatic M2M relation.

        This is the source projection for forward M2M filter paths.
        """

        model = ThroughPost
        registry = THROUGH_REGISTRY
        only_fields = ("id", "title", "targets")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Exclude private posts without materializing the queryset.

        Args:
            queryset: Candidate post rows.
            info: Current request.

        Returns:
            Public post rows.
        """
        return queryset.exclude(title__startswith="private-")


class ThroughPostList(DjangoListObjectType):
    """Publish forward custom-through filter paths.

    The nested target name is matched using a visible linked row.
    """

    class Meta:
        """Declare target-name predicates.

        The root title path keeps the shared post input complete.
        """

        model = ThroughPost
        registry = THROUGH_REGISTRY
        filter_fields = {"title": ("exact",), "targets__name": ("exact",)}


class ThroughTagList(DjangoListObjectType):
    """Publish reverse custom-through filter paths.

    The nested post title is matched through the distinct query name.
    """

    class Meta:
        """Declare post-title predicates through the ORM query name.

        The root name path keeps the shared tag input complete.
        """

        model = ThroughTag
        registry = THROUGH_REGISTRY
        filter_fields = {"name": ("exact",), "article_link__title": ("exact",)}


class ThroughQuery(ObjectType):
    """Serve both custom-through directions through public GraphQL lists.

    The same relation is tested from each side of its join table.
    """

    posts = DjangoListObjectField(ThroughPostList)
    tags = DjangoListObjectField(ThroughTagList)


THROUGH_SCHEMA = DjangoGraphQLSchema(
    query=ThroughQuery, registries=isolated_pair(THROUGH_REGISTRY)
)


@pytest.fixture
def rows(db: None) -> dict[str, Any]:
    """Create visible, hidden, mixed and absent M2M witnesses.

    Args:
        db: Pytest-Django database fixture.

    Returns:
        Named model rows used by the public assertions.
    """
    visible = AndManyTag.objects.create(label="match", color="visible")
    hidden = AndManyTag.objects.create(label="match", color="hidden")
    other = AndManyTag.objects.create(label="other", color="visible")
    posts = {
        name: AndManyPost.objects.create(title=name)
        for name in ("only-hidden", "with-visible", "mixed", "absent")
    }
    posts["only-hidden"].tags.add(hidden)
    posts["with-visible"].tags.add(visible)
    posts["mixed"].tags.add(hidden, other)
    private = AndManyPost.objects.create(title="private-match")
    public = AndManyPost.objects.create(title="public-match")
    reverse_hidden = AndManyTag.objects.create(label="reverse-hidden", color="visible")
    reverse_visible = AndManyTag.objects.create(
        label="reverse-visible", color="visible"
    )
    reverse_mixed = AndManyTag.objects.create(label="reverse-mixed", color="visible")
    for tag in (reverse_hidden, reverse_mixed):
        private.tags.add(tag)
    for tag in (reverse_visible, reverse_mixed):
        public.tags.add(tag)
    return {
        "visible": visible,
        "hidden": hidden,
        "other": other,
        "posts": posts,
        "private": private,
        "public": public,
    }


def _names(
    root: str,
    filter_input: str,
    field: str,
    *,
    schema: DjangoGraphQLSchema = SCHEMA,
) -> tuple[list[str], Any]:
    """Execute one public filter and return sorted result names.

    Args:
        root: Public list field to query.
        filter_input: GraphQL input object literal.
        field: Scalar result field.
        schema: Active compiled public schema.

    Returns:
        Sorted names and the request context.
    """
    context = SimpleNamespace(visible_color="visible", tag_aliases=[], post_aliases=[])
    query = (
        "{ " + root + "(filter: " + filter_input + ") "
        "{ results { " + field + " } totalCount } }"
    )
    result = graphql_sync(schema.graphql_schema, query, context_value=context)
    assert result.errors is None, [str(error) for error in result.errors or ()]
    names = sorted(item[field] for item in result.data[root]["results"])
    assert result.data[root]["totalCount"] == len(names)
    return names, context


def test_forward_m2m_requires_visible_matching_target(rows: dict[str, Any]) -> None:
    """A hidden-only match and hidden match beside visible nonmatch are excluded.

    Args:
        rows: Database witness rows.
    """
    names, context = _names("posts", '{ tags: { label: { exact: "match" } } }', "title")
    assert names == ["with-visible"]
    assert context.tag_aliases and set(context.tag_aliases) == {"default"}


def test_reverse_m2m_requires_visible_matching_target(rows: dict[str, Any]) -> None:
    """A private target cannot witness a reverse M2M predicate.

    Args:
        rows: Database witness rows.
    """
    hidden, _ = _names(
        "tags", '{ posts: { title: { exact: "private-match" } } }', "label"
    )
    assert hidden == []
    visible, context = _names(
        "tags", '{ posts: { title: { exact: "public-match" } } }', "label"
    )
    assert visible == ["reverse-mixed", "reverse-visible"]
    assert context.post_aliases and set(context.post_aliases) == {"default"}


def test_m2m_not_complements_visible_parent_matches(rows: dict[str, Any]) -> None:
    """A visible nonmatching sibling cannot invert a visible match.

    Args:
        rows: Database witness rows.
    """
    names, _ = _names(
        "posts", '{ not: { tags: { label: { exact: "match" } } } }', "title"
    )
    assert "mixed" in names
    assert "with-visible" not in names
    assert "only-hidden" in names


def test_reverse_m2m_not_and_unrelated_or_preserve_parent_set(
    rows: dict[str, Any],
) -> None:
    """Reverse NOT excludes parents with a visible match despite siblings.

    Args:
        rows: Database witness rows.
    """
    complemented, _ = _names(
        "tags", '{ not: { posts: { title: { exact: "public-match" } } } }', "label"
    )
    assert "reverse-mixed" not in complemented
    assert "reverse-visible" not in complemented
    assert "reverse-hidden" in complemented
    unrelated, _ = _names(
        "posts",
        '{ or: [{ tags: { label: { exact: "match" } } }, '
        '{ title: { exact: "absent" } }] }',
        "title",
    )
    assert unrelated == ["absent", "with-visible"]


def test_forward_m2m_ids_use_visible_destination_universe(rows: dict[str, Any]) -> None:
    """Even an exact destination ID cannot witness an invisible tag.

    Args:
        rows: Database witness rows.
    """
    hidden_id = rows["hidden"].pk
    visible_id = rows["visible"].pk
    hidden, _ = _names(
        "posts", f"{{ tags: {{ id: {{ exact: {hidden_id} }} }} }}", "title"
    )
    visible, _ = _names(
        "posts", f"{{ tags: {{ id: {{ exact: {visible_id} }} }} }}", "title"
    )
    in_both, _ = _names(
        "posts", f"{{ tags: {{ id: {{ in: [{hidden_id}, {visible_id}] }} }} }}", "title"
    )
    assert hidden == []
    assert visible == ["with-visible"]
    assert in_both == ["with-visible"]


def test_reverse_m2m_ids_use_visible_destination_universe(rows: dict[str, Any]) -> None:
    """A reverse link's private post ID cannot disclose its tag.

    Args:
        rows: Database witness rows.
    """
    private_id = rows["private"].pk
    public_id = rows["public"].pk
    hidden, _ = _names(
        "tags", f"{{ posts: {{ id: {{ exact: {private_id} }} }} }}", "label"
    )
    visible, _ = _names(
        "tags", f"{{ posts: {{ id: {{ exact: {public_id} }} }} }}", "label"
    )
    assert hidden == []
    assert visible == ["reverse-mixed", "reverse-visible"]


@pytest.mark.parametrize("nested", ["{}", "{ or: [] }", "{ not: {} }", "{ label: {} }"])
def test_empty_m2m_child_is_noop(rows: dict[str, Any], nested: str) -> None:
    """Empty nested operands do not prune parents by destination visibility.

    Args:
        rows: Database witness rows.
        nested: Empty filter object with an established no-op meaning.
    """
    names, context = _names("posts", "{ tags: " + nested + " }", "title")
    assert names == ["absent", "mixed", "only-hidden", "public-match", "with-visible"]
    assert context.tag_aliases == []


def test_m2m_absence_and_null_match_only_visible_universe(rows: dict[str, Any]) -> None:
    """No visible tag behaves like an absent related row for SQL NULL.

    Args:
        rows: Database witness rows.
    """
    for lookup in ("exact: null", "isnull: true"):
        names, _ = _names("posts", "{ tags: { color: { " + lookup + " } } }", "title")
        assert "absent" in names
        assert "only-hidden" in names
        assert "with-visible" not in names


def test_m2m_boolean_grouping_uses_visible_witnesses(rows: dict[str, Any]) -> None:
    """Separate AND branches may use different visible tags, one object may not.

    Args:
        rows: Database witness rows.
    """
    split = AndManyPost.objects.create(title="split-visible")
    split.tags.add(rows["visible"], rows["other"])
    separate, _ = _names(
        "posts",
        '{ and: [{ tags: { label: { exact: "match" } } }, '
        f"{{ tags: {{ id: {{ exact: {rows['other'].pk} }} }} }}] }}",
        "title",
    )
    grouped, _ = _names(
        "posts",
        '{ tags: { label: { exact: "match" }, '
        f"id: {{ exact: {rows['other'].pk} }} }} }}",
        "title",
    )
    assert separate == ["split-visible"]
    assert grouped == []


def test_m2m_request_visibility_changes_without_cache(rows: dict[str, Any]) -> None:
    """Back-to-back requests use their own tag visibility policy.

    Args:
        rows: Database witness rows.
    """
    query = '{ posts(filter: { tags: { label: { exact: "match" } } }) { results { title } } }'
    visible = SimpleNamespace(visible_color="visible", tag_aliases=[], post_aliases=[])
    hidden = SimpleNamespace(visible_color="hidden", tag_aliases=[], post_aliases=[])
    first = graphql_sync(SCHEMA.graphql_schema, query, context_value=visible)
    second = graphql_sync(SCHEMA.graphql_schema, query, context_value=hidden)
    assert first.errors is None and second.errors is None
    assert sorted(item["title"] for item in first.data["posts"]["results"]) == [
        "with-visible"
    ]
    assert sorted(item["title"] for item in second.data["posts"]["results"]) == [
        "mixed",
        "only-hidden",
    ]


def test_m2m_scope_uses_active_compiled_registry(rows: dict[str, Any]) -> None:
    """A second schema must not inherit the first one's destination hook.

    Args:
        rows: Database witness rows.
    """
    scoped, _ = _names("posts", '{ tags: { label: { exact: "match" } } }', "title")
    unscoped, _ = _names(
        "posts",
        '{ tags: { label: { exact: "match" } } }',
        "title",
        schema=NOHOOK_SCHEMA,
    )
    assert scoped == ["with-visible"]
    assert unscoped == ["mixed", "only-hidden", "with-visible"]


def test_direct_m2m_target_ids_respect_both_destination_hooks(
    rows: dict[str, Any],
) -> None:
    """A direct relation ID is still a traversal of an M2M target table.

    Args:
        rows: Database witness rows.
    """
    hidden_id = rows["hidden"].pk
    visible_id = rows["visible"].pk
    private_id = rows["private"].pk
    public_id = rows["public"].pk
    forward_hidden, _ = _names(
        "posts", f"{{ tags: {{ exact: {hidden_id} }} }}", "title", schema=DIRECT_SCHEMA
    )
    forward_visible, _ = _names(
        "posts",
        f"{{ tags: {{ in: [{hidden_id}, {visible_id}] }} }}",
        "title",
        schema=DIRECT_SCHEMA,
    )
    reverse_hidden, _ = _names(
        "tags", f"{{ posts: {{ exact: {private_id} }} }}", "label", schema=DIRECT_SCHEMA
    )
    reverse_visible, _ = _names(
        "tags",
        f"{{ posts: {{ in: [{private_id}, {public_id}] }} }}",
        "label",
        schema=DIRECT_SCHEMA,
    )
    assert forward_hidden == []
    assert forward_visible == ["with-visible"]
    assert reverse_hidden == []
    assert reverse_visible == ["reverse-mixed", "reverse-visible"]


def test_nested_m2m_scopes_each_hop(rows: dict[str, Any]) -> None:
    """A hidden post through a visible tag cannot witness a second M2M hop.

    Args:
        rows: Database witness rows.
    """
    hidden, _ = _names(
        "posts", '{ tags: { posts: { title: { exact: "private-match" } } } }', "title"
    )
    visible, _ = _names(
        "posts", '{ tags: { posts: { title: { exact: "public-match" } } } }', "title"
    )
    assert hidden == []
    assert visible == ["public-match"]


def test_nested_m2m_independent_and_keeps_one_visible_outer_target(
    rows: dict[str, Any],
) -> None:
    """Separate inner branches may use different visible linked posts.

    The outer tag remains one visible witness, and a hidden inner post cannot
    satisfy either branch.

    Args:
        rows: Database witness rows.
    """
    second = AndManyPost.objects.create(title="public-second")
    second.tags.add(rows["visible"])
    names, _ = _names(
        "posts",
        "{ tags: { and: ["
        '{ posts: { title: { exact: "with-visible" } } }, '
        '{ posts: { title: { exact: "public-second" } } }'
        "] } }",
        "title",
    )
    assert names == ["public-second", "with-visible"]


def test_m2m_hook_wrong_alias_fails_closed(
    rows: dict[str, Any], monkeypatch: Any
) -> None:
    """A hook cannot move destination witnesses off the source database alias.

    Args:
        rows: Database witness rows.
        monkeypatch: Pytest's temporary patch fixture.
    """

    def wrong_alias(cls: type, queryset: Any, info: Any) -> Any:
        """Return an unauthorized alias without evaluating the queryset.

        Args:
            cls: Destination output type.
            queryset: Candidate destination rows.
            info: Active request.

        Returns:
            A queryset bound to another alias.
        """
        return queryset.using("other")

    monkeypatch.setattr(ScopedTagType, "get_queryset", classmethod(wrong_alias))
    context = SimpleNamespace(visible_color="visible", tag_aliases=[], post_aliases=[])
    result = graphql_sync(
        SCHEMA.graphql_schema,
        '{ posts(filter: { tags: { label: { exact: "match" } } }) { results { title } } }',
        context_value=context,
    )
    assert result.errors is not None
    assert "retain the destination model and database alias" in str(result.errors[0])


def test_m2m_hook_exception_fails_closed(
    rows: dict[str, Any], monkeypatch: Any
) -> None:
    """A destination hook error cannot silently revert to unscoped filtering.

    Args:
        rows: Database witness rows.
        monkeypatch: Pytest's temporary patch fixture.

    Raises:
        RuntimeError: Raised by the scope hook to simulate a failing tag scope.
    """

    def broken(cls: type, queryset: Any, info: Any) -> Any:
        """Raise the destination's authorization failure.

        Args:
            cls: Destination output type.
            queryset: Candidate destination rows.
            info: Active request.

        Raises:
            RuntimeError: Always, as an authorization failure witness.
        """
        raise RuntimeError("tag scope failed")

    monkeypatch.setattr(ScopedTagType, "get_queryset", classmethod(broken))
    context = SimpleNamespace(visible_color="visible", tag_aliases=[], post_aliases=[])
    result = graphql_sync(
        SCHEMA.graphql_schema,
        '{ posts(filter: { tags: { label: { exact: "match" } } }) { results { title } } }',
        context_value=context,
    )
    assert result.errors is not None
    assert "tag scope failed" in str(result.errors[0])


def test_reverse_m2m_query_name_follows_automatic_accessor(db: None) -> None:
    """A query-name path finds the published accessor without skipping scope.

    Args:
        db: Pytest-Django database fixture.
    """
    hidden_tag = AliasTag.objects.create(label="hidden-link")
    visible_tag = AliasTag.objects.create(label="visible-link")
    private = AliasPost.objects.create(title="private-match")
    public = AliasPost.objects.create(title="public-match")
    private.tags.add(hidden_tag)
    public.tags.add(visible_tag)
    hidden, _ = _names(
        "tags",
        '{ entryLookup: { title: { exact: "private-match" } } }',
        "label",
        schema=ALIAS_SCHEMA,
    )
    visible, _ = _names(
        "tags",
        '{ entryLookup: { title: { exact: "public-match" } } }',
        "label",
        schema=ALIAS_SCHEMA,
    )
    assert hidden == []
    assert visible == ["visible-link"]


def test_declared_reverse_m2m_accessor_does_not_reopen_filter_path() -> None:
    """Replacing the automatic output accessor preserves projection refusal.

    Merely naming the ORM path cannot bypass a declared field's mask.
    """
    local_registry = Registry()

    class LocalPostType(DjangoObjectType):
        """Publish the destination of the explicit list resolver.

        Its presence proves refusal is due to the masked relation.
        """

        class Meta:
            """Bind a local output type without an authorization hook.

            The projection publishes the queried title column.
            """

            model = AliasPost
            registry = local_registry
            only_fields = ("id", "title")

    class LocalTagType(DjangoObjectType):
        """Replace the automatic accessor with a declared list resolver.

        This replacement must not reactivate the ORM query-name filter.
        """

        entries = DjangoFilterListField(LocalPostType)

        class Meta:
            """Bind the declared relation to a separate schema registry.

            No other compiled schema can determine this projection.
            """

            model = AliasTag
            registry = local_registry

    class LocalTagList(DjangoListObjectType):
        """Attempt the forbidden ORM query-name traversal.

        Schema construction must reject this filter declaration.
        """

        class Meta:
            """Declare the path that the explicit resolver withdraws.

            A successful build would expose a hidden joined-row oracle.
            """

            model = AliasTag
            registry = local_registry
            filter_fields = {"entry_lookup__title": ("exact",)}

    class LocalQuery(ObjectType):
        """Force compilation of the projected local list field.

        The failure is required before any request executes.
        """

        tags = DjangoListObjectField(LocalTagList)

    with pytest.raises(ImproperlyConfigured, match="does not publish as a relation"):
        DjangoGraphQLSchema(query=LocalQuery, registries=isolated_pair(local_registry))


def test_custom_through_fields_scope_both_m2m_directions(db: None) -> None:
    """ORM correlation honors explicit through FK names in both directions.

    Args:
        db: Pytest-Django database fixture.
    """
    hidden_tag = ThroughTag.objects.create(name="match", visible=False)
    visible_tag = ThroughTag.objects.create(name="match", visible=True)
    hidden_post = ThroughPost.objects.create(title="private-match")
    hidden_link_post = ThroughPost.objects.create(title="hidden-link")
    visible_post = ThroughPost.objects.create(title="public-match")
    ThroughLink.objects.create(post_ref=hidden_post, tag_ref=visible_tag)
    ThroughLink.objects.create(post_ref=hidden_link_post, tag_ref=hidden_tag)
    ThroughLink.objects.create(post_ref=visible_post, tag_ref=visible_tag)
    forward, _ = _names(
        "posts",
        '{ targets: { name: { exact: "match" } } }',
        "title",
        schema=THROUGH_SCHEMA,
    )
    reverse, _ = _names(
        "tags",
        '{ articleLink: { title: { exact: "private-match" } } }',
        "name",
        schema=THROUGH_SCHEMA,
    )
    assert forward == ["public-match"]
    assert reverse == []


def test_m2m_scope_keeps_one_set_based_query_per_list(rows: dict[str, Any]) -> None:
    """Adding parents does not run the destination hook once per parent.

    Args:
        rows: Database witness rows.
    """
    for index in range(30):
        post = AndManyPost.objects.create(title=f"bulk-{index:02d}")
        post.tags.add(rows["visible"])
    with CaptureQueriesContext(connection) as captured:
        names, context = _names(
            "posts", '{ tags: { label: { exact: "match" } } }', "title"
        )
    assert len(names) == 31
    assert len(captured) <= 3
    assert context.tag_aliases == ["default"]
