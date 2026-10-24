"""Public string Literal input enum contract."""

from __future__ import annotations

from typing import Literal

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import Field

from django_graphex.core import InputType, Mutation, ObjectType, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.schema import DjangoGraphQLSchema


def test_public_mutation_uses_literal_enum_and_raw_resolver_value() -> None:
    """Expose an enum on the wire while returning the original Python string.

    Scenario: public mutation uses literal enum and raw resolver value.
    """
    seen: list[dict[str, object]] = []

    class ArticleInput(InputType):
        status: Literal["draft", "published"]

    input_type = compile_input_type(ArticleInput, name="ArticleInput")

    class Submit(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Return the coerced status and record the resolver input.

            Args:
                _root: Unused mutation root.
                _info: Unused execution context.
                payload: Coerced input dictionary.

            Returns:
                A result containing the original string value.
            """
            seen.append(payload)
            return {"result": str(payload["status"])}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class MutationRoot(ObjectType):
        submit = Submit.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=MutationRoot).graphql_schema
    sdl = print_schema(schema)
    assert "status: ArticleInputStatusEnum!" in sdl
    assert "enum ArticleInputStatusEnum" in sdl
    assert "DRAFT" in sdl and "PUBLISHED" in sdl

    result = graphql_sync(
        schema, "mutation { submit(payload: {status: DRAFT}) { result } }"
    )
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "draft"}}
    assert seen == [{"status": "draft"}]

    enum = schema.type_map["ArticleInputStatusEnum"]
    assert isinstance(enum, GraphQLEnumType)
    assert {name: item.value for name, item in enum.values.items()} == {
        "DRAFT": "draft",
        "PUBLISHED": "published",
    }

    variable_query = (
        "mutation($payload: ArticleInput!) { submit(payload: $payload) { result } }"
    )
    variable = graphql_sync(
        schema, variable_query, variable_values={"payload": {"status": "PUBLISHED"}}
    )
    assert variable.errors is None, variable.errors
    assert variable.data == {"submit": {"result": "published"}}
    assert seen[-1] == {"status": "published"}

    for query in (
        'mutation { submit(payload: {status: "draft"}) { result } }',
        "mutation { submit(payload: {status: UNKNOWN}) { result } }",
    ):
        invalid = graphql_sync(schema, query)
        assert invalid.errors
        assert len(seen) == 2
    for value in ("draft", "UNKNOWN"):
        invalid = graphql_sync(
            schema, variable_query, variable_values={"payload": {"status": value}}
        )
        assert invalid.errors
        assert len(seen) == 2


def test_wrapped_literal_alias_and_nested_input_keep_enum_values() -> None:
    """Preserve wrapper nullability and resolver-facing names inside nested input.

    Scenario: wrapped literal alias and nested input keep enum values.
    """

    class InnerInput(InputType):
        publish_state: Literal["draft", "published"] | None = Field(
            default=None, alias="publishState"
        )

    class OuterInput(InputType):
        item: InnerInput
        states: list[Literal["draft", "published"] | None]

    outer = compile_input_type(OuterInput, name="OuterInput")
    item = outer.fields["item"].type
    assert isinstance(item, GraphQLNonNull)
    inner = item.of_type
    nested_enum = inner.fields["publishState"].type
    assert isinstance(nested_enum, GraphQLEnumType)
    assert nested_enum.name == "InnerInputPublishStateEnum"
    states = outer.fields["states"].type
    assert isinstance(states, GraphQLNonNull)
    assert isinstance(states.of_type, GraphQLList)
    assert states.of_type.of_type.name == "OuterInputStatesEnum"
    assert outer.fields["item"].type.of_type is inner
    assert (
        compile_input_type(OuterInput, name="OuterInput").fields["item"].type.of_type
        is inner
    )

    seen: list[dict[str, object]] = []

    class SubmitWrapped(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(outer))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Capture nested raw values without automatic model validation.

            Args:
                _root: Unused mutation root.
                _info: Unused execution context.
                payload: Coerced nested input dictionary.

            Returns:
                A result describing the first list member.
            """
            seen.append(payload)
            return {"result": str(payload["states"][0])}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class MutationRoot(ObjectType):
        submit = SubmitWrapped.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=MutationRoot).graphql_schema
    result = graphql_sync(
        schema,
        "mutation { submit(payload: {item: {publishState: PUBLISHED}, "
        "states: [DRAFT, null]}) { result } }",
    )
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "draft"}}
    assert seen == [{"item": {"publish_state": "published"}, "states": ["draft", None]}]


