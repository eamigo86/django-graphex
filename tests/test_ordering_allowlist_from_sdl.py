# -*- coding: utf-8 -*-
"""Tests for the ordering allowlist being READ from the compiled type, not mirrored.

Four rounds of fixes chased one defect through its instances. The allowlist that
decides which columns "ordering" may name was built by RE-IMPLEMENTING the three
filters "core.output_compiler.compile_output_fields" applies -- a mirror of the
compiler, held in a second place, drifting from it on every shape the copy did
not anticipate:

  - a multi-table-inheritance child publishes the PARENT's key as "id" while its
    own pk is the parent link, so the mirror concluded the type hid its primary
    key and refused cursor pagination on a configuration whose SDL plainly
    carries "id",
  - an explicitly declared field re-exposes a concrete column "only_fields"
    removed (types "_compile_declared_fields" lets a real class attribute win),
    so the mirror refused ordering by a column the SDL shows,
  - and the enumeration of "deliberate differences" written in the mirror's own
    docstring already had one entry wrong, which is how the first hole survived
    two reviews.

The allowlist is now DERIVED from the compiled type's own field map. The compiled
type IS the SDL, so "orderable" and "selectable" cannot drift apart, and every
filter the compiler grows later is inherited without a second edit. The mapping
back to ORM attnames is the only real work left and is pinned here: a forward FK
published as "author" orders by "author_id".

Also pinned here, because a per-schema fact used to live on a process-global
object: two schemas over ONE list container class each get their own answer.
Before this, building the second schema re-stamped the shared paginator and the
FIRST schema started accepting the hidden column again at runtime.
"""

from __future__ import annotations

from copy import copy

from django.test import TestCase
from graphql import GraphQLObjectType, GraphQLString, graphql_sync

from django_graphex.core import CharField, ObjectType
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    projected_ordering_attnames,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import Author, CustomPKProduct, MtiRestaurant, Post

# ---------------------------------------------------------------------------
# Multi-table inheritance: the child's pk is the parent link, published as "id"
# ---------------------------------------------------------------------------

_RMTI2 = Registry()


class SdlMtiRestaurantType(DjangoObjectType):
    """Child node of a multi-table-inherited model under an "only_fields" list.

    "only_fields" is what makes this shape sharp: the implicit "mtiplace_ptr"
    parent link can never appear in such a list (it is join plumbing the
    compiler drops), so a mirror that filters on the FIELD NAME concludes the
    primary key was projected away -- while the SDL carries the parent's "id",
    whose value is the very same row identifier.
    """

    class Meta:
        """Configuration for "SdlMtiRestaurantType".

        Names "id" explicitly, so the type's own SDL is the proof that the key
        is exposed.
        """

        model = MtiRestaurant
        registry = _RMTI2
        only_fields = ("id", "name", "serves_pizza")


class SdlMtiRestaurantListType(DjangoListObjectType):
    """Cursor-paginated container over "SdlMtiRestaurantType".

    Cursor pagination is the path that refuses a type hiding its primary key,
    so it is the one that has to accept this one.
    """

    class Meta:
        """Configuration for "SdlMtiRestaurantListType".

        Orders by "name", a column the node type exposes, so nothing but the
        primary-key question can make this configuration fail.
        """

        model = MtiRestaurant
        registry = _RMTI2
        pagination = CursorGraphqlPagination(ordering="name", page_size=2)


class SdlMtiQuery(ObjectType):
    """Root query exposing the cursor-paginated MTI child list.

    Feeds the multi-table-inheritance tests below.
    """

    restaurants = DjangoListObjectField(SdlMtiRestaurantListType)


sdl_mti_schema = DjangoGraphQLSchema(
    query=SdlMtiQuery, registries=isolated_pair(_RMTI2)
)


# ---------------------------------------------------------------------------
# A declared class attribute re-exposes a column "only_fields" removed
# ---------------------------------------------------------------------------

_RDECL = Registry()


