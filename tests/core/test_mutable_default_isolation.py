"""Mutable literal defaults must be fresh for every execution."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import Field, InputType, ObjectType
from django_graphex.core._args import native_arg
from django_graphex.core.fresh_defaults import is_mutable_default
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema


class Inner(InputType):
    """Nested input carrying its own mutable default.

    The default must be isolated at every nesting depth.
    """

    tags: list[str] = []


class Params(InputType):
    """Input with list, dict and nested mutable defaults.

    Each field exercises a different default path of the compiler.
    """

    tags: list[str] = []
    flags: dict[str, bool] = {"a": True}
    counts: dict[str, int] = {"a": 1}
    inner: Inner | None = None
    inners: list[Inner] | None = None


def _run_three(schema: GraphQLSchema, query: str, variables: Any = None) -> None:
    """Execute the query three times and assert it succeeds each time.

    Args:
        schema: Schema under test.
        query: Operation text.
        variables: Optional variable values.
    """
    for _ in range(3):
        result = graphql_sync(schema, query, variable_values=variables)
        assert result.errors is None, result.errors


def test_input_field_defaults_are_fresh_per_request() -> None:
    """A resolver that mutates its input never leaks into the next request.

    Three executions must each see the pristine declared defaults.
    """
    seen: list[tuple[Any, ...]] = []

    def resolve(root: Any, info: Any, i: dict[str, Any]) -> str:
        """Record the incoming defaults, then mutate them.

        Args:
            root: Unused root value.
            info: Unused resolve info.
            i: The coerced input object.

        Returns:
            A constant.
        """
        seen.append((list(i["tags"]), dict(i["flags"]), dict(i["counts"])))
        i["tags"].append("x")
        i["flags"]["b"] = False
        i["counts"]["z"] = 9
        return "ok"

    query = GraphQLObjectType(
        "Q",
        {
            "x": GraphQLField(
                GraphQLString,
                args={"i": GraphQLArgument(compile_input_type(Params, name="Params"))},
                resolve=resolve,
            )
        },
    )
    _run_three(GraphQLSchema(query=query), "query($v:Params){x(i:$v)}", {"v": {}})
    assert seen == [([], {"a": True}, {"a": 1})] * 3


def test_nested_and_listed_input_defaults_are_fresh() -> None:
    """Defaults inside nested input objects and lists of inputs are fresh too.

    The nested resolver mutations must not reach later requests.
    """
    seen: list[Any] = []

    def resolve(root: Any, info: Any, i: dict[str, Any]) -> str:
        """Record nested defaults, then mutate each of them.

        Args:
            root: Unused root value.
            info: Unused resolve info.
            i: The coerced input object.

        Returns:
            A constant.
        """
        seen.append((list(i["inner"]["tags"]), [list(n["tags"]) for n in i["inners"]]))
        i["inner"]["tags"].append("x")
        for item in i["inners"]:
            item["tags"].append("y")
        return "ok"

    query = GraphQLObjectType(
        "Q",
        {
            "x": GraphQLField(
                GraphQLString,
                args={"i": GraphQLArgument(compile_input_type(Params, name="Params"))},
                resolve=resolve,
            )
        },
    )
    variables = {"v": {"inner": {}, "inners": [{}, {}]}}
    _run_three(GraphQLSchema(query=query), "query($v:Params){x(i:$v)}", variables)
    assert seen == [([], [[], []])] * 3


def test_argument_defaults_are_fresh_per_request() -> None:
    """A list default declared on a field argument is not shared.

    The resolver appends to it on every call.
    """
    seen: list[list[str]] = []

    def resolve(root: Any, info: Any, tags: list[str]) -> str:
        """Record the incoming default, then mutate it.

        Args:
            root: Unused root value.
            info: Unused resolve info.
            tags: The argument value.

        Returns:
            A constant.
        """
        seen.append(list(tags))
        tags.append("x")
        return "ok"

    class Query(ObjectType):
        """Declare a field whose argument has a mutable default."""

        out = Field(
            GraphQLString,
            args={"tags": Field(GraphQLList(GraphQLString), default=["a"])},
            resolver=resolve,
        )

    schema = DjangoGraphQLSchema(query=Query).graphql_schema
    _run_three(schema, "{ out }")
    assert seen == [["a"]] * 3


def test_default_is_still_rendered_in_sdl() -> None:
    """Copying at execution time does not change the printed default.

    The SDL keeps rendering the declared literal.
    """
    from graphql import print_type

    sdl = print_type(compile_input_type(Params, name="Params"))
    assert "tags: [String!]! = []" in sdl or "tags: [String!] = []" in sdl


@pytest.mark.parametrize(
    "value", [None, 1, 1.5, "s", True, b"b", (), (1, "a"), frozenset({1})]
)
def test_immutable_defaults_are_not_copied(value: Any) -> None:
    """Immutable values are left alone so they cost nothing per request.

    Args:
        value: An immutable default.
    """
    assert is_mutable_default(value) is False


@pytest.mark.parametrize("value", [[], {}, {1}, ([],), bytearray(b"x")])
def test_mutable_defaults_are_detected(value: Any) -> None:
    """Containers, and tuples holding them, are copied.

    Args:
        value: A mutable default.
    """
    assert is_mutable_default(value) is True


def test_pruned_schema_keeps_defaults_fresh() -> None:
    """A permission-pruned clone still isolates input and argument defaults.

    The clone rebuilds both the input type callback and the argument.
    """
    seen: list[Any] = []

    def resolve(root: Any, info: Any, i: dict[str, Any], tags: list[str]) -> str:
        """Record both defaults, then mutate them.

        Args:
            root: Unused root value.
            info: Unused resolve info.
            i: The coerced input object.
            tags: The argument value.

        Returns:
            A constant.
        """
        seen.append((list(i["tags"]), list(tags)))
        i["tags"].append("x")
        tags.append("y")
        return "ok"

    query = GraphQLObjectType(
        "Q",
        {
            "x": GraphQLField(
                GraphQLString,
                args={
                    "i": GraphQLArgument(compile_input_type(Params, name="Params")),
                    "tags": native_arg(
                        GraphQLArgument(
                            GraphQLList(GraphQLString), default_value=["a"]
                        ),
                        "tags",
                    ),
                },
                resolve=resolve,
            )
        },
    )
    pruned = prune_schema(GraphQLSchema(query=query), frozenset())
    _run_three(pruned, "query($v:Params){x(i:$v)}", {"v": {}})
    assert seen == [([], ["a"])] * 3
