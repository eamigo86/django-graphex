"""Public GraphQL regressions for destination-scoped reverse-FK filters."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField, DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .test_and_many_filtering import (
    AndManyComment,
    AndManyOwner,
    AndManyPost,
    AndManyTag,
)
from .test_sd1_reverse_accessor_scope import (
    SD1VerifyChild,
    SD1VerifyNamedChild,
    SD1VerifyParent,
)

REGISTRY = Registry()


class ScopedOwnerType(DjangoObjectType):
    """Publish the owner used by a nested forward-FK control.

    Its name is the final leaf in a reverse-then-forward filter path.
    """

    class Meta:
        """Bind the owner model to this request-local schema registry.

        Its name is available to nested relation filters.
        """

        model = AndManyOwner
        registry = REGISTRY
        only_fields = ("id", "name")


class ScopedTagType(DjangoObjectType):
    """Publish tag labels below a visible reverse-FK child.

    Tags have no destination scope in this bounded reverse-FK test.
    """

    class Meta:
        """Bind tag output to the same isolated schema.

        Child-level explicit AND branches can traverse this relation.
        """

        model = AndManyTag
        registry = REGISTRY
        only_fields = ("id", "label")


class ScopedCommentType(DjangoObjectType):
    """Expose only child rows allowed by the current request.

    The visibility column remains private to the GraphQL schema.
    """

    class Meta:
        """Publish comment fields while keeping the scope discriminator private.

        The hook may filter a column that is not in the GraphQL output.
        """

        model = AndManyComment
        registry = REGISTRY
        only_fields = ("id", "label", "note", "owner", "tags")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Filter children by the current request's visible color.

        Args:
            queryset: Candidate comments on the source database alias.
            info: Current GraphQL resolve information.

        Returns:
            Child rows visible to this request.

        Raises:
            RuntimeError: When the request asks for a failing hook witness.
        """
        info.context.hook_aliases.append(queryset.db)
        if info.context.fail_scope:
            raise RuntimeError("comment scope failed")
        return queryset.filter(color=info.context.visible_color)


class ScopedPostType(DjangoObjectType):
    """Keep source-row visibility separate from child-row visibility.

    A visible child cannot restore a source excluded by this type.
    """

    class Meta:
        """Publish post fields and the automatic comments relation.

        The reverse relation must remain available for input projection.
        """

        model = AndManyPost
        registry = REGISTRY
        only_fields = ("id", "title", "comments")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Hide private source posts without changing the child scope.

        Args:
            queryset: Candidate parent rows.
            info: Current GraphQL request.

        Returns:
            Public parent rows.
        """
        return queryset.exclude(title="private")


class ScopedPostList(DjangoListObjectType):
    """Expose reverse-child filter paths through the public list resolver.

    It uses the registered post node type for active-schema resolution.
    """

    class Meta:
        """Declare child lookups and the source-row title control.

        Grouped and split child predicates use the ordinary native planner.
        """

        model = AndManyPost
        registry = REGISTRY
        filter_fields = {
            "title": ("exact",),
            "comments__id": ("exact", "in"),
            "comments__label": ("exact",),
            "comments__note": ("exact", "isnull"),
            "comments__owner__name": ("exact",),
            "comments__tags__label": ("exact",),
        }


class Query(ObjectType):
    """Serve the scoped native filter through a public GraphQL field.

    The field exercises production input compilation and list resolution.
    """

    posts = DjangoListObjectField(ScopedPostList)


SCHEMA = DjangoGraphQLSchema(query=Query, registries=isolated_pair(REGISTRY))


DIRECT_REGISTRY = Registry()


class DirectCommentType(ScopedCommentType):
    """Scoped child in a schema with direct relation-ID lookups.

    Its hook is inherited while its registry is independent.
    """

    class Meta:
        """Keep direct IDs separate from nested child fields.

        This follows the public input compiler's distinct declaration shape.
        """

        model = AndManyComment
        registry = DIRECT_REGISTRY
        only_fields = ("id", "label", "note", "owner")


class DirectOwnerType(ScopedOwnerType):
    """Register the child owner for the direct-ID schema.

    The compiler can then publish the child's owner relation.
    """

    class Meta:
        """Use the direct-ID schema registry without changing its fields.

        The owner is not itself filtered in this schema.
        """

        model = AndManyOwner
        registry = DIRECT_REGISTRY
        only_fields = ("id", "name")


class DirectPostList(DjangoListObjectType):
    """Publish the reverse relation as direct child-ID lookups.

    These lookups traverse the child table rather than a parent column.
    """

    class Meta:
        """Declare source title and child ID lookups only.

        Direct reverse IDs still consult the child row scope.
        """

        model = AndManyPost
        registry = DIRECT_REGISTRY
        filter_fields = {"comments": ("exact", "in")}


class DirectQuery(ObjectType):
    """Expose the direct child-ID filter through public GraphQL.

    Its input shape is distinct from nested child-field filters.
    """

    posts = DjangoListObjectField(DirectPostList)


DIRECT_SCHEMA = DjangoGraphQLSchema(
    query=DirectQuery, registries=isolated_pair(DIRECT_REGISTRY)
)


ACCESSOR_REGISTRY = Registry()


class DefaultAccessorChildType(DjangoObjectType):
    """Publish the default-accessor child with a destination scope.

    The output accessor differs from Django's reverse query name.
    """

    class Meta:
        """Bind the default-accessor child to the accessor schema.

        The visibility flag is deliberately not published.
        """

        model = SD1VerifyChild
        registry = ACCESSOR_REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Retain only visible children of the default reverse accessor.

        Args:
            queryset: Candidate child rows.
            info: Current GraphQL request.

        Returns:
            Visible child rows.
        """
        return queryset.filter(visible=True)


