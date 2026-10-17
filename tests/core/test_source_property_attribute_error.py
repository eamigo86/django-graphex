"""Public explicit-source property failure contracts."""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import RequestFactory, override_settings
from graphql import GraphQLString, graphql_sync

from django_graphex.core import Field, ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import BaseGraphQLView
from tests.models import Author


def test_source_property_attribute_error_surfaces_graphql_resolution_error() -> None:
    """Expose a property getter failure without losing sibling data or origin."""
    failure = AttributeError("failure inside property getter")

    class Root:
        """Expose a failing property and a healthy sibling attribute."""

        healthy = "visible"

        @property
        def broken(self) -> str:
            """Raise the exact property failure witnessed by GraphQL.

            Raises:
                AttributeError: The captured getter failure.
            """
            raise failure

    class Query(ObjectType):
        """Map explicit source attributes to public GraphQL fields."""

        broken = Field(GraphQLString, source="broken", name="brokenAlias")
        healthy = Field(GraphQLString, source="healthy")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    result = graphql_sync(schema, "{ brokenAlias healthy }", root_value=Root())

    assert result.data == {"brokenAlias": None, "healthy": "visible"}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["brokenAlias"]
    assert result.errors[0].original_error is failure


def test_inherited_source_property_failure_preserves_required_propagation() -> None:
    """Propagate required-field null while retaining inherited getter origin."""
    failure = AttributeError("inherited property failure")

    class BaseRoot:
        """Define the inherited failing source property."""

        @property
        def broken(self) -> str:
            """Raise the captured inherited property failure.

            Raises:
                AttributeError: The captured inherited getter failure.
            """
            raise failure

    class Root(BaseRoot):
        """Inherit the property without replacing its descriptor."""

    class Query(ObjectType):
        """Expose the inherited property through a required alias."""

        required = Field(GraphQLString, source="broken", required=True)

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    result = graphql_sync(schema, "{ required }", root_value=Root())

    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["required"]
    assert result.errors[0].original_error is failure


def test_source_absence_and_successful_dynamic_fallback_remain_nullable() -> None:
    """Keep normal missing, null, mapping, and dynamic lookup semantics."""

    class Root:
        """Provide successful and absent source attributes."""

        healthy = "visible"

        @property
        def empty(self) -> None:
            """Return a legitimate null from a property."""
            return None

        @property
        def fallback(self) -> str:
            """Trigger normal Python dynamic fallback.

            Raises:
                AttributeError: Signals that Python should try dynamic lookup.
            """
            raise AttributeError("property intentionally defers")

        def method(self) -> str:
            """Return a zero-argument source method value.

            Returns:
                The source method value.
            """
            return "called"

        def __getattr__(self, name: str) -> str:
            """Provide one fallback and leave all other names absent.

            Args:
                name: Attribute requested by Python lookup.

            Returns:
                The dynamic fallback value when available.

            Raises:
                AttributeError: The requested dynamic attribute is absent.
            """
            if name == "fallback":
                return "dynamic"
            raise AttributeError(name)

    class Query(ObjectType):
        """Expose independent source lookup shapes."""

        healthy = Field(GraphQLString, source="healthy")
        empty = Field(GraphQLString, source="empty")
        missing = Field(GraphQLString, source="missing")
        fallback = Field(GraphQLString, source="fallback")
        method = Field(GraphQLString, source="method")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    result = graphql_sync(
        schema, "{ healthy empty missing fallback method }", root_value=Root()
    )
    assert result.data == {
        "healthy": "visible",
        "empty": None,
        "missing": None,
        "fallback": "dynamic",
        "method": "called",
    }
    assert result.errors is None

    mapping = graphql_sync(
        schema, "{ healthy missing }", root_value={"healthy": "mapped"}
    )
    assert mapping.data == {"healthy": "mapped", "missing": None}
    assert mapping.errors is None


def test_absent_django_reverse_one_to_one_stays_nullable_through_property() -> None:
    """Treat Django's absent reverse relation as null, even in a property."""

    class Root:
        """Wrap an unsaved author with no reverse one-to-one relation."""

        author = Author(name="unpersisted", bio="")

        @property
        def profile(self) -> Any:
            """Read the genuinely absent Django relation.

            Returns:
                The related profile if one exists.

            Raises:
                ObjectDoesNotExist: The reverse relation is absent.
            """
            return self.author.author_profile

    class Query(ObjectType):
        """Read both direct and property-wrapped reverse relations."""

        direct = Field(GraphQLString, source="author_profile")
        wrapped = Field(GraphQLString, source="profile")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    root = Root()
    direct = graphql_sync(schema, "{ direct }", root_value=root.author)
    wrapped = graphql_sync(schema, "{ wrapped }", root_value=root)
    assert direct.data == {"direct": None} and direct.errors is None
    assert wrapped.data == {"wrapped": None} and wrapped.errors is None


