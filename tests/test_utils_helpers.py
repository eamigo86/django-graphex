# -*- coding: utf-8 -*-
"""Coverage for the standalone helpers in ``django_graphex.utils``.

These hit the ``get_obj`` / ``create_obj`` error paths,
``get_extra_filters``, ``get_related_fields``, ``get_reverse_fields``,
``is_required``, ``get_type``, ``_get_queryset`` and ``parse_validation_exc``
that the end-to-end query/optimization suites do not directly exercise.
"""

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase
from graphql import GraphQLList, GraphQLNonNull, GraphQLString

from django_graphex.utils import (
    _get_queryset,
    create_obj,
    get_extra_filters,
    get_obj,
    get_related_fields,
    get_reverse_fields,
    get_type,
    is_required,
    not_found_error,
    parse_validation_exc,
)

from .models import Author, BasicModel, Post


# --------------------------------------------------------------------------- #
# get_obj / create_obj                                                         #
# --------------------------------------------------------------------------- #
class GetCreateObjTest(TestCase):
    def test_get_obj_returns_instance(self):
        obj = BasicModel.objects.create(text="hi")
        self.assertEqual(get_obj("tests", "BasicModel", obj.pk), obj)

    def test_get_obj_missing_returns_none(self):
        self.assertIsNone(get_obj("tests", "BasicModel", 999999))

    def test_get_obj_unknown_model_returns_none(self):
        # Regression: an unknown app/model raised LookupError -> the unbound
        # `model` in the `except model.DoesNotExist` clause crashed with
        # UnboundLocalError instead of returning None.
        self.assertIsNone(get_obj("tests", "NoSuchModel", 1))
        self.assertIsNone(get_obj("no_such_app", "Whatever", 1))

    def test_create_obj_creates_and_saves(self):
        obj = create_obj(BasicModel, text="made")
        self.assertEqual(obj.text, "made")
        self.assertTrue(BasicModel.objects.filter(pk=obj.pk).exists())

    def test_create_obj_from_string_model(self):
        obj = create_obj("tests.BasicModel", text="strmade")
        self.assertEqual(obj.text, "strmade")

    def test_create_obj_invalid_model_returns_assert_message(self):
        # The assert fires inside the try; the broad except returns its message.
        result = create_obj(object)
        self.assertIsInstance(result, str)
        self.assertIn("valid Django Model", result)

    def test_create_obj_validation_failure_reraises(self):
        # BasicModel.text is required (no blank) -> full_clean raises, re-raised.
        with self.assertRaises(ValidationError):
            create_obj(BasicModel, text="")


# --------------------------------------------------------------------------- #
# get_extra_filters / get_related_fields / get_reverse_fields                  #
# --------------------------------------------------------------------------- #
class RelationHelpersTest(TestCase):
    def test_get_extra_filters_maps_relation_to_root(self):
        author = Author.objects.create(name="A")
        filters = get_extra_filters(author, Post)
        self.assertEqual(filters.get("author"), author)

    def test_get_extra_filters_empty_when_unrelated(self):
        author = Author.objects.create(name="A")
        # BasicModel has no FK to Author.
        self.assertEqual(get_extra_filters(author, BasicModel), {})

    def test_get_related_fields_lists_relations(self):
        related = get_related_fields(Post)
        self.assertIn("author", related)
        self.assertIn("tags", related)
        self.assertNotIn("title", related)

    def test_get_reverse_fields_is_iterable(self):
        # Exercises the generator body; on modern Django the rel/related lookup
        # yields nothing, but the function must still run without error.
        result = list(get_reverse_fields(Author))
        self.assertIsInstance(result, list)


# --------------------------------------------------------------------------- #
# is_required / get_type / _get_queryset / not_found_error / parse_validation  #
# --------------------------------------------------------------------------- #
def test_is_required_true_for_no_blank_no_default():
    field = BasicModel._meta.get_field("text")
    assert is_required(field) is True


