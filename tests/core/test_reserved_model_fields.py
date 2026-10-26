"""Generated mutation inputs preserve Django fields with Pydantic-reserved names."""

from __future__ import annotations

import importlib.metadata
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import graphql
import pytest
from django.db import connection, models
from django.test import RequestFactory
from django.test.utils import isolate_apps
from graphql import GraphQLString, graphql_sync
from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

import django_graphex
from django_graphex.core import ObjectType, field
from django_graphex.core.fields import build_model_schema
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.validators import build_validator_model
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests._schema_isolation import isolated_pair


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("host_kind", ["type", "mutation"])
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("hook_kind", ["validator", "serializer"])
def test_inherited_model_config_hooks_use_original_field(
    host_kind: str, operation: str, hook_kind: str
) -> None:
    """Run inherited Pydantic field hooks on the isolated Django column.

    Args:
        host_kind: Public generated mutation frontend.
        operation: Generated create or update mutation.
        hook_kind: Inherited validator or serializer binding to exercise.

    Raises:
        ValueError: The inherited hook rejects blocked input, which the
            generated mutation reports as a structured validation error.
    """
    calls: list[str] = []
    with isolate_apps():
        model_cls = type(
            f"ConfigHooks_{host_kind}_{operation}_{hook_kind}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "app_label": "tests",
                        "db_table": f"t_config_hooks_{host_kind}_{operation}_{hook_kind}",
                    },
                ),
                "model_config": models.CharField(max_length=40),
            },
        )

        if hook_kind == "validator":

            class Rules(BaseModel):
                """Reject a disallowed original Django column value."""

                model_config = ConfigDict(extra="forbid")

                @field_validator("model_config", check_fields=False)
                @classmethod
                def reject(cls, value: str) -> str:
                    """Reject blocked input before it can be persisted.

                    Args:
                        value: Original Django column value.

                    Returns:
                        The allowed value.

                    Raises:
                        ValueError: The value is blocked by the application.
                    """
                    calls.append(value)
                    if value == "blocked":
                        raise ValueError("application rule rejects value")
                    return value

            hook_info = Rules.__pydantic_decorators__.field_validators["reject"].info
        else:

            class Rules(BaseModel):
                """Serialize a field using its original Django column name."""

                model_config = ConfigDict(extra="forbid")

                @field_serializer("model_config", check_fields=False)
                def upper(self, value: str) -> str:
                    """Transform the original column before persistence.

                    Args:
                        value: Validated original Django column value.

                    Returns:
                        Uppercase value for the persisted model.
                    """
                    calls.append(value)
                    return value.upper()

            hook_info = Rules.__pydantic_decorators__.field_serializers["upper"].info

        assert hook_info.fields == ("model_config",)
        with connection.schema_editor() as editor:
            editor.create_model(model_cls)
        try:
            private_registry = Registry()
            if host_kind == "type":

                class ConfigType(DjangoModelType):
                    class Meta:
                        model = model_cls
                        pydantic_model = Rules
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

                host = ConfigType
            else:

                class ConfigMutation(DjangoModelMutation):
                    class Meta:
                        model = model_cls
                        registry = private_registry
                        pydantic_model = Rules
                        input_field_name = "payload"
                        output_field_name = "record"
                        model_operations = ("create", "update")

                host = ConfigMutation

            class Query(ObjectType):
                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                create = host.CreateField()
                update = host.UpdateField()

            schema = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            ).graphql_schema
            row = (
                model_cls.objects.create(model_config="original")
                if operation == "update"
                else None
            )
            supplied = "blocked" if hook_kind == "validator" else "lower"
            payload = (
                f'id: "{row.pk}", modelConfig: "{supplied}"'
                if row is not None
                else f'modelConfig: "{supplied}"'
            )
            result = graphql_sync(
                schema,
                f"mutation {{ {operation}(payload: {{{payload}}}) "
                "{ ok errors { field messages } record { id modelConfig } } }",
                context_value=RequestFactory().post(
                    "/graphql/", content_type="application/json"
                ),
            )
            assert result.errors is None
            response = result.data[operation]
            assert calls == [supplied]
            assert hook_info.fields == ("model_config",)
            if hook_kind == "validator":
                assert response["ok"] is False
                assert {error["field"] for error in response["errors"]} == {
                    "model_config"
                }
                if row is None:
                    assert not model_cls.objects.exists()
                else:
                    row.refresh_from_db()
                    assert row.model_config == "original"
            else:
                assert response["ok"] is True
                assert response["record"]["modelConfig"] == "LOWER"
                assert model_cls.objects.get().model_config == "LOWER"
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model_cls)