def test_literal_defaults_and_factory_are_not_frozen_at_compile_time() -> None:
    """Render a fixed enum default but evaluate a factory for each input.

    Scenario: literal defaults and factory are not frozen at compile time.
    """
    calls: list[str] = []

    def next_status() -> str:
        """Alternate the raw enum default for consecutive input objects."""
        calls.append("factory")
        return "draft" if len(calls) % 2 else "published"

    class DefaultInput(InputType):
        fixed: Literal["draft", "published"] = "draft"
        generated: Literal["draft", "published"] = Field(default_factory=next_status)

    compiled = compile_input_type(DefaultInput, name="DefaultInput")
    assert calls == []

    class SubmitDefault(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(compiled))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Return the two raw enum default values.

            Args:
                _root: Unused mutation root.
                _info: Unused execution context.
                payload: Coerced input dictionary.

            Returns:
                A joined pair of raw values.
            """
            return {"result": f"{payload['fixed']}:{payload['generated']}"}

    class Query(ObjectType):
        ping = field(GraphQLString)

    class MutationRoot(ObjectType):
        submit = SubmitDefault.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=MutationRoot).graphql_schema
    sdl = print_schema(schema)
    assert "fixed: DefaultInputFixedEnum = DRAFT" in sdl
    assert "generated: DefaultInputGeneratedEnum" in sdl
    assert "generated: DefaultInputGeneratedEnum =" not in sdl
    assert calls == []
    first = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    second = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    assert first.errors is None and second.errors is None
    assert first.data == {"submit": {"result": "draft:draft"}}
    assert second.data == {"submit": {"result": "draft:published"}}
    assert calls == ["factory", "factory"]


def test_compiled_name_and_inherited_public_alias_define_enum_name() -> None:
    """Name the enum from the compiled type and inherited wire alias.

    Scenario: compiled name and inherited public alias define enum name.
    """

    class BaseInput(InputType):
        publication_state: Literal["draft", "published"] = Field(alias="publishState")

    class InheritedArticleInput(BaseInput):
        title: str

    compiled = compile_input_type(InheritedArticleInput, name="CustomArticleInput")
    enum = compiled.fields["publishState"].type
    assert isinstance(enum, GraphQLNonNull)
    assert enum.of_type.name == "CustomArticleInputPublishStateEnum"
    assert compiled.fields["publishState"].out_name == "publication_state"
    assert compiled.fields["publishState"].type.of_type is enum.of_type


def test_member_collision_rejects_ambiguous_literals() -> None:
    """Reject values that normalize to the same enum member name.

    Scenario: member collision rejects ambiguous literals.
    """

    class AmbiguousInput(InputType):
        status: Literal["draft-one", "draft one"]

    compiled = compile_input_type(AmbiguousInput, name="AmbiguousInput")
    with pytest.raises(TypeError, match="DRAFT_ONE") as error:
        _ = compiled.fields
    assert isinstance(error.value.__cause__, ImproperlyConfigured)


def test_reserved_double_underscore_literal_is_rejected_at_build() -> None:
    """Reject a Literal value whose enum member would be a reserved name.

    Scenario: a "__x" member becomes "__X", which GraphQL reserves.
    """

    class ReservedInput(InputType):
        status: Literal["ok", "__x"]

    compiled = compile_input_type(ReservedInput, name="ReservedInput")
    with pytest.raises(TypeError, match="status.*ReservedInput.*'__x'") as error:
        _ = compiled.fields
    assert isinstance(error.value.__cause__, ImproperlyConfigured)
