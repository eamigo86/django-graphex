"""Positive integer validation in generated GraphQL mutation inputs."""

from __future__ import annotations

import enum
import json
from typing import Any

import pytest
from django.db import connection, models
from django.test import Client, RequestFactory, override_settings
from django.test.utils import isolate_apps
from django.urls import path
from graphql import GraphQLError, GraphQLString, get_named_type, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.core.fields import _positive_integer_validator
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair


class _PositiveNestedParent(models.Model):
    """Parent fixture for a reverse-FK nested input."""

    name = models.CharField(max_length=12)

    class Meta:
        """Bind the fixture to the installed tests app."""

        app_label = "tests"


class _PositiveNestedChild(models.Model):
    """Child fixture with a positive integer column."""

    parent = models.ForeignKey(
        _PositiveNestedParent, related_name="children", on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField()

    class Meta:
        """Bind the fixture to the installed tests app."""

        app_label = "tests"


def test_positive_validator_preserves_null_and_reports_invalid_choice_value() -> None:
    """Keep nullable input while rejecting a choice that is not an integer.

    Django converts stored choice values before persistence; this guard must
    report conversion failure as input validation rather than a raw exception.
    """
    validator = _positive_integer_validator(models.PositiveIntegerField(null=True))

    class Choice(enum.Enum):
        """Represent a malformed stored numeric choice value."""

        INVALID = "not-an-integer"

    assert validator(None) is None
    with pytest.raises(ValueError, match="valid integer"):
        validator(Choice.INVALID)


def _post(
    schema: DjangoGraphQLSchema,
    query: str,
    *,
    atomic_mutations: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Execute a mutation through the public Django HTTP endpoint.

    Args:
        schema: Compiled GraphQL schema to serve.
        query: GraphQL mutation document.
        atomic_mutations: Whether the view wraps the whole mutation in a transaction.

    Returns:
        HTTP status and decoded JSON response.
    """
    urlconf = type("PositiveInputURLConf", (), {})
    urlconf.urlpatterns = [path("graphql/", GraphQLView.as_view(schema=schema))]
    with override_settings(
        ROOT_URLCONF=urlconf,
        DJANGO_GRAPHEX={
            "SCHEMA": None,
            "CACHE_ACTIVE": False,
            "ATOMIC_MUTATIONS": atomic_mutations,
        },
    ):
        response = Client().post(
            "/graphql/", json.dumps({"query": query}), content_type="application/json"
        )
    return response.status_code, response.json()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("host_kind", ["mutation", "type"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("field_name", ["quantity", "small"])
def test_generated_positive_input_rejects_negative_before_sql(
    host_kind: str, operation: str, field_name: str
) -> None:
    """Return a field error without changing a row for either positive field.

    Args:
        host_kind: Generated mutation frontend.
        operation: Create or update operation.
        field_name: Positive integer column receiving the negative value.
    """
    with isolate_apps():
        model_cls = type(
            f"PositiveCase_{host_kind}_{operation}_{field_name}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "app_label": "tests",
                        "db_table": f"t_positive_{host_kind}_{operation}_{field_name}",
                    },
                ),
                "title": models.CharField(max_length=12),
                "quantity": models.PositiveIntegerField(),
                "small": models.PositiveSmallIntegerField(default=0),
            },
        )
        with connection.schema_editor() as editor:
            editor.create_model(model_cls)
        try:
            private_registry = Registry()
            if host_kind == "mutation":

                class PositiveHost(DjangoModelMutation):
                    """Generated mutation host for the temporary model."""

                    class Meta:
                        """Bind the model and private Registry."""

                        model = model_cls
                        registry = private_registry
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

            else:

                class PositiveHost(DjangoModelType):
                    """Generated model type host for the temporary model."""

                    class Meta:
                        """Bind the temporary model."""

                        model = model_cls
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

            class Query(ObjectType):
                """Provide the required GraphQL query root."""

                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                """Expose generated create and update operations."""

                create = PositiveHost.CreateField()
                update = PositiveHost.UpdateField()

            compiled = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            )
            schema = compiled.graphql_schema
            input_type = get_named_type(
                schema.mutation_type.fields[operation].args["payload"].type
            )
            assert get_named_type(input_type.fields[field_name].type).name == "Int"
            row = (
                model_cls.objects.create(title="before", quantity=2, small=3)
                if operation == "update"
                else None
            )
            values = {"quantity": 1, "small": 1}
            values[field_name] = -1
            payload = f'title: "after", quantity: {values["quantity"]}, small: {values["small"]}'
            if row is not None:
                payload = f'id: "{row.pk}", {payload}'
            status, response = _post(
                compiled,
                f"mutation {{ {operation}(payload: {{{payload}}}) "
                "{ ok errors { field messages } record { id } } }",
            )
            assert status == 200
            assert "errors" not in response
            assert response["data"][operation]["ok"] is False
            assert {
                error["field"] for error in response["data"][operation]["errors"]
            } == {field_name}
            if row is None:
                assert not model_cls.objects.exists()
            else:
                row.refresh_from_db()
                assert (row.title, row.quantity, row.small) == ("before", 2, 3)
            valid_payload = 'title: "valid", quantity: 0, small: 2'
            if row is not None:
                valid_payload = f'id: "{row.pk}", {valid_payload}'
            valid_status, valid_response = _post(
                compiled,
                f"mutation {{ {operation}(payload: {{{valid_payload}}}) "
                "{ ok errors { field } } }",
            )
            assert valid_status == 200
            assert "errors" not in valid_response
            assert valid_response["data"][operation]["ok"] is True
            assert model_cls.objects.filter(title="valid", quantity=0, small=2).exists()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model_cls)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("atomic_mutations", [False, True])
def test_positive_field_error_preserves_earlier_sibling_write(
    atomic_mutations: bool,
) -> None:
    """Keep a successful sibling when negative input is a business error.

    Args:
        atomic_mutations: Whether to wrap both root fields in one transaction.

    Raises:
        GraphQLError: Raised by the nested resolver and handled by GraphQL.
    """
    with isolate_apps():
        suffix = "atomic" if atomic_mutations else "ordinary"
        positive_model = type(
            f"PositiveSiblingCase_{suffix}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "app_label": "tests",
                        "db_table": f"t_positive_sibling_case_{suffix}",
                    },
                ),
                "quantity": models.PositiveIntegerField(),
            },
        )
        sibling_model = type(
            f"PositiveEarlierSibling_{suffix}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {"app_label": "tests", "db_table": f"t_positive_earlier_{suffix}"},
                ),
                "name": models.CharField(max_length=30),
            },
        )
        with connection.schema_editor() as editor:
            editor.create_model(positive_model)
            editor.create_model(sibling_model)
        try:
            private_registry = Registry()

            class PositiveHost(DjangoModelMutation):
                """Create a positive-input model."""

                class Meta:
                    """Bind the generated positive-input model."""

                    model = positive_model
                    registry = private_registry
                    input_field_name = "payload"
                    model_operations = ("create",)

            class SiblingHost(DjangoModelMutation):
                """Create an earlier sibling model."""

                class Meta:
                    """Bind the generated sibling model."""

                    model = sibling_model
                    registry = private_registry
                    input_field_name = "payload"
                    model_operations = ("create",)

            class Query(ObjectType):
                """Provide the required query root."""

                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                """Expose both generated roots and an unrelated execution error."""

                sibling = SiblingHost.CreateField()
                positive = PositiveHost.CreateField()
                explode = field(GraphQLString)

                @staticmethod
                def resolve_explode(root: Any, info: Any) -> str:
                    """Raise an unrelated GraphQL execution error.

                    Args:
                        root: Unused root value.
                        info: Unused execution context.

                    Raises:
                        GraphQLError: Always, to exercise transaction rollback.
                    """
                    raise GraphQLError("Unrelated execution failure")

            compiled = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            )
            status, response = _post(
                compiled,
                'mutation { sibling(payload: {name: "kept"}) { ok } '
                "positive(payload: {quantity: -1}) { ok errors { field } } }",
                atomic_mutations=atomic_mutations,
            )
            assert status == 200
            assert "errors" not in response
            assert response["data"]["sibling"]["ok"] is True
            assert response["data"]["positive"]["ok"] is False
            assert {
                error["field"] for error in response["data"]["positive"]["errors"]
            } == {"quantity"}
            assert sibling_model.objects.filter(name="kept").exists()
            assert not positive_model.objects.exists()

            if atomic_mutations:
                status, response = _post(
                    compiled,
                    'mutation { sibling(payload: {name: "rolled-back"}) { ok } explode }',
                    atomic_mutations=True,
                )
                assert status == 200
                assert response["errors"][0]["path"] == ["explode"]
                assert not sibling_model.objects.filter(name="rolled-back").exists()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(sibling_model)
                editor.delete_model(positive_model)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field_name", ["quantity", "small"])
def test_positive_choices_validate_stored_number_and_keep_enum(
    field_name: str,
) -> None:
    """Reject a negative choice without replacing valid Enum input values.

    Args:
        field_name: Choice-backed positive integer column.
    """
    with isolate_apps():
        model_cls = type(
            f"PositiveChoices_{field_name}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "app_label": "tests",
                        "db_table": f"t_positive_choices_{field_name}",
                    },
                ),
                field_name: (
                    models.PositiveIntegerField(
                        choices=[(-1, "Negative"), (0, "Zero"), (2, "Two")]
                    )
                    if field_name == "quantity"
                    else models.PositiveSmallIntegerField(
                        choices=[(-1, "Negative"), (0, "Zero"), (2, "Two")]
                    )
                ),
            },
        )
        with connection.schema_editor() as editor:
            editor.create_model(model_cls)
        try:
            private_registry = Registry()

            class PositiveHost(DjangoModelMutation):
                """Expose a generated choice-backed positive input."""

                class Meta:
                    """Bind the temporary choice-backed model."""

                    model = model_cls
                    registry = private_registry
                    input_field_name = "payload"
                    model_operations = ("create",)

            class Query(ObjectType):
                """Provide the required query root."""

                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                """Expose generated choice-backed create."""

                create = PositiveHost.CreateField()

            compiled = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            )
            input_type = get_named_type(
                compiled.graphql_schema.mutation_type.fields["create"]
                .args["payload"]
                .type
            )
            enum_type = get_named_type(input_type.fields[field_name].type)
            assert enum_type.name != "Int"

            def choice_name(value: int) -> str:
                """Find the existing generated Enum member for a stored value.

                Args:
                    value: Stored integer choice value.

                Returns:
                    GraphQL member name for the choice.
                """
                return next(
                    name
                    for name, member in enum_type.values.items()
                    if getattr(member.value, "value", member.value) == value
                )

            for value, expected_ok in [(-1, False), (0, True), (2, True)]:
                status, response = _post(
                    compiled,
                    f"mutation {{ create(payload: {{{field_name}: {choice_name(value)}}}) "
                    "{ ok errors { field } } }",
                )
                assert status == 200
                assert "errors" not in response
                assert response["data"]["create"]["ok"] is expected_ok
                if expected_ok:
                    assert model_cls.objects.filter(**{field_name: value}).exists()
                else:
                    assert {
                        error["field"] for error in response["data"]["create"]["errors"]
                    } == {field_name}
                    assert not model_cls.objects.filter(**{field_name: -1}).exists()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model_cls)


@pytest.mark.django_db(transaction=True)
def test_nested_positive_input_rejects_child_before_parent_persists() -> None:
    """Roll back a nested parent and child for a negative child integer.

    The generated nested input uses the same field validation as root inputs.
    """
    parent = _PositiveNestedParent
    child = _PositiveNestedChild
    private_registry = Registry()

    class ParentHost(DjangoModelMutation):
        """Expose generated nested parent creation."""

        class Meta:
            """Bind temporary parent and child models."""

            model = parent
            registry = private_registry
            nested_fields = {"children": child}
            input_field_name = "payload"
            model_operations = ("create",)

    class Query(ObjectType):
        """Provide the required query root."""

        ping = field(GraphQLString)

    class MutationRoot(ObjectType):
        """Expose generated parent creation."""

        create = ParentHost.CreateField()

    schema = DjangoGraphQLSchema(
        query=Query,
        mutation=MutationRoot,
        registries=isolated_pair(private_registry),
    ).graphql_schema
    result = graphql_sync(
        schema,
        'mutation { create(payload: {name: "parent", children: [{quantity: -1}]}) '
        "{ ok errors { field } } }",
        context_value=RequestFactory().post("/graphql/"),
    )
    assert result.errors is None
    assert result.data["create"]["ok"] is False
    assert any(
        "quantity" in error["field"] for error in result.data["create"]["errors"]
    )
    assert not parent.objects.exists()
    assert not child.objects.exists()