class SdlDeclaredAuthorType(DjangoObjectType):
    """Author node whose "only_fields" drops "bio" while a declared field restores it.

    "types._compile_declared_fields" lets a REAL class attribute win over the
    model-derived field of the same name, so "bio" is published after all. A
    mirror reading "Meta.only_fields" cannot see that, and refused to order by
    a column the SDL shows.
    """

    bio = CharField()

    class Meta:
        """Configuration for "SdlDeclaredAuthorType".

        Restricts the model-derived fields to "id" and "name"; the declared
        "bio" attribute above re-publishes the third column.
        """

        model = Author
        registry = _RDECL
        only_fields = ("id", "name")


class SdlDeclaredAuthorListType(DjangoListObjectType):
    """Paginated container over "SdlDeclaredAuthorType".

    Present so the node type is compiled into a schema and its "ordering"
    argument can be exercised.
    """

    class Meta:
        """Configuration for "SdlDeclaredAuthorListType".

        Declares no projection of its own; the node type's applies.
        """

        model = Author
        registry = _RDECL
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class SdlDeclaredQuery(ObjectType):
    """Root query exposing the author list whose node re-declares "bio".

    Feeds the declared-field tests below.
    """

    authors = DjangoListObjectField(SdlDeclaredAuthorListType)


sdl_declared_schema = DjangoGraphQLSchema(
    query=SdlDeclaredQuery, registries=isolated_pair(_RDECL)
)


# ---------------------------------------------------------------------------
# Two schemas over ONE list container class
# ---------------------------------------------------------------------------

_RFORK_A = Registry()
_RFORK_B = Registry()


class ForkAuthorProjectedType(DjangoObjectType):
    """Author node hiding "bio", registered in the FIRST schema's registry.

    The first schema's node type. Its projection is the answer the first
    schema's list field has to keep after any number of later schema builds.
    """

    class Meta:
        """Configuration for "ForkAuthorProjectedType".

        Hides "bio" so an ordering term naming it must be refused.
        """

        model = Author
        registry = _RFORK_A
        only_fields = ("id", "name")


class ForkAuthorOpenType(DjangoObjectType):
    """Author node exposing every column, registered in the SECOND schema's registry.

    Building a schema against this registry re-resolves the SHARED container
    class's results element to this unprojected type. Before the fix the
    container's paginator was a single process-global object, so that second
    build wrote its answer over the first schema's.
    """

    class Meta:
        """Configuration for "ForkAuthorOpenType".

        Projects nothing away, which is what makes the cross-schema overwrite
        visible: the first schema's allowlist is replaced by "no allowlist".
        """

        model = Author
        registry = _RFORK_B


class ForkAuthorListType(DjangoListObjectType):
    """The ONE list container class both schemas compile.

    Sharing the container between schemas is the whole point: its resolved
    paginator carries a PER-SCHEMA fact (which columns THIS schema's node type
    publishes), so that fact cannot live on an object the schemas share.
    """

    class Meta:
        """Configuration for "ForkAuthorListType".

        Carries the module-level paginator instance both schemas resolve.
        """

        model = Author
        registry = _RFORK_A
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class ForkQuery(ObjectType):
    """Root query mounting the shared container, compiled into both schemas.

    One root class, two schemas, two registries -- the shape a project reaches
    for when it serves a public and an internal schema from one set of types.
    """

    authors = DjangoListObjectField(ForkAuthorListType)


# ---------------------------------------------------------------------------
# One paginator instance mounted on two list CONTAINERS in one schema
# ---------------------------------------------------------------------------

_RTWIN = Registry()

#: Mounted on BOTH containers below. A module-level paginator reused across
#: several list types is the ordinary shape, so the per-schema stamp has to land
#: on a copy or the last container compiled decides both answers.
_twin_paginator = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class TwinAuthorType(DjangoObjectType):
    """Author node hiding "bio", served by the first container.

    Its allowlist must survive the compilation of the second container.
    """

    class Meta:
        """Configuration for "TwinAuthorType".

        Hides "bio" and keeps "name" orderable.
        """

        model = Author
        registry = _RTWIN
        only_fields = ("id", "name")


