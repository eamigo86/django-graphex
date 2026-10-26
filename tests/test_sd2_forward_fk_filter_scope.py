"""Public GraphQL regressions for destination-scoped forward-FK filters."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from graphql import (
    GraphQLError,
    GraphQLField,
    GraphQLID,
    GraphQLList,
    GraphQLObjectType,
    graphql_sync,
)

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.filtering.backend import NativeFilterBackend, apply_filter_backend
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Category, Comment, Post

REGISTRY = Registry()


class VisibleAuthorType(DjangoObjectType):
    """Author rows allowed by the active GraphQL request.

    The hook changes its answer for each request context.
    """

    class Meta:
        """Publish the author name and use the isolated registry.

        The schema exposes only values needed by the filter witness.
        """

        model = Author
        registry = REGISTRY
        only_fields = ("id", "name")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Keep only the author selected by this request.

        Args:
            queryset: Candidate author rows.
            info: Current GraphQL resolve information.

        Returns:
            Authors visible to the current request.

        Raises:
            RuntimeError: If the test requests a failing scope hook.
        """
        if getattr(info.context, "fail_scope", False):
            raise RuntimeError("author scope failed")
        return queryset.filter(name=info.context.allowed_author)


class VisibleCategoryType(DjangoObjectType):
    """Category rows allowed by the active GraphQL request.

    The nullable post relation makes real absence observable separately.
    """

    class Meta:
        """Publish the category title and use the isolated registry.

        The title is the nested filter's visible leaf.
        """

        model = Category
        registry = REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Keep only the category selected by this request.

        Args:
            queryset: Candidate category rows.
            info: Current GraphQL resolve information.

        Returns:
            Categories visible to the current request.
        """
        return queryset.filter(title=info.context.allowed_category)


class VisiblePostType(DjangoObjectType):
    """Public posts with forward author and nullable category filters.

    Source visibility is independent of both destination hooks.
    """

    class Meta:
        """Expose direct FK IDs separately from traversed target fields.

        The compiled input combines both declaration forms for this model.
        """

        model = Post
        registry = REGISTRY
        only_fields = ("id", "title", "author", "category")
        filter_fields = {
            "id": ("exact",),
            "title": ("exact",),
            "author": ("exact", "in"),
            "author__name": ("exact",),
            "category": ("exact",),
            "category__title": ("exact", "isnull"),
        }

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Keep the source-side public posts before applying the filter.

        Args:
            queryset: Candidate post rows.
            info: Current GraphQL resolve information.

        Returns:
            Public posts only.
        """
        return queryset.filter(title__startswith="pub-")


class VisibleCommentType(DjangoObjectType):
    """Comments that exercise a two-hop forward-FK filter.

    Their source rows are not scoped by the post hook.
    """

    class Meta:
        """Expose comment to post to author traversal.

        Both forward hops must enforce their own destination scope.
        """

        model = Comment
        registry = REGISTRY
        only_fields = ("id", "body", "post")
        filter_fields = {
            "post__title": ("exact",),
            "post__author__name": ("exact",),
        }


class Query(ObjectType):
    """Expose the scoped filter paths through ordinary public list fields.

    Both root fields run the native filter backend.
    """

    posts = DjangoFilterListField(VisiblePostType)
    comments = DjangoFilterListField(VisibleCommentType)


SCHEMA = DjangoGraphQLSchema(query=Query, registries=isolated_pair(REGISTRY))


DIRECT_REGISTRY = Registry()


class DirectAuthorType(VisibleAuthorType):
    """Scoped author target in a schema with direct FK-ID filters only.

    Its hook must not narrow source-owned ID predicates.
    """

    class Meta:
        """Bind the author to the direct-filter schema registry.

        This registry is separate from the nested-filter schema.
        """

        model = Author
        registry = DIRECT_REGISTRY
        only_fields = ("id", "name")


class DirectCategoryType(VisibleCategoryType):
    """Scoped category target in a schema with direct FK-ID filters only.

    The target hook must not redefine a source NULL lookup.
    """

    class Meta:
        """Bind the category to the direct-filter schema registry.

        This keeps direct and nested input forms independent.
        """

        model = Category
        registry = DIRECT_REGISTRY
        only_fields = ("id", "title")


