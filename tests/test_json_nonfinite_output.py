"""Raw JSON output rejects non-finite numbers so responses stay valid JSON."""

from __future__ import annotations

import collections
import inspect
import json
import types
from collections.abc import AsyncIterator
from typing import Any

import pytest
from django.test import RequestFactory
from graphql import GraphQLError, GraphQLString, graphql_sync, parse, subscribe

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxJSON
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_NAN = float("nan")
_INF = float("inf")


def _resolve_value(root: Any, info: Any) -> Any:
    """Return the value the test placed on the root.

    Args:
        root: Root value carrying the "value" key.
        info: Unused GraphQL resolver context.

    Returns:
        The configured value.
    """
    return root["value"]


class _Query(ObjectType):
    """Expose the configured value through the raw JSON scalar.



    Verifies the behavior named in the summary line.

    """

    value = field(GdxJSON, resolver=_resolve_value)
    plain = field(GraphQLString)


_SCHEMA = DjangoGraphQLSchema(query=_Query)


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF])
@pytest.mark.parametrize(
    "wrap",
    [
        lambda v: v,
        lambda v: {"a": v},
        lambda v: [1, v],
        lambda v: {"a": [{"b": v}]},
    ],
    ids=["top-level", "dict", "list", "deeply-nested"],
)
def test_nonfinite_output_is_a_field_error(bad: float, wrap: Any) -> None:
    """A non-finite float anywhere in the value becomes a field error.

    Args:
        bad: The non-finite float.
        wrap: Builds the value shape that contains it.
    """
    result = graphql_sync(
        _SCHEMA.graphql_schema, "{ value }", root_value={"value": wrap(bad)}
    )
    assert result.data == {"value": None}
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert result.errors[0].path == ["value"]


@pytest.mark.parametrize(
    "good",
    [
        1.5,
        0,
        "NaN",
        None,
        True,
        {"a": [1, 2.5, {"b": "x"}], "c": None},
        [[], {}],
    ],
)
def test_finite_values_are_unchanged(good: Any) -> None:
    """Finite and non-numeric values pass through untouched.

    Args:
        good: A JSON-representable value.
    """
    result = graphql_sync(
        _SCHEMA.graphql_schema, "{ value }", root_value={"value": good}
    )
    assert result.errors is None
    assert result.data == {"value": good}


def test_self_referencing_value_does_not_loop() -> None:
    """A cyclic container is traversed once instead of recursing forever.

    Verifies that serialization terminates without an error.
    """
    cyclic: list[Any] = [1]
    cyclic.append(cyclic)
    result = graphql_sync(
        _SCHEMA.graphql_schema, "{ value }", root_value={"value": cyclic}
    )
    assert result.errors is None


def test_http_response_stays_strict_json() -> None:
    """The HTTP body of a non-finite output parses with a strict JSON parser.

    Verifies that no NaN or Infinity constant reaches the wire.
    """

    class _Strict(GraphQLView):
        """Serve a root value carrying a non-finite number.



        Verifies the behavior named in the summary line.

        """

        def get_root_value(self, request: Any) -> Any:
            """Return the offending root value.

            Args:
                request: Unused HTTP request.

            Returns:
                A root mapping holding a nested NaN.
            """
            return {"value": {"a": [_NAN]}}

    request = RequestFactory().post(
        "/graphql/", {"query": "{ value }"}, content_type="application/json"
    )
    response = _Strict.as_view(schema=_SCHEMA)(request)

    body = json.loads(
        response.content,
        parse_constant=lambda constant: pytest.fail(f"non-standard {constant}"),
    )
    assert body["data"] == {"value": None}
    assert "non-finite" in body["errors"][0]["message"]


async def test_subscription_payload_is_rejected_too() -> None:
    """Subscription events share the scalar, so transports never see NaN.

    Verifies that a non-finite event payload becomes a field error.
    """
    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
    )

    async def source(root: Any, info: Any) -> AsyncIterator[Any]:
        """Yield one event carrying a non-finite number.

        Args:
            root: Unused root value.
            info: Unused GraphQL resolve information.

        Yields:
            An event payload.
        """
        yield {"a": _INF}

    schema = GraphQLSchema(
        query=GraphQLObjectType("Q", {"x": GraphQLField(GraphQLString)}),
        subscription=GraphQLObjectType(
            "S",
            {
                "ev": GraphQLField(
                    GdxJSON, resolve=lambda event, info: event, subscribe=source
                )
            },
        ),
    )
    stream: Any = subscribe(schema, parse("subscription { ev }"))
    if inspect.isawaitable(stream):
        stream = await stream
    result = await stream.__anext__()
    assert result.errors is not None
    assert isinstance(result.errors[0], GraphQLError)
    assert "non-finite" in result.errors[0].message


@pytest.mark.parametrize(
    "wrap",
    [
        lambda v: (1, v),
        lambda v: collections.OrderedDict(a=v),
        lambda v: {"a": (v,)},
        lambda v: {"a": {v}},
        lambda v: collections.namedtuple("Pair", "x y")(1, v),
        lambda v: types.MappingProxyType({"a": v}),
    ],
    ids=["tuple", "ordered-dict", "tuple-in-dict", "set", "namedtuple", "mapping"],
)
def test_nonfinite_inside_other_containers_is_a_field_error(wrap: Any) -> None:
    """A non-finite float in a tuple, OrderedDict, set or other mapping is rejected.

    Args:
        wrap: Builds a non-list, non-dict container holding the float.
    """
    result = graphql_sync(
        _SCHEMA.graphql_schema, "{ value }", root_value={"value": wrap(_NAN)}
    )
    assert result.data == {"value": None}
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message


def test_strings_and_bytes_are_not_traversed() -> None:
    """A string is a sequence of strings; it must not be walked character by character.



    Verifies the behavior named in the summary line.

    """
    result = graphql_sync(
        _SCHEMA.graphql_schema, "{ value }", root_value={"value": ("nan", b"inf")}
    )
    assert result.errors is None