class TwinPostType(DjangoObjectType):
    """Post node hiding "views", served by the second container.

    Declared after the author node so, without the copy, its columns are the
    ones both containers end up validating against.
    """

    class Meta:
        """Configuration for "TwinPostType".

        Hides "views" and keeps "title" orderable.
        """

        model = Post
        registry = _RTWIN
        only_fields = ("id", "title")


class TwinAuthorListType(DjangoListObjectType):
    """Author container carrying the shared paginator instance.

    Half of the pair whose two answers must not collapse into one.
    """

    class Meta:
        """Configuration for "TwinAuthorListType".

        Mounts the module-level paginator shared with the post container.
        """

        model = Author
        registry = _RTWIN
        pagination = _twin_paginator


class TwinPostListType(DjangoListObjectType):
    """Post container carrying the SAME paginator instance.

    The other half of the pair.
    """

    class Meta:
        """Configuration for "TwinPostListType".

        Mounts the very same paginator object the author container mounts.
        """

        model = Post
        registry = _RTWIN
        pagination = _twin_paginator


class TwinQuery(ObjectType):
    """Root query exposing both containers built on one paginator instance.

    Feeds the shared-instance test below.
    """

    authors = DjangoListObjectField(TwinAuthorListType)
    posts = DjangoListObjectField(TwinPostListType)


twin_schema = DjangoGraphQLSchema(query=TwinQuery, registries=isolated_pair(_RTWIN))


# ---------------------------------------------------------------------------
# One paginator instance mounted on two flat filter-paginate list fields
# ---------------------------------------------------------------------------

_RSHARED = Registry()

#: Mounted on BOTH fields below. "DjangoFilterPaginateListField" copies it
#: before stamping; without that copy the last field constructed decides every
#: other field's allowlist.
_shared_flat_paginator = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class SharedFlatAuthorType(DjangoObjectType):
    """Author node hiding "bio", mounted on the first flat list field.

    Its allowlist must survive the construction of the second field below.
    """

    class Meta:
        """Configuration for "SharedFlatAuthorType".

        Hides "bio" and keeps "name" orderable.
        """

        model = Author
        registry = _RSHARED
        only_fields = ("id", "name")


class SharedFlatPostType(DjangoObjectType):
    """Post node hiding "views", mounted on the second flat list field.

    Declared AFTER the author node so, without the copy, its columns are the
    ones both fields end up validating against.
    """

    class Meta:
        """Configuration for "SharedFlatPostType".

        Hides "views" and keeps "title" orderable. "author" is listed so the
        forward-FK name-to-attname mapping has a published relation to read.
        """

        model = Post
        registry = _RSHARED
        only_fields = ("id", "title", "author")


class SharedFlatQuery(ObjectType):
    """Root query mounting two flat paginated lists on ONE paginator instance.

    The two node types project different columns away, so a shared allowlist
    is visible immediately: each field starts refusing the other's columns.
    """

    authors = DjangoFilterPaginateListField(
        SharedFlatAuthorType, pagination=_shared_flat_paginator
    )
    posts = DjangoFilterPaginateListField(
        SharedFlatPostType, pagination=_shared_flat_paginator
    )


shared_flat_schema = DjangoGraphQLSchema(
    query=SharedFlatQuery, registries=isolated_pair(_RSHARED)
)


def _errors(schema: DjangoGraphQLSchema, query: str) -> list[str]:
    """Execute "query" against "schema" and return its error messages.

    Args:
        schema: The compiled schema to execute against.
        query: The GraphQL document to execute.

    Returns:
        The list of error messages, empty when the query succeeded.
    """
    result = graphql_sync(schema.graphql_schema, query)
    return [str(err.message) for err in (result.errors or [])]


# ---------------------------------------------------------------------------