def test_custom_attribute_lookup_and_nested_required_propagation() -> None:
    """Preserve successful custom lookup and a nested required error path."""
    failure = AttributeError("nested property failed")

    class ChildRoot:
        """Provide a failing property and a successful custom attribute."""

        @property
        def broken(self) -> str:
            """Raise the nested failure without changing its identity.

            Raises:
                AttributeError: The captured nested getter failure.
            """
            raise failure

        def __getattribute__(self, name: str) -> Any:
            """Override one source name while delegating normal lookup.

            Args:
                name: Attribute requested by Python lookup.

            Returns:
                The custom value or normal attribute value.
            """
            if name == "custom":
                return "custom value"
            return object.__getattribute__(self, name)

    class Child(ObjectType):
        """Make one source non-null and another custom-lookup backed."""

        broken = Field(GraphQLString, source="broken", required=True)
        custom = Field(GraphQLString, source="custom")

    class Query(ObjectType):
        """Expose a nullable child alongside a healthy sibling."""

        child = Field(Child, resolver=lambda root, info: ChildRoot())
        sibling = Field(GraphQLString, resolver=lambda root, info: "visible")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    custom = graphql_sync(schema, "{ child { custom } sibling }")
    assert custom.data == {"child": {"custom": "custom value"}, "sibling": "visible"}
    assert custom.errors is None

    failed = graphql_sync(schema, "{ child { broken } sibling }")
    assert failed.data == {"child": None, "sibling": "visible"}
    assert failed.errors is not None and len(failed.errors) == 1
    assert failed.errors[0].path == ["child", "broken"]
    assert failed.errors[0].original_error is failure


def test_unrelated_descriptor_and_dynamic_absence_keep_legacy_null() -> None:
    """Do not apply the property policy to other descriptors or absent fallback."""

    class Descriptor:
        """Represent a non-property descriptor whose lookup fails."""

        def __get__(self, instance: Any, owner: type[Any]) -> str:
            """Raise an attribute absence unrelated to a Python property.

            Args:
                instance: Object being resolved.
                owner: Class containing this descriptor.

            Raises:
                AttributeError: The descriptor does not supply a value.
            """
            raise AttributeError("other descriptor is absent")

    class Root:
        """Expose distinct non-property and dynamic absence paths."""

        other = Descriptor()

        @property
        def deferred(self) -> str:
            """Defer to dynamic lookup rather than surface a getter failure.

            Raises:
                AttributeError: Request the normal dynamic fallback.
            """
            raise AttributeError("try dynamic lookup")

        def __getattr__(self, name: str) -> str:
            """Leave the deferred dynamic attribute absent.

            Args:
                name: Attribute requested by Python lookup.

            Raises:
                AttributeError: The dynamic attribute is absent.
            """
            raise AttributeError(name)

    class Query(ObjectType):
        """Read both absence paths through explicit source declarations."""

        other = Field(GraphQLString, source="other")
        deferred = Field(GraphQLString, source="deferred")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    result = graphql_sync(schema, "{ other deferred }", root_value=Root())
    assert result.data == {"other": None, "deferred": None}
    assert result.errors is None


def test_explicit_resolver_precedes_source_and_method_body_error_is_unchanged() -> None:
    """Keep resolver precedence and non-property method errors unchanged."""
    method_failure = AttributeError("method failed")

    class Root:
        """Expose a property and a method that must not be conflated."""

        @property
        def broken(self) -> str:
            """Fail only if explicit resolver precedence breaks.

            Raises:
                AttributeError: The source must not run with explicit resolver.
            """
            raise AttributeError("source should not run")

        def method(self) -> str:
            """Raise the original method-body exception.

            Raises:
                AttributeError: The captured method-body failure.
            """
            raise method_failure

    class Query(ObjectType):
        """Use a resolver for one field and a source method for another."""

        explicit = Field(
            GraphQLString,
            source="broken",
            resolver=lambda root, info: "explicit",
        )
        method = Field(GraphQLString, source="method")

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    result = graphql_sync(schema, "{ explicit method }", root_value=Root())
    assert result.data == {"explicit": "explicit", "method": None}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["method"]
    assert result.errors[0].original_error is method_failure


@override_settings(DEBUG=False)
def test_source_property_failure_keeps_safe_http_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hide getter details from HTTP while correlating the original in logs.

    Args:
        caplog: Captured internal error records.
    """
    failure = AttributeError("private source property failure")

    class Root:
        """Expose an HTTP request's failing source property."""

        @property
        def broken(self) -> str:
            """Raise the exact private failure for HTTP diagnostics.

            Raises:
                AttributeError: The captured request-local getter failure.
            """
            raise failure

    class Child(ObjectType):
        """Expose the failing property with an explicit source."""

        broken = Field(GraphQLString, source="broken")

    class Query(ObjectType):
        """Return the request-local object to the public view."""

        child = Field(Child, resolver=lambda root, info: info.context.test_root)

    schema = DjangoGraphQLSchema(query=Query)
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": "{ child { broken } }"}),
        content_type="application/json",
    )
    request.test_root = Root()
    request.user = SimpleNamespace(is_authenticated=True, pk=7, is_active=True)
    with caplog.at_level(logging.ERROR, logger="django_graphex.internal_errors"):
        response = BaseGraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code == 200
    assert payload["data"] == {"child": {"broken": None}}
    error = payload["errors"][0]
    assert error["message"] == "An internal error occurred."
    assert error["path"] == ["child", "broken"]
    assert error["extensions"]["code"] == "INTERNAL_SERVER_ERROR"
    error_id = error["extensions"]["errorId"]
    assert re.fullmatch(r"[0-9a-f]{32}", error_id)
    assert "private source" not in response.content.decode()
    records = [record for record in caplog.records if error_id in record.getMessage()]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is failure
