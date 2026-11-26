"""Edge cases of the client-error helpers shared by HTTP, SSE and WebSocket."""

from __future__ import annotations

from graphql import GraphQLError

from django_graphex.security import internal_error_cause, scrub_cause_text


def test_scrub_keeps_the_message_when_the_cause_has_no_text() -> None:
    """An exception with an empty message leaves the client message unchanged.

    There is no raw text to remove, so the message is returned as is.
    """
    assert scrub_cause_text("Expected type Int.", ValueError()) == "Expected type Int."


def test_scrub_drops_the_encountered_error_clause() -> None:
    """The clause graphql-core appends with the raw exception text is removed.

    The rest of the coercion message stays readable for the client.
    """
    message = "Expected type 'Money'. Expected a number, but encountered error 'bad'."

    assert scrub_cause_text(message, ValueError("bad")) == (
        "Expected type 'Money'. Expected a number."
    )


def test_a_cyclic_original_error_chain_is_treated_as_internal() -> None:
    """A chain of GraphQL errors that loops back on itself is never public.

    The cycle guard stops the walk and reports the outer error as internal.
    """
    outer = GraphQLError("outer")
    inner = GraphQLError("inner", original_error=outer)
    outer.original_error = inner

    assert internal_error_cause(outer) is outer


def test_scrub_replaces_raw_exception_text_elsewhere_in_the_message() -> None:
    """Exception text outside graphql-core's clause is replaced, never echoed.

    The raw value becomes a fixed placeholder in the client message.
    """
    message = "Variable '$v' got invalid value secret-token."

    assert scrub_cause_text(message, ValueError("secret-token")) == (
        "Variable '$v' got invalid value invalid value."
    )
