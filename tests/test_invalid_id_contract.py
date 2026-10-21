"""Public malformed-ID contract for model-backed GraphQL lookups."""

from __future__ import annotations

import pytest
from graphql import GraphQLError, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import ScopedArticle, UUIDThing

_REGISTRY = Registry()


class _ArticleType(DjangoObjectType):
    class Meta:
        model = ScopedArticle
        registry = _REGISTRY
        only_fields = ("id", "title")


class _UUIDType(DjangoObjectType):
    class Meta:
        model = UUIDThing
        registry = _REGISTRY
        only_fields = ("id", "name")


class _Query(ObjectType):
    article = DjangoObjectField(_ArticleType)
    thing = DjangoObjectField(_UUIDType)


_SCHEMA = DjangoGraphQLSchema(query=_Query, registries=isolated_pair(_REGISTRY))


@pytest.mark.django_db
def test_malformed_integer_id_has_safe_public_error() -> None:
    result = graphql_sync(
        _SCHEMA.graphql_schema, '{ article(id: "not-an-id") { title } }'
    )
    assert result.data == {"article": None}
    assert result.errors is not None and len(result.errors) == 1
    error = result.errors[0]
    assert error.message == "Invalid ID: expected an integer."
    assert error.extensions == {"code": "INVALID_ID"}
    assert error.path == ["article"]
    assert "not-an-id" not in str(error.formatted)


@pytest.mark.django_db
def test_malformed_uuid_id_has_safe_public_error() -> None:
    result = graphql_sync(
        _SCHEMA.graphql_schema, '{ thing(id: "not-a-uuid") { name } }'
    )
    assert result.data == {"thing": None}
    assert result.errors is not None and len(result.errors) == 1
    error = result.errors[0]
    assert error.message == "Invalid ID: expected a UUID."
    assert error.extensions == {"code": "INVALID_ID"}
    assert error.path == ["thing"]
    assert "not-a-uuid" not in str(error.formatted)


@pytest.mark.django_db
def test_get_node_rejects_malformed_integer_id() -> None:
    with pytest.raises(GraphQLError) as caught:
        _ArticleType.get_node(None, "not-an-id")
    assert caught.value.message == "Invalid ID: expected an integer."
    assert caught.value.extensions == {"code": "INVALID_ID"}


def test_malformed_id_in_generated_retrieve_field(db: None) -> None:
    """Generated retrieve fields use the same safe error contract."""
    from django_graphex.types import DjangoModelType

    from ._schema_isolation import isolated_default_pair
    from .models import HookModel

    with isolated_default_pair():

        class HookType(DjangoModelType):
            class Meta:
                model = HookModel
                model_operations = ("retrieve",)

        class Query(ObjectType):
            hook = HookType.RetrieveField()

        schema = DjangoGraphQLSchema(query=Query)
        result = graphql_sync(
            schema.graphql_schema, '{ hook(id: "not-an-id") { text } }'
        )

    assert result.data == {"hook": None}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].message == "Invalid ID: expected an integer."
    assert result.errors[0].extensions == {"code": "INVALID_ID"}


@pytest.mark.django_db
def test_valid_missing_and_char_primary_keys_keep_orm_meaning() -> None:
    """Missing rows stay null and text primary keys are not treated as malformed."""
    from .models import CustomPKProduct

    assert _ArticleType.get_node(None, 999999) is None
    article = graphql_sync(
        _SCHEMA.graphql_schema, '{ article(id: "999999") { title } }'
    )
    assert article.data == {"article": None} and article.errors is None

    product = CustomPKProduct.objects.create(slug="abc", title="valid")
    local_registry = Registry()

    class ProductType(DjangoObjectType):
        class Meta:
            model = CustomPKProduct
            registry = local_registry
            only_fields = ("slug", "title")

    assert ProductType.get_node(None, "abc") == product
    assert ProductType.get_node(None, "missing") is None


