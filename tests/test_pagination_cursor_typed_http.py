"""HTTP regressions for cursor ordering on typed nested lists."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.test import RequestFactory

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.paginations.pagination import CursorGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, ScalarKindsModel

RF = Registry()


class FloatNode(DjangoObjectType):
    """Expose the float scalar object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure FloatNode for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RF


class FloatList(DjangoListObjectType):
    """Expose the float cursor list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure FloatList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RF
        pagination = CursorGraphqlPagination(ordering="floating", page_size=2)


class FloatAuthor(DjangoObjectType):
    """Expose the float author object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_kinds = DjangoNestedListObjectField(FloatList, accessor="scalar_kinds")

    class Meta:
        """Configure FloatAuthor for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RF


class FloatAuthorList(DjangoListObjectType):
    """Expose the float author list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure FloatAuthorList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RF


class FloatQuery(ObjectType):
    """Expose the float root query in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_rows = DjangoListObjectField(FloatList)
    authors = DjangoListObjectField(FloatAuthorList)


FLOAT_SCHEMA = DjangoGraphQLSchema(query=FloatQuery, registries=isolated_pair(RF))

RD = Registry()


class DecimalNode(DjangoObjectType):
    """Expose the decimal scalar object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure DecimalNode for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RD


class DecimalList(DjangoListObjectType):
    """Expose the decimal cursor list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure DecimalList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RD
        pagination = CursorGraphqlPagination(ordering="decimal", page_size=2)


class DecimalAuthor(DjangoObjectType):
    """Expose the decimal author object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_kinds = DjangoNestedListObjectField(DecimalList, accessor="scalar_kinds")

    class Meta:
        """Configure DecimalAuthor for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RD


class DecimalAuthorList(DjangoListObjectType):
    """Expose the decimal author list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure DecimalAuthorList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RD


class DecimalQuery(ObjectType):
    """Expose the decimal root query in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_rows = DjangoListObjectField(DecimalList)
    authors = DjangoListObjectField(DecimalAuthorList)


DECIMAL_SCHEMA = DjangoGraphQLSchema(query=DecimalQuery, registries=isolated_pair(RD))

RU = Registry()


class UuidNode(DjangoObjectType):
    """Expose the uuid scalar object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure UuidNode for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RU


class UuidList(DjangoListObjectType):
    """Expose the uuid cursor list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure UuidList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = ScalarKindsModel
        registry = RU
        pagination = CursorGraphqlPagination(ordering="uuid_field", page_size=2)


class UuidAuthor(DjangoObjectType):
    """Expose the uuid author object in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_kinds = DjangoNestedListObjectField(UuidList, accessor="scalar_kinds")

    class Meta:
        """Configure UuidAuthor for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RU


class UuidAuthorList(DjangoListObjectType):
    """Expose the uuid author list in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    class Meta:
        """Configure UuidAuthorList for the isolated cursor test.

        Bind the model and registry used by this schema.
        """

        model = Author
        registry = RU


class UuidQuery(ObjectType):
    """Expose the uuid root query in the isolated test schema.

    Keep this registry separate from the other scalar cases.
    """

    scalar_rows = DjangoListObjectField(UuidList)
    authors = DjangoListObjectField(UuidAuthorList)


UUID_SCHEMA = DjangoGraphQLSchema(query=UuidQuery, registries=isolated_pair(RU))