class DirectPostType(VisiblePostType):
    """Public posts exposing only source-owned direct FK-ID filters.

    The source hook still removes private posts.
    """

    class Meta:
        """Keep direct FK-ID inputs separate from nested traversal inputs.

        A combined declaration compiles direct IDs as nested PK children.
        """

        model = Post
        registry = DIRECT_REGISTRY
        only_fields = ("id", "title", "author", "category")
        filter_fields = {
            "author": ("exact", "in"),
            "category": ("exact",),
        }


class DirectQuery(ObjectType):
    """Expose the source-owned ID filter controls through public GraphQL.

    The field uses an isolated schema to retain the direct input shape.
    """

    posts = DjangoFilterListField(DirectPostType)


DIRECT_SCHEMA = DjangoGraphQLSchema(
    query=DirectQuery, registries=isolated_pair(DIRECT_REGISTRY)
)


ALTERNATE_REGISTRY = Registry()


class AlternateAuthorType(DjangoObjectType):
    """A second schema's author type with an independent visibility rule.

    It intentionally disagrees with the first schema for the same model.
    """

    class Meta:
        """Bind the same model to a distinct, schema-local registry.

        No global registry lookup should override this binding.
        """

        model = Author
        registry = ALTERNATE_REGISTRY
        only_fields = ("id", "name")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Expose only the hidden-named author in this separate schema.

        Args:
            queryset: Candidate author rows.
            info: Current GraphQL resolve information.

        Returns:
            Rows allowed by this schema's independent hook.
        """
        return queryset.filter(name="hidden")


class AlternatePostType(VisiblePostType):
    """Public posts that traverse the alternate schema's author type.

    Their source hook remains the same as in the first schema.
    """

    class Meta:
        """Bind forward-FK filtering to the alternate registry.

        The compiled relation field must carry this schema's target.
        """

        model = Post
        registry = ALTERNATE_REGISTRY
        only_fields = ("id", "title", "author")
        filter_fields = {"author__name": ("exact",)}


class AlternateQuery(ObjectType):
    """Expose the alternate schema's nested author filter.

    The same model rows can then be queried with two visibility policies.
    """

    posts = DjangoFilterListField(AlternatePostType)


ALTERNATE_SCHEMA = DjangoGraphQLSchema(
    query=AlternateQuery, registries=isolated_pair(ALTERNATE_REGISTRY)
)


def _execute(
    filter_input: str,
    *,
    root: str = "posts",
    direct: bool = False,
    alternate: bool = False,
    **context: Any,
) -> Any:
    """Run a public GraphQL query with request-specific visibility.

    Args:
        filter_input: GraphQL filter object literal.
        root: Public list field to query.
        direct: Whether to use the direct FK-ID control schema.
        alternate: Whether to use the independent destination-hook schema.
        **context: Overrides for the request visibility context.

    Returns:
        The GraphQL execution result.
    """
    request = SimpleNamespace(
        allowed_author=context.get("allowed_author", "visible"),
        allowed_category=context.get("allowed_category", "allowed"),
        fail_scope=context.get("fail_scope", False),
    )
    query = (
        f"{{ {root}(filter: {filter_input}) {{ title }} }}"
        if root == "posts"
        else (f"{{ {root}(filter: {filter_input}) {{ body }} }}")
    )
    schema = ALTERNATE_SCHEMA if alternate else (DIRECT_SCHEMA if direct else SCHEMA)
    return graphql_sync(schema.graphql_schema, query, context_value=request)


@pytest.fixture
def rows(db: None) -> dict[str, Any]:
    """Create visible, hidden, nullable, and source-hidden FK witnesses.

    Args:
        db: Pytest-django database access fixture.

    Returns:
        Named model instances for direct-ID control assertions.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    allowed = Category.objects.create(title="allowed")
    denied = Category.objects.create(title="denied")
    public_visible = Post.objects.create(
        title="pub-visible", author=visible, category=allowed
    )
    public_hidden = Post.objects.create(
        title="pub-hidden", author=hidden, category=denied
    )
    public_null = Post.objects.create(title="pub-null", author=visible)
    private = Post.objects.create(title="private", author=visible, category=allowed)
    for post in (public_visible, public_hidden, public_null, private):
        Comment.objects.create(post=post, body=post.title)
    return {
        "visible": visible,
        "hidden": hidden,
        "allowed": allowed,
        "denied": denied,
        "public_hidden": public_hidden,
    }