@pytest.mark.django_db
def test_hidden_row_still_looks_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queryset scope remains before PK lookup and hides a valid ID."""
    row = ScopedArticle.objects.create(title="private", is_public=False)
    seen: list[str] = []

    @classmethod
    def scoped(cls, queryset, info):
        seen.append("scope")
        return queryset.filter(is_public=True)

    monkeypatch.setattr(_ArticleType, "get_queryset", scoped)
    assert _ArticleType.get_node(None, row.pk) is None
    result = graphql_sync(
        _SCHEMA.graphql_schema, f'{{ article(id: "{row.pk}") {{ title }} }}'
    )
    assert result.data == {"article": None} and result.errors is None
    assert seen == ["scope", "scope"]


@pytest.mark.django_db
def test_unrelated_queryset_errors_are_not_relabelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even another malformed value for the same PK is unrelated to this ID."""
    import django_graphex.types as types_module

    class OtherLookup:
        model = ScopedArticle

        def get(self, **kwargs):
            assert kwargs == {"pk": "accepted"}
            return ScopedArticle.objects.get(pk="different-malformed")

    monkeypatch.setattr(
        types_module, "apply_object_type_get_queryset", lambda *args: OtherLookup()
    )
    with pytest.raises(ValueError, match="different-malformed"):
        _ArticleType.get_node(None, "accepted")

    class DirectFailure:
        model = ScopedArticle

        def get(self, **kwargs):
            assert kwargs == {"pk": "accepted"}
            raise ValueError("queryset failure")

    monkeypatch.setattr(
        types_module, "apply_object_type_get_queryset", lambda *args: DirectFailure()
    )
    with pytest.raises(ValueError, match="queryset failure"):
        _ArticleType.get_node(None, "accepted")


@pytest.mark.django_db
def test_custom_primary_key_prepared_once_with_generic_error() -> None:
    """A custom field's conversion runs once and never leaks its message."""
    from django.core.exceptions import ValidationError
    from django.db import models

    class CustomKey(models.CharField):
        calls = 0

        def get_prep_value(self, value):
            type(self).calls += 1
            if value == "bad-custom":
                raise ValidationError("private custom field detail")
            return super().get_prep_value(value)

    class CustomRow(models.Model):
        key = CustomKey(max_length=30, primary_key=True)

        class Meta:
            app_label = "tests"

    local_registry = Registry()

    class CustomType(DjangoObjectType):
        class Meta:
            model = CustomRow
            registry = local_registry
            only_fields = ("key",)

    with pytest.raises(GraphQLError) as caught:
        CustomType.get_node(None, "bad-custom")
    assert caught.value.message == "The ID format is invalid."
    assert caught.value.extensions == {"code": "INVALID_ID"}
    assert "private custom" not in str(caught.value.formatted)
    assert CustomKey.calls == 1


@pytest.mark.django_db
def test_custom_primary_key_renamed_argument_keeps_safe_public_error() -> None:
    """A custom preparation parameter name does not affect error attribution."""
    import json

    from django.core.exceptions import ValidationError
    from django.db import models
    from django.test import RequestFactory, override_settings

    from django_graphex.views import GraphQLView

    class CustomKey(models.CharField):
        calls: list[object] = []

        def get_prep_value(self, raw):
            type(self).calls.append(raw)
            if raw == "malformed-renamed-id":
                raise ValidationError(f"private custom field detail: {raw}")
            return super().get_prep_value(raw)

    class RenamedKeyRow(models.Model):
        key = CustomKey(max_length=30, primary_key=True)

        class Meta:
            app_label = "tests"

    local_registry = Registry()

    class CustomType(DjangoObjectType):
        class Meta:
            model = RenamedKeyRow
            registry = local_registry
            only_fields = ("key",)

    class Query(ObjectType):
        custom = DjangoObjectField(CustomType)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    query = '{ custom(id: "malformed-renamed-id") { key } }'

    result = graphql_sync(schema.graphql_schema, query)
    assert result.data == {"custom": None}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].message == "The ID format is invalid."
    assert result.errors[0].extensions == {"code": "INVALID_ID"}
    assert "private custom" not in str(result.errors[0].formatted)
    assert CustomKey.calls == ["malformed-renamed-id"]

    request = RequestFactory().post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    with override_settings(DEBUG=False):
        response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert payload["data"] == {"custom": None}
    assert payload["errors"][0]["message"] == "The ID format is invalid."
    assert payload["errors"][0]["extensions"] == {"code": "INVALID_ID"}
    assert "private custom" not in response.content.decode()
    assert CustomKey.calls == ["malformed-renamed-id"] * 2

    raw_id = "malformed-renamed-id"
    with pytest.raises(GraphQLError) as caught:
        CustomType.get_node(None, raw_id)
    assert caught.value.message == "The ID format is invalid."
    assert caught.value.extensions == {"code": "INVALID_ID"}
    assert CustomKey.calls[-1] is raw_id
    assert len(CustomKey.calls) == 3