class TestMtiChildKeepsCursorPagination(TestCase):
    """A multi-table-inherited child publishing "id" is not hiding its primary key.

    The cursor guard refuses a type that hides its pk, because every cursor
    carries the pk as its tiebreak. On an MTI child the pk column is the parent
    link, which the compiler drops from the SDL as join plumbing while
    publishing the parent's "id" -- the SAME value. A guard that refuses this
    configuration is as much a defect as the leak it was added for.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two restaurants so a cursor page has a boundary to encode.

        Two rows are the minimum that makes "hasNextPage" and the boundary
        cursors meaningful at "page_size=2".
        """
        MtiRestaurant.objects.create(name="Alfa", address="1 A St", serves_pizza=True)
        MtiRestaurant.objects.create(name="Bravo", address="2 B St", serves_pizza=False)

    def test_the_parents_key_is_in_the_sdl(self) -> None:
        """Assert the compiled node type publishes "id" and not the parent link.

        This is the fact the guard has to read. If it fails, the rest of the
        class is testing the wrong shape.
        """
        gql_type = sdl_mti_schema.graphql_schema.type_map["SdlMtiRestaurantType"]
        assert "id" in gql_type.fields
        assert "mtiplacePtr" not in gql_type.fields

    def test_cursor_pagination_is_not_refused(self) -> None:
        """Assert the cursor list resolves instead of raising the hidden-pk error.

        The mirror concluded the primary key was projected away because the
        parent link cannot appear in an "only_fields" list, and refused every
        request.
        """
        errors = _errors(
            sdl_mti_schema,
            "{ restaurants { results { id name } } }",
        )
        assert errors == []

    def test_cursor_page_info_is_served(self) -> None:
        """Assert the cursor "pageInfo" resolves, which is the second guarded seam.

        Both "paginate_queryset" and "get_page_info" resolve the ordering
        through the same helper, so both had to be refused before and both have
        to work now.
        """
        result = graphql_sync(
            sdl_mti_schema.graphql_schema,
            "{ restaurants { pageInfo { hasNextPage endCursor } } }",
        )
        assert result.errors is None
        assert result.data["restaurants"]["pageInfo"]["endCursor"]

    def test_the_pk_aliases_are_orderable(self) -> None:
        """Assert "pk" and the parent-link attname stay in the derived allowlist.

        Both are spellings of the child's own key column, whose value the type
        already publishes as "id". Dropping them would take the pk tiebreak of
        every ordering path down with them.
        """
        gql_type = sdl_mti_schema.graphql_schema.type_map["SdlMtiRestaurantType"]
        allowed = projected_ordering_attnames(MtiRestaurant, gql_type)
        assert allowed is not None
        assert {"pk", "id", "mtiplace_ptr_id"} <= allowed
        assert "address" not in allowed


class TestDeclaredFieldReopensAColumn(TestCase):
    """A declared class attribute re-publishes a column "only_fields" removed.

    The compiler lets a real class attribute win over the model-derived field of
    the same name. Reading "Meta.only_fields" cannot see that; reading the
    compiled type does.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors with distinct bios so an ordering has an effect.

        The rows only need to exist; the assertion is on the ordering being
        accepted, not on the sequence.
        """
        Author.objects.create(name="Zoe", bio="zeta")
        Author.objects.create(name="Ada", bio="alpha")

    def test_the_declared_column_is_in_the_sdl(self) -> None:
        """Assert "bio" really is published despite the "only_fields" list.

        Without this the ordering assertion below would be pinning a column
        nobody can read, which is the opposite of the point.
        """
        gql_type = sdl_declared_schema.graphql_schema.type_map["SdlDeclaredAuthorType"]
        assert "bio" in gql_type.fields

    def test_ordering_by_the_declared_column_is_accepted(self) -> None:
        """Assert ordering by the re-published column is no longer refused.

        A column the SDL shows is readable, so ranking rows by it reveals
        nothing the client cannot already select.
        """
        errors = _errors(
            sdl_declared_schema,
            '{ authors { results(ordering: "bio") { id name bio } } }',
        )
        assert errors == []

    def test_a_column_neither_path_publishes_is_still_refused(self) -> None:
        """Assert the allowlist did not simply widen to every concrete column.

        "Post.body" has no analogue here, so the check uses the author column
        that neither "only_fields" nor a declared attribute re-publishes.
        """
        gql_type = sdl_declared_schema.graphql_schema.type_map["SdlDeclaredAuthorType"]
        allowed = projected_ordering_attnames(Author, gql_type)
        assert allowed is not None
        assert allowed == {"id", "name", "bio", "pk"}


