"""EmailField syntax validation in generated mutation inputs."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.db import connection, models
from django.test import RequestFactory
from django.test.utils import isolate_apps
from graphql import GraphQLString, graphql_sync, print_schema
from pydantic import BaseModel, ValidationError, field_validator

from django_graphex.core import ObjectType, field
from django_graphex.core.fields import build_model_schema
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair


class _EmailParent(models.Model):
    """Temporary parent for a reverse-FK nested create."""

    name = models.CharField(max_length=30)

    class Meta:
        """Bind the parent to the installed tests app."""

        app_label = "tests"


class _EmailChild(models.Model):
    """Temporary child with an EmailField."""

    parent = models.ForeignKey(
        _EmailParent, on_delete=models.CASCADE, related_name="children"
    )
    email = models.EmailField()

    class Meta:
        """Bind the child to the installed tests app."""

        app_label = "tests"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("host_kind", ["mutation", "type"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_generated_email_input_rejects_invalid_syntax(
    host_kind: str, operation: str
) -> None:
    """Reject a supplied invalid address without changing a database row.

    Args:
        host_kind: Generated mutation frontend to exercise.
        operation: Create or update operation under test.
    """
    with isolate_apps():
        model_cls = type(
            f"EmailCase_{host_kind}_{operation}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "app_label": "tests",
                        "db_table": f"t_email_{host_kind}_{operation}",
                    },
                ),
                "email": models.EmailField(max_length=254),
            },
        )
        with connection.schema_editor() as editor:
            editor.create_model(model_cls)
        try:
            private_registry = Registry()
            if host_kind == "mutation":

                class EmailHost(DjangoModelMutation):
                    """Expose generated mutation fields for the temporary model."""

                    class Meta:
                        """Bind the test model and registry."""

                        model = model_cls
                        registry = private_registry
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

            else:

                class EmailHost(DjangoModelType):
                    """Expose generated CRUD fields for the temporary model."""

                    class Meta:
                        """Bind the test model."""

                        model = model_cls
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

            class Query(ObjectType):
                """Provide the required query root."""

                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                """Expose both generated operations."""

                create = EmailHost.CreateField()
                update = EmailHost.UpdateField()

            compiled = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            )
            schema = compiled.graphql_schema
            assert "email: String" in print_schema(schema)
            row = (
                model_cls.objects.create(email="before@example.com")
                if operation == "update"
                else None
            )
            payload = (
                f'id: "{row.pk}", email: "not-an-email"'
                if row is not None
                else 'email: "not-an-email"'
            )
            operation_source = (
                f"mutation {{ {operation}(payload: {{{payload}}}) "
                "{ ok errors { field messages } record { id email } } }"
            )
            result = graphql_sync(
                schema,
                operation_source,
                context_value=RequestFactory().post("/graphql/"),
            )
            assert result.errors is None
            response: dict[str, Any] = result.data[operation]
            assert response["ok"] is False
            assert {error["field"] for error in response["errors"]} == {"email"}
            request = RequestFactory().post(
                "/graphql/",
                json.dumps({"query": operation_source}),
                content_type="application/json",
            )
            http = GraphQLView.as_view(schema=compiled)(request)
            http_result = json.loads(http.content)
            assert http.status_code == 200
            assert http_result["data"][operation]["ok"] is False
            assert {
                error["field"] for error in http_result["data"][operation]["errors"]
            } == {"email"}
            if row is None:
                assert not model_cls.objects.exists()
            else:
                row.refresh_from_db()
                assert row.email == "before@example.com"
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model_cls)


def test_email_syntax_preserves_optional_defaults_length_and_custom_rules() -> None:
    """Validate syntax only for supplied nonempty values after existing rules.

    Raises:
        ValidationError: Expected for an overlong or malformed address.
    """
    with isolate_apps():

        class CustomEmailField(models.EmailField):
            """Exercise Django EmailField subclasses without a new scalar."""

        class EmailModel(models.Model):
            """Hold nullable, required, and defaulted email columns."""

            email = CustomEmailField(max_length=18, blank=False)
            optional = models.EmailField(null=True, blank=True)
            with_default = models.EmailField(default=lambda: "factory-default")

            class Meta:
                """Register only within the isolated test app."""

                app_label = "tests"

        class BaseRules(BaseModel):
            """Retain custom Pydantic validation on an EmailField."""

            @field_validator("email", mode="before", check_fields=False)
            @classmethod
            def complete_address(cls, value: str) -> str:
                """Transform a supplied short name before syntax checking.

                Args:
                    value: Supplied local-part or full address.

                Returns:
                    A full address for the generated syntax validator.
                """
                return value + "@x.test" if "@" not in value and value else value

        schema = build_model_schema(EmailModel, base=BaseRules)
        instance = schema.model_validate({"email": "ok", "optional": None})
        assert instance.email == "ok@x.test"
        assert instance.optional is None
        assert instance.with_default == "factory-default"
        assert schema.model_validate({"email": ""}).email == ""
        with pytest.raises(ValidationError) as overlong:
            schema.model_validate({"email": "longaddress@example.test"})
        assert overlong.value.errors()[0]["loc"] == ("email",)
        with pytest.raises(ValidationError) as invalid:
            schema.model_validate({"email": "bad@@example.test"})
        assert invalid.value.errors()[0]["loc"] == ("email",)
        partial = build_model_schema(EmailModel, partial=True, base=BaseRules)
        assert partial.model_validate({}).model_fields_set == set()
        assert partial.model_validate({"optional": None}).optional is None


def test_reserved_named_email_keeps_original_error_field() -> None:
    """Validate an EmailField isolated from Pydantic's model_config name.

    Raises:
        ValidationError: An invalid address remains associated with the
            original Django and GraphQL field name.
    """
    with isolate_apps():

        class ReservedEmail(models.Model):
            """Provide an EmailField whose name Pydantic reserves."""

            model_config = models.EmailField()

            class Meta:
                """Register only within the isolated test app."""

                app_label = "tests"

        schema = build_model_schema(ReservedEmail)
        instance = schema.model_validate({"model_config": "ok@example.com"})
        internal_name = next(iter(schema.__gdx_original_fields__))
        assert getattr(instance, internal_name) == "ok@example.com"
        with pytest.raises(ValidationError) as invalid:
            schema.model_validate({"model_config": "bad"})
        assert invalid.value.errors()[0]["loc"] == ("model_config",)


@pytest.mark.django_db(transaction=True)
def test_nested_email_validation_rolls_back_parent_and_child() -> None:
    """Reject a malformed child email before either nested row persists.

    The failure uses the existing nested mutation error envelope and leaves
    both temporary tables unchanged.
    """
    Parent = _EmailParent
    Child = _EmailChild
    private_registry = Registry()

    class ParentMutation(DjangoModelMutation):
        """Expose the nested child create input."""

        class Meta:
            """Bind the parent, child, and registry."""

            model = Parent
            registry = private_registry
            nested_fields = {"children": Child}
            input_field_name = "payload"
            output_field_name = "record"
            model_operations = ("create",)

    class Query(ObjectType):
        """Provide the required query root."""

        ping = field(GraphQLString)

    class MutationRoot(ObjectType):
        """Expose the generated parent creation."""

        create = ParentMutation.CreateField()

    schema = DjangoGraphQLSchema(
        query=Query,
        mutation=MutationRoot,
        registries=isolated_pair(private_registry),
    ).graphql_schema
    result = graphql_sync(
        schema,
        'mutation { create(payload: {name: "P", children: '
        '[{email: "not-an-email"}]}) '
        "{ ok errors { field messages } record { id } } }",
        context_value=RequestFactory().post("/graphql/"),
    )
    assert result.errors is None
    assert result.data["create"]["ok"] is False
    assert any("email" in error["field"] for error in result.data["create"]["errors"])
    assert not Parent.objects.exists()
    assert not Child.objects.exists()