def test_inherited_mixed_hooks_preserve_modes_and_caller_base() -> None:
    """Retarget only the isolated binding in inherited mixed-field hooks.

    The user base, its configuration, and decorators on ordinary fields must
    remain intact after the generated schema is constructed.

    Raises:
        ValidationError: The inherited strict-extras policy rejects a key.
    """
    with isolate_apps():
        model_cls = type(
            "MixedConfigHooks",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "tests"}),
                "model_config": models.CharField(max_length=40),
                "note": models.CharField(max_length=40),
            },
        )
        calls: list[str] = []

        class ParentRules(BaseModel):
            """Declare inherited mixed-field and object validation rules."""

            model_config = ConfigDict(extra="forbid")

            @field_validator("model_config", "note", mode="before", check_fields=False)
            @classmethod
            def prefix(cls, value: str) -> str:
                """Transform both selected fields before normal validation.

                Args:
                    value: Supplied field value.

                Returns:
                    Prefixed value.
                """
                calls.append(f"field:{value}")
                return f"pre-{value}"

            @field_serializer("model_config", check_fields=False)
            def upper(self, value: str) -> str:
                """Serialize the isolated field through the inherited hook.

                Args:
                    value: Validated field value.

                Returns:
                    Uppercase serialized value.
                """
                calls.append(f"serialize:{value}")
                return value.upper()

            @field_serializer("note", check_fields=False)
            def note_suffix(self, value: str) -> str:
                """Keep unrelated inherited field serialization intact.

                Args:
                    value: Validated ordinary field value.

                Returns:
                    Value with its serializer suffix.
                """
                calls.append(f"serialize-note:{value}")
                return f"{value}-out"

            @model_validator(mode="after")
            def record(self) -> ParentRules:
                """Retain ordinary inherited object-validator execution.

                Returns:
                    The unchanged validated model.
                """
                calls.append("model")
                return self

        class ChildRules(ParentRules):
            """Inherit all custom base rules without mutating their metadata."""

        schema = build_model_schema(model_cls, base=ChildRules)
        internal_name = next(iter(schema.__gdx_original_fields__))
        validated = schema(model_config="lower", note="plain")
        assert getattr(validated, internal_name) == "pre-lower"
        assert validated.note == "pre-plain"
        assert calls == ["field:lower", "field:plain", "model"]
        dumped = BaseModel.model_dump(validated)
        assert dumped[internal_name] == "PRE-LOWER"
        assert dumped["note"] == "pre-plain-out"
        assert calls[-2:] == ["serialize:pre-lower", "serialize-note:pre-plain"]
        for base in (ParentRules, ChildRules):
            assert base.__pydantic_decorators__.field_validators[
                "prefix"
            ].info.fields == (
                "model_config",
                "note",
            )
            assert base.__pydantic_decorators__.field_serializers[
                "upper"
            ].info.fields == ("model_config",)
            assert base.__pydantic_decorators__.field_serializers[
                "note_suffix"
            ].info.fields == ("note",)
            assert base.model_config["extra"] == "forbid"
        with pytest.raises(ValidationError):
            schema(model_config="lower", note="plain", unknown="forbidden")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "reserved_name", ["model_dump", "model_validate", "model_config"]
)
@pytest.mark.parametrize("host_kind", ["type", "mutation"])
def test_generated_mutation_persists_reserved_field(
    reserved_name: str, host_kind: str
) -> None:
    """Create and update the original Django column through the public input.

    Args:
        reserved_name: Pydantic-reserved Django column name under test.
        host_kind: Public generated mutation host to exercise.
    """
    assert graphql.__version__ == importlib.metadata.version("graphql-core")
    assert Version("3.3.0") <= Version(graphql.__version__) < Version("3.4")
    assert (
        Path(django_graphex.__file__)
        .resolve()
        .is_relative_to(Path(__file__).resolve().parents[2])
    )

    with isolate_apps():
        model_cls = type(
            f"Reserved_{reserved_name}",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type(
                    "Meta",
                    (),
                    {"app_label": "tests", "db_table": f"t_reserved_{reserved_name}"},
                ),
                reserved_name: models.CharField(max_length=40),
            },
        )
        with connection.schema_editor() as editor:
            editor.create_model(model_cls)
        try:
            private_registry = Registry()

            warning_context = (
                pytest.warns(
                    UserWarning,
                    match=rf'Field name "{reserved_name}" in "Reserved_{reserved_name}Native" shadows an attribute in parent "BaseModel"',
                )
                if reserved_name in {"model_dump", "model_validate"}
                else nullcontext()
            )
            with warning_context as caught:
                if host_kind == "type":

                    class ReservedType(DjangoModelType):
                        class Meta:
                            model = model_cls
                            input_field_name = "payload"
                            output_field_name = "record"
                            model_operations = ("create", "update")

                    host = ReservedType
                else:

                    class ReservedMutation(DjangoModelMutation):
                        class Meta:
                            model = model_cls
                            registry = private_registry
                            input_field_name = "payload"
                            output_field_name = "record"
                            model_operations = ("create", "update")

                    host = ReservedMutation
            if caught is not None:
                assert len(caught) == 2, [str(warning.message) for warning in caught]
                expected = (
                    f'Field name "{reserved_name}" in '
                    f'"Reserved_{reserved_name}Native" shadows an attribute '
                    'in parent "BaseModel"'
                )
                assert all(
                    type(warning.message) is UserWarning
                    and str(warning.message) == expected
                    for warning in caught
                )

            class Query(ObjectType):
                ping = field(GraphQLString)

            class MutationRoot(ObjectType):
                create = host.CreateField()
                update = host.UpdateField()

            schema = DjangoGraphQLSchema(
                query=Query,
                mutation=MutationRoot,
                registries=isolated_pair(private_registry),
            ).graphql_schema
            gql_name = "".join(
                word if index == 0 else word.capitalize()
                for index, word in enumerate(reserved_name.split("_"))
            )
            context = RequestFactory().post(
                "/graphql/", content_type="application/json"
            )
            create = graphql_sync(
                schema,
                f'mutation {{ create(payload: {{{gql_name}: "created"}}) '
                f"{{ ok errors {{ field messages }} record {{ id {gql_name} }} }} }}",
                context_value=context,
            )
            assert create.errors is None
            assert create.data["create"]["ok"] is True
            assert create.data["create"]["record"][gql_name] == "created"
            row = model_cls.objects.get()
            assert getattr(row, reserved_name) == "created"

            too_long = "x" * 41
            invalid = graphql_sync(
                schema,
                f'mutation {{ create(payload: {{{gql_name}: "{too_long}"}}) '
                "{ ok errors { field messages } } }",
                context_value=context,
            )
            assert invalid.errors is None
            assert invalid.data["create"]["ok"] is False
            assert {error["field"] for error in invalid.data["create"]["errors"]} == {
                reserved_name
            }
            assert model_cls.objects.count() == 1

            update = graphql_sync(
                schema,
                f'mutation {{ update(payload: {{id: "{row.pk}", '
                f'{gql_name}: "updated"}}) '
                f"{{ ok errors {{ field messages }} record {{ id {gql_name} }} }} }}",
                context_value=context,
            )
            assert update.errors is None
            assert update.data["update"]["ok"] is True
            row.refresh_from_db()
            assert getattr(row, reserved_name) == "updated"
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model_cls)