class TestAllowlistMapsSdlNamesBackToAttnames(TestCase):
    """The SDL publishes field NAMES; the ORM orders by ATTNAMES.

    A forward foreign key published as "author" is ordered by "author_id", so
    the mapping is real work rather than a rename. It is pinned directly because
    getting it wrong silently refuses a legitimate ordering.
    """

    def test_a_forward_fk_maps_to_its_id_column(self) -> None:
        """Assert an FK published under its relation name yields the id attname.

        The id is already readable through the relation itself, so gating it
        would break a working ordering without hiding anything.
        """
        gql_type = shared_flat_schema.graphql_schema.type_map["SharedFlatPostType"]
        allowed = projected_ordering_attnames(Post, gql_type)
        assert allowed is not None
        assert "author" in gql_type.fields
        assert "author_id" in allowed

    def test_a_hidden_natural_key_takes_its_aliases_with_it(self) -> None:
        """Assert a projected-away natural primary key leaves no orderable spelling.

        A slug or a code carries business data and is hidden like any other
        column; while it is hidden, "pk", its name and its attname all resolve
        to the same unreadable column.
        """
        empty = GraphQLObjectType("Empty", lambda: {"title": GraphQLString})
        allowed = projected_ordering_attnames(CustomPKProduct, empty)
        assert allowed == {"title"}

    def test_an_unavailable_compiled_type_fails_closed(self) -> None:
        """Assert a node the registry could not resolve allows NOTHING.

        The derivation reads the compiled type; when there is none there is no
        SDL to read, and the safe answer is an empty allowlist rather than a
        fall back to the model's every column.
        """
        assert projected_ordering_attnames(Author, GraphQLString) == frozenset()
        assert projected_ordering_attnames(Author, None) == frozenset()


class TestAllowlistIsPerSchema(TestCase):
    """Two schemas over one list container class must each keep their own answer.

    Which columns a node type publishes is a PER-SCHEMA fact, so it cannot live
    on the paginator instance the schemas share. Before the fix, building the
    second schema replaced the first schema's allowlist with its own, and the
    first schema started sorting by the hidden column again at runtime.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author so the list resolves to a real row.

        The assertion is on the ordering being refused, but a resolving list
        proves the refusal is the allowlist and not a broken schema.
        """
        Author.objects.create(name="Ada", bio="alpha")

    def test_the_first_schema_still_refuses_after_the_second_is_built(self) -> None:
        """Assert building a second schema does not re-open the first one's oracle.

        Both schemas are built inside the test so the ordering of the two builds
        is the thing under test, not a module-import accident.
        """
        first = DjangoGraphQLSchema(query=ForkQuery, registries=isolated_pair(_RFORK_A))
        query = '{ authors { results(ordering: "bio") { id } } }'
        assert _errors(first, query) == ["Invalid ordering field: 'bio'."]

        second = DjangoGraphQLSchema(
            query=ForkQuery, registries=isolated_pair(_RFORK_B)
        )
        # The second schema's node type publishes every column, so it legitimately
        # accepts the ordering the first one refuses.
        assert _errors(second, query) == []
        assert _errors(first, query) == ["Invalid ordering field: 'bio'."]

    def test_the_shared_container_paginator_is_never_mutated(self) -> None:
        """Assert the class-level paginator carries no per-schema allowlist at all.

        This is the structural half of the guarantee: as long as the shared
        object holds no answer, no schema build can overwrite another's.
        """
        DjangoGraphQLSchema(query=ForkQuery, registries=isolated_pair(_RFORK_A))
        DjangoGraphQLSchema(query=ForkQuery, registries=isolated_pair(_RFORK_B))
        shared = ForkAuthorListType._meta.paginator
        assert shared.ordering_allowed_attnames is None