def _values(result: Any, *, root: str = "posts") -> list[str]:
    """Read sorted public values from a successful GraphQL result.

    Args:
        result: GraphQL execution result.
        root: Queried public list field.

    Returns:
        Sorted post titles or comment bodies.
    """
    assert result.errors is None, [str(error) for error in result.errors or ()]
    key = "title" if root == "posts" else "body"
    return sorted(item[key] for item in result.data[root])


def test_forward_fk_filter_uses_request_destination_scope(rows: dict[str, Any]) -> None:
    """A hidden author cannot match while the same request can match a visible one.

    Args:
        rows: Database witnesses.
    """
    match_hidden = '{ author: { name: { exact: "hidden" } } }'
    assert _values(_execute(match_hidden)) == []
    assert _values(_execute(match_hidden, allowed_author="hidden")) == ["pub-hidden"]
    assert _values(_execute('{ author: { name: { exact: "visible" } } }')) == [
        "pub-null",
        "pub-visible",
    ]


def test_nullable_fk_traversal_preserves_real_null(rows: dict[str, Any]) -> None:
    """A real absent FK still matches isnull while a hidden target does not.

    Args:
        rows: Database witnesses.
    """
    assert _values(_execute('{ category: { title: { exact: "denied" } } }')) == []
    assert _values(_execute("{ category: { title: { isnull: true } } }")) == [
        "pub-null"
    ]


def test_direct_fk_ids_and_omission_keep_source_contract(rows: dict[str, Any]) -> None:
    """Direct source FK identifiers remain separate from destination traversal.

    Args:
        rows: Database witnesses.
    """
    hidden_id = rows["hidden"].pk
    assert _values(
        _execute(f"{{ author: {{ exact: {hidden_id} }} }}", direct=True)
    ) == ["pub-hidden"]
    assert _values(_execute(f"{{ author: {{ in: [{hidden_id}] }} }}", direct=True)) == [
        "pub-hidden"
    ]
    assert _values(_execute("{ category: { exact: null } }", direct=True)) == [
        "pub-null"
    ]
    assert _values(_execute("{}")) == ["pub-hidden", "pub-null", "pub-visible"]


def test_boolean_composition_does_not_prune_unrelated_matches(
    rows: dict[str, Any],
) -> None:
    """AND, OR and NOT retain Boolean meaning around a scoped traversal.

    Args:
        rows: Database witnesses.
    """
    hidden = '{ author: { name: { exact: "hidden" } } }'
    assert _values(
        _execute(f'{{ or: [{hidden}, {{ title: {{ exact: "pub-null" }} }}] }}')
    ) == ["pub-null"]
    assert (
        _values(
            _execute(f'{{ and: [{hidden}, {{ title: {{ exact: "pub-hidden" }} }}] }}')
        )
        == []
    )
    assert _values(_execute(f"{{ not: {hidden} }}")) == [
        "pub-hidden",
        "pub-null",
        "pub-visible",
    ]
    assert (
        _values(_execute('{ author: { not: { name: { exact: "visible" } } } }')) == []
    )


def test_each_forward_fk_chain_hop_is_scoped(rows: dict[str, Any]) -> None:
    """The post and author hooks both constrain comment traversal.

    Args:
        rows: Database witnesses.
    """
    hidden_author = '{ post: { author: { name: { exact: "hidden" } } } }'
    assert _values(_execute(hidden_author, root="comments"), root="comments") == []
    assert _values(
        _execute(hidden_author, root="comments", allowed_author="hidden"),
        root="comments",
    ) == ["pub-hidden"]
    private_post = '{ post: { title: { exact: "private" } } }'
    assert _values(_execute(private_post, root="comments"), root="comments") == []


def test_scope_failure_is_not_unscoped_fallback(rows: dict[str, Any]) -> None:
    """A failing destination hook returns an error, never hidden matches.

    Args:
        rows: Database witnesses.
    """
    result = _execute('{ author: { name: { exact: "hidden" } } }', fail_scope=True)
    assert result.errors
    assert result.data is not None
    assert result.data["posts"] is None
    assert "author scope failed" in str(result.errors[0])


