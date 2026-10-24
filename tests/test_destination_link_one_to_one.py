"""Forward OneToOne links honor the destination row scope, in one query."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, AuthorProfile, Post, Tag


def _hide_prefix(field: str) -> Any:
    """Build a row hook hiding rows whose field starts with "hidden".

    Args:
        field: Name of the column the hook inspects.

    Returns:
        A classmethod usable as a destination get_queryset.
    """

    def hook(cls: Any, queryset: QuerySet, info: Any) -> QuerySet:
        """Hide rows by prefix.

        Args:
            cls: The output type.
            queryset: The unscoped queryset.
            info: The request resolve info.

        Returns:
            The visible rows.
        """
        return queryset.exclude(**{f"{field}__startswith": "hidden"})

    return classmethod(hook)


def _profile_schema(nested: bool) -> DjangoGraphQLSchema:
    """Build profile mutations whose author destination hides some rows.

    Args:
        nested: Whether the author is also a nested field.

    Returns:
        The executable schema.
    """

    class ScopedAuthor(DjangoObjectType):
        """Publish only authors that are not hidden."""

        class Meta:
            """Bind the author model."""

            model = Author

        get_queryset = _hide_prefix("name")

    assert ScopedAuthor._meta.model is Author

    class ProfileCRUD(DjangoModelMutation):
        """Expose generated profile mutations."""

        class Meta:
            """Bind the profile model."""

            model = AuthorProfile
            if nested:
                nested_fields = {"author": Author}

    create, _delete, update = ProfileCRUD.MutationFields()

    class Query(ObjectType):
        """Provide the required query root."""

        ready = BooleanField()

    class Mutation(ObjectType):
        """Expose generated profile roots."""

        profile_create = create
        profile_update = update

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    )


def _run(schema: DjangoGraphQLSchema, query: str) -> dict[str, Any]:
    """Execute a mutation and return its single payload.

    Args:
        schema: Schema under test.
        query: Mutation document.

    Returns:
        The payload of the only root field.
    """
    result = graphql_sync(
        schema.graphql_schema,
        query,
        context_value=RequestFactory().post("/graphql/"),
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    return next(iter(result.data.values()))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("shape", "operation"),
    (
        ("scalar", "create"),
        ("scalar", "update"),
        ("nested_id", "update"),
    ),
)
def test_forward_one_to_one_hidden_equals_missing(shape: str, operation: str) -> None:
    """A hidden forward OneToOne target answers exactly like an absent row.

    Args:
        shape: Plain ID or nested id-only payload.
        operation: Generated create or update.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden-a")
    spare = Author.objects.create(name="visible-spare")
    existing = AuthorProfile.objects.create(author=spare, bio="original")
    with isolated_default_pair():
        schema = _profile_schema(nested=shape == "nested_id")

        def attempt(identifier: int) -> dict[str, Any]:
            """Try to point a profile at one author ID.

            Args:
                identifier: Requested author pk.

            Returns:
                The mutation payload.
            """
            link = (
                f'author: "{identifier}"'
                if shape == "scalar"
                else f'author: {{id: "{identifier}"}}'
            )
            if operation == "create":
                return _run(
                    schema,
                    f'mutation {{ profileCreate(newAuthorprofile: {{bio: "x", {link}}})'
                    " { ok errors { field messages } } }",
                )
            return _run(
                schema,
                f'mutation {{ profileUpdate(newAuthorprofile: {{id: "{existing.pk}", '
                f"{link}}}) {{ ok errors {{ field messages }} }} }}",
            )

        hidden_result = attempt(hidden.pk)
        missing_id = hidden.pk + 1000000
        missing_result = attempt(missing_id)
        ok_result = attempt(visible.pk)

    assert hidden_result["ok"] is False
    assert hidden_result["errors"] == [
        {
            "field": "author",
            "messages": [f'Invalid pk "{hidden.pk}" - object does not exist.'],
        }
    ]
    assert missing_result["ok"] is False
    assert missing_result["errors"] == [
        {
            "field": "author",
            "messages": [f'Invalid pk "{missing_id}" - object does not exist.'],
        }
    ]
    assert ok_result["ok"] is True
    assert not AuthorProfile.objects.filter(author=hidden).exists()


