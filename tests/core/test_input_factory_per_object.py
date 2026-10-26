"""GraphQL-coerced hand-authored input factories run per input object."""

from __future__ import annotations

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    print_schema,
)
from pydantic import BaseModel, Field

from django_graphex.core import InputType, Mutation, field
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.schema_pruner import prune_schema


def test_omitted_factory_values_are_fresh_across_graphql_executions() -> None:
    """Do not evaluate factories while building SDL or share raw input defaults.

    Separate literals receive fresh values; aliases of one variable reuse the
    same coerced input object rather than making another factory call.
    """
    calls: list[str] = []
    received_lists: list[list[str]] = []

    def next_uid() -> str:
        """Return a distinct identifier for each coerced input object."""
        value = f"uid-{len([call for call in calls if call == 'uid']) + 1}"
        calls.append("uid")
        return value

    def make_tags() -> list[str]:
        """Return a new mutable list for each coerced input object."""
        calls.append("tags")
        return ["seed"]

    class FreshFactoryInput(InputType):
        uid: str = Field(default_factory=next_uid)
        tags: list[str] = Field(default_factory=make_tags)

    input_type = compile_input_type(FreshFactoryInput, name="FreshFactoryInput")

    class SubmitFactory(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Record and mutate the raw resolver dictionary without validation.

            Args:
                _root: Unused GraphQL root.
                _info: Unused GraphQL execution information.
                payload: GraphQL-coerced input dictionary.

            Returns:
                A mutation payload with the observed identifier and tags.
            """
            tags = payload["tags"]
            assert isinstance(tags, list)
            received_lists.append(tags)
            tags.append("changed")
            return {"result": f"{payload['uid']}:{','.join(tags)}"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("FactoryQuery", {"ping": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType(
            "FactoryMutation", {"submit": SubmitFactory.Field()}
        ),
    )
    sdl = print_schema(schema)
    assert calls == []
    assert "uid: String" in sdl and "uid: String =" not in sdl
    assert "tags: [String!]" in sdl and "tags: [String!] =" not in sdl
    introspection = graphql_sync(
        schema,
        '{ __type(name: "FreshFactoryInput") { inputFields { name defaultValue } } }',
    )
    assert introspection.errors is None, introspection.errors
    assert introspection.data is not None
    assert {
        field["name"]: field["defaultValue"]
        for field in introspection.data["__type"]["inputFields"]
    } == {
        "uid": None,
        "tags": None,
    }
    assert calls == []

    query = "mutation { submit(payload: {}) { result } }"
    first = graphql_sync(schema, query)
    second = graphql_sync(schema, query)
    assert first.errors is None, first.errors
    assert second.errors is None, second.errors
    assert first.data == {"submit": {"result": "uid-1:seed,changed"}}
    assert second.data == {"submit": {"result": "uid-2:seed,changed"}}
    assert calls == ["uid", "tags", "uid", "tags"]
    assert received_lists[0] is not received_lists[1]

    shared = graphql_sync(
        schema,
        "mutation($payload: FreshFactoryInput!) { "
        "first: submit(payload: $payload) { result } "
        "second: submit(payload: $payload) { result } }",
        variable_values={"payload": {}},
    )
    assert shared.errors is None, shared.errors
    assert shared.data == {
        "first": {"result": "uid-3:seed,changed"},
        "second": {"result": "uid-3:seed,changed,changed"},
    }
    assert calls == ["uid", "tags"] * 3
    assert received_lists[2] is received_lists[3]

    inline = graphql_sync(
        schema,
        "mutation { first: submit(payload: {}) { result } "
        "second: submit(payload: {}) { result } }",
    )
    assert inline.errors is None, inline.errors
    assert inline.data == {
        "first": {"result": "uid-4:seed,changed"},
        "second": {"result": "uid-5:seed,changed"},
    }
    assert calls == ["uid", "tags"] * 5
    assert received_lists[4] is not received_lists[5]


def test_factory_respects_variables_explicit_values_and_field_aliases() -> None:
    """Use resolver out-names and skip factories for supplied values or null.

    The wire alias must not appear as an extra key in the resolver mapping.
    """
    calls: list[str] = []
    observed: list[dict[str, object]] = []

    def make_name() -> str:
        """Create a visible fresh default for an aliased field."""
        calls.append("factory")
        return f"generated-{len(calls)}"

    class AliasedFactoryInput(InputType):
        display_name: str | None = Field(default_factory=make_name, alias="displayName")

    input_type = compile_input_type(AliasedFactoryInput, name="AliasedFactoryInput")

    class SubmitAlias(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Expose the input mapping's real key rather than its wire alias.

            Args:
                _root: Unused GraphQL root.
                _info: Unused execution information.
                payload: Coerced input mapping.

            Returns:
                A payload naming the observed resolver key and value.
            """
            observed.append(payload)
            assert "displayName" not in payload
            return {"result": f"{list(payload)}:{payload['display_name']}"}

    schema = GraphQLSchema(
        query=GraphQLObjectType("AliasQuery", {"ping": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("AliasMutation", {"submit": SubmitAlias.Field()}),
    )
    assert calls == []
    operation = "mutation($payload: AliasedFactoryInput!) { submit(payload: $payload) { result } }"
    for variables, expected in (
        ({"payload": {}}, "generated-1"),
        ({"payload": {"displayName": "given"}}, "given"),
        ({"payload": {"displayName": None}}, "None"),
        ({"payload": {}}, "generated-2"),
    ):
        result = graphql_sync(schema, operation, variable_values=variables)
        assert result.errors is None, result.errors
        assert result.data == {"submit": {"result": f"['display_name']:{expected}"}}
    assert calls == ["factory", "factory"]
    assert all(list(value) == ["display_name"] for value in observed)


def test_nested_inputs_and_inline_aliases_create_distinct_objects() -> None:
    """Run nested factories for each new object, not once per operation.

    Distinct inline mutation aliases and list items all need separate values.
    """
    calls: list[int] = []

    def next_number() -> int:
        """Count individual nested object coercions."""
        calls.append(len(calls) + 1)
        return calls[-1]

    class NestedFactoryItem(InputType):
        number: int = Field(default_factory=next_number)

    class NestedFactoryBatch(InputType):
        items: list[NestedFactoryItem]

    input_type = compile_input_type(NestedFactoryBatch, name="NestedFactoryBatch")

    class SubmitBatch(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Report the nested input numbers without changing the mapping.

            Args:
                _root: Unused GraphQL root.
                _info: Unused execution information.
                payload: Coerced batch of nested objects.

            Returns:
                The nested default numbers in encounter order.
            """
            items = payload["items"]
            assert isinstance(items, list)
            return {"result": ",".join(str(item["number"]) for item in items)}

    schema = GraphQLSchema(
        query=GraphQLObjectType("BatchQuery", {"ping": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType("BatchMutation", {"submit": SubmitBatch.Field()}),
    )
    result = graphql_sync(
        schema,
        "mutation { one: submit(payload: {items: [{}, {}]}) { result } "
        "two: submit(payload: {items: [{}]}) { result } }",
    )
    assert result.errors is None, result.errors
    assert result.data == {"one": {"result": "1,2"}, "two": {"result": "3"}}
    assert calls == [1, 2, 3]


def test_factory_failures_are_graphql_input_errors_without_private_text() -> None:
    """Report factory failures safely for literal and variable coercion.

    Raises:
        ValueError: The nested test factory raises; GraphQL must capture and
            redact it instead of propagating the original exception text.
    """

    def fail_default() -> str:
        """Raise a sentinel secret that must not reach a GraphQL response."""
        raise ValueError("private-token-123")

    class FailingFactoryInput(InputType):
        value: str = Field(default_factory=fail_default)

    input_type = compile_input_type(FailingFactoryInput, name="FailingFactoryInput")

    class SubmitFailure(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Return a value only when input coercion succeeds.

            Args:
                _root: Unused GraphQL root.
                _info: Unused execution information.
                payload: Successfully coerced input.

            Returns:
                The explicit or defaulted value.
            """
            return {"result": str(payload["value"])}

    schema = GraphQLSchema(
        query=GraphQLObjectType("FailureQuery", {"ping": GraphQLField(GraphQLString)}),
        mutation=GraphQLObjectType(
            "FailureMutation", {"submit": SubmitFailure.Field()}
        ),
    )
    for operation, variables in (
        ("mutation { submit(payload: {}) { result } }", None),
        (
            "mutation($payload: FailingFactoryInput!) { submit(payload: $payload) { result } }",
            {"payload": {}},
        ),
    ):
        result = graphql_sync(schema, operation, variable_values=variables)
        assert result.errors
        assert "Could not resolve default for input field 'value'" in str(
            result.errors[0]
        )
        assert "private-token-123" not in str(result.errors[0])
        assert result.data is None or result.data["submit"] is None
    explicit = graphql_sync(
        schema, 'mutation { submit(payload: {value: "ok"}) { result } }'
    )
    assert explicit.errors is None, explicit.errors
    assert explicit.data == {"submit": {"result": "ok"}}


def test_permission_pruned_input_does_not_reinsert_hidden_factory_field() -> None:
    """Retain a public factory while removing a restricted factory in a clone.

    A cloned input type must not reinsert a field removed by schema pruning.
    """
    public_calls: list[int] = []
    hidden_calls: list[int] = []

    def public_default() -> str:
        """Supply a public default."""
        public_calls.append(1)
        return "public"

    def hidden_default() -> str:
        """Supply a restricted default only when the field survives."""
        hidden_calls.append(1)
        return "hidden"

    class PrunedFactoryInput(InputType):
        public: str = Field(default_factory=public_default)
        hidden: str = Field(default_factory=hidden_default)

    input_type = compile_input_type(PrunedFactoryInput, name="PrunedFactoryInput")
    input_type.fields["hidden"].extensions = {
        "gdx_required_perms": frozenset({"sample.see_hidden"})
    }
    seen: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the fields delivered by a permission-pruned schema.

        Args:
            _root: Unused GraphQL root.
            _info: Unused execution information.
            payload: Coerced input dictionary.

        Returns:
            A harmless response value.
        """
        seen.append(payload)
        return "ok"

    full = GraphQLSchema(
        query=GraphQLObjectType(
            "PrunedQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    pruned = prune_schema(full, frozenset())
    result = graphql_sync(pruned, "{ probe(payload: {}) }")
    assert result.errors is None, result.errors
    assert seen == [{"public": "public"}]
    assert public_calls == [1]
    assert hidden_calls == []


def test_validated_data_factory_remains_a_model_validation_default() -> None:
    """Leave validated-data factories absent from raw GraphQL dictionaries.

    Pydantic alone evaluates these factories after it receives validated data.
    """
    raw_inputs: list[dict[str, object]] = []

    class ValidatedDataFactoryInput(InputType):
        count: int = 2
        next_count: int = Field(default_factory=lambda data: data["count"] + 1)

    input_type = compile_input_type(
        ValidatedDataFactoryInput, name="ValidatedDataFactoryInput"
    )

    class SubmitValidated(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Validate only after observing the raw coerced mapping.

            Args:
                _root: Unused GraphQL root.
                _info: Unused execution information.
                payload: Raw GraphQL-coerced dictionary.

            Returns:
                The model-derived validated-data default.
            """
            raw_inputs.append(dict(payload))
            validated = ValidatedDataFactoryInput.model_validate(payload)
            return {"result": str(validated.next_count)}

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "ValidatedQuery", {"ping": GraphQLField(GraphQLString)}
        ),
        mutation=GraphQLObjectType(
            "ValidatedMutation", {"submit": SubmitValidated.Field()}
        ),
    )
    assert "nextCount: Int =" not in print_schema(schema)
    result = graphql_sync(schema, "mutation { submit(payload: {}) { result } }")
    assert result.errors is None, result.errors
    assert result.data == {"submit": {"result": "3"}}
    assert raw_inputs == [{"count": 2}]


def test_model_derived_input_keeps_omitted_factory_field_absent() -> None:
    """Do not inject model-derived defaults into partial mutation inputs.

    Model-derived omission remains distinct from an explicit null assignment.
    """
    calls: list[int] = []

    def make_tags() -> list[str]:
        """Count factory calls if a model is explicitly validated."""
        calls.append(1)
        return ["model"]

    class DerivedInput(BaseModel):
        tags: list[str] = Field(default_factory=make_tags)

    input_type = compile_input_type(DerivedInput, name="DerivedFactoryInput")
    seen: list[dict[str, object]] = []

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Capture the omitted raw model-derived input.

        Args:
            _root: Unused GraphQL root.
            _info: Unused execution information.
            payload: GraphQL-coerced model-derived mapping.

        Returns:
            A harmless response value.
        """
        seen.append(payload)
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "DerivedQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    assert "tags: [String!] =" not in print_schema(schema)
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None, result.errors
    assert seen == [{}]
    assert calls == []
    assert DerivedInput.model_validate({}).tags == ["model"]
    assert calls == [1]


def test_overwritten_wire_alias_only_runs_effective_field_factory() -> None:
    """Do not restore a field replaced by a later shared wire alias.

    The existing compiler exposes only the final GraphQL input field. Its
    resolver-facing out-name alone may receive an omitted-field default.
    """
    calls: list[str] = []
    seen: list[dict[str, object]] = []

    def earlier_default() -> str:
        """Mark an overwritten factory invocation as an unwanted side effect."""
        calls.append("earlier")
        return "earlier-default"

    def later_default() -> str:
        """Create the effective field default on each omitted input."""
        calls.append("later")
        return "later-default"

    class SharedWireInput(InputType):
        earlier: str = Field(default_factory=earlier_default, alias="wire")
        later: str | None = Field(default_factory=later_default, alias="wire")

    input_type = compile_input_type(SharedWireInput, name="SharedWireInput")

    class SubmitSharedWire(Mutation):
        result = field(GraphQLString)

        class Arguments:
            payload = GraphQLArgument(GraphQLNonNull(input_type))

        @staticmethod
        def mutate(
            _root: object, _info: object, payload: dict[str, object]
        ) -> dict[str, str]:
            """Capture the public GraphQL-coerced input mapping.

            Args:
                _root: Unused root object.
                _info: Unused execution information.
                payload: Coerced resolver input.

            Returns:
                A mutation payload confirming execution.
            """
            seen.append(dict(payload))
            return {"result": "ok"}

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "SharedWireQuery", {"ping": GraphQLField(GraphQLString)}
        ),
        mutation=GraphQLObjectType(
            "SharedWireMutation", {"submit": SubmitSharedWire.Field()}
        ),
    )
    assert list(input_type.fields) == ["wire"]
    assert input_type.fields["wire"].out_name == "later"
    assert calls == []

    for wire, expected in (
        ("", "later-default"),
        ('wire: "given"', "given"),
        ("wire: null", None),
    ):
        result = graphql_sync(
            schema, f"mutation {{ submit(payload: {{{wire}}}) {{ result }} }}"
        )
        assert result.errors is None, result.errors
        assert result.data == {"submit": {"result": "ok"}}
        assert seen[-1] == {"later": expected}
    assert calls == ["later"]


def test_literal_field_overwriting_factory_alias_does_not_run_factory() -> None:
    """Do not run a hidden factory when the final wire field is literal.

    Existing last-alias-wins projection and fixed literal SDL defaults remain
    intact even when an earlier field at that alias declared a factory.
    """
    calls: list[str] = []
    seen: list[dict[str, object]] = []

    def hidden_default() -> str:
        """Count any invocation of the overwritten factory."""
        calls.append("hidden")
        return "hidden-default"

    class LiteralWinsInput(InputType):
        earlier: str = Field(default_factory=hidden_default, alias="wire")
        later: str = Field(default="literal-default", alias="wire")

    input_type = compile_input_type(LiteralWinsInput, name="LiteralWinsInput")

    def resolve(_root: object, _info: object, payload: dict[str, object]) -> str:
        """Observe the effective input mapping without model validation.

        Args:
            _root: Unused GraphQL root.
            _info: Unused execution information.
            payload: Coerced resolver input.

        Returns:
            A harmless query value.
        """
        seen.append(dict(payload))
        return "ok"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "LiteralWinsQuery",
            {
                "probe": GraphQLField(
                    GraphQLString,
                    args={"payload": GraphQLArgument(input_type)},
                    resolve=resolve,
                )
            },
        )
    )
    assert list(input_type.fields) == ["wire"]
    assert input_type.fields["wire"].out_name == "later"
    assert 'wire: String = "literal-default"' in print_schema(schema)
    result = graphql_sync(schema, "{ probe(payload: {}) }")
    assert result.errors is None, result.errors
    assert seen == [{"later": "literal-default"}]
    assert calls == []