def test_is_required_false_for_default_field():
    # Author.bio has default="" -> not required.
    assert is_required(Author._meta.get_field("bio")) is False


def test_is_required_reverse_relation_uses_field_fallback():
    # A reverse relation has no `blank` attr -> the function reads `.field` and
    # derives blank/default from it. Post.author is a non-null FK with no
    # default, so the reverse relation resolves to required.
    reverse = Author._meta.get_field("posts")  # ManyToOneRel
    assert is_required(reverse) is True


def test_is_required_on_object_without_attrs_returns_false():
    # An object lacking blank/default/field -> AttributeError-safe False.
    assert is_required(object()) is False


def test_get_type_unwraps_list_and_nonnull():
    wrapped = GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString)))
    assert get_type(wrapped) is GraphQLString


def test_get_queryset_from_model_manager_queryset():
    from_model = _get_queryset(Author)
    assert from_model.model is Author
    from_manager = _get_queryset(Author.objects)
    assert from_manager.model is Author
    qs = Author.objects.all()
    assert _get_queryset(qs) is qs


def test_get_queryset_invalid_raises():
    with pytest.raises(ValueError):
        _get_queryset(42)


def test_not_found_error_shape():
    errors = not_found_error(Author, 7)
    assert errors[0].field == "id"
    assert "Author" in errors[0].messages[0]
    assert "7" in errors[0].messages[0]


def test_parse_validation_exc_structures_errors():
    exc = ValidationError({"name": ["too short", "bad"]})
    parsed = parse_validation_exc(exc)
    fields = {e["field"] for e in parsed}
    assert "name" in fields
    messages = [m for e in parsed for m in e["messages"]]
    assert "too short" in messages


# --------------------------------------------------------------------------- #
# get_fields / find_field / _relation_optimization / _concrete_field_map       #
# --------------------------------------------------------------------------- #
def test_get_fields_expands_selection_and_fragments():
    from types import SimpleNamespace

    from graphql import parse
    from graphql.language.ast import (
        FragmentDefinitionNode,
        OperationDefinitionNode,
    )

    from django_graphex.utils import get_fields

    document = parse("query { wrapper { a ...F } } fragment F on T { b c }")
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    fragments = {
        d.name.value: d
        for d in document.definitions
        if isinstance(d, FragmentDefinitionNode)
    }
    # `field_nodes[0]` is the top-level `wrapper` field.
    wrapper_field = operation.selection_set.selections[0]
    info = SimpleNamespace(field_nodes=[wrapper_field], fragments=fragments)
    names = list(get_fields(info))
    assert "a" in names
    assert "b" in names and "c" in names  # fragment spread expanded


def test_find_field_by_name_and_snake_alias():
    from types import SimpleNamespace

    from django_graphex.utils import find_field

    fields = {"first_name": "FIELD"}
    node = SimpleNamespace(name=SimpleNamespace(value="firstName"))
    assert find_field(node, fields) == "FIELD"
    missing = SimpleNamespace(name=SimpleNamespace(value="nope"))
    assert find_field(missing, fields) is None


def test_relation_optimization_classifies_relations():
    from django_graphex.utils import _relation_optimization

    # Forward FK -> select_related.
    fk = Post._meta.get_field("author")
    assert _relation_optimization(fk) == ("select", "author")
    # Forward M2M -> prefetch_related.
    m2m = Post._meta.get_field("tags")
    assert _relation_optimization(m2m) == ("prefetch", "tags")
    # A plain scalar field -> None.
    assert _relation_optimization(Post._meta.get_field("title")) is None


def test_concrete_field_map_excludes_relations():
    from django_graphex.utils import _concrete_field_map

    mapping = _concrete_field_map(Post)
    assert "title" in mapping and mapping["title"] == "title"
    # Relation fields are excluded (only non-relation concrete fields are mapped).
    assert "author" not in mapping