def test_internal_name_avoids_real_column_and_preserves_inline_validation() -> None:
    """Preserve original selectors and validators while isolating the column.

    Raises:
        ValidationError: The direct validation control rejects a blocked value.
    """
    with isolate_apps():
        model_cls = type(
            "ReservedWithCollision",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "tests"}),
                "model_config": models.CharField(max_length=40),
                "gdx_model_config_field": models.CharField(max_length=40),
            },
        )

        class OrdinaryRules(BaseModel):
            """User-provided Pydantic validators for noncolliding columns remain active."""

            @field_validator("gdx_model_config_field", check_fields=False)
            @classmethod
            def upper(cls, value: str) -> str:
                """Transform the ordinary column supplied by the client.

                Args:
                    value: Ordinary column value.

                Returns:
                    Uppercase value.
                """
                return value.upper()

        class Host:
            """Provide inline field and object validators using original names."""

            def validate_model_config(self, value: str) -> str:
                """Reject a disallowed reserved-column value.

                Args:
                    value: Reserved-column value.

                Returns:
                    The allowed value.

                Raises:
                    ValueError: The value is disallowed.
                """
                if value == "blocked":
                    raise ValueError("blocked reserved value")
                return value

            def validate(self, data: dict[str, str]) -> dict[str, str]:
                """Transform through original column keys, not internal aliases.

                Args:
                    data: Validated values under original Django field names.

                Returns:
                    The transformed data.
                """
                assert "model_config" in data
                assert "gdx_model_config_field_" not in data
                data["model_config"] = data["model_config"] + "!"
                return data

        base = build_validator_model(Host, model_cls, OrdinaryRules)
        schema = build_model_schema(model_cls, base=base)
        assert schema.__gdx_original_fields__ == {
            "gdx_model_config_field_": "model_config"
        }
        projected = compile_input_type(
            schema, name="ReservedOnlyInput", only_fields=("model_config",)
        )
        assert set(projected.fields) == {"modelConfig"}
        assert projected.fields["modelConfig"].out_name == "model_config"
        excluded = compile_input_type(
            schema, name="ReservedExcludedInput", exclude_fields=("model_config",)
        )
        assert "modelConfig" not in excluded.fields
        assert "gdxModelConfigField" in excluded.fields
        validated = schema(model_config="allowed", gdx_model_config_field="normal")
        assert validated.gdx_model_config_field_ == "allowed!"
        assert validated.gdx_model_config_field == "NORMAL"
        with pytest.raises(ValidationError) as exc_info:
            schema(model_config="blocked", gdx_model_config_field="normal")
        assert exc_info.value.errors(include_url=False)[0]["loc"] == ("model_config",)


