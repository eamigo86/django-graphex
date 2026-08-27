# -*- coding: utf-8 -*-
"""Tests for the escape hatch that scopes an auto-expanded relation.

"docs/usage/types.md" documents a scope boundary: a relation django-graphex
auto-expands on a parent type does not run the target type's "get_queryset" --
a forward FK is a plain attribute read off the already-fetched parent, and a
to-MANY container reads the parent's prefetch cache. The mitigation the guide
offers has to be one that actually executes: a code sample in a security note
that silently does nothing is worse than the boundary it claims to close,
because the reader believes the hole is shut.

Three shapes are pinned here:

  - a bare "resolve_<relation>" method on the parent type, with no matching
    field declaration, is INERT. The output compiler derives the FK field from
    the MODEL and never consults the source class, so the method is never
    called. This is the shape the guide must NOT teach.
  - a to-ONE relation DECLARED on the parent type plus its "resolve_" method
    wins over the auto-derived field, so the scope really runs.
  - a to-MANY relation declared as a "DjangoFilterListField" replaces the
    auto-expanded container with a field that applies the hook itself.

The last two are the snippets the guide ships, and declaring either one is what
withdraws that relation from the projection's other axes -- one rule, both
directions, because both are a resolver of the reader's own standing between the
client and the rows. The to-ONE arm loses its "_id" column from the ordering
allowlist AND its filter paths; the to-MANY arm owns no column on the parent row,
so it loses only the filter paths. Both are pinned below.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import Field, ObjectType
from django_graphex.fields import DjangoFilterListField, DjangoFilterPaginateListField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post

# ---------------------------------------------------------------------------
# The INERT shape: a bare resolve_<relation> with no declaration
# ---------------------------------------------------------------------------

_RINERT = Registry()

#: Appended to by "InertPostType.resolve_author" so the test can tell whether
#: the method ever ran. It lives at module level because the native base is a
#: Pydantic model class: a plain class attribute is swallowed by its metaclass.
_INERT_CALLS: list[int] = []


class InertAuthorType(DjangoObjectType):
    """Author node used as the FK target of the inert-hatch schema.

    Declares no scope of its own; the point of this schema is what the PARENT
    type fails to do.
    """

    class Meta:
        """Configuration for "InertAuthorType".

        Plain projection-free node so the FK renders as usual.
        """

        model = Author
        registry = _RINERT


class InertPostType(DjangoObjectType):
    """Post node declaring only a "resolve_author" method, no "author" field.

    The method is what the guide used to tell readers to write. Nothing mounts
    it, so it must be observably never called.
    """

    class Meta:
        """Configuration for "InertPostType".

        Keeps "author" in the projection so the FK is auto-expanded and the
        bare resolver has something to (fail to) intercept.
        """

        model = Post
        registry = _RINERT
        only_fields = ("id", "title", "author")

    def resolve_author(self, info: Any) -> Any:
        """Record the call and hide every author.

        Args:
            info: The GraphQL resolve info.

        Returns:
            Always "None", so a served author proves the method was skipped.
        """
        _INERT_CALLS.append(1)
        return None


class InertQuery(ObjectType):
    """Root query listing posts with their auto-expanded author.

    Uses the flat paginated list field so the rows come back as a plain list.
    """

    posts = DjangoFilterPaginateListField(InertPostType)


inert_schema = DjangoGraphQLSchema(query=InertQuery, registries=isolated_pair(_RINERT))


# ---------------------------------------------------------------------------
# The WORKING to-ONE shape: an explicit declaration plus its resolver
# ---------------------------------------------------------------------------

_RHATCH = Registry()


class HatchAuthorType(DjangoObjectType):
    """Author node whose "get_queryset" hides everyone but "visible".

    The scope is what the parent type's declared resolver has to reapply by
    hand, since the auto-expanded FK read would skip it.
    """

    class Meta:
        """Configuration for "HatchAuthorType".

        Plain projection-free node; the scoping lives in the hook below.
        """

        model = Author
        registry = _RHATCH

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Scope the author rows this type is allowed to serve.

        Args:
            queryset: The base author queryset.
            info: The GraphQL resolve info.

        Returns:
            The queryset narrowed to the visible author.
        """
        return queryset.filter(name="visible")