class NamedAccessorChildType(DjangoObjectType):
    """Publish the named-accessor child with a destination scope.

    Its related name and related query name intentionally differ.
    """

    class Meta:
        """Bind the named-accessor child to the accessor schema.

        The visibility flag is deliberately not published.
        """

        model = SD1VerifyNamedChild
        registry = ACCESSOR_REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Retain only visible children of the named reverse accessor.

        Args:
            queryset: Candidate child rows.
            info: Current GraphQL request.

        Returns:
            Visible child rows.
        """
        return queryset.filter(visible=True)


class AccessorParentType(DjangoObjectType):
    """Publish both reverse relation accessors for input projection.

    Automatic output fields are the filter traversal boundary.
    """

    class Meta:
        """Bind the parent output type to the accessor registry.

        Both reverse children are registered in the same isolated schema.
        """

        model = SD1VerifyParent
        registry = ACCESSOR_REGISTRY


class AccessorParentList(DjangoListObjectType):
    """Filter reverse children by ORM query name, not output accessor.

    The public input compiler translates these declared paths.
    """

    class Meta:
        """Declare both default and custom-query-name reverse paths.

        Each path must resolve the published automatic child accessor.
        """

        model = SD1VerifyParent
        registry = ACCESSOR_REGISTRY
        filter_fields = {
            "sd1verifychild__title": ("exact",),
            "named_match__title": ("exact",),
        }


class AccessorQuery(ObjectType):
    """Serve both accessor shapes through the public native list field.

    The parent list shares one active compiled schema.
    """

    parents = DjangoListObjectField(AccessorParentList)


ACCESSOR_SCHEMA = DjangoGraphQLSchema(
    query=AccessorQuery, registries=isolated_pair(ACCESSOR_REGISTRY)
)


NOHOOK_REGISTRY = Registry()


class UnscopedCommentType(DjangoObjectType):
    """Expose the same child model without a destination hook.

    This gives the registry-isolation test its unscoped control.
    """

    class Meta:
        """Bind the unscoped child to a separate compiled schema.

        It cannot inherit the first registry's visibility policy.
        """

        model = AndManyComment
        registry = NOHOOK_REGISTRY
        only_fields = ("id", "label", "note", "owner")


class UnscopedOwnerType(DjangoObjectType):
    """Publish the owner in the no-hook control schema.

    The related field remains compilable in this registry.
    """

    class Meta:
        """Bind the owner to the no-hook schema.

        No row-level hook is defined on this output type.
        """

        model = AndManyOwner
        registry = NOHOOK_REGISTRY
        only_fields = ("id", "name")


class UnscopedPostList(DjangoListObjectType):
    """Expose the same reverse predicate from another registry.

    Its result differs only because its child type has no hook.
    """

    class Meta:
        """Keep the other registry's filter declaration equivalent.

        The same model rows are queried under another compiled schema.
        """

        model = AndManyPost
        registry = NOHOOK_REGISTRY
        filter_fields = {"comments__label": ("exact",)}


class UnscopedQuery(ObjectType):
    """Serve the no-hook registry independently of the scoped schema.

    Requests alternate between these two schemas in one process.
    """

    posts = DjangoListObjectField(UnscopedPostList)


NOHOOK_SCHEMA = DjangoGraphQLSchema(
    query=UnscopedQuery, registries=isolated_pair(NOHOOK_REGISTRY)
)


@pytest.fixture
def rows(db: None) -> dict[str, Any]:
    """Create visible, hidden, mixed, absent and split child witnesses.

    Args:
        db: Pytest-Django database access fixture.

    Returns:
        Named source and child rows for public assertions.
    """
    owner = AndManyOwner.objects.create(name="owner")
    posts = {
        name: AndManyPost.objects.create(title=name)
        for name in (
            "hidden-only",
            "visible-match",
            "mixed",
            "both",
            "absent",
            "split",
            "grouped",
            "visible-null",
            "hidden-null",
        )
    }

    def child(post: str, label: str, color: str, note: str | None = "present") -> Any:
        """Create one related comment with an explicit visibility color.

        Args:
            post: Named source row.
            label: Public predicate value.
            color: Private scope discriminator.
            note: Nullable public predicate value.

        Returns:
            The created comment row.
        """
        return AndManyComment.objects.create(
            post=posts[post], owner=owner, label=label, color=color, note=note
        )

    hidden_match = child("hidden-only", "match", "hidden")
    visible_match = child("visible-match", "match", "visible")
    child("mixed", "match", "hidden")
    child("mixed", "other", "visible")
    child("both", "match", "visible")
    child("both", "other", "visible")
    child("split", "x", "visible", "no")
    child("split", "y", "visible", "yes")
    child("grouped", "x", "visible", "yes")
    child("visible-null", "other", "visible", None)
    child("hidden-null", "other", "hidden", None)
    return {
        "posts": posts,
        "hidden_match": hidden_match,
        "visible_match": visible_match,
    }


def _execute(
    filter_input: str,
    *,
    direct: bool = False,
    visible_color: str = "visible",
    fail_scope: bool = False,
) -> tuple[Any, SimpleNamespace]:
    """Run a public request and expose hook alias observations.

    Args:
        filter_input: GraphQL filter object literal.
        direct: Whether to use the direct child-ID schema.
        visible_color: Current request's allowed child color.
        fail_scope: Whether the destination hook raises.

    Returns:
        GraphQL result and the request context.
    """
    context = SimpleNamespace(
        visible_color=visible_color, fail_scope=fail_scope, hook_aliases=[]
    )
    schema = DIRECT_SCHEMA if direct else SCHEMA
    query = "{ posts(filter: " + filter_input + ") { results { title } totalCount } }"
    return graphql_sync(schema.graphql_schema, query, context_value=context), context


def _titles(result: Any) -> list[str]:
    """Read sorted public source titles from one successful result.

    Args:
        result: GraphQL execution result.

    Returns:
        Sorted source titles.
    """
    assert result.errors is None, [str(error) for error in result.errors or ()]
    values = sorted(item["title"] for item in result.data["posts"]["results"])
    assert result.data["posts"]["totalCount"] == len(values)
    return values


def test_reverse_fk_positive_requires_visible_matching_child(
    rows: dict[str, Any],
) -> None:
    """Hidden-only and mixed nonmatching-visible children cannot witness a match.

    Args:
        rows: Database witnesses.
    """
    result, context = _execute('{ comments: { label: { exact: "match" } } }')
    assert _titles(result) == ["both", "visible-match"]
    assert context.hook_aliases and set(context.hook_aliases) == {"default"}
    changed, _ = _execute(
        '{ comments: { label: { exact: "match" } } }', visible_color="hidden"
    )
    assert _titles(changed) == ["hidden-only", "mixed"]


def test_reverse_fk_not_complements_matching_parent_set(rows: dict[str, Any]) -> None:
    """A visible nonmatching sibling cannot invert a visible matching child.

    Args:
        rows: Database witnesses.
    """
    result, _ = _execute('{ not: { comments: { label: { exact: "match" } } } }')
    assert _titles(result) == [
        "absent",
        "grouped",
        "hidden-null",
        "hidden-only",
        "mixed",
        "split",
        "visible-null",
    ]


def test_reverse_fk_and_retains_split_and_grouped_witnesses(
    rows: dict[str, Any],
) -> None:
    """Separate AND branches may use distinct visible children; one group cannot.

    Args:
        rows: Database witnesses.
    """
    split, _ = _execute(
        '{ and: [{ comments: { label: { exact: "x" } } }, '
        '{ comments: { note: { exact: "yes" } } }] }'
    )
    assert _titles(split) == ["grouped", "split"]
    grouped, _ = _execute(
        '{ comments: { label: { exact: "x" }, note: { exact: "yes" } } }'
    )
    assert _titles(grouped) == ["grouped"]


def test_reverse_fk_absence_and_null_predicates(rows: dict[str, Any]) -> None:
    """Missing or hidden-only children remain distinct from visible child NULLs.

    Args:
        rows: Database witnesses.
    """
    for lookup in ("exact: null", "isnull: true"):
        result, _ = _execute("{ comments: { note: { " + lookup + " } } }")
        assert _titles(result) == [
            "absent",
            "hidden-null",
            "hidden-only",
            "visible-null",
        ]


@pytest.mark.parametrize("owner_scope", [False, True])
def test_reverse_absence_nested_forward_null(
    rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch, owner_scope: bool
) -> None:
    """A missing visible child matches a nested nullable-join predicate.

    Args:
        rows: Public schema database witnesses.
        monkeypatch: Temporary request-scope hook replacement.
        owner_scope: Whether the forward destination also has a hook.
    """
    if owner_scope:

        def scope(cls: type, queryset: Any, info: Any) -> Any:
            """Retain the owner without changing its database alias.

            Args:
                cls: Public owner type.
                queryset: Candidate owner rows.
                info: Request information.

            Returns:
                The same visible owner as the no-hook control.
            """
            return queryset.filter(name="owner")

        monkeypatch.setattr(ScopedOwnerType, "get_queryset", classmethod(scope))
    result, _ = _execute("{ comments: { owner: { name: { exact: null } } } }")
    assert _titles(result) == ["absent", "hidden-null", "hidden-only"]


def test_reverse_fk_direct_child_ids_are_destination_scoped(
    rows: dict[str, Any],
) -> None:
    """Direct child IDs traverse the child table and cannot name hidden rows.

    Args:
        rows: Database witnesses.
    """
    hidden_id = rows["hidden_match"].pk
    visible_id = rows["visible_match"].pk
    hidden, _ = _execute(f"{{ comments: {{ exact: {hidden_id} }} }}", direct=True)
    visible, _ = _execute(f"{{ comments: {{ in: [{visible_id}] }} }}", direct=True)
    assert _titles(hidden) == []
    assert _titles(visible) == ["visible-match"]


def test_reverse_fk_empty_filter_and_hook_failure(rows: dict[str, Any]) -> None:
    """An empty relation is a no-op and hook failures cannot fall back unscoped.

    Args:
        rows: Database witnesses.
    """
    empty, context = _execute("{ comments: {} }")
    assert len(_titles(empty)) == 9
    assert context.hook_aliases == []
    failed, _ = _execute('{ comments: { label: { exact: "match" } } }', fail_scope=True)
    assert failed.errors
    assert "comment scope failed" in str(failed.errors[0])


def test_reverse_fk_boolean_and_nested_forward_hop(rows: dict[str, Any]) -> None:
    """OR and nested owner predicates retain the same visible child witness.

    Args:
        rows: Database witnesses.
    """
    combined, _ = _execute(
        '{ or: [{ comments: { label: { exact: "match" } } }, '
        '{ comments: { owner: { name: { exact: "owner" } }, '
        'label: { exact: "x" } } }] }'
    )
    assert _titles(combined) == ["both", "grouped", "split", "visible-match"]
    negative, _ = _execute('{ comments: { not: { label: { exact: "match" } } } }')
    assert "both" in _titles(negative)
    assert "hidden-only" in _titles(negative)


def test_reverse_fk_uses_active_registry_without_scope_leak(
    rows: dict[str, Any],
) -> None:
    """A second compiled registry must not inherit the first one's hook.

    Args:
        rows: Database witnesses.
    """
    scoped, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert _titles(scoped) == ["both", "visible-match"]
    query = '{ posts(filter: { comments: { label: { exact: "match" } } }) { results { title } totalCount } }'
    unscoped = graphql_sync(NOHOOK_SCHEMA.graphql_schema, query)
    assert _titles(unscoped) == ["both", "hidden-only", "mixed", "visible-match"]
    scoped_again, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert _titles(scoped_again) == ["both", "visible-match"]


def test_reverse_fk_resolves_default_and_named_accessors(db: None) -> None:
    """ORM query names must resolve the active output accessor child type.

    Args:
        db: Pytest-Django database access fixture.
    """
    hidden = SD1VerifyParent.objects.create(name="hidden")
    visible = SD1VerifyParent.objects.create(name="visible")
    for parent, state in ((hidden, False), (visible, True)):
        SD1VerifyChild.objects.create(owner=parent, visible=state, title="match")
        SD1VerifyNamedChild.objects.create(owner=parent, visible=state, title="match")
    for relation in ("sd1verifychild", "namedMatch"):
        query = (
            "{ parents(filter: { " + relation + ': { title: { exact: "match" } } }) '
            "{ results { name } totalCount } }"
        )
        result = graphql_sync(ACCESSOR_SCHEMA.graphql_schema, query)
        assert result.errors is None, [str(error) for error in result.errors or ()]
        assert result.data["parents"]["results"] == [{"name": "visible"}]


def test_declared_reverse_accessor_cannot_reopen_filter_path() -> None:
    """An explicit resolver masks its ORM query-name alias as well.

    Publishing the accessor by name is not sufficient when it is declared.
    """
    local_registry = Registry()

    class ChildType(DjangoObjectType):
        """Give the declared child relation a published output type.

        The child type itself is available to the temporary schema.
        """

        class Meta:
            """Bind the child to the isolated masked-field registry.

            Its ordinary scalar fields remain published.
            """

            model = SD1VerifyNamedChild
            registry = local_registry
            only_fields = ("id", "title")

    class ParentType(DjangoObjectType):
        """Replace automatic reverse output with a declared list resolver.

        This replacement must retain the projection mask.
        """

        named_children = DjangoFilterListField(ChildType)

        class Meta:
            """Bind the explicit relation to its parent model.

            The alias test uses a distinct registry from the other schemas.
            """

            model = SD1VerifyParent
            registry = local_registry

    class ParentList(DjangoListObjectType):
        """Try to reopen the relation through its ORM query name.

        Schema construction must reject this declaration.
        """

        class Meta:
            """Declare the forbidden nested reverse filter.

            The target field is otherwise public on its child type.
            """

            model = SD1VerifyParent
            registry = local_registry
            filter_fields = {"named_match__title": ("exact",)}

    class MaskedQuery(ObjectType):
        """Provide the public schema compiler's root field.

        Building this root triggers the projection refusal.
        """

        parents = DjangoListObjectField(ParentList)

    with pytest.raises(ImproperlyConfigured, match="does not publish as a relation"):
        DjangoGraphQLSchema(query=MaskedQuery, registries=isolated_pair(local_registry))


def test_reverse_fk_source_and_destination_scopes_are_distinct(
    rows: dict[str, Any],
) -> None:
    """A visible matching child cannot restore an excluded source parent.

    Args:
        rows: Database witnesses.
    """
    private = AndManyPost.objects.create(title="private")
    AndManyComment.objects.create(
        post=private,
        owner=AndManyOwner.objects.get(name="owner"),
        label="match",
        color="visible",
        note="present",
    )
    result, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert _titles(result) == ["both", "visible-match"]


def test_reverse_fk_scope_is_one_composed_query_not_per_parent(
    rows: dict[str, Any],
) -> None:
    """A larger parent set does not multiply destination hook queries.

    Args:
        rows: Database witnesses.
    """
    with CaptureQueriesContext(connection) as queries:
        result, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert _titles(result) == ["both", "visible-match"]
    assert len(queries) <= 4


def test_reverse_fk_nested_independent_and_keeps_one_visible_child(
    rows: dict[str, Any],
) -> None:
    """Different tags may satisfy branches only below one visible comment.

    Args:
        rows: Database witnesses.
    """
    red = AndManyTag.objects.create(label="red", color="plain")
    blue = AndManyTag.objects.create(label="blue", color="plain")
    together = AndManyPost.objects.create(title="together")
    separate = AndManyPost.objects.create(title="separate")
    owner = AndManyOwner.objects.get(name="owner")
    both_tags = AndManyComment.objects.create(
        post=together, owner=owner, label="other", color="visible"
    )
    both_tags.tags.add(red, blue)
    for post, tag in ((separate, red), (separate, blue)):
        comment = AndManyComment.objects.create(
            post=post, owner=owner, label="other", color="visible"
        )
        comment.tags.add(tag)
    result, _ = _execute(
        '{ comments: { and: [{ tags: { label: { exact: "red" } } }, '
        '{ tags: { label: { exact: "blue" } } }] } }'
    )
    assert _titles(result) == ["together"]


def test_reverse_fk_boolean_null_branch_accepts_hidden_only(
    rows: dict[str, Any],
) -> None:
    """Nested Boolean NULL predicates preserve missing-child semantics.

    Args:
        rows: Database witnesses.
    """
    result, _ = _execute(
        "{ comments: { or: [{ note: { exact: null } }, "
        '{ label: { exact: "never" } }] } }'
    )
    assert _titles(result) == ["absent", "hidden-null", "hidden-only", "visible-null"]


def test_reverse_fk_nested_boolean_null_and_match_branches(
    rows: dict[str, Any],
) -> None:
    """Nested OR and AND preserve the missing-child and visible-match branches.

    Args:
        rows: Database witnesses.
    """
    result, _ = _execute(
        "{ comments: { or: [{ note: { exact: null } }, "
        '{ and: [{ label: { exact: "match" } }, '
        '{ owner: { name: { exact: "owner" } } }] }] } }'
    )
    assert _titles(result) == [
        "absent",
        "both",
        "hidden-null",
        "hidden-only",
        "visible-match",
        "visible-null",
    ]


def test_reverse_fk_wrong_model_hook_fails_closed(
    rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destination hook cannot replace the child model in its witness.

    Args:
        rows: Database witnesses.
        monkeypatch: Temporary hook replacement.
    """

    def wrong_model(cls: type, queryset: Any, info: Any) -> Any:
        """Return an incompatible model for the public failure witness.

        Args:
            cls: Destination GraphQL output type.
            queryset: Child rows normally supplied to the hook.
            info: Current GraphQL request.

        Returns:
            An invalid queryset over parent rows.
        """
        return AndManyPost.objects.all()

    monkeypatch.setattr(ScopedCommentType, "get_queryset", classmethod(wrong_model))
    result, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert result.errors
    assert "retain the destination model and database alias" in str(result.errors[0])


def test_reverse_fk_wrong_alias_hook_fails_closed(
    rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destination hook cannot switch its child witness database.

    Args:
        rows: Database witnesses.
        monkeypatch: Temporary hook replacement.
    """

    def wrong_alias(cls: type, queryset: Any, info: Any) -> Any:
        """Return a child queryset bound to an unauthorized alias.

        Args:
            cls: Destination GraphQL output type.
            queryset: Child rows on the source alias.
            info: Current GraphQL request.

        Returns:
            A queryset whose alias no longer matches the source.
        """
        return queryset.using("other")

    monkeypatch.setattr(ScopedCommentType, "get_queryset", classmethod(wrong_alias))
    result, _ = _execute('{ comments: { label: { exact: "match" } } }')
    assert result.errors
    assert "retain the destination model and database alias" in str(result.errors[0])