@pytest.mark.django_db
def test_http_production_wire_keeps_deliberate_error() -> None:
    """Production HTTP formatting retains the approved public error and code."""
    import json

    from django.test import RequestFactory, override_settings

    from django_graphex.views import GraphQLView

    request = RequestFactory().post(
        "/graphql/",
        data=json.dumps({"query": '{ article(id: "not-an-id") { title } }'}),
        content_type="application/json",
    )
    with override_settings(DEBUG=False):
        response = GraphQLView.as_view(schema=_SCHEMA)(request)
    payload = json.loads(response.content)
    assert payload["data"] == {"article": None}
    assert payload["errors"][0]["message"] == "Invalid ID: expected an integer."
    assert payload["errors"][0]["extensions"]["code"] == "INVALID_ID"
    assert "not-an-id" not in response.content.decode()


@pytest.mark.django_db
def test_existing_numeric_and_null_coercion_remain_orm_owned() -> None:
    """Accepted Python lookup forms retain Django's existing behavior."""
    row = ScopedArticle.objects.create(title="first", is_public=True)
    assert row.pk == 1
    assert _ArticleType.get_node(None, float(row.pk)) == row
    assert _ArticleType.get_node(None, True) == row
    assert _ArticleType.get_node(None, None) is None


@pytest.mark.django_db
def test_non_null_field_bubbles_the_deliberate_error() -> None:
    """GraphQL non-null propagation keeps the safe error and field path."""
    from graphql import GraphQLNonNull, GraphQLString

    from django_graphex.core import field

    class RequiredQuery(ObjectType):
        article = field(
            GraphQLNonNull(GraphQLString),
            resolver=lambda root, info: _ArticleType.get_node(info, "bad-id"),
        )

    schema = DjangoGraphQLSchema(query=RequiredQuery)
    result = graphql_sync(schema.graphql_schema, "{ article }")
    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].message == "Invalid ID: expected an integer."
    assert result.errors[0].extensions == {"code": "INVALID_ID"}
    assert result.errors[0].path == ["article"]


@pytest.mark.django_db
def test_uuid_missing_and_valid_ids_keep_lookup_behavior() -> None:
    """A valid UUID resolves normally and a different valid UUID is missing."""
    from uuid import UUID

    row = UUIDThing.objects.create(name="found")
    assert _UUIDType.get_node(None, row.pk) == row
    assert _UUIDType.get_node(None, UUID(int=0)) is None
    found = graphql_sync(
        _SCHEMA.graphql_schema, f'{{ thing(id: "{row.pk}") {{ name }} }}'
    )
    missing = graphql_sync(
        _SCHEMA.graphql_schema,
        '{ thing(id: "00000000-0000-0000-0000-000000000000") { name } }',
    )
    assert found.data == {"thing": {"name": "found"}} and found.errors is None
    assert missing.data == {"thing": None} and missing.errors is None


@pytest.mark.django_db
def test_retrieve_authorization_error_precedes_id_conversion() -> None:
    """A permission-hook failure is never recast as an ID-format error."""
    from django_graphex.types import DjangoModelType

    from ._schema_isolation import isolated_default_pair
    from .models import HookModel

    with isolated_default_pair():

        class HookType(DjangoModelType):
            class Meta:
                model = HookModel
                model_operations = ("retrieve",)

        @classmethod
        def deny(cls, info, action):
            assert action == "retrieve"
            raise ValueError("permission hook failure")

        HookType.authorize = deny
        with pytest.raises(ValueError, match="permission hook failure"):
            HookType.retrieve(HookModel.objects, None, None, id="not-an-id")


@pytest.mark.django_db
def test_existing_missing_exception_boundary_in_hooks_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model missing exception raised by a lookup hook still means no row."""
    import django_graphex.fields as fields_module
    import django_graphex.types as types_module
    from django_graphex.types import DjangoModelType

    from ._schema_isolation import isolated_default_pair
    from .models import HookModel

    def missing(model):
        raise model.DoesNotExist()

    monkeypatch.setattr(
        types_module,
        "apply_object_type_get_queryset",
        lambda *args: missing(ScopedArticle),
    )
    assert _ArticleType.get_node(None, 123) is None

    monkeypatch.setattr(
        fields_module,
        "queryset_factory",
        lambda *args, **kwargs: missing(ScopedArticle),
    )
    assert (
        DjangoObjectField.object_resolver(
            ScopedArticle.objects, _ArticleType, None, None, id=123
        )
        is None
    )

    with isolated_default_pair():

        class HookType(DjangoModelType):
            class Meta:
                model = HookModel
                model_operations = ("retrieve",)

        monkeypatch.setattr(HookType, "authorize", classmethod(lambda *args: None))
        monkeypatch.setattr(
            types_module,
            "queryset_factory",
            lambda *args, **kwargs: missing(HookModel),
        )
        assert HookType.retrieve(HookModel.objects, None, None, id=123) is None