class TestSharedPaginatorAcrossContainers(TestCase):
    """Two list containers sharing ONE paginator instance keep two answers.

    A module-level paginator reused across list types is the ordinary shape.
    The per-schema allowlist is stamped on a COPY inside each container's fields
    thunk; without that copy the two thunks overwrite each other and each
    container starts validating against the other's columns.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author and one post so both containers resolve rows.

        Both lists are exercised, so both models need a row.
        """
        author = Author.objects.create(name="Ada", bio="alpha")
        Post.objects.create(title="First", body="b", author=author, views=3)

    def test_each_container_orders_by_its_own_exposed_column(self) -> None:
        """Assert neither container validates against the other's columns.

        This is the mutation pin for the thunk-local copy: share the instance
        and exactly one of these two orderings survives.
        """
        assert (
            _errors(twin_schema, '{ authors { results(ordering: "name") { id } } }')
            == []
        )
        assert (
            _errors(twin_schema, '{ posts { results(ordering: "title") { id } } }')
            == []
        )

    def test_each_container_still_refuses_its_own_hidden_column(self) -> None:
        """Assert both copies carry a real allowlist rather than no allowlist.

        A copy stamped with "None" would satisfy the test above for the wrong
        reason, so the refusals are pinned next to it.
        """
        assert _errors(
            twin_schema, '{ authors { results(ordering: "bio") { id } } }'
        ) == ["Invalid ordering field: 'bio'."]
        assert _errors(
            twin_schema, '{ posts { results(ordering: "views") { id } } }'
        ) == ["Invalid ordering field: 'views'."]

    def test_the_mounted_instance_is_left_untouched(self) -> None:
        """Assert the paginator the caller constructed carries no allowlist.

        The shared object holding no answer is what makes it impossible for one
        container's compile to overwrite another's.
        """
        assert _twin_paginator.ordering_allowed_attnames is None


class TestFlatListFieldCopiesItsPaginator(TestCase):
    """One paginator instance mounted on two flat list fields keeps two answers.

    "DjangoFilterPaginateListField" paginates in its OWN resolver, so it stamps
    its own copy. Deleting that copy makes the last field constructed decide
    every other field's allowlist -- each field then starts refusing the columns
    its own type publishes.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author and one post so both flat lists resolve rows.

        Both fields are exercised, so both models need a row.
        """
        author = Author.objects.create(name="Ada", bio="alpha")
        Post.objects.create(title="First", body="b", author=author, views=3)

    def test_each_field_orders_by_its_own_exposed_column(self) -> None:
        """Assert neither field validates against the other's columns.

        This is the mutation pin: without the copy the two fields share one
        allowlist and exactly one of these two orderings survives.
        """
        assert _errors(shared_flat_schema, '{ authors(ordering: "name") { id } }') == []
        assert _errors(shared_flat_schema, '{ posts(ordering: "title") { id } }') == []

    def test_each_field_still_refuses_its_own_hidden_column(self) -> None:
        """Assert the copies carry a real allowlist rather than no allowlist.

        A copy stamped with "None" would pass the test above for the wrong
        reason, so the refusals are pinned alongside it.
        """
        assert _errors(shared_flat_schema, '{ authors(ordering: "bio") { id } }') == [
            "Invalid ordering field: 'bio'."
        ]
        assert _errors(shared_flat_schema, '{ posts(ordering: "views") { id } }') == [
            "Invalid ordering field: 'views'."
        ]

    def test_the_mounted_instance_is_not_the_stamped_one(self) -> None:
        """Assert the paginator the caller constructed is left untouched.

        A caller may mount one instance on any number of fields; stamping it in
        place would make the mount order decide the schema's ordering surface.
        """
        assert _shared_flat_paginator.ordering_allowed_attnames is None
        assert copy(_shared_flat_paginator).ordering_allowed_attnames is None