@pytest.mark.django_db
def test_forward_one_to_one_update_keeping_current_target_is_allowed() -> None:
    """Re-sending the current (now hidden) author is not a new link.

    The profile keeps pointing at the same row, so nothing is re-scoped.
    """
    author = Author.objects.create(name="hidden-current")
    profile = AuthorProfile.objects.create(author=author, bio="original")
    with isolated_default_pair():
        schema = _profile_schema(nested=True)
        payload = _run(
            schema,
            f'mutation {{ profileUpdate(newAuthorprofile: {{id: "{profile.pk}", '
            f'bio: "edited", author: {{id: "{author.pk}"}}}}) '
            "{ ok errors { field messages } } }",
        )
    assert payload["ok"] is True, payload
    profile.refresh_from_db()
    assert profile.bio == "edited"


@pytest.mark.django_db
def test_link_membership_uses_one_query_per_relation() -> None:
    """Many M2M IDs cost one membership query, not one per ID.

    The query count must not grow with the number of linked IDs.
    """
    author = Author.objects.create(name="visible")
    tags = [Tag.objects.create(label=f"t{i}") for i in range(60)]
    with isolated_default_pair():

        class ScopedTag(DjangoObjectType):
            """Hide tags whose label starts with hidden."""

            class Meta:
                """Bind the tag model."""

                model = Tag

            get_queryset = _hide_prefix("label")

        assert ScopedTag._meta.model is Tag

        class PostCRUD(DjangoModelMutation):
            """Expose generated post mutations."""

            class Meta:
                """Bind the post model."""

                model = Post

        create, _delete, _update = PostCRUD.MutationFields()

        class Query(ObjectType):
            """Provide the required query root."""

            ready = BooleanField()

        class Mutation(ObjectType):
            """Expose the create root."""

            post_create = create

        schema = DjangoGraphQLSchema(
            query=Query,
            mutation=Mutation,
            registries=isolated_pair(get_global_registry()),
        )

        def write(count: int) -> int:
            """Create a post linking the first tags and count its queries.

            Args:
                count: Number of tag IDs to link.

            Returns:
                The number of SQL queries the mutation ran.
            """
            ids = ", ".join(f'"{tag.pk}"' for tag in tags[:count])
            document = (
                f'mutation {{ postCreate(newPost: {{title: "many-{count}", body: "", '
                f'author: "{author.pk}", tags: [{ids}]}}) '
                "{ ok errors { field messages } } }"
            )
            with CaptureQueriesContext(connection) as queries:
                payload = _run(schema, document)
            assert payload["ok"] is True, payload
            assert Post.objects.get(title=f"many-{count}").tags.count() == count
            return len(queries)

        small = write(5)
        large = write(60)

    # Only the batched M2M insert may grow with the number of linked rows.
    assert large <= small + 1, (small, large)


@pytest.mark.django_db
def test_out_of_range_and_malformed_ids_are_reported_missing() -> None:
    """Report values no row can hold as missing.

    A valid ID in a later request still succeeds.
    """
    visible = Author.objects.create(name="visible")
    with isolated_default_pair():
        schema = _profile_schema(nested=False)
        huge = 10**30
        payloads = [
            _run(
                schema,
                f'mutation {{ profileCreate(newAuthorprofile: {{bio: "x", author: "{value}"}})'
                " { ok errors { field messages } } }",
            )
            for value in (huge, "abc")
        ]
        good = _run(
            schema,
            f'mutation {{ profileCreate(newAuthorprofile: {{bio: "x", author: "{visible.pk}"}})'
            " { ok errors { field messages } } }",
        )
    assert [p["ok"] for p in payloads] == [False, False]
    assert payloads[0]["errors"][0]["messages"] == [
        f'Invalid pk "{huge}" - object does not exist.'
    ]
    assert good["ok"] is True