def test_reserved_default_and_partial_omission_keep_original_presence() -> None:
    """Distinguish an omitted generated update field from explicit null.

    The private Pydantic name must not turn an omitted value into a write.
    """
    with isolate_apps():
        model_cls = type(
            "ReservedOptional",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "tests"}),
                "model_config": models.CharField(max_length=40, null=True, blank=True),
            },
        )
        schema = build_model_schema(model_cls, partial=True)
        internal_name = next(iter(schema.__gdx_original_fields__))
        missing = schema()
        assert internal_name not in missing.model_fields_set
        explicit_null = schema(model_config=None)
        assert internal_name in explicit_null.model_fields_set
        assert getattr(explicit_null, internal_name) is None


def test_original_methods_remain_available_on_generated_class() -> None:
    """Validate and serialize protected-column values on a generated schema.

    User-supplied Pydantic validators still target the original field name.

    Raises:
        ValidationError: The inherited strict-extras policy rejects an extra key.
    """
    with isolate_apps():
        model_cls = type(
            "ReservedMethods",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "tests"}),
                "model_dump": models.CharField(max_length=40),
                "model_validate": models.CharField(max_length=40),
            },
        )

        class Rules(BaseModel):
            """Keep a user-provided Pydantic validator on the original field."""

            model_config = ConfigDict(extra="forbid")

            @field_validator("model_dump", check_fields=False)
            @classmethod
            def uppercase(cls, value: str) -> str:
                """Transform the reserved column through its original validator.

                Args:
                    value: Supplied column value.

                Returns:
                    Uppercase column value.
                """
                return value.upper()

        with pytest.warns(
            UserWarning,
            match=r'Field name "model_(?:dump|validate)" in "ReservedMethodsNative" shadows an attribute in parent ".*Rules"',
        ) as caught:
            schema = build_model_schema(model_cls, base=Rules)
        assert len(caught) == 2
        assert all(type(warning.message) is UserWarning for warning in caught)
        assert 'Field name "model_dump" in "ReservedMethodsNative"' in str(
            caught[0].message
        )
        assert 'Field name "model_validate" in "ReservedMethodsNative"' in str(
            caught[1].message
        )
        assert all('shadows an attribute in parent "' in str(w.message) for w in caught)
        assert schema.model_config["extra"] == "forbid"
        validated = schema.model_validate(
            {"model_dump": "first", "model_validate": "second"}
        )
        assert BaseModel.model_dump(validated) == {
            "model_dump": "FIRST",
            "model_validate": "second",
        }
        with pytest.raises(ValidationError):
            schema.model_validate(
                {"model_dump": "first", "model_validate": "second", "extra": "bad"}
            )


def test_existing_custom_base_config_and_dump_override_remain_active() -> None:
    """Preserve user Pydantic configuration and serialization on working names.

    The special unbound dump call must not replace an existing user's method
    for an ordinary Django model that built successfully before this change.

    Raises:
        ValidationError: The strict-extras control rejects an unknown key.
    """
    with isolate_apps():
        model_cls = type(
            "OrdinaryField",
            (models.Model,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "tests"}),
                "value": models.CharField(max_length=40),
            },
        )

        class Rules(BaseModel):
            """Apply strict extras policy and a custom serialization method."""

            model_config = ConfigDict(extra="forbid")

            def model_dump(self, **kwargs: Any) -> dict[str, Any]:
                """Transform the persisted value through the user override.

                Args:
                    **kwargs: Pydantic serialization options.

                Returns:
                    The transformed payload.
                """
                payload = super().model_dump(**kwargs)
                payload["value"] = payload["value"].upper()
                return payload

        schema = build_model_schema(model_cls, base=Rules)
        assert schema.model_config["extra"] == "forbid"
        validated = schema(value="lower")
        assert validated.model_dump(include=set(validated.model_fields_set)) == {
            "value": "LOWER"
        }
        with pytest.raises(ValidationError):
            schema(value="valid", unexpected="not allowed")
