"""Public HTTP regressions for numeric date-part query filters."""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, time, timezone
from typing import Any

import pytest
from django.db import connection, models
from django.test import Client, override_settings
from django.urls import path
from graphql import GraphQLBoolean, GraphQLInt, GraphQLList, GraphQLString

from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
)
from django_graphex.filtering.native_schema import (
    _lookups_input_type,
    build_subscription_filter_input_type,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView

from ._schema_isolation import isolated_pair

_registry = Registry()
_front_registry = Registry()

_FILTER_FIELDS = {
    "calendar_day": (
        "exact",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "range",
        "isnull",
        "year",
        "month",
        "day",
        "week_day",
    ),
    "moment": (
        "exact",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "range",
        "isnull",
        "year",
        "month",
        "day",
        "week_day",
        "hour",
        "minute",
        "second",
    ),
    "clock": ("exact", "hour"),
    "label": ("exact", "year"),
}


class DatePartFilterParent(models.Model):
    """Isolated owner for the nested relation-filter frontend.

    The owner distinguishes the nested path from root list queries.
    """

    label = models.CharField(max_length=32)

    class Meta:
        """Keep the owner table in disposable tests only.

        A unique table name avoids collisions with production models.
        """

        app_label = "tests"
        db_table = "t11b_date_part_filter_parent"


class DatePartFilterRow(models.Model):
    """Isolated row with the two approved source field kinds.

    The extra fields guard unchanged TimeField and custom lookup behavior.
    """

    label = models.CharField(max_length=32)
    calendar_day = models.DateField(null=True)
    moment = models.DateTimeField(null=True)
    clock = models.TimeField(null=True)
    parent = models.ForeignKey(
        DatePartFilterParent,
        null=True,
        related_name="dated_children",
        on_delete=models.CASCADE,
    )

    class Meta:
        """Keep the model and table local to disposable tests.

        The schema is not added to an application migration.
        """

        app_label = "tests"
        db_table = "t11b_date_part_filter_row"


class DatePartFilterList(DjangoListObjectType):
    """Expose explicitly selected date and datetime part lookups.

    The generated list-object field uses this declaration.
    """

    class Meta:
        """Bind an isolated registry and an explicit lookup declaration.

        The broad list covers both changed parts and preserved whole values.
        """

        model = DatePartFilterRow
        registry = _registry
        filter_fields = _FILTER_FIELDS


class DatePartFilterObject(DjangoObjectType):
    """Expose the same model through flat and paginated query fields.

    A separate public output type exercises both root frontends.
    """

    class Meta:
        """Use a separate registry for the distinct public output type.

        This honors the one-output-per-model-per-registry boundary.
        """

        model = DatePartFilterRow
        registry = _front_registry
        filter_fields = _FILTER_FIELDS


class DatePartFilterParentType(DjangoObjectType):
    """Expose nested child filters through the same date-part input.

    The parent provides a real reverse foreign-key path.
    """

    class Meta:
        """Bind the owner to the separate frontend registry.

        It shares the child output type without duplicating that model slot.
        """

        model = DatePartFilterParent
        registry = _front_registry

    dated_children = DjangoFilterListField(DatePartFilterObject)


class DatePartFilterQuery(ObjectType):
    """Serve generated date-part filters through the public list field.

    This root is used by the primary HTTP regression.
    """

    rows = DjangoListObjectField(DatePartFilterList)


class DatePartFilterFrontQuery(ObjectType):
    """Serve flat and paginated filters from one canonical input type.

    The same schema also exposes a nested relation consumer.
    """

    flat_rows = DjangoFilterListField(DatePartFilterObject)
    paged_rows = DjangoFilterPaginateListField(
        DatePartFilterObject,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, ordering="id"),
    )
    parents = DjangoFilterListField(DatePartFilterParentType)


_schema = DjangoGraphQLSchema(
    query=DatePartFilterQuery, registries=isolated_pair(_registry)
)
_front_schema = DjangoGraphQLSchema(
    query=DatePartFilterFrontQuery, registries=isolated_pair(_front_registry)
)
_urlconf = types.ModuleType("t11b_date_part_filter_urls")
_urlconf.urlpatterns = [
    path("graphql/", GraphQLView.as_view(schema=_schema)),
    path("front/", GraphQLView.as_view(schema=_front_schema)),
]
sys.modules[_urlconf.__name__] = _urlconf


def _post(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    endpoint: str = "graphql",
) -> tuple[int, dict]:
    """Execute a query through the public Django GraphQL HTTP view.

    Args:
        query: GraphQL document to execute.
        variables: Optional GraphQL variable values.
        endpoint: The public test URL to call.

    Returns:
        HTTP status and decoded response payload.
    """
    with override_settings(ROOT_URLCONF=_urlconf.__name__, TIME_ZONE="UTC"):
        response = Client().post(
            f"/{endpoint}/",
            data=json.dumps({"query": query, "variables": variables}),
            content_type="application/json",
        )
    return response.status_code, json.loads(response.content)


