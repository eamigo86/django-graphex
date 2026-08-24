# -*- coding: utf-8 -*-
"""Coverage for the standalone helpers in "django_graphex.utils".

These hit the "get_obj" / "create_obj" error paths,
"get_extra_filters", "get_related_fields", "get_reverse_fields",
"is_required", "get_type", "_get_queryset" and "parse_validation_exc"
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

from .models import Author, BasicModel, Comment, Post


# --------------------------------------------------------------------------- #
# get_obj / create_obj                                                         #
# --------------------------------------------------------------------------- #
class GetCreateObjTest(TestCase):
    """Behavior of "get_obj" and "create_obj" across success and error paths.

    Covers found/missing/unknown-model lookups and creation success/failure.
    """

    def test_get_obj_returns_instance(self) -> None:
        """Ship-broken contract: an existing primary key must resolve to the
        matching model instance.
        """
        obj = BasicModel.objects.create(text="hi")
        self.assertEqual(get_obj("tests", "BasicModel", obj.pk), obj)

    def test_get_obj_missing_returns_none(self) -> None:
        """Ship-broken contract: a primary key with no matching row must
        resolve to None, not raise.
        """
        self.assertIsNone(get_obj("tests", "BasicModel", 999999))

    def test_get_obj_unknown_model_returns_none(self) -> None:
        """Ship-broken contract: an unknown app label or model name must
        resolve to None instead of crashing.

        Regression: an unknown app/model raised LookupError, and the unbound
        "model" name in the "except model.DoesNotExist" clause then crashed
        with UnboundLocalError instead of returning None.
        """
        self.assertIsNone(get_obj("tests", "NoSuchModel", 1))
        self.assertIsNone(get_obj("no_such_app", "Whatever", 1))

    def test_create_obj_creates_and_saves(self) -> None:
        """Ship-broken contract: "create_obj" must persist a new instance
        with the given field values.
        """
        obj = create_obj(BasicModel, text="made")
        self.assertEqual(obj.text, "made")
        self.assertTrue(BasicModel.objects.filter(pk=obj.pk).exists())

    def test_create_obj_from_string_model(self) -> None:
        """Ship-broken contract: "create_obj" must accept a dotted
        "app_label.ModelName" string in place of the model class.
        """
        obj = create_obj("tests.BasicModel", text="strmade")
        self.assertEqual(obj.text, "strmade")

    def test_create_obj_invalid_model_returns_assert_message(self) -> None:
        """Ship-broken contract: passing a non-Django-model class must make
        "create_obj" return the assertion message as a string, not raise.
        """
        # The assert fires inside the try; the broad except returns its message.
        result = create_obj(object)
        self.assertIsInstance(result, str)
        self.assertIn("valid Django Model", result)

    def test_create_obj_validation_failure_reraises(self) -> None:
        """Ship-broken contract: a model-validation failure during
        "create_obj" must propagate as "ValidationError", not be swallowed.
        """
        # BasicModel.text is required (no blank) -> full_clean raises, re-raised.
        with self.assertRaises(ValidationError):
            create_obj(BasicModel, text="")


# --------------------------------------------------------------------------- #
# get_extra_filters / get_related_fields / get_reverse_fields                  #
# --------------------------------------------------------------------------- #
class RelationHelpersTest(TestCase):
    """Behavior of the relation-introspection helpers.

    Covers "get_extra_filters", "get_related_fields", and "get_reverse_fields".
    """

    def test_get_extra_filters_maps_relation_to_root(self) -> None:
        """Ship-broken contract: "get_extra_filters" must map a related
        instance to the foreign-key field that points at it.

        "Comment" is used rather than "Post" because "Post" reaches "Author"
        through BOTH "author" and "co_authors": that pair is ambiguous and is
        now refused outright (see the audit regression suite), where before it
        produced a conjunction that scoped every nested list to the empty set.
        """
        author = Author.objects.create(name="A")
        post = Post.objects.create(title="T", author=author)
        filters = get_extra_filters(post, Comment)
        self.assertEqual(filters, {"post": post})

    def test_get_extra_filters_empty_when_unrelated(self) -> None:
        """Ship-broken contract: "get_extra_filters" must return an empty
        mapping when the target model has no relation to the given instance.
        """
        author = Author.objects.create(name="A")
        # BasicModel has no FK to Author.
        self.assertEqual(get_extra_filters(author, BasicModel), {})

    def test_get_related_fields_lists_relations(self) -> None:
        """Ship-broken contract: "get_related_fields" must list relation
        field names and exclude plain scalar fields.
        """
        related = get_related_fields(Post)
        self.assertIn("author", related)
        self.assertIn("tags", related)
        self.assertNotIn("title", related)

    def test_get_reverse_fields_is_iterable(self) -> None:
        """Ship-broken contract: "get_reverse_fields" must run to completion
        and yield a list, even when there is nothing to report.
        """
        # Exercises the generator body; on modern Django the rel/related lookup
        # yields nothing, but the function must still run without error.
        result = list(get_reverse_fields(Author))
        self.assertIsInstance(result, list)


# --------------------------------------------------------------------------- #
# is_required / get_type / _get_queryset / not_found_error / parse_validation  #
# --------------------------------------------------------------------------- #
def test_is_required_true_for_no_blank_no_default() -> None:
    """Ship-broken contract: a field with neither "blank" nor a default must
    be reported as required.
    """
    field = BasicModel._meta.get_field("text")
    assert is_required(field) is True


def test_is_required_false_for_default_field() -> None:
    """Ship-broken contract: a field carrying a default value must be
    reported as not required.
    """
    # Author.bio has default="" -> not required.
    assert is_required(Author._meta.get_field("bio")) is False


def test_is_required_reverse_relation_uses_field_fallback() -> None:
    """Ship-broken contract: a reverse relation (no "blank" attribute of its
    own) must fall back to its underlying "field" to derive requiredness.
    """
    # A reverse relation has no `blank` attr -> the function reads `.field` and
    # derives blank/default from it. Post.author is a non-null FK with no
    # default, so the reverse relation resolves to required.
    reverse = Author._meta.get_field("posts")  # ManyToOneRel
    assert is_required(reverse) is True


def test_is_required_on_object_without_attrs_returns_false() -> None:
    """Ship-broken contract: an object lacking "blank"/"default"/"field"
    attributes must resolve to False, not raise AttributeError.
    """
    # An object lacking blank/default/field -> AttributeError-safe False.
    assert is_required(object()) is False


def test_get_type_unwraps_list_and_nonnull() -> None:
    """Ship-broken contract: "get_type" must strip GraphQLNonNull and
    GraphQLList wrappers down to the underlying named type.
    """
    wrapped = GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString)))
    assert get_type(wrapped) is GraphQLString


def test_get_queryset_from_model_manager_queryset() -> None:
    """Ship-broken contract: "_get_queryset" must accept a model class, a
    manager, or an existing queryset, always returning a queryset for the
    right model -- and a CLONE, never the caller's own instance, so a
    long-lived "Meta.queryset" can never accumulate a result cache.
    """
    from_model = _get_queryset(Author)
    assert from_model.model is Author
    from_manager = _get_queryset(Author.objects)
    assert from_manager.model is Author
    qs = Author.objects.all()
    from_queryset = _get_queryset(qs)
    assert from_queryset is not qs
    assert from_queryset.model is Author


def test_get_queryset_invalid_raises() -> None:
    """Ship-broken contract: an unsupported input type must make
    "_get_queryset" raise ValueError.
    """
    with pytest.raises(ValueError):
        _get_queryset(42)


def test_not_found_error_shape() -> None:
    """Ship-broken contract: "not_found_error" must produce an "id"-scoped
    error whose message names both the model and the missing identifier.
    """
    errors = not_found_error(Author, 7)
    assert errors[0].field == "id"
    assert "Author" in errors[0].messages[0]
    assert "7" in errors[0].messages[0]


def test_parse_validation_exc_structures_errors() -> None:
    """Ship-broken contract: "parse_validation_exc" must restructure a
    Django "ValidationError" into per-field entries preserving the original
    messages.
    """
    exc = ValidationError({"name": ["too short", "bad"]})
    parsed = parse_validation_exc(exc)
    fields = {e["field"] for e in parsed}
    assert "name" in fields
    messages = [m for e in parsed for m in e["messages"]]
    assert "too short" in messages


# --------------------------------------------------------------------------- #
# get_fields / find_field / _relation_optimization / _concrete_field_map       #
# --------------------------------------------------------------------------- #
def test_get_fields_expands_selection_and_fragments() -> None:
    """Ship-broken contract: "get_fields" must list directly selected field
    names and expand fragment spreads into their constituent field names.
    """
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


def test_find_field_by_name_and_snake_alias() -> None:
    """Ship-broken contract: "find_field" must resolve a camelCase GraphQL
    field name to its snake_case mapping entry, and return None when missing.
    """
    from types import SimpleNamespace

    from django_graphex.utils import find_field

    fields = {"first_name": "FIELD"}
    node = SimpleNamespace(name=SimpleNamespace(value="firstName"))
    assert find_field(node, fields) == "FIELD"
    missing = SimpleNamespace(name=SimpleNamespace(value="nope"))
    assert find_field(missing, fields) is None


def test_relation_optimization_classifies_relations() -> None:
    """Ship-broken contract: "_relation_optimization" must classify a
    forward FK as select_related, a forward M2M as prefetch_related, and a
    plain scalar field as neither (None).
    """
    from django_graphex.utils import _relation_optimization

    # Forward FK -> select_related.
    fk = Post._meta.get_field("author")
    assert _relation_optimization(fk) == ("select", "author")
    # Forward M2M -> prefetch_related.
    m2m = Post._meta.get_field("tags")
    assert _relation_optimization(m2m) == ("prefetch", "tags")
    # A plain scalar field -> None.
    assert _relation_optimization(Post._meta.get_field("title")) is None


def test_concrete_field_map_excludes_relations() -> None:
    """Ship-broken contract: "_concrete_field_map" must map plain scalar
    field names to themselves while excluding relation fields entirely.
    """
    from django_graphex.utils import _concrete_field_map

    mapping = _concrete_field_map(Post)
    assert "title" in mapping and mapping["title"] == "title"
    # Relation fields are excluded (only non-relation concrete fields are mapped).
    assert "author" not in mapping
