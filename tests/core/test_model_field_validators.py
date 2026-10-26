"""Django model field validators run on generated mutation writes."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import connection, models
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.core.backend import PydanticBackend
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from tests._schema_isolation import isolated_pair


def _even(value: int) -> None:
    """Reject odd numbers with a parameterised message.

    Args:
        value: The candidate number.

    Raises:
        ValidationError: The number is odd.
    """
    if value % 2:
        raise ValidationError("%(value)s is odd", code="odd", params={"value": value})


class _VParent(models.Model):
    """Parent row with a validated numeric column."""

    name = models.CharField(max_length=20)
    rank = models.IntegerField(default=2, validators=[_even])

    class Meta:
        """Bind to the installed tests app."""

        app_label = "tests"


class _VItem(models.Model):
    """Item with one column per validator kind."""

    score = models.IntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    slug = models.CharField(
        max_length=6, default="ok", validators=[RegexValidator(r"^[a-z]+$")]
    )
    even = models.IntegerField(default=2, validators=[_even])
    title = models.CharField(max_length=10, blank=False, default="t")
    tag = models.CharField(max_length=10, null=True, blank=False)
    parent = models.ForeignKey(
        _VParent,
        null=True,
        blank=True,
        related_name="items",
        on_delete=models.CASCADE,
        validators=[_even],
    )
    stamp = models.CharField(max_length=5, default="s", editable=False)

    class Meta:
        """Bind to the installed tests app."""

        app_label = "tests"


class _ItemMutation(DjangoModelMutation):
    """Generated create and update for the item model."""

    class Meta:
        """Bind the model and a private registry."""

        model = _VItem
        registry = Registry()
        input_field_name = "payload"
        output_field_name = "record"
        model_operations = ("create", "update")


class _ParentMutation(DjangoModelMutation):
    """Generated create with nested items."""

    class Meta:
        """Bind the parent, the nested child and a private registry."""

        model = _VParent
        registry = Registry()
        nested_fields = {"items": _VItem}
        input_field_name = "payload"
        output_field_name = "record"
        model_operations = ("create",)


def _schema(mutation_cls: Any, **ops: Any) -> Any:
    """Compile a schema exposing the host's generated fields.

    Args:
        mutation_cls: The generated mutation host.
        **ops: Root field name mapped to the host field factory name.

    Returns:
        The compiled GraphQL schema.
    """

    class Query(ObjectType):
        """Provide the required query root."""

        ping = field(GraphQLString)

    attrs = {name: getattr(mutation_cls, op)() for name, op in ops.items()}
    root = type("MutationRoot", (ObjectType,), attrs)
    return DjangoGraphQLSchema(
        query=Query,
        mutation=root,
        registries=isolated_pair(mutation_cls._meta.registry),
    ).graphql_schema


def _run(schema: Any, query: str) -> dict[str, Any]:
    """Execute one mutation and return its data.

    Args:
        schema: The compiled GraphQL schema.
        query: The mutation document.

    Returns:
        The response data (never a top-level error).
    """
    result = graphql_sync(
        schema, query, context_value=RequestFactory().post("/graphql/")
    )
    assert result.errors is None, result.errors
    return result.data


def _errors(data: dict[str, Any], op: str) -> dict[str, list[str]]:
    """Map a mutation's error entries to field -> messages.

    Args:
        data: The response data.
        op: The root field name.

    Returns:
        The error entries keyed by field.
    """
    assert data[op]["ok"] is False
    return {e["field"]: e["messages"] for e in data[op]["errors"]}


@pytest.fixture
def item_schema() -> Any:
    """Compile the item create and update schema.

    Returns:
        The GraphQL schema.
    """
    return _schema(_ItemMutation, create="CreateField", update="UpdateField")


FIELDS = "ok errors { field messages }"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("literal", "name", "message"),
    [
        ("score: 0", "score", "greater than or equal to 1"),
        ("score: 11", "score", "less than or equal to 10"),
        ('slug: "BAD"', "slug", "Enter a valid value."),
        ("even: 3", "even", "3 is odd"),
        ('title: ""', "title", "This field cannot be blank."),
        ('tag: ""', "tag", "This field cannot be blank."),
        ('slug: "toolongslug"', "slug", "at most 6 characters"),
    ],
)
def test_create_rejects_invalid_value_and_writes_nothing(
    item_schema: Any, literal: str, name: str, message: str
) -> None:
    """Return an ok-false field error and persist no row.

    Args:
        item_schema: The compiled schema.
        literal: The offending input literal.
        name: The field expected in the error.
        message: A fragment of the expected Django message.
    """
    data = _run(
        item_schema, f"mutation {{ create(payload: {{{literal}}}) {{ {FIELDS} }} }}"
    )
    errors = _errors(data, "create")
    assert message in " ".join(errors[name])
    assert not _VItem.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_all_messages_of_one_field_and_every_bad_field_are_reported(
    item_schema: Any,
) -> None:
    """Report each failing field once with all its messages.

    Args:
        item_schema: The compiled schema.
    """
    data = _run(
        item_schema,
        'mutation { create(payload: {score: 99, slug: "X"}) { ok errors { field messages } } }',
    )
    errors = _errors(data, "create")
    assert set(errors) == {"score", "slug"}


@pytest.mark.django_db(transaction=True)
def test_valid_create_succeeds_with_a_single_query(item_schema: Any) -> None:
    """Add no query for a payload that satisfies the validators.

    Args:
        item_schema: The compiled schema.
    """
    with CaptureQueriesContext(connection) as ctx:
        data = _run(
            item_schema,
            'mutation { create(payload: {score: 3, slug: "abc", tag: null}) '
            f"{{ {FIELDS} }} }}",
        )
    assert data["create"]["ok"] is True
    assert len(ctx.captured_queries) == 1
    assert _VItem.objects.get().score == 3


@pytest.mark.django_db(transaction=True)
def test_defaults_are_not_validated(item_schema: Any) -> None:
    """Keep developer defaults that the client did not write.

    Args:
        item_schema: The compiled schema.
    """
    default_field = _VItem._meta.get_field("title")
    _VItem._meta.get_field("title").default = ""
    try:
        data = _run(item_schema, f"mutation {{ create(payload: {{}}) {{ {FIELDS} }} }}")
    finally:
        default_field.default = "t"
    assert data["create"]["ok"] is True


@pytest.mark.django_db(transaction=True)
def test_update_validates_only_written_fields(item_schema: Any) -> None:
    """Skip stored values that the partial update does not touch.

    Args:
        item_schema: The compiled schema.
    """
    row = _VItem.objects.create(score=999)  # already invalid, never written
    ok = _run(
        item_schema,
        f'mutation {{ update(payload: {{id: "{row.pk}", slug: "fine"}}) {{ {FIELDS} }} }}',
    )
    assert ok["update"]["ok"] is True
    bad = _run(
        item_schema,
        f'mutation {{ update(payload: {{id: "{row.pk}", score: 0}}) {{ {FIELDS} }} }}',
    )
    assert "score" in _errors(bad, "update")
    row.refresh_from_db()
    assert row.score == 999
    assert row.slug == "fine"


@pytest.mark.django_db(transaction=True)
def test_foreign_key_validators_run_without_an_existence_query() -> None:
    """Run validators declared on a relation field, no extra SELECT.

    Asserts the behavior named in the summary.
    """
    backend = PydanticBackend(_VItem)
    errors = backend._model_field_errors({"parent": 3}, _VItem())
    assert errors == {"parent": ["3 is odd"]}
    with CaptureQueriesContext(connection) as ctx:
        assert backend._model_field_errors({"parent": 4}, _VItem()) == {}
    assert not ctx.captured_queries


def test_non_editable_and_unknown_fields_are_untouched() -> None:
    """Skip fields Django excludes from validation.

    Asserts the behavior named in the summary.
    """
    backend = PydanticBackend(_VItem)
    assert backend._model_field_errors({"stamp": "", "nope": 1}, _VItem()) == {}


def test_model_clean_is_not_called() -> None:
    """Do not run Model.clean or constraint validation.

    Asserts the behavior named in the summary.
    """
    backend = PydanticBackend(_VItem)
    calls: list[str] = []
    obj = _VItem()
    obj.clean = lambda: calls.append("clean")  # type: ignore[method-assign]
    obj.validate_unique = lambda *a, **k: calls.append("unique")  # type: ignore[method-assign]
    obj.validate_constraints = lambda *a, **k: calls.append("constraints")  # type: ignore[method-assign]
    assert backend._model_field_errors({"score": 3}, obj) == {}
    assert calls == []


@pytest.mark.django_db(transaction=True)
def test_nested_child_error_carries_the_nested_path() -> None:
    """Prefix the child's field error and roll the parent back.

    Asserts the behavior named in the summary.
    """
    schema = _schema(_ParentMutation, create="CreateField")
    data = _run(
        schema,
        'mutation { create(payload: {name: "P", items: [{score: 0}]}) '
        f"{{ {FIELDS} }} }}",
    )
    errors = _errors(data, "create")
    assert "items.score" in errors
    assert not _VParent.objects.exists()
    assert not _VItem.objects.exists()