@pytest.mark.django_db(transaction=True)
def test_numeric_date_parts_have_int_sdl_and_work_over_http() -> None:
    """Date and datetime part literals and variables select the matching row.

    Also preserve full-value filters and existing null and Boolean behavior.
    """

    filter_type = _schema.graphql_schema.query_type.fields["rows"].args["filter"].type
    date_lookups = filter_type.fields["calendarDay"].type.fields
    datetime_lookups = filter_type.fields["moment"].type.fields
    actual_types = {
        "date_year": date_lookups["year"].type,
        "datetime_year": datetime_lookups["year"].type,
        "datetime_hour": datetime_lookups["hour"].type,
    }
    print("DATE_PART_SDL", {key: str(value) for key, value in actual_types.items()})

    existing_tables = set(connection.introspection.table_names())
    parent_created_here = DatePartFilterParent._meta.db_table not in existing_tables
    created_here = DatePartFilterRow._meta.db_table not in existing_tables
    if parent_created_here:
        with connection.schema_editor() as editor:
            editor.create_model(DatePartFilterParent)
    if created_here:
        with connection.schema_editor() as editor:
            editor.create_model(DatePartFilterRow)
    try:
        parent = DatePartFilterParent.objects.create(label="group")
        DatePartFilterRow.objects.bulk_create(
            [
                DatePartFilterRow(
                    label="match",
                    calendar_day=date(2024, 7, 5),
                    moment=datetime(2024, 7, 5, 11, 30, tzinfo=timezone.utc),
                    clock=time(11, 30),
                    parent=parent,
                ),
                DatePartFilterRow(
                    label="other",
                    calendar_day=date(2023, 8, 6),
                    moment=datetime(2023, 8, 6, 12, 31, 1, tzinfo=timezone.utc),
                    clock=time(12, 31, 1),
                    parent=parent,
                ),
                DatePartFilterRow(
                    label="null", calendar_day=None, moment=None, parent=parent
                ),
            ]
        )
        cases = (
            (
                "date_year_literal",
                "{ rows(filter: { calendarDay: { year: 2024 } }) { results { label } } }",
                None,
            ),
            (
                "datetime_hour_literal",
                "{ rows(filter: { moment: { hour: 11 } }) { results { label } } }",
                None,
            ),
            (
                "date_year_variable",
                "query($part: Int!) { rows(filter: { calendarDay: { year: $part } }) { results { label } } }",
                {"part": 2024},
            ),
            (
                "datetime_year_variable",
                "query($part: Int!) { rows(filter: { moment: { year: $part } }) { results { label } } }",
                {"part": 2024},
            ),
        )
        observed = {}
        for label, query, variables in cases:
            status, payload = _post(query, variables)
            print("DATE_PART_HTTP", label, status, json.dumps(payload, sort_keys=True))
            observed[label] = (status, payload)

        assert all(value is GraphQLInt for value in actual_types.values())
        for status, payload in observed.values():
            assert status == 200, payload
            assert payload["data"]["rows"]["results"] == [{"label": "match"}]

        date_parts = {"year": 2024, "month": 7, "day": 5, "week_day": 6}
        datetime_parts = {
            **date_parts,
            "hour": 11,
            "minute": 30,
            "second": 0,
        }
        for field_name, parts in (
            ("calendarDay", date_parts),
            ("moment", datetime_parts),
        ):
            for lookup, value in parts.items():
                status, payload = _post(
                    f"{{ rows(filter: {{ {field_name}: {{ {lookup}: {value} }} }}) "
                    "{ results { label } } }"
                )
                assert status == 200, (field_name, lookup, payload)
                assert payload["data"]["rows"]["results"] == [{"label": "match"}], (
                    field_name,
                    lookup,
                    payload,
                )

        for field_name, scalar_name, iso_value in (
            ("calendarDay", "Date", "2024-07-05"),
            ("moment", "DateTime", "2024-07-05T11:30:00+00:00"),
        ):
            fields = filter_type.fields[field_name].type.fields
            for lookup in ("exact", "gt", "gte", "lt", "lte"):
                assert fields[lookup].type.name == scalar_name
            for lookup in ("in", "range"):
                assert isinstance(fields[lookup].type, GraphQLList)
                assert fields[lookup].type.of_type.name == scalar_name
            assert fields["isnull"].type is GraphQLBoolean
            for lookup, value in (
                ("exact", f'"{iso_value}"'),
                ("gte", f'"{iso_value}"'),
                ("in", f'["{iso_value}"]'),
                ("range", f'["{iso_value}", "{iso_value}"]'),
            ):
                status, payload = _post(
                    f"{{ rows(filter: {{ {field_name}: {{ {lookup}: {value} }} }}) "
                    "{ results { label } } }"
                )
                assert status == 200, (field_name, lookup, payload)
                assert payload["data"]["rows"]["results"] == [{"label": "match"}], (
                    field_name,
                    lookup,
                    payload,
                )
            status, _ = _post(
                f"{{ rows(filter: {{ {field_name}: {{ exact: 2024 }} }}) "
                "{ results { label } } }"
            )
            assert status == 400
            status, _ = _post(
                f'{{ rows(filter: {{ {field_name}: {{ year: "2024" }} }}) '
                "{ results { label } } }"
            )
            assert status == 400

            for lookup, expected in (
                ("exact: null", ["null"]),
                ("isnull: true", ["null"]),
                ("", ["match", "null", "other"]),
            ):
                status, payload = _post(
                    f"{{ rows(filter: {{ {field_name}: {{ {lookup} }} }}) "
                    "{ results { label } } }"
                )
                assert status == 200, payload
                assert (
                    sorted(row["label"] for row in payload["data"]["rows"]["results"])
                    == expected
                )

        for boolean_filter in ("or: []", "not: {}"):
            status, payload = _post(
                f"{{ rows(filter: {{ {boolean_filter} }}) {{ results {{ label }} }} }}"
            )
            assert status == 200, payload
            assert sorted(
                row["label"] for row in payload["data"]["rows"]["results"]
            ) == ["match", "null", "other"]

        for root_name in ("flatRows", "pagedRows"):
            status, payload = _post(
                f"{{ {root_name}(filter: {{ calendarDay: {{ year: 2024 }} }}) "
                "{ label } }",
                endpoint="front",
            )
            assert status == 200, payload
            assert payload["data"][root_name] == [{"label": "match"}]

        status, payload = _post(
            "{ parents { datedChildren(filter: { moment: { hour: 11 } }) { label } } }",
            endpoint="front",
        )
        assert status == 200, payload
        assert payload["data"]["parents"] == [{"datedChildren": [{"label": "match"}]}]
    finally:
        DatePartFilterRow.objects.all().delete()
        DatePartFilterParent.objects.all().delete()
        if created_here:
            with connection.schema_editor() as editor:
                editor.delete_model(DatePartFilterRow)
        if parent_created_here:
            with connection.schema_editor() as editor:
                editor.delete_model(DatePartFilterParent)


