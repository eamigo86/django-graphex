"""Public HTTP regression for relation fields sharing lookup names."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from django.db import models
from django.test import Client, override_settings
from django.urls import path

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.filtering.translate import to_q
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.views import GraphQLView

from ._schema_isolation import isolated_pair


class LookupNameTarget(models.Model):
    """Related row with fields whose names overlap lookup operators.

    The primary key is named code to test non-id primary-key traversal.
    """

    code = models.IntegerField(primary_key=True)
    year = models.IntegerField()
    month = models.IntegerField()
    day = models.IntegerField()
    range = models.CharField(max_length=20)
    exact = models.IntegerField()

    class Meta:
        """Keep the regression's tables isolated from application models.

        The test app creates these tables in its disposable database.
        """

        app_label = "tests"
        db_table = "t11d_lookup_name_target"


class LookupNameOwner(models.Model):
    """Parent row filtered by its target's fields or primary key.

    Forward and many-to-many relations exercise both translator paths.
    """

    name = models.CharField(max_length=20)
    target = models.ForeignKey(
        LookupNameTarget, related_name="owners", on_delete=models.CASCADE
    )
    targets = models.ManyToManyField(LookupNameTarget, related_name="group_owners")

    class Meta:
        """Keep the regression's tables isolated from application models.

        The test app creates these tables in its disposable database.
        """

        app_label = "tests"
        db_table = "t11d_lookup_name_owner"


_nested_registry = Registry()


class LookupNameTargetType(DjangoObjectType):
    """Publish target fields to the native relation filter builder.

    The nested owner schema uses this projection for filter paths.
    """

    class Meta:
        """Bind this output type to the nested schema registry.

        The isolated registry avoids cross-schema type-name reuse.
        """

        model = LookupNameTarget
        registry = _nested_registry


class NestedLookupNameOwnerType(DjangoObjectType):
    """Declare paths through related fields that share lookup names.

    The direct relation declaration also checks combined-input behavior.
    """

    class Meta:
        """Expose the existing nested relation filter input.

        Both forward and many-to-many paths use ordinary declarations.
        """

        model = LookupNameOwner
        registry = _nested_registry
        filter_fields = {
            "target": ("exact", "in", "range"),
            "target__year": ("exact",),
            "target__month": ("exact",),
            "target__day": ("exact",),
            "target__range": ("exact",),
            "target__exact": ("exact",),
            "targets__range": ("exact",),
        }


class NestedLookupNameQuery(ObjectType):
    """Serve nested relation filters through the public list field.

    HTTP requests pass through the production resolver and backend.
    """

    owners = DjangoFilterListField(NestedLookupNameOwnerType)


_nested_schema = DjangoGraphQLSchema(
    query=NestedLookupNameQuery, registries=isolated_pair(_nested_registry)
)
_direct_registry = Registry()


class DirectLookupNameTargetType(DjangoObjectType):
    """Publish the target to a separate direct-PK filter schema.

    Its fields retain names that may shadow direct lookup operators.
    """

    class Meta:
        """Bind this output type to the direct schema registry.

        The pair is separate from the nested-input schema.
        """

        model = LookupNameTarget
        registry = _direct_registry


class DirectLookupNameOwnerType(DjangoObjectType):
    """Declare direct relation primary-key lookups.

    Their generated scalar/list shape differs from nested field inputs.
    """

    class Meta:
        """Expose the existing direct relation lookup input.

        No nested path is declared in this schema.
        """

        model = LookupNameOwner
        registry = _direct_registry
        filter_fields = {
            "target": ("exact", "in", "range"),
            "targets": ("exact", "in", "range"),
        }


class DirectLookupNameQuery(ObjectType):
    """Serve direct relation filters through the public list field.

    HTTP assertions therefore cover the generated query boundary.
    """

    owners = DjangoFilterListField(DirectLookupNameOwnerType)


_direct_schema = DjangoGraphQLSchema(
    query=DirectLookupNameQuery, registries=isolated_pair(_direct_registry)
)
_urlconf = types.ModuleType("t11d_lookup_name_urls")
_urlconf.urlpatterns = [
    path("nested/", GraphQLView.as_view(schema=_nested_schema)),
    path("direct/", GraphQLView.as_view(schema=_direct_schema)),
]
sys.modules[_urlconf.__name__] = _urlconf


def _post(
    endpoint: str, query: str, variables: dict[str, Any] | None = None
) -> list[str]:
    """Execute one public HTTP filter and return sorted parent names.

    Args:
        endpoint: Which of the two generated schemas to query.
        query: A complete GraphQL document.
        variables: Optional variables for the document.

    Returns:
        Sorted names from the successful public response.
    """
    with override_settings(ROOT_URLCONF=_urlconf.__name__):
        response = Client().post(
            f"/{endpoint}/",
            data=json.dumps({"query": query, "variables": variables}),
            content_type="application/json",
        )
    payload: dict[str, Any] = json.loads(response.content)
    assert response.status_code == 200, payload
    assert "errors" not in payload, payload
    return sorted(row["name"] for row in payload["data"]["owners"])


@pytest.mark.django_db
def test_nested_lookup_name_and_direct_pk_exact() -> None:
    """Nested fields and shadowed PK lookups select their ORM row sets.

    Literal and variable inputs retain the previously generated SDL shape.
    """
    first = LookupNameTarget.objects.create(
        code=1, year=2024, month=2, day=3, range="alpha", exact=7
    )
    second = LookupNameTarget.objects.create(
        code=2, year=2023, month=3, day=4, range="beta", exact=8
    )
    third = LookupNameTarget.objects.create(
        code=3, year=2025, month=2, day=3, range="beta", exact=9
    )
    owner_first = LookupNameOwner.objects.create(name="first", target=first)
    owner_second = LookupNameOwner.objects.create(name="second", target=second)
    owner_third = LookupNameOwner.objects.create(name="third", target=third)
    owner_first.targets.add(first, second)
    owner_second.targets.add(second)
    owner_third.targets.add(third)

    nested_input = (
        _nested_schema.graphql_schema.query_type.fields["owners"].args["filter"].type
    )
    direct_input = (
        _direct_schema.graphql_schema.query_type.fields["owners"].args["filter"].type
    )
    assert set(nested_input.fields["target"].type.fields) >= {
        "code",
        "year",
        "month",
        "day",
        "range",
        "exact",
    }
    assert {
        name: str(field.type)
        for name, field in direct_input.fields["target"].type.fields.items()
    } == {"exact": "Int", "in": "[Int]", "range": "[Int]"}

    assert _post(
        "nested",
        "{ owners(filter: { target: { year: { exact: 2024 } } }) { name } }",
    ) == ["first"]
    assert _post("direct", "{ owners(filter: { target: { exact: 1 } }) { name } }") == [
        "first"
    ]
    for field, value, expected in (
        ("month", "2", ["first", "third"]),
        ("day", "3", ["first", "third"]),
        ("range", '"beta"', ["second", "third"]),
        ("exact", "8", ["second"]),
    ):
        assert (
            _post(
                "nested",
                f"{{ owners(filter: {{ target: {{ {field}: {{ exact: {value} }} }} }}) {{ name }} }}",
            )
            == expected
        )
    assert _post(
        "direct", "{ owners(filter: { target: { in: [1, 3] } }) { name } }"
    ) == ["first", "third"]
    assert _post(
        "direct", "{ owners(filter: { target: { range: [1, 3] } }) { name } }"
    ) == ["first", "second", "third"]
    assert _post(
        "direct", "{ owners(filter: { targets: { exact: 1 } }) { name } }"
    ) == ["first"]
    assert _post(
        "direct", "{ owners(filter: { targets: { in: [1, 2] } }) { name } }"
    ) == ["first", "second"]
    assert _post(
        "direct", "{ owners(filter: { targets: { range: [1, 3] } }) { name } }"
    ) == ["first", "second", "third"]
    assert _post(
        "nested",
        '{ owners(filter: { targets: { range: { exact: "alpha" } } }) { name } }',
    ) == ["first"]
    prefixed_q, prefixed_many = to_q(
        {"target": {"exact": 1}}, LookupNameOwner, prefix="outer__"
    )
    assert prefixed_q == models.Q(outer__target__pk__exact=1)
    assert prefixed_many is False
    reverse_q, reverse_many = to_q(
        {"owners": {"exact": owner_first.pk}}, LookupNameTarget
    )
    assert reverse_many is True
    assert list(
        LookupNameTarget.objects.filter(reverse_q).values_list("code", flat=True)
    ) == [1]

    variable_query = (
        f"query ($filter: {nested_input.name}) {{ owners(filter: $filter) {{ name }} }}"
    )
    assert _post(
        "nested",
        variable_query,
        {"filter": {"target": {"year": {"exact": 2024}, "code": {"exact": 1}}}},
    ) == ["first"]
