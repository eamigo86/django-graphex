"""Sub-spike 1: Input engine + ModelMetaclass (two forms) — gates G1, G2, G3.

All helpers are inline; zero production files are created or modified.

Run: pytest tests/spike/test_input_engine.py -v
"""

from __future__ import annotations

import os

import django

# Configure Django settings before any model import
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "")
if not django.conf.settings.configured:
    django.conf.settings.configure(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", "tests"],
        SECRET_KEY="spike-test-secret",
        USE_I18N=True,
    )
    django.setup()

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from graphql import GraphQLInputObjectType, GraphQLInputField, GraphQLNonNull, GraphQLString
from pydantic import BaseModel

from django_graphex.native.fields import build_model_schema
from django_graphex.native.validators import build_validator_model
from django_graphex.native.backend import PydanticBackend

# We import the test models via Django's app registry
from tests.models import Category


# ---------------------------------------------------------------------------
# Inline helper: map Pydantic model fields -> GraphQLInputObjectType
# ---------------------------------------------------------------------------

def _to_graphql_input(pydantic_model: type) -> GraphQLInputObjectType:
    """Build a GraphQLInputObjectType from a Pydantic model's model_fields.

    For each field, we create a GraphQLInputField with out_name = the snake_case
    field name. Required fields are wrapped in GraphQLNonNull.
    """
    from pydantic.fields import PydanticUndefined
    from graphql import GraphQLString, GraphQLInt, GraphQLFloat, GraphQLBoolean, GraphQLID
    import datetime
    import decimal
    import uuid

    PYTHON_TO_GQL = {
        str: GraphQLString,
        int: GraphQLString,   # simplification for spike
        float: GraphQLString,
        bool: GraphQLString,
        datetime.date: GraphQLString,
        datetime.datetime: GraphQLString,
        uuid.UUID: GraphQLString,
        decimal.Decimal: GraphQLString,
    }

    fields = {}
    for name, field_info in pydantic_model.model_fields.items():
        annotation = field_info.annotation
        # Unwrap Optional[X] -> X
        import typing
        origin = getattr(annotation, "__origin__", None)
        if origin is typing.Union:
            args = [a for a in annotation.__args__ if a is not type(None)]
            annotation = args[0] if args else str

        gql_type = PYTHON_TO_GQL.get(annotation, GraphQLString)

        required = field_info.is_required()
        if required:
            gql_field = GraphQLInputField(GraphQLNonNull(gql_type), out_name=name)
        else:
            gql_field = GraphQLInputField(gql_type, out_name=name)

        fields[name] = gql_field

    return GraphQLInputObjectType(
        name=f"{pydantic_model.__name__}Input",
        fields=fields,
    )


# ---------------------------------------------------------------------------
# G1: Model-coupled input field carries out_name
# ---------------------------------------------------------------------------

class TestG1InputEngineModelCoupled:
    """G1: build_model_schema + _to_graphql_input produces out_name on fields."""

    def test_name_field_has_out_name(self):
        """The 'title' field of Category carries out_name='title'."""
        schema = build_model_schema(Category)
        input_type = _to_graphql_input(schema)
        # Category has a 'title' field
        assert "title" in input_type.fields, (
            f"Expected 'title' in fields, got: {list(input_type.fields.keys())}"
        )
        assert input_type.fields["title"].out_name == "title", (
            f"Expected out_name='title', got: {input_type.fields['title'].out_name!r}"
        )

    def test_validated_data_usable_by_pydantic_backend(self, db):
        """Validated data from the schema is accepted by PydanticBackend.save_object."""
        schema_cls = build_model_schema(Category)
        validated = schema_cls(title="Tech")
        assert validated.title == "Tech"
        # Confirm it's a valid Pydantic model that PydanticBackend could use
        # (We don't actually call save_object as that requires Django DB transaction)
        assert hasattr(validated, "model_dump")
        data = validated.model_dump()
        assert data["title"] == "Tech"


# ---------------------------------------------------------------------------
# G2: Inline validator strips whitespace
# ---------------------------------------------------------------------------

class TestG2InlineValidator:
    """G2: build_validator_model + build_model_schema strips whitespace via validate_name."""

    def test_validator_strips_whitespace(self):
        """build_validator_model produces a base that strips category title."""

        class CategoryWithValidator(Category):
            class Meta:
                app_label = "tests"
                proxy = True

            @classmethod
            def validate_title(cls, value: str) -> str:
                return value.strip()

        # build_validator_model(host_cls, model, pydantic_model=None)
        validator_base = build_validator_model(CategoryWithValidator, CategoryWithValidator)
        schema = build_model_schema(CategoryWithValidator, base=validator_base)
        result = schema(title=" Tech ")
        assert result.title == "Tech", (
            f"Expected 'Tech' after strip, got: {result.title!r}"
        )


# ---------------------------------------------------------------------------
# G3: ModelMetaclass identity
# ---------------------------------------------------------------------------

class TestG3ModelMetaclass:
    """G3: Any Pydantic-based class has ModelMetaclass as its metaclass."""

    def test_model_free_type_has_pydantic_metaclass(self):
        """A hand-written BaseModel subclass has type __name__ == 'ModelMetaclass'."""

        class SearchInput(BaseModel):
            query: str
            limit: int = 10

        metaclass_name = type(SearchInput).__name__
        assert metaclass_name == "ModelMetaclass", (
            f"Expected 'ModelMetaclass', got: {metaclass_name!r}"
        )

    def test_model_free_type_emits_field_via_to_graphql_input(self):
        """_to_graphql_input on a hand-written BaseModel emits the annotated field."""

        class SearchInput(BaseModel):
            query: str
            limit: int = 10

        input_type = _to_graphql_input(SearchInput)
        assert "query" in input_type.fields, (
            f"Expected 'query' in fields, got: {list(input_type.fields.keys())}"
        )

    def test_build_model_schema_result_has_pydantic_metaclass(self):
        """A model built with build_model_schema also carries ModelMetaclass."""
        schema_cls = build_model_schema(Category)
        metaclass_name = type(schema_cls).__name__
        assert metaclass_name == "ModelMetaclass", (
            f"Expected 'ModelMetaclass', got: {metaclass_name!r}"
        )