class HatchPostType(DjangoObjectType):
    """Post node that DECLARES "author" so its resolver actually runs.

    This is the to-ONE snippet the guide ships, verbatim in shape: the declared
    field replaces the auto-derived FK field, and only that path wires a
    "resolve_" method.
    """

    author = Field(HatchAuthorType)

    class Meta:
        """Configuration for "HatchPostType".

        Keeps "author" in the projection so the declared field overrides an
        auto-derived one rather than adding a second field.
        """

        model = Post
        registry = _RHATCH
        only_fields = ("id", "title", "author")

    def resolve_author(self, info: Any) -> Any:
        """Apply the target type's scope to the auto-expanded FK read.

        Args:
            info: The GraphQL resolve info.

        Returns:
            The scoped author row, or "None" when the scope excludes it.
        """
        return HatchAuthorType.get_queryset(
            Author.objects.filter(pk=self.author_id), info
        ).first()


class HatchQuery(ObjectType):
    """Root query listing posts with the explicitly declared author field.

    Ordered by title in the assertions so the two rows compare stably.
    """

    posts = DjangoFilterPaginateListField(HatchPostType)


hatch_schema = DjangoGraphQLSchema(query=HatchQuery, registries=isolated_pair(_RHATCH))


# ---------------------------------------------------------------------------
# The to-MANY arm of the same hatch: a hand-mounted relation list
# ---------------------------------------------------------------------------

_RMANY = Registry()