def test_schema_and_request_isolation(rows: dict[str, Any]) -> None:
    """Two schema registries and repeated requests never share visibility.

    Args:
        rows: Database witnesses.
    """
    target = '{ author: { name: { exact: "hidden" } } }'
    assert _values(_execute(target)) == []
    assert _values(_execute(target, alternate=True)) == ["pub-hidden"]
    assert _values(_execute(target, allowed_author="hidden")) == ["pub-hidden"]
    assert _values(_execute(target)) == []


def test_incompatible_destination_hook_fails_closed(
    rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook returning another model cannot satisfy the FK predicate.

    Args:
        rows: Database witnesses.
        monkeypatch: Scoped replacement for the target hook.
    """

    def wrong_model(cls: type, queryset: Any, info: Any) -> Any:
        """Return an unrelated queryset instead of visible authors.

        Args:
            cls: Destination output type.
            queryset: Candidate authors.
            info: Current GraphQL request.

        Returns:
            An incompatible post queryset.
        """
        return Post.objects.all()

    monkeypatch.setattr(VisibleAuthorType, "get_queryset", classmethod(wrong_model))
    result = _execute('{ author: { name: { exact: "hidden" } } }')
    assert result.errors
    assert "retain the destination model and database alias" in str(result.errors[0])
    assert result.data["posts"] is None


def test_missing_compiled_destination_type_fails_closed(rows: dict[str, Any]) -> None:
    """A mismatched output type never permits an unscoped FK filter.

    Args:
        rows: Database witnesses.
    """
    unrelated = GraphQLObjectType(
        "UnrelatedFilterResult", {"id": GraphQLField(GraphQLID)}
    )
    info = SimpleNamespace(return_type=GraphQLList(unrelated))
    with pytest.raises(GraphQLError, match="no destination type"):
        NativeFilterBackend().apply(
            Post.objects.all(),
            {"author": {"name": {"exact": "hidden"}}},
            info=info,
        )


def test_overridden_native_backend_keeps_two_argument_seam(
    rows: dict[str, Any],
) -> None:
    """A third-party native subclass need not accept a new info parameter.

    Args:
        rows: Database witnesses.
    """

    class LegacyBackend(NativeFilterBackend):
        """Simulate an existing native backend subclass with its own apply."""

        def apply(self, queryset: Any, value: Any) -> Any:
            """Ignore native translation and retain the old call signature.

            Args:
                queryset: Source posts.
                value: Submitted filter input.

            Returns:
                Public posts under this custom implementation.
            """
            return queryset.filter(title__startswith="pub-")

    queryset = apply_filter_backend(LegacyBackend(), Post.objects.all(), {}, object())
    assert sorted(queryset.values_list("title", flat=True)) == [
        "pub-hidden",
        "pub-null",
        "pub-visible",
    ]


@pytest.mark.parametrize(
    "filter_input",
    [
        "{ author: {} }",
        "{ author: { or: [] } }",
        "{ author: { not: {} } }",
        "{ author: { name: {} } }",
        "{ category: { or: [] } }",
        "{ not: { author: { or: [] } } }",
    ],
)
def test_empty_forward_fk_traversal_remains_noop(
    rows: dict[str, Any], filter_input: str
) -> None:
    """An empty relation predicate must not become a visibility predicate.

    Args:
        rows: Database witnesses.
        filter_input: Empty public GraphQL filter shape.
    """
    assert _values(_execute(filter_input)) == ["pub-hidden", "pub-null", "pub-visible"]


def test_nullable_forward_fk_negative_filter_keeps_real_null(
    rows: dict[str, Any],
) -> None:
    """Negating a hidden match includes a genuinely absent FK.

    Args:
        rows: Database witnesses.
    """
    cases = [
        ("{ category: { title: { exact: null } } }", ["pub-null"]),
        ('{ category: { not: { title: { exact: "allowed" } } } }', ["pub-null"]),
        (
            '{ or: [{ category: { title: { exact: "denied" } } }, '
            '{ title: { exact: "pub-visible" } }] }',
            ["pub-visible"],
        ),
        (
            '{ not: { category: { title: { exact: "denied" } } } }',
            ["pub-hidden", "pub-null", "pub-visible"],
        ),
    ]
    for predicate, expected in cases:
        assert _values(_execute(predicate)) == expected
