"""Sub-spike 2: OUTPUT zero-instantiation proof — gate G4 (riskiest gate).

Instruments Pydantic model __init__ with counters and verifies that
graphql_sync does NOT call __init__ on any output model at resolve time.

Run: pytest tests/spike/test_output_zero_instantiation.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from graphql import (
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    GraphQLList,
    graphql_sync,
)
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Setup: cyclic Pydantic models with cross-references
# ---------------------------------------------------------------------------

class AuthorSpec(BaseModel):
    """Pydantic output spec for Author — build-time declaration only."""

    firstName: str
    lastName: str
    # Forward reference to BookSpec (resolved via model_rebuild)
    books: list["BookSpec"] = []

    class Config:
        arbitrary_types_allowed = True


class BookSpec(BaseModel):
    """Pydantic output spec for Book — build-time declaration only."""

    title: str
    # Forward reference back to AuthorSpec
    author: "AuthorSpec | None" = None


# Resolve the forward references via two-phase model_rebuild
AuthorSpec.model_rebuild(raise_errors=False)
BookSpec.model_rebuild(raise_errors=False)
AuthorSpec.model_rebuild(raise_errors=True)
BookSpec.model_rebuild(raise_errors=True)


# ---------------------------------------------------------------------------
# Helper: build GraphQLObjectType with thunks + camelCase dict keys
# ---------------------------------------------------------------------------

def _build_schema_with_thunks() -> GraphQLSchema:
    """Build a schema with mutual recursion broken by fields=lambda thunks.

    Keys use camelCase (dict key approach, not out_name).
    Resolvers return SimpleNamespace objects — NOT Pydantic model instances.
    """
    # We need mutable container to hold type refs for thunks
    type_cache: dict[str, GraphQLObjectType] = {}

    # Create AuthorType first, register before thunk runs
    author_type = GraphQLObjectType(
        "Author",
        fields=lambda: {
            "firstName": GraphQLField(GraphQLString),
            "lastName": GraphQLField(GraphQLString),
            "books": GraphQLField(GraphQLList(type_cache["Book"])),
        },
    )
    type_cache["Author"] = author_type

    book_type = GraphQLObjectType(
        "Book",
        fields=lambda: {
            "title": GraphQLField(GraphQLString),
            "author": GraphQLField(type_cache["Author"]),
        },
    )
    type_cache["Book"] = book_type

    query_type = GraphQLObjectType(
        "Query",
        fields={
            "author": GraphQLField(
                author_type,
                resolve=lambda root, info: SimpleNamespace(
                    firstName="Jane",
                    lastName="Austen",
                    books=[
                        SimpleNamespace(
                            title="Pride and Prejudice",
                            author=SimpleNamespace(
                                firstName="Jane",
                                lastName="Austen",
                                books=[],
                            ),
                        )
                    ],
                ),
            ),
        },
    )

    return GraphQLSchema(query=query_type)


# ---------------------------------------------------------------------------
# G4: Zero instantiation tests
# ---------------------------------------------------------------------------

class TestG4ZeroInstantiation:
    """G4: Pydantic __init__ must NOT be called during graphql_sync execution."""

    def test_author_spec_init_never_called(self):
        """AuthorSpec.__init__ call count must be 0 after graphql_sync."""
        author_init_count = 0

        original_init = AuthorSpec.__init__

        def counting_author_init(self, /, **data):
            nonlocal author_init_count
            author_init_count += 1
            original_init(self, **data)

        schema = _build_schema_with_thunks()

        with patch.object(AuthorSpec, "__init__", counting_author_init):
            result = graphql_sync(
                schema,
                """
                {
                    author {
                        firstName
                        lastName
                        books {
                            title
                        }
                    }
                }
                """,
            )

        # Assert no errors in the graphql execution
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data["author"]["firstName"] == "Jane"

        # THE GO GATE: Pydantic __init__ must not have been called
        assert author_init_count == 0, (
            f"NO-GO: AuthorSpec.__init__ was called {author_init_count} times. "
            "graphql-core instantiates Pydantic models at resolve time. "
            "Fallback required: Pydantic INPUT-only + dict-keyed functional output compiler."
        )

    def test_book_spec_init_never_called(self):
        """BookSpec.__init__ call count must be 0 after graphql_sync."""
        book_init_count = 0

        original_init = BookSpec.__init__

        def counting_book_init(self, /, **data):
            nonlocal book_init_count
            book_init_count += 1
            original_init(self, **data)

        schema = _build_schema_with_thunks()

        with patch.object(BookSpec, "__init__", counting_book_init):
            result = graphql_sync(
                schema,
                """
                {
                    author {
                        books {
                            title
                            author {
                                firstName
                            }
                        }
                    }
                }
                """,
            )

        # Assert no errors in the graphql execution
        assert result.errors is None, f"GraphQL errors: {result.errors}"

        # THE GO GATE: Pydantic __init__ must not have been called
        assert book_init_count == 0, (
            f"NO-GO: BookSpec.__init__ was called {book_init_count} times. "
            "graphql-core instantiates Pydantic models at resolve time. "
            "Fallback required: Pydantic INPUT-only + dict-keyed functional output compiler."
        )
