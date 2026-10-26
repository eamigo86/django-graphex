"""BigInt contracts for model output, generated inputs, and filter lookups."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from django.test import RequestFactory
from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)
from graphql.language.ast import IntValueNode, StringValueNode

from django_graphex.core import ObjectType, field
from django_graphex.core.fields import build_model_schema
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.core.scalars import GdxBigInt
from django_graphex.fields import DjangoFilterListField
from django_graphex.filtering.native_schema import build_filter_input_type
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_pair


class _Numbers(models.Model):
    """Unmigrated model with signed, positive, and ordinary integer columns."""

    big = models.BigIntegerField()
    positive = models.PositiveBigIntegerField()
    ordinary = models.IntegerField()

    class Meta:
        """Bind the test-only model to the installed tests app."""

        app_label = "tests"


class _NumbersType(DjangoObjectType):
    """Expose automatically derived model fields without scalar overrides."""

    class Meta:
        """Select the test-only model."""

        model = _Numbers


class _Query(ObjectType):
    """Return an in-memory model from GraphQL context without database I/O."""

    item = field(_NumbersType)

    @staticmethod
    def resolve_item(root: Any, info: Any) -> Any:
        """Return the model supplied by the test.

        Args:
            root: Unused root value.
            info: GraphQL context containing the model.

        Returns:
            The in-memory model instance.
        """
        return info.context["item"]


class _BigKey(models.Model):
    """Explicit BigInteger primary key for output wrapper compatibility."""

    amount = models.BigIntegerField(primary_key=True)

    class Meta:
        """Bind the test-only model to the installed tests app."""

        app_label = "tests"


class _BigKeyType(DjangoObjectType):
    """Expose the explicit BigInteger primary key."""

    class Meta:
        """Select the test-only primary-key model."""

        model = _BigKey


class _BigRelationTarget(models.Model):
    """Use a regular BigInteger primary key behind a relation ID input."""

    id = models.BigIntegerField(primary_key=True)

    class Meta:
        """Bind the test-only relation target to the installed tests app."""

        app_label = "tests"


class _BigRelationHost(models.Model):
    """Accept an existing ID-typed foreign key to a BigInteger target."""

    target = models.ForeignKey(_BigRelationTarget, on_delete=models.CASCADE)

    class Meta:
        """Bind the test-only relation host to the installed tests app."""

        app_label = "tests"


class _PositiveBigChoice(models.Model):
    """Expose a numeric choice through the existing GraphQL Enum input."""

    positive = models.PositiveBigIntegerField(choices=[(1, "One"), (2, "Two")])

    class Meta:
        """Bind the test-only choices model to the installed tests app."""

        app_label = "tests"


def _echo_schema(input_type: Any, captured: list[Any]) -> GraphQLSchema:
    """Build a small execution schema around a generated input type.

    Args:
        input_type: Compiled input object used as the mutation argument.
        captured: List receiving values delivered to the resolver.

    Returns:
        An executable schema without database side effects.
    """

    def resolve_echo(root: Any, info: Any, input: Any) -> str:
        """Record parsed values delivered to the mutation resolver.

        Args:
            root: Unused root value.
            info: Unused execution context.
            input: Parsed GraphQL input mapping.

        Returns:
            String representation of the signed BigInteger value.
        """
        captured.append(input)
        return str(input["big"])

    query = GraphQLObjectType("BigIntProbeQuery", {"noop": GraphQLField(GraphQLString)})
    mutation = GraphQLObjectType(
        "BigIntProbeMutation",
        {
            "echo": GraphQLField(
                GraphQLString,
                args={"input": GraphQLArgument(input_type)},
                resolve=resolve_echo,
            )
        },
    )
    return GraphQLSchema(query=query, mutation=mutation)


@pytest.mark.parametrize(
    "value", [0, 42, 2147483648, 9007199254740993, 9223372036854775807]
)
def test_auto_output_uses_decimal_string_bigint(value: int) -> None:
    """Return decimal strings, including small integers and JS-unsafe values.

    Args:
        value: Signed and positive value exercising the approved range.
    """
    schema = DjangoGraphQLSchema(query=_Query).graphql_schema
    result = graphql_sync(
        schema,
        "{ item { big positive ordinary id } }",
        context_value={"item": _Numbers(id=1, big=value, positive=value, ordinary=7)},
    )
    assert result.errors is None
    assert result.data == {
        "item": {"big": str(value), "positive": str(value), "ordinary": 7, "id": "1"}
    }
    fields = _NumbersType._meta.graphql_output_type.fields
    assert fields["big"].type.name == "BigInt"
    assert fields["positive"].type.name == "BigInt"
    assert fields["ordinary"].type.name == "Int"
    assert fields["id"].type.of_type.name == "ID"


def test_explicit_bigint_primary_key_keeps_nonnull_wrapper() -> None:
    """Preserve the original required primary-key output wrapper.

    Only the wrapped scalar changes from Int to BigInt.
    """
    gql_type = _BigKeyType._meta.graphql_output_type.fields["amount"].type
    assert isinstance(gql_type, GraphQLNonNull)
    assert gql_type.of_type.name == "BigInt"


def test_nullable_bigint_output_keeps_null() -> None:
    """Leave ordinary model scalar fields nullable in the output schema.

    The change is to the named scalar, not the field wrapper.
    """
    schema = DjangoGraphQLSchema(query=_Query).graphql_schema
    result = graphql_sync(
        schema,
        "{ item { big positive } }",
        context_value={"item": _Numbers(big=None, positive=None, ordinary=0)},
    )
    assert result.errors is None
    assert result.data == {"item": {"big": None, "positive": None}}


def test_explicit_scalar_override_keeps_its_declared_contract() -> None:
    """Do not replace a user-declared String field with automatic BigInt.

    The model mapping applies only to auto-derived fields.
    """
    local_registry = Registry()

    def resolve_big(root: Any, info: Any) -> str:
        """Return a value through the explicitly selected scalar.

        Args:
            root: Model supplied by the query.
            info: Unused GraphQL execution context.

        Returns:
            A user-defined string value.
        """
        return f"custom-{root.big}"

    class _OverrideType(DjangoObjectType):
        """Override only the large integer field on a private type."""

        big = field(GraphQLString, resolver=resolve_big)

        class Meta:
            """Select the test model and private registry."""

            model = _Numbers
            registry = local_registry

    class _OverrideQuery(ObjectType):
        """Expose the private override type."""

        item = field(_OverrideType)

        @staticmethod
        def resolve_item(root: Any, info: Any) -> _Numbers:
            """Return the in-memory test model.

            Args:
                root: Unused root value.
                info: Unused GraphQL execution context.

            Returns:
                An in-memory test model.
            """
            return _Numbers(big=42, positive=42, ordinary=7)

    schema = DjangoGraphQLSchema(
        query=_OverrideQuery, registries=isolated_pair(local_registry)
    ).graphql_schema
    assert _OverrideType._meta.graphql_output_type.fields["big"].type.name == "String"
    result = graphql_sync(schema, "{ item { big positive } }")
    assert result.errors is None
    assert result.data == {"item": {"big": "custom-42", "positive": "42"}}


def test_null_bigint_primary_key_propagates_nonnull_error() -> None:
    """Keep a null explicit primary key from returning a partial object.

    The GraphQL non-null error must bubble to the nullable parent.
    """

    class _KeyQuery(ObjectType):
        """Expose the explicit key through a nullable object field."""

        item = field(_BigKeyType)

        @staticmethod
        def resolve_item(root: Any, info: Any) -> _BigKey:
            """Return the intentionally invalid in-memory object.

            Args:
                root: Unused root value.
                info: Unused execution context.

            Returns:
                A model whose required key is null.
            """
            return _BigKey(amount=None)

    result = graphql_sync(
        DjangoGraphQLSchema(query=_KeyQuery).graphql_schema, "{ item { amount } }"
    )
    assert result.data == {"item": None}
    assert result.errors and result.errors[0].path == ["item", "amount"]


def test_signed_minimum_and_out_of_range_output() -> None:
    """Serialize the signed minimum but reject output outside 64-bit range.

    Non-integer values cannot be silently coerced.
    """
    assert GdxBigInt.serialize(-(1 << 63)) == "-9223372036854775808"
    for value in (-(1 << 63) - 1, 1 << 63, True, 1.5, "42"):
        with pytest.raises(GraphQLError):
            GdxBigInt.serialize(value)


def test_generated_input_parses_decimal_strings_to_python_int() -> None:
    """Accept exact 64-bit strings in generated mutation inputs.

    Literal and variable paths must deliver Python integers to resolvers.
    """
    compiled = compile_input_type(
        build_model_schema(_Numbers), name="BigNumbersCreateInput"
    )
    assert compiled.fields["big"].type.of_type.name == "BigInt"
    assert compiled.fields["positive"].type.of_type.name == "BigInt"
    assert compiled.fields["ordinary"].type.of_type.name == "Int"
    captured: list[Any] = []
    schema = _echo_schema(compiled, captured)
    for value in (
        "42",
        "2147483648",
        "9007199254740993",
        "9223372036854775807",
        "-9223372036854775808",
    ):
        positive = "0" if value.startswith("-") else value
        result = graphql_sync(
            schema,
            f'mutation {{ echo(input: {{big: "{value}", positive: "{positive}", ordinary: 7}}) }}',
        )
        assert result.errors is None
        assert result.data == {"echo": value}
        assert captured[-1]["big"] == int(value)
        assert captured[-1]["positive"] == int(positive)
    variable_result = graphql_sync(
        schema,
        "mutation($arg: BigNumbersCreateInput) { echo(input: $arg) }",
        variable_values={
            "arg": {"big": "9007199254740993", "positive": "42", "ordinary": 7}
        },
    )
    assert variable_result.errors is None
    assert captured[-1]["big"] == 9007199254740993


@pytest.mark.parametrize(
    "value",
    [
        "",
        "01",
        "+1",
        "-0",
        "1.0",
        "1e3",
        "١",
        "9223372036854775808",
        "-9223372036854775809",
        "9" * 10000,
        42,
        True,
        1.5,
        None,
    ],
)
def test_bigint_rejects_invalid_variables_before_resolver(value: Any) -> None:
    """Reject non-string or malformed variable values without resolver calls.

    Args:
        value: Invalid wire value, including bounded-length attack input.
    """
    compiled = compile_input_type(
        build_model_schema(_Numbers), name="BigIntInvalidInput"
    )
    captured: list[Any] = []
    schema = _echo_schema(compiled, captured)
    result = graphql_sync(
        schema,
        "mutation($arg: BigIntInvalidInput) { echo(input: $arg) }",
        variable_values={"arg": {"big": value, "positive": "1", "ordinary": 1}},
    )
    assert result.errors
    assert captured == []
    assert len(result.errors[0].message) < 300


def test_bigint_accepts_only_string_literals() -> None:
    """Reject numeric literals even when they fit GraphQL Int.

    The approved public input format is a decimal string.
    """
    assert GdxBigInt.parse_literal(StringValueNode(value="-9223372036854775808")) == -(
        1 << 63
    )
    with pytest.raises(GraphQLError):
        GdxBigInt.parse_literal(IntValueNode(value="42"))
    with pytest.raises(GraphQLError):
        GdxBigInt.parse_value(42)


def test_positive_bigint_validation_keeps_nonnegative_constraint() -> None:
    """Keep positive model validation while the wire scalar stays signed.

    The signed scalar serves both model field classes.
    """
    schema = build_model_schema(_Numbers)
    assert schema.model_validate(
        {"big": -(1 << 63), "positive": 0, "ordinary": 1}
    ).big == -(1 << 63)
    with pytest.raises(ValueError):
        schema.model_validate({"big": 1, "positive": -1, "ordinary": 1})


def test_relation_ids_with_explicit_bigint_pk_keep_old_input_type() -> None:
    """Do not migrate M2M relation ID lists with model value columns.

    A8 approval covers model-derived BigInteger values, not relation IDs.
    """

    class _Related(models.Model):
        """Use an explicit BigInteger primary key as a relation target."""

        id = models.BigIntegerField(primary_key=True)

        class Meta:
            """Bind the test-only relation target to the tests app."""

            app_label = "tests"

    class _Host(models.Model):
        """Expose an M2M list of relation identifiers."""

        related = models.ManyToManyField(_Related)

        class Meta:
            """Bind the test-only relation host to the tests app."""

            app_label = "tests"

    compiled = compile_input_type(build_model_schema(_Host), name="BigRelHostInput")
    assert str(compiled.fields["related"].type) == "[Int!]"


@pytest.mark.django_db
@pytest.mark.parametrize("wire", ["42", 42])
def test_bigint_foreign_key_id_mutation_accepts_existing_wire_values(
    wire: str | int,
) -> None:
    """Keep both ID wire representations valid for a BigInteger-key relation.

    Args:
        wire: Existing string or integer GraphQL ID variable value.
    """
    local_registry = Registry()

    class _TargetType(DjangoObjectType):
        """Register the relation target for the generated input."""

        class Meta:
            """Use the test-only target and private registry."""

            model = _BigRelationTarget
            registry = local_registry

    class _CreateHost(DjangoModelMutation):
        """Create a relation host through the production mutation path."""

        class Meta:
            """Use the test-only host and private registry."""

            model = _BigRelationHost
            registry = local_registry

    class _RootQuery(ObjectType):
        """Provide the required query root."""

        noop = field(GraphQLString)

    class _RootMutation(ObjectType):
        """Mount the generated relation mutation."""

        create_host = _CreateHost.CreateField()

    schema = DjangoGraphQLSchema(
        query=_RootQuery,
        mutation=_RootMutation,
        registries=isolated_pair(local_registry),
    ).graphql_schema
    mutation = schema.mutation_type.fields["createHost"]
    argument_name, argument = next(iter(mutation.args.items()))
    assert str(argument.type.of_type.fields["target"].type) == "ID!"
    _BigRelationTarget.objects.create(id=42)

    result = graphql_sync(
        schema,
        f"mutation($input: {argument.type}) {{ createHost({argument_name}: $input) {{ ok errors {{ field messages }} }} }}",
        variable_values={"input": {"target": wire}},
        context_value=RequestFactory().post(
            "/graphql/", content_type="application/json"
        ),
    )

    assert result.errors is None
    assert result.data["createHost"]["ok"] is True, result.formatted
    assert _BigRelationHost.objects.get().target_id == 42


@pytest.mark.django_db
def test_positive_bigint_numeric_choice_mutation_accepts_valid_enum() -> None:
    """Keep a valid numeric choice accepted by its existing Enum input.

    Invalid Enum members must still be rejected before persistence.
    """
    local_registry = Registry()

    class _CreateChoice(DjangoModelMutation):
        """Create a numeric-choice row through the production mutation path."""

        class Meta:
            """Use the test-only choice model and private registry."""

            model = _PositiveBigChoice
            registry = local_registry

    class _RootQuery(ObjectType):
        """Provide the required query root."""

        noop = field(GraphQLString)

    class _RootMutation(ObjectType):
        """Mount the generated choices mutation."""

        create_choice = _CreateChoice.CreateField()

    schema = DjangoGraphQLSchema(
        query=_RootQuery,
        mutation=_RootMutation,
        registries=isolated_pair(local_registry),
    ).graphql_schema
    mutation = schema.mutation_type.fields["createChoice"]
    argument_name, argument = next(iter(mutation.args.items()))
    enum_type = argument.type.of_type.fields["positive"].type.of_type
    choice_name = next(
        name for name, choice in enum_type.values.items() if choice.value == 1
    )
    result = graphql_sync(
        schema,
        f"mutation($input: {argument.type}) {{ createChoice({argument_name}: $input) {{ ok errors {{ field messages }} }} }}",
        variable_values={"input": {"positive": choice_name}},
        context_value=RequestFactory().post(
            "/graphql/", content_type="application/json"
        ),
    )

    assert result.errors is None
    assert result.data["createChoice"]["ok"] is True
    assert _PositiveBigChoice.objects.get().positive == 1

    invalid = graphql_sync(
        schema,
        f"mutation($input: {argument.type}) {{ createChoice({argument_name}: $input) {{ ok }} }}",
        variable_values={"input": {"positive": "INVALID"}},
    )
    assert invalid.errors
    assert _PositiveBigChoice.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_generated_model_mutation_persists_exact_bigint() -> None:
    """Carry string input through the generated mutation and ORM unchanged.

    This tests the real persistence boundary, not only a compiler stub.
    """
    from django.test import RequestFactory

    from django_graphex.mutation import DjangoModelMutation

    class _CreateNumbers(DjangoModelMutation):
        """Build the real generated create mutation for the test model."""

        class Meta:
            """Select the unmigrated test model."""

            model = _Numbers

    class _RootQuery(ObjectType):
        """Provide a query root required by GraphQLSchema."""

        noop = field(GraphQLString)

    class _RootMutation(ObjectType):
        """Mount the generated model create field."""

        create_numbers = _CreateNumbers.CreateField()

    schema = DjangoGraphQLSchema(query=_RootQuery, mutation=_RootMutation)
    gql_field = schema.graphql_schema.mutation_type.fields["createNumbers"]
    argument_name, argument = next(iter(gql_field.args.items()))
    assert argument.type.of_type.fields["big"].type.of_type.name == "BigInt"
    result = graphql_sync(
        schema.graphql_schema,
        f'mutation {{ createNumbers({argument_name}: {{big: "9007199254740993", positive: "2147483648", ordinary: 7}}) {{ ok errors {{ field messages }} }} }}',
        context_value=RequestFactory().post(
            "/graphql/", content_type="application/json"
        ),
    )
    assert result.errors is None
    assert result.data["createNumbers"]["ok"] is True
    row = _Numbers.objects.get()
    assert (row.big, row.positive, row.ordinary) == (9007199254740993, 2147483648, 7)


def test_automatic_filter_lookups_use_bigint() -> None:
    """Use BigInt for exact, list, and range lookup values.

    Parsed filter values reaching resolvers must remain Python integers.
    """
    local_registry = Registry()

    class _FilterType(DjangoObjectType):
        """Register the serving model for the filter surface assertion."""

        class Meta:
            """Bind the test-only type to its private registry."""

            model = _Numbers
            registry = local_registry

    gql_filter = build_filter_input_type(
        _Numbers,
        {"big": ("exact", "in", "range"), "positive": ("exact",)},
        local_registry,
    )
    assert gql_filter is not None
    lookups = gql_filter.fields["big"].type.fields
    assert lookups["exact"].type.name == "BigInt"
    assert lookups["in"].type.of_type.name == "BigInt"
    assert lookups["range"].type.of_type.name == "BigInt"
    assert gql_filter.fields["positive"].type.fields["exact"].type.name == "BigInt"

    captured: list[Any] = []

    def resolve_filter(root: Any, info: Any, filter: Any) -> str:
        """Record lookup values after automatic filter-input parsing.

        Args:
            root: Unused root value.
            info: Unused execution context.
            filter: Parsed automatic filter input.

        Returns:
            The exact signed lookup value as text.
        """
        captured.append(filter)
        return str(filter["big"]["exact"])

    query = GraphQLObjectType(
        "BigIntFilterQuery",
        {
            "echo": GraphQLField(
                GraphQLString,
                args={"filter": GraphQLArgument(gql_filter)},
                resolve=resolve_filter,
            )
        },
    )
    schema = GraphQLSchema(query=query)
    result = graphql_sync(
        schema,
        f"query($arg: {gql_filter.name}) {{ echo(filter: $arg) }}",
        variable_values={
            "arg": {
                "big": {
                    "exact": "9007199254740993",
                    "in": ["42", "9223372036854775807"],
                    "range": ["-9223372036854775808", "42"],
                },
                "positive": {"exact": "2147483648"},
            }
        },
    )
    assert result.errors is None
    assert result.data == {"echo": "9007199254740993"}
    assert captured[-1]["big"] == {
        "exact": 9007199254740993,
        "in": [42, 9223372036854775807],
        "range": [-9223372036854775808, 42],
    }
    assert captured[-1]["positive"]["exact"] == 2147483648


@pytest.mark.django_db
def test_automatic_bigint_filter_executes_orm_query() -> None:
    """Filter persisted rows by an exact JS-unsafe BigInt string.

    The automatic filter must pass its parsed integer to the ORM.
    """
    local_registry = Registry()

    class _FilterNumbersType(DjangoObjectType):
        """Expose only the BigInteger filter in a private registry."""

        class Meta:
            """Select the model and approved filter lookup."""

            model = _Numbers
            registry = local_registry
            filter_fields = {"big": ("exact",)}

    class _FilterQuery(ObjectType):
        """Expose a real ORM-backed filter-list field."""

        items = DjangoFilterListField(_FilterNumbersType)

    _Numbers.objects.create(big=9007199254740993, positive=2147483648, ordinary=7)
    _Numbers.objects.create(big=42, positive=42, ordinary=7)
    schema = DjangoGraphQLSchema(
        query=_FilterQuery, registries=isolated_pair(local_registry)
    )
    result = graphql_sync(
        schema.graphql_schema,
        '{ items(filter: { big: { exact: "9007199254740993" } }) { big positive } }',
    )
    assert result.errors is None
    assert result.data == {
        "items": [{"big": "9007199254740993", "positive": "2147483648"}]
    }
