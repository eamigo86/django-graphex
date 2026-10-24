"""Nested id links: SQL-variable limits, host scope, no-op re-sends, big ids."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.db.models.signals import post_save
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from django_graphex.utils import present_values
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, Post, Tag

_MANY = 33_000


def _build(
    *, output_scope: bool, host_scope: bool = False, nested_tags: bool = True
) -> DjangoGraphQLSchema:
    """Build a schema whose Post update accepts nested tags and author.

    Args:
        output_scope: Whether Tag gets an output type hiding "hidden" labels.
        host_scope: Whether a Tag update host hides "hidden" labels.
        nested_tags: Whether tags are nested objects instead of plain ids.

    Returns:
        The compiled schema with a "postUpdate" mutation.
    """
    if output_scope:

        class TagType(DjangoObjectType):
            """Output type hiding hidden tags."""

            class Meta:
                """Bind to the default registry."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide tags labelled hidden.

                Args:
                    queryset: Unscoped rows.
                    info: Request resolve info.

                Returns:
                    The visible rows.
                """
                return queryset.exclude(label__startswith="hidden")

    if host_scope:

        class TagHost(DjangoModelType):
            """Update host hiding hidden tags."""

            class Meta:
                """Serve only update."""

                model = Tag
                model_operations = ("update",)

            @classmethod
            def filter_queryset(cls, queryset: QuerySet, info: Any, **kw: Any) -> Any:
                """Hide tags labelled hidden.

                Args:
                    queryset: Unscoped rows.
                    info: Request resolve info.
                    **kw: Unused filter arguments.

                Returns:
                    The visible rows.
                """
                return queryset.exclude(label__startswith="hidden")

        class AuthorHost(DjangoModelType):
            """Update host hiding hidden authors."""

            class Meta:
                """Serve only update."""

                model = Author
                model_operations = ("update",)

            @classmethod
            def filter_queryset(cls, queryset: QuerySet, info: Any, **kw: Any) -> Any:
                """Hide authors named hidden.

                Args:
                    queryset: Unscoped rows.
                    info: Request resolve info.
                    **kw: Unused filter arguments.

                Returns:
                    The visible rows.
                """
                return queryset.exclude(name__startswith="hidden")

    class PostMutation(DjangoModelMutation):
        """Post writes with nested tags and author."""

        class Meta:
            """Declare the nested relations."""

            model = Post
            nested_fields = (
                {"tags": Tag, "author": Author} if nested_tags else {"author": Author}
            )

    _, _, update = PostMutation.MutationFields()

    class Query(ObjectType):
        """Minimal query root."""

        ready = BooleanField()

    class Mutation(ObjectType):
        """Mutation root."""

        post_update = update

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    )


def _update(schema: DjangoGraphQLSchema, post: Post, body: str) -> Any:
    """Run a postUpdate with extra input fields.

    Args:
        schema: Schema to execute against.
        post: Post being updated.
        body: Extra input fields, GraphQL syntax.

    Returns:
        The execution result.
    """
    return graphql_sync(
        schema.graphql_schema,
        'mutation { postUpdate(newPost: {id: "%d", %s}) { ok errors { field messages } } }'
        % (post.pk, body),
        context_value=RequestFactory().post("/graphql/"),
    )


def _payload(result: Any) -> Any:
    """Return the mutation payload, asserting there is no top-level error.

    Args:
        result: Execution result.

    Returns:
        The postUpdate payload.
    """
    assert result.errors is None, result.errors
    return result.data["postUpdate"]


@pytest.mark.django_db
@pytest.mark.parametrize("output_scope", [False, True], ids=["unscoped", "scoped"])
def test_many_plain_ids_are_checked_in_chunks(output_scope: bool) -> None:
    """Tens of thousands of linked ids do not hit the SQL variable limit.

    Args:
        output_scope: Whether the Tag output type is scoped.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", author=author)
    Tag.objects.bulk_create([Tag(label=f"t{i}") for i in range(_MANY)])
    body = "tags: [%s]" % ",".join(
        '"%d"' % pk for pk in Tag.objects.values_list("pk", flat=True)
    )
    with isolated_default_pair():
        schema = _build(output_scope=output_scope, nested_tags=False)
        payload = _payload(_update(schema, post, body))
    assert payload == {"ok": True, "errors": None}
    assert post.tags.count() == _MANY


@pytest.mark.django_db
def test_nested_ids_are_checked_in_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scoped nested link check chunks its membership lookups.

    Args:
        monkeypatch: Fixture lowering the reported parameter limit.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", author=author)
    Tag.objects.bulk_create([Tag(label=f"t{i}") for i in range(250)])
    monkeypatch.setattr(
        type(connection.features), "max_query_params", property(lambda self: 120)
    )
    body = "tags: [%s]" % ",".join(
        '{id: "%d"}' % pk for pk in Tag.objects.values_list("pk", flat=True)
    )
    with isolated_default_pair():
        schema = _build(output_scope=True)
        with CaptureQueriesContext(connection) as queries:
            payload = _payload(_update(schema, post, body))
    assert payload == {"ok": True, "errors": None}
    assert post.tags.count() == 250
    lookups = [q["sql"] for q in queries if " IN (" in q["sql"]]
    assert lookups
    assert all(sql.count("%s") + sql.count("?") <= 120 for sql in lookups)