class ManyPostType(DjangoObjectType):
    """Post node whose "get_queryset" hides everything but the public title.

    Serves as the child of the hand-mounted relation list below.
    """

    class Meta:
        """Configuration for "ManyPostType".

        Trimmed to the columns the assertions read.
        """

        model = Post
        registry = _RMANY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Scope the post rows this type is allowed to serve.

        Args:
            queryset: The base post queryset.
            info: The GraphQL resolve info.

        Returns:
            The queryset narrowed to the public posts.
        """
        return queryset.filter(title__startswith="pub")


class ManyAuthorType(DjangoObjectType):
    """Author node that REPLACES the auto-expanded "posts" container.

    The declared field is the to-MANY half of the documented hatch: it swaps
    the container for a list field whose resolver does apply the child type's
    scope.
    """

    posts = DjangoFilterListField(ManyPostType)

    class Meta:
        """Configuration for "ManyAuthorType".

        Keeps "posts" in the projection so the declaration overrides the
        auto-expanded container instead of adding a sibling field.
        """

        model = Author
        registry = _RMANY
        only_fields = ("id", "name", "posts")


class ManyQuery(ObjectType):
    """Root query listing authors with their hand-mounted post list.

    The parent list is itself hand-mounted so the relation resolves through the
    normal nested path.
    """

    authors = DjangoFilterListField(ManyAuthorType)


many_schema = DjangoGraphQLSchema(query=ManyQuery, registries=isolated_pair(_RMANY))


class OrderedManyQuery(ObjectType):
    """Root query mounting the same node behind a paginated, orderable list.

    The plain "DjangoFilterListField" above carries no "ordering" argument at
    all, so it cannot say whether the stamp took anything off the ordering
    axis. This one can.
    """

    authors = DjangoFilterPaginateListField(
        ManyAuthorType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, max_limit=20),
    )


ordered_many_schema = DjangoGraphQLSchema(
    query=OrderedManyQuery, registries=isolated_pair(_RMANY)
)


@pytest.mark.django_db
class BareResolveMethodIsInertTests(TestCase):
    """A "resolve_<relation>" alone never reaches the auto-derived FK field.

    Pins the shape the guide must not teach as a mitigation.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one post owned by one author.

        Returns:
            None.
        """
        author = Author.objects.create(name="hidden", bio="")
        Post.objects.create(title="p1", author=author)

    def test_bare_resolve_method_never_runs(self) -> None:
        """The relation is served despite a resolver that returns None.

        Returns:
            None.
        """
        _INERT_CALLS.clear()
        result = graphql_sync(
            inert_schema.graphql_schema,
            "{ posts { title author { name } } }",
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        assert result.data["posts"][0]["author"] == {"name": "hidden"}
        assert _INERT_CALLS == []


@pytest.mark.django_db
class DeclaredToOneHatchTests(TestCase):
    """The declared to-ONE field plus its resolver is the hatch that works.

    Executes the guide's to-ONE snippet end to end.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one visible-author post and one hidden-author post.

        Returns:
            None.
        """
        visible = Author.objects.create(name="visible", bio="")
        hidden = Author.objects.create(name="hidden", bio="")
        Post.objects.create(title="shown", author=visible)
        Post.objects.create(title="scoped", author=hidden)

    def test_declared_relation_field_runs_the_scope(self) -> None:
        """The excluded author is nulled out while the allowed one survives.

        Returns:
            None.
        """
        result = graphql_sync(
            hatch_schema.graphql_schema,
            '{ posts(ordering: "title") { title author { name } } }',
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        assert result.data["posts"] == [
            {"title": "scoped", "author": None},
            {"title": "shown", "author": {"name": "visible"}},
        ]


@pytest.mark.django_db
class DeclaredToManyHatchTests(TestCase):
    """The to-MANY half of the hatch: a hand-mounted relation list field.

    Executes the guide's to-MANY snippet end to end.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author owning one public and one private post.

        Returns:
            None.
        """
        author = Author.objects.create(name="writer", bio="")
        Post.objects.create(title="pub1", author=author)
        Post.objects.create(title="secret", author=author)

    def test_declared_relation_list_runs_the_scope(self) -> None:
        """The scoped-out post must not reach the response through the parent.

        Returns:
            None.
        """
        result = graphql_sync(
            many_schema.graphql_schema,
            "{ authors { name posts { title } } }",
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        assert result.data["authors"] == [
            {"name": "writer", "posts": [{"title": "pub1"}]}
        ]


@pytest.mark.django_db
class DeclaredRelationClosesBothProjectionAxesTests(TestCase):
    """Declaring the hatch withdraws the relation from ordering and filtering.

    Both axes read the relation UNSCOPED: "ordering" ranks by the raw foreign
    key on the parent's own row, and a nested filter compiles to an ORM join
    that never passes through the target type's "get_queryset". So a schema
    that leaves them open answers, one request at a time, the very question the
    resolver exists to refuse -- and a resolver that returns no author at all
    leaves a ranking oracle over a key NO type in the schema serves.

    The two shapes are indistinguishable at build time, because the difference
    lives in a resolver body. The boundary therefore fails CLOSED for both,
    which is what the guide already told readers to do by hand.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two posts owned by two different authors.

        Returns:
            None.
        """
        visible = Author.objects.create(name="visible", bio="")
        hidden = Author.objects.create(name="hidden", bio="")
        Post.objects.create(title="shown", author=visible)
        Post.objects.create(title="scoped", author=hidden)

    def test_the_relations_column_leaves_the_ordering_allowlist(self) -> None:
        """ "ordering: authorId" must be refused once the resolver is declared.

        Returns:
            None.
        """
        result = graphql_sync(
            hatch_schema.graphql_schema,
            '{ posts(ordering: "-authorId") { title } }',
        )
        assert result.errors is not None
        assert "Invalid ordering field" in str(result.errors[0])

    def test_the_relation_is_no_longer_traversable_by_the_filter(self) -> None:
        """A "filter_fields" path through the hatch stops the schema building.

        The refusal is a build-time contradiction between two Meta options, so
        it names the relation and the reason rather than dropping the entry --
        and the reason has to include this one, or the reader reads "publish
        'author'" while looking at 'author' in their own "only_fields".

        Returns:
            None.
        """
        with pytest.raises(ImproperlyConfigured) as caught:

            class FilterableHatchPostType(DjangoObjectType):
                """The same hatch, with the relation declared as a filter path.

                Building this type is the assertion: the declaration and the
                filter entry contradict each other.
                """

                author = Field(HatchAuthorType)

                class Meta:
                    """Configuration for "FilterableHatchPostType".

                    Filters across the very relation the declaration overrides.
                    """

                    model = Post
                    registry = _RHATCH
                    skip_registry = True
                    only_fields = ("id", "title", "author")
                    filter_fields = {"title": ("exact",), "author__name": ("exact",)}

                def resolve_author(self, info: Any) -> Any:
                    """Apply the target type's scope to the FK read.

                    Args:
                        info: The GraphQL resolve info.

                    Returns:
                        The scoped author row, or "None" when it is excluded.
                    """
                    return HatchAuthorType.get_queryset(
                        Author.objects.filter(pk=self.author_id), info
                    ).first()

            class FilterableQuery(ObjectType):
                """Root query mounting the contradictory type."""

                filterable_posts = DjangoFilterPaginateListField(
                    FilterableHatchPostType
                )

            DjangoGraphQLSchema(
                query=FilterableQuery, registries=isolated_pair(_RHATCH)
            )

        message = str(caught.value)
        assert "traverses 'author'" in message
        assert "over a resolver of its own" in message


@pytest.mark.django_db
class DeclaredToManyHatchClosesTheFilterAxisTests(TestCase):
    """The to-MANY arm answers the traversal question the same way.

    "posts = DjangoFilterListField(PostType)" is the hatch the guide ships for
    the to-MANY direction, and it carries a resolver for exactly the reason the
    to-ONE declaration does: the rows the client reads are the ones that
    resolver hands back. A "posts__title" filter compiles to a JOIN that never
    reaches it, so leaving the hop traversable answers through the relation the
    very question the hatch exists to refuse -- while the byte-equivalent
    to-ONE shape is refused. One rule, both directions.

    The to-MANY relation owns no column on the parent row, so the stamp costs
    the type nothing on the ordering axis; only traversal closes.
    """

    def test_the_relation_is_no_longer_traversable_by_the_filter(self) -> None:
        """A "filter_fields" path through the to-MANY hatch stops the build.

        Returns:
            None.
        """
        with pytest.raises(ImproperlyConfigured) as caught:

            class FilterableManyAuthorType(DjangoObjectType):
                """The to-MANY hatch, with the relation declared as a path.

                Building this type is the assertion.
                """

                posts = DjangoFilterListField(ManyPostType)

                class Meta:
                    """Configuration for "FilterableManyAuthorType".

                    Filters across the very relation the declaration replaces.
                    """

                    model = Author
                    registry = _RMANY
                    skip_registry = True
                    only_fields = ("id", "name", "posts")
                    filter_fields = {"name": ("exact",), "posts__title": ("exact",)}

            class FilterableManyQuery(ObjectType):
                """Root query mounting the contradictory type."""

                filterable_authors = DjangoFilterListField(FilterableManyAuthorType)

            DjangoGraphQLSchema(
                query=FilterableManyQuery, registries=isolated_pair(_RMANY)
            )

        message = str(caught.value)
        assert "traverses 'posts'" in message
        assert "over a resolver of its own" in message

    def test_the_parents_own_columns_stay_orderable(self) -> None:
        """The stamp costs the to-MANY arm nothing on the ordering axis.

        A reverse foreign key owns no column on the parent row, so there is no
        key behind it to withdraw -- which is the whole difference between what
        this arm of the hatch costs and what the to-ONE one does.

        Returns:
            None.
        """
        Author.objects.create(name="zed", bio="")
        Author.objects.create(name="amy", bio="")

        result = graphql_sync(
            ordered_many_schema.graphql_schema,
            '{ authors(ordering: "name") { name } }',
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        assert [row["name"] for row in result.data["authors"]] == ["amy", "zed"]


class DeclaredListObjectFieldClosesTheSameWayTests(TestCase):
    """The THIRD spelling of a declared to-many relation answers alike.

    A relation can be declared three ways -- "DjangoFilterListField",
    "DjangoFilterPaginateListField", and the container "DjangoListObjectField"
    (which "DjangoNestedListObjectField" subclasses). All three replace the
    auto-expanded relation and all three carry a resolver, so all three hide the
    rows a traversal would otherwise join straight past. Closing only two of them
    made the boundary answer differently for three ways of writing one intent.
    """

    def test_a_declared_container_is_no_longer_traversable(self) -> None:
        """A "filter_fields" path through a declared container stops the build.

        Returns:
            None.
        """
        from django_graphex.fields import DjangoListObjectField
        from django_graphex.types import DjangoListObjectType

        reg = Registry()

        class ThirdPostType(DjangoObjectType):
            """The node the declared container serves."""

            class Meta:
                """Bind the node to "Post" inside an isolated registry."""

                model = Post
                registry = reg
                only_fields = ("id", "title")

        class ThirdPostListType(DjangoListObjectType):
            """The container spelling of the same relation."""

            class Meta:
                """Bind the container to "Post" with its own pagination."""

                model = Post
                registry = reg
                pagination = LimitOffsetGraphqlPagination(default_limit=10)

        with pytest.raises(ImproperlyConfigured) as caught:

            class ThirdAuthorType(DjangoObjectType):
                """Declares the relation as a container and filters through it.

                Building this type is the assertion.
                """

                posts = DjangoListObjectField(ThirdPostListType)

                class Meta:
                    """Filter across the very relation the declaration replaces."""

                    model = Author
                    registry = reg
                    skip_registry = True
                    only_fields = ("id", "name", "posts")
                    filter_fields = {"name": ("exact",), "posts__title": ("exact",)}

            class ThirdQuery(ObjectType):
                """Root query mounting the contradictory type."""

                third_authors = DjangoFilterListField(ThirdAuthorType)

            DjangoGraphQLSchema(query=ThirdQuery, registries=isolated_pair(reg))

        assert "posts" in str(caught.value)