def test_lookup_type_boundaries_and_shared_inputs() -> None:
    """Only approved date-family parts change their generated scalar.

    Defaults, subclass handling, custom names, subscriptions and cache reuse remain bounded.
    """
    query_fields = _schema.graphql_schema.query_type.fields
    filter_type = query_fields["rows"].args["filter"].type
    date_fields = filter_type.fields["calendarDay"].type.fields
    datetime_fields = filter_type.fields["moment"].type.fields

    for lookup in ("year", "month", "day", "week_day"):
        assert date_fields[lookup].type is GraphQLInt
        assert datetime_fields[lookup].type is GraphQLInt
        assert date_fields[lookup].out_name == lookup
    for lookup in ("hour", "minute", "second"):
        assert datetime_fields[lookup].type is GraphQLInt
        assert lookup not in date_fields

    assert filter_type.fields["clock"].type.fields["hour"].type.name == "Time"
    assert filter_type.fields["label"].type.fields["year"].type is GraphQLString
    assert "hour" not in date_fields

    default_date = _lookups_input_type(
        DatePartFilterRow,
        DatePartFilterRow._meta.get_field("calendar_day"),
        "default_calendar_day",
        None,
        _registry,
    )
    default_datetime = _lookups_input_type(
        DatePartFilterRow,
        DatePartFilterRow._meta.get_field("moment"),
        "default_moment",
        None,
        _registry,
    )
    assert not set(date_parts := ("year", "month", "day", "week_day")) & set(
        default_date.fields
    )
    assert not set((*date_parts, "hour", "minute", "second")) & set(
        default_datetime.fields
    )
    assert default_date.fields["exact"].type.name == "Date"
    assert default_datetime.fields["exact"].type.name == "DateTime"

    class CustomDateField(models.DateField):
        """Exercise a Django DateField subclass without broadening lookup names."""

    class CustomDateTimeField(models.DateTimeField):
        """Exercise a Django DateTimeField subclass and its time parts."""

    for field, field_name, lookup in (
        (CustomDateField(), "custom_date", "week_day"),
        (CustomDateTimeField(), "custom_datetime", "second"),
    ):
        subtype = _lookups_input_type(
            DatePartFilterRow, field, field_name, ("exact", lookup), _registry
        )
        assert subtype.fields[lookup].type is GraphQLInt

    subscription_input = build_subscription_filter_input_type(
        DatePartFilterRow, ("calendar_day", "moment"), _registry
    )
    assert subscription_input is not None
    for name, scalar_name in (("calendarDay", "Date"), ("moment", "DateTime")):
        fields = subscription_input.fields[name].type.fields
        assert fields["exact"].type.name == scalar_name
        assert not set((*date_parts, "hour", "minute", "second")) & set(fields)

    front_fields = _front_schema.graphql_schema.query_type.fields
    assert (
        front_fields["flatRows"].args["filter"].type
        is front_fields["pagedRows"].args["filter"].type
    )
