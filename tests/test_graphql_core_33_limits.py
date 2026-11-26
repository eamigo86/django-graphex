"""graphql-core 3.3.2+ limits answer with the library's coded client errors."""

from typing import Any

import pytest
from graphql import (
    ExecutionResult,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)
from graphql.validation.validate import ValidationAbortedError

from django_graphex.security import mark_client_errors, mark_request_errors
from django_graphex.validation import _FRAGMENT_NESTING_VISITOR, run_validation
from django_graphex.views import DEFAULT_VALIDATION_RULES, _parse_or_depth_error

_ABORT = "Validation aborted."
_VARIABLES = "Variable values are nested too deeply."
_SELECTIONS = "Selections are nested too deeply. Execution aborted."


def _schema() -> GraphQLSchema:
    """Build a self-referential Node schema.

    Returns:
        schema: Schema whose query root exposes "root" of type Node.
    """
    node = GraphQLObjectType(
        "Node",
        lambda: {"name": GraphQLField(GraphQLString), "child": GraphQLField(node)},
    )
    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"root": GraphQLField(node)}), types=[node]
    )


def _fake_validate(*errors: GraphQLError) -> Any:
    """Return a validate callable that answers the given errors.

    Args:
        *errors: The errors the callable returns.

    Returns:
        fake: The callable.
    """
    return lambda *_args, **_kwargs: list(errors)


def _codes(errors: list[GraphQLError]) -> list[str | None]:
    """Collect the extension codes of the errors.

    Args:
        errors: The errors to read.

    Returns:
        codes: One "extensions.code" value per error.
    """
    return [(e.extensions or {}).get("code") for e in errors]


def test_parser_depth_limit_is_a_query_too_deep_error() -> None:
    """An inline document past the parser limit is a coded depth error.

    The assertions below pin the contract.
    """
    query = "{ root { " + "child { " * 400 + "name" + " }" * 400 + " } }"

    with pytest.raises(GraphQLError) as caught:
        _parse_or_depth_error(query)

    assert _codes([caught.value]) == ["QUERY_TOO_DEEP"]
    assert caught.value.message == "Query is nested too deeply to be parsed."


def test_other_syntax_errors_stay_syntax_errors() -> None:
    """Only the depth abort is rewritten; a plain typo keeps its message.

    The assertions below pin the contract.
    """
    with pytest.raises(GraphQLError) as caught:
        _parse_or_depth_error("{ root")

    assert _codes([caught.value]) == [None]
    assert caught.value.message.startswith("Syntax Error")


def test_fragment_nesting_abort_is_a_query_too_deep_error() -> None:
    """A fragment chain past the upstream limit is a coded depth error.

    The assertions below pin the contract.
    """
    parts = ["{ root { ...F0 } }"]
    for i in range(300):
        body = f"...F{i + 1}" if i + 1 < 300 else "name"
        parts.append(f"fragment F{i} on Node {{ child {{ {body} }} }}")

    errors = run_validation(
        validate, _schema(), parse("\n".join(parts)), list(DEFAULT_VALIDATION_RULES)
    )

    assert _codes(errors) == ["QUERY_TOO_DEEP"]


def test_validation_budget_abort_is_a_query_too_complex_error() -> None:
    """An abort that is not about nesting is a coded complexity error.

    Only graphql-core 3.3.2+ sends that bare abort, and it ships the nesting
    visitor that classifies it; on 3.3.1 the abort is left untouched.
    """
    abort = ValidationAbortedError(_ABORT)
    errors = run_validation(
        _fake_validate(abort), _schema(), parse("{ root { name } }"), []
    )

    if _FRAGMENT_NESTING_VISITOR is None:
        assert errors == [abort]
        return
    assert _codes(errors) == ["QUERY_TOO_COMPLEX"]
    assert not any(isinstance(e, ValidationAbortedError) for e in errors)


def test_error_limit_abort_keeps_its_message() -> None:
    """The MAX_VALIDATION_ERRORS cap is not a depth or budget abort.

    The assertions below pin the contract.
    """
    capped = ValidationAbortedError(
        "Too many validation errors, error limit reached. Validation aborted."
    )

    errors = run_validation(
        _fake_validate(capped), _schema(), parse("{ root { name } }"), []
    )

    assert errors == [capped]


def test_upstream_variable_and_selection_depth_errors_are_coded() -> None:
    """Pre-execution depth errors carry QUERY_TOO_DEEP on every surface.

    The assertions below pin the contract.
    """
    result = ExecutionResult(
        data=None, errors=[GraphQLError(_VARIABLES), GraphQLError(_SELECTIONS)]
    )
    listed = mark_client_errors([GraphQLError(_VARIABLES)])

    marked = mark_request_errors(result)

    assert _codes(marked.errors or []) == ["QUERY_TOO_DEEP"] * 2
    assert (marked.errors or [])[0].message == (
        "Variables are nested too deeply to be coerced."
    )
    assert (marked.errors or [])[1].message == _SELECTIONS
    assert _codes(listed) == ["QUERY_TOO_DEEP"]


def test_resolver_error_with_a_depth_message_is_left_alone() -> None:
    """A resolver error carries a path, so it is never rewritten.

    The assertions below pin the contract.
    """
    error = GraphQLError(_VARIABLES, path=["root"])

    mark_request_errors(ExecutionResult(data=None, errors=[error]))

    assert _codes([error]) == [None]