class TestTypedCursorHttp:
    """Compare root ORM lists with materialized nested lists through HTTP.

    The three schemas differ only in their cursor ordering field.
    """

    def _post(
        self,
        schema: DjangoGraphQLSchema,
        query: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a JSON GraphQL request through the public view.

        Args:
            schema: Schema exposing one typed cursor list.
            query: GraphQL query text.
            variables: Optional cursor variables.

        Returns:
            The decoded response body.
        """
        view = GraphQLView.as_view(schema=schema)
        body = json.dumps({"query": query, "variables": variables or {}})
        response = view(
            RequestFactory().post(
                "/graphql/",
                body,
                content_type="application/json",
                HTTP_X_CSRF_TOKEN="test",
            )
        )
        assert response.status_code == 200
        return json.loads(response.content)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "field,values,schema",
        [
            ("floating", [1.1, 2.2, 3.3], FLOAT_SCHEMA),
            (
                "decimal",
                [Decimal("1.10"), Decimal("2.20"), Decimal("3.30")],
                DECIMAL_SCHEMA,
            ),
            ("uuid_field", [uuid.UUID(int=i) for i in (1, 2, 3)], UUID_SCHEMA),
        ],
    )
    def test_generated_root_cursor_and_nested_relation_http(
        self,
        field: str,
        values: list[float | Decimal | uuid.UUID],
        schema: DjangoGraphQLSchema,
    ) -> None:
        """Resume ORM and nested lists with the same server-emitted cursor.

        Args:
            field: Django model field used for ordering.
            values: Three ordered values assigned to the test rows.
            schema: Isolated public schema for that field.
        """
        author = Author.objects.create(name=f"cursor-parent-{field}")
        rows = [
            ScalarKindsModel.objects.create(
                char=f"cursor-{field}-{i}", author=author, **{field: value}
            )
            for i, value in enumerate(values)
        ]
        wire_field = {"uuid_field": "uuidField"}.get(field, field)
        first_query = f"""query {{ scalarRows {{ results(first: 2) {{ id {wire_field} }} pageInfo(first: 2) {{ endCursor hasNextPage hasPreviousPage }} }} authors {{ results {{ scalarKinds {{ results(first: 2) {{ id {wire_field} }} pageInfo(first: 2) {{ endCursor hasNextPage hasPreviousPage }} }} }} }} }}"""
        first = self._post(schema, first_query)
        assert "errors" not in first, first
        db_first = first["data"]["scalarRows"]
        nested_first = first["data"]["authors"]["results"][0]["scalarKinds"]
        assert db_first["pageInfo"] == nested_first["pageInfo"]
        assert db_first["pageInfo"]["hasNextPage"] is True
        token = db_first["pageInfo"]["endCursor"]
        assert token == nested_first["pageInfo"]["endCursor"]
        assert [int(x["id"]) for x in db_first["results"]] == [rows[0].pk, rows[1].pk]
        assert [int(x["id"]) for x in nested_first["results"]] == [
            rows[0].pk,
            rows[1].pk,
        ]

        next_query = f"""query($cursor: String!) {{ scalarRows {{ results(first: 2, cursor: $cursor) {{ id {wire_field} }} pageInfo(first: 2, cursor: $cursor) {{ endCursor hasNextPage hasPreviousPage }} }} authors {{ results {{ scalarKinds {{ results(first: 2, cursor: $cursor) {{ id {wire_field} }} pageInfo(first: 2, cursor: $cursor) {{ endCursor hasNextPage hasPreviousPage }} }} }} }} }}"""
        next_result = self._post(schema, next_query, {"cursor": token})
        assert [int(x["id"]) for x in next_result["data"]["scalarRows"]["results"]] == [
            rows[2].pk
        ]
        assert next_result["data"]["scalarRows"]["pageInfo"]["hasPreviousPage"] is True
        assert next_result["data"]["scalarRows"]["pageInfo"]["hasNextPage"] is False
        assert "errors" not in next_result, next_result
        nested_second = next_result["data"]["authors"]["results"][0]["scalarKinds"]
        assert nested_second == next_result["data"]["scalarRows"]
        assert [int(item["id"]) for item in nested_second["results"]] == [rows[2].pk]
        assert nested_second["pageInfo"]["hasPreviousPage"] is True
        assert nested_second["pageInfo"]["hasNextPage"] is False

    @pytest.mark.django_db
    def test_malformed_cursor_is_existing_graphql_error_envelope(self) -> None:
        """Keep the established non-base64 cursor error envelope.

        This check guards a separate, already-supported invalid input.
        """
        query = """query($cursor: String!) { scalarRows { results(first: 2, cursor: $cursor) { id floating } pageInfo(first: 2, cursor: $cursor) { endCursor hasNextPage } } }"""
        result = self._post(FLOAT_SCHEMA, query, {"cursor": "not-base64"})
        assert "errors" in result
        assert any(
            "Invalid cursor" in error["message"] for error in result["errors"]
        ), result

    @pytest.mark.django_db
    def test_typed_invalid_cursor_value_current_http_error(self) -> None:
        """Retain the existing encoded invalid-boundary error behavior.

        Typed invalid input policy is outside this compatible fix.
        """
        author = Author.objects.create(name="cursor-parent-invalid")
        ScalarKindsModel.objects.create(
            char="invalid-boundary", author=author, floating=1.1
        )
        token = CursorGraphqlPagination.encode_cursor("not-a-float", 1)
        query = """query($cursor: String!) { authors { results { scalarKinds { results(first: 2, cursor: $cursor) { id floating } pageInfo(first: 2, cursor: $cursor) { endCursor hasNextPage } } } } }"""
        result = self._post(FLOAT_SCHEMA, query, {"cursor": token})
        assert "errors" in result, result
        messages = [error["message"] for error in result["errors"]]
        assert len(messages) == 2, result
        assert all(
            "not supported between instances of 'float' and 'str'" in message
            for message in messages
        ), result

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "field,values",
        [
            ("floating", [1.1, 2.2, 2.2, 3.3]),
            (
                "decimal",
                [Decimal("1.10"), Decimal("2.20"), Decimal("2.20"), Decimal("3.30")],
            ),
            ("uuid_field", [uuid.UUID(int=i) for i in (1, 2, 2, 3)]),
        ],
    )
    @pytest.mark.parametrize("descending", [False, True])
    def test_tied_boundaries_match_orm_in_both_orderings(
        self,
        field: str,
        values: list[float | Decimal | uuid.UUID],
        descending: bool,
    ) -> None:
        """Preserve tied rows in either ordering direction.

        Args:
            field: Django model field used for ordering.
            values: Four values including a tie across the page boundary.
            descending: Whether to reverse the configured ordering.
        """
        rows = [
            ScalarKindsModel.objects.create(char=f"tie-{index}", **{field: value})
            for index, value in enumerate(values)
        ]
        paginator = CursorGraphqlPagination(
            ordering=f"{'-' if descending else ''}{field}", page_size=2
        )
        queryset = ScalarKindsModel.objects.all()
        first_db = list(paginator.paginate_queryset(queryset, first=2))
        first_memory = list(paginator.paginate_queryset(rows, first=2))
        assert [row.pk for row in first_db] == [row.pk for row in first_memory]
        db_info = paginator.get_page_info(queryset, first=2)
        assert db_info == paginator.get_page_info(rows, first=2)
        cursor = db_info["end_cursor"]
        next_db = list(paginator.paginate_queryset(queryset, first=2, cursor=cursor))
        next_memory = list(paginator.paginate_queryset(rows, first=2, cursor=cursor))
        assert [row.pk for row in next_db] == [row.pk for row in next_memory]
        assert len({row.pk for row in first_db + next_db}) == 4
        assert paginator.get_page_info(queryset, first=2, cursor=cursor) == (
            paginator.get_page_info(rows, first=2, cursor=cursor)
        )