class _FakeQuerySet:
    """Queryset stand-in whose database answers in another letter case."""

    def __init__(self, stored: list[str]) -> None:
        """Remember the stored keys.

        Args:
            stored: Keys as the database holds them.
        """
        self.stored = stored
        self.db = "default"

    def filter(self, **lookup: Any) -> _FakeQuerySet:
        """Match case-insensitively, like a CI collation.

        Args:
            **lookup: The "<field>__in" lookup.

        Returns:
            Self, already narrowed.
        """
        wanted = {str(v).casefold() for v in next(iter(lookup.values()))}
        return _FakeQuerySet([k for k in self.stored if k.casefold() in wanted])

    def values_list(self, name: str, flat: bool = False) -> list[str]:
        """Return the stored keys.

        Args:
            name: Field name, unused.
            flat: Flat result flag, unused.

        Returns:
            The narrowed stored keys.
        """
        return self.stored


@pytest.mark.django_db
def test_present_values_matches_keys_the_database_returns_in_another_case() -> None:
    """A case-insensitive collation must not report an existing key missing.

    The stub database answers in the stored letter case.
    """
    from django.db.models import CharField

    field = CharField(max_length=10, name="code")
    found = present_values(_FakeQuerySet(["Abc", "XYZ"]), field, ["abc", "xyz", "no"])  # type: ignore[arg-type]
    assert found == {"abc", "xyz"}


@pytest.mark.django_db
def test_host_hidden_ids_answer_like_missing_ones() -> None:
    """A tag hidden only by the update host is refused like a missing tag.

    Both the id-only and the id-with-data shapes must answer identically.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", author=author)
    hidden = Tag.objects.create(label="hidden-tag")
    with isolated_default_pair():
        schema = _build(output_scope=False, host_scope=True)
        for body in ('{id: "%s"}', '{id: "%s", label: "x"}'):
            missing = _payload(_update(schema, post, "tags: [%s]" % (body % 99999)))
            seen = _payload(_update(schema, post, "tags: [%s]" % (body % hidden.pk)))
            assert missing["ok"] is False
            assert seen["ok"] is False
            assert seen["errors"][0]["messages"] == [
                m.replace("99999", str(hidden.pk))
                for m in missing["errors"][0]["messages"]
            ]
            assert seen["errors"][0]["field"] == missing["errors"][0]["field"]
            assert not post.tags.exists()


@pytest.mark.django_db
def test_host_hidden_forward_author_answers_like_missing() -> None:
    """A forward author hidden only by the update host is refused like a missing one.

    The parent keeps its current author.
    """
    author = Author.objects.create(name="a")
    hidden = Author.objects.create(name="hidden-author")
    post = Post.objects.create(title="p", author=author)
    with isolated_default_pair():
        schema = _build(output_scope=False, host_scope=True)
        missing = _payload(_update(schema, post, 'author: {id: "99999"}'))
        seen = _payload(_update(schema, post, 'author: {id: "%d"}' % hidden.pk))
    assert missing["ok"] is False
    assert seen["ok"] is False
    assert seen["errors"][0]["field"] == missing["errors"][0]["field"]
    assert seen["errors"][0]["messages"] == [
        m.replace("99999", str(hidden.pk)) for m in missing["errors"][0]["messages"]
    ]
    post.refresh_from_db()
    assert post.author_id == author.pk


@pytest.mark.django_db
def test_id_only_resend_of_current_forward_target_writes_nothing() -> None:
    """Re-sending the current author's id alone does not save that row.

    No post_save signal may fire for it.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", author=author)
    saves: list[Any] = []

    def receiver(sender: Any, instance: Any, **kwargs: Any) -> None:
        """Count saves of authors.

        Args:
            sender: Saved model class.
            instance: Saved row.
            **kwargs: Signal extras.
        """
        saves.append(instance.pk)

    with isolated_default_pair():
        schema = _build(output_scope=False)
        post_save.connect(receiver, sender=Author)
        try:
            payload = _payload(_update(schema, post, 'author: {id: "%d"}' % author.pk))
        finally:
            post_save.disconnect(receiver, sender=Author)
    assert payload["ok"] is True
    assert saves == []


@pytest.mark.django_db
@pytest.mark.parametrize("scoped", [False, True], ids=["unscoped", "scoped"])
def test_oversized_forward_id_is_a_field_error(scoped: bool) -> None:
    """An id beyond the database integer range answers "does not exist".

    Args:
        scoped: Whether the Tag output type is scoped (unused by author).
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", author=author)
    with isolated_default_pair():
        schema = _build(output_scope=scoped)
        payload = _payload(
            _update(schema, post, 'author: {id: "99999999999999999999999"}')
        )
    assert payload["ok"] is False
    assert payload["errors"][0]["field"] == "author"
    assert "does not exist" in payload["errors"][0]["messages"][0]
