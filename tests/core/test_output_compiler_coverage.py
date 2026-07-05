"""R6 coverage — behavioral tests for "native.output_compiler" uncovered branches.

The scalar / FK / camelCase happy paths and the rank-6 unregistered-relation drop
are covered by "test_output_compiler.py"; the ArrayField / RangeField paths by
"test_output_postgres.py". This file pins the remaining helper branches by
asserting their ACTUAL behaviour:

- "_gfk_flat_resolver": "app_label" / "id" / "model_name" arms + null root.
- "_compile_generic_foreign_key": camel key + resolver reading the GFK accessor
  off an object AND off a dict.
- "_is_many_relation": "OneToOneRel" is to-ONE (False), reverse-FK is to-many.
- "_compile_choices_enum_field": a no-usable-choices field returns None.
- "_inner_output_type": choices base -> enum, MRO scalar map, unknown -> None.
- "_get_range_composite_type" bound resolver: object / dict / null root arms.
- "_to_graphql_field": scalar resolver dict-path; relation with no related model
  -> {}; choices field with no shared registry falls through to the scalar map.
- "compile_output_fields": "get_fields" exception fallback to concrete_fields.

Run: .venv/bin/python -m pytest \
    tests/core/test_output_compiler_coverage.py -q -o addopts=""
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.db import models  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLField,
    GraphQLInt,
    GraphQLObjectType,
    GraphQLString,
)

# ---------------------------------------------------------------------------
# Stub models
# ---------------------------------------------------------------------------


class OcAuthor(models.Model):
    """Minimal stub model used as an FK/O2O target in the coverage tests.

    Registered under the "tests" app label so it resolves cleanly without a
    matching database migration.
    """

    name = models.CharField(max_length=100)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class OcBook(models.Model):
    """Minimal stub model with a required FK to "OcAuthor".

    Registered under the "tests" app label so it resolves cleanly without a
    matching database migration.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        OcAuthor, on_delete=models.CASCADE, related_name="oc_books"
    )

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class OcProfile(models.Model):
    """Forward O2O target so "OcAuthor" gets a reverse OneToOneRel.

    Registered under the "tests" app label so it resolves cleanly without a
    matching database migration.
    """

    author = models.OneToOneField(
        OcAuthor, on_delete=models.CASCADE, related_name="oc_profile"
    )
    bio = models.TextField()

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class OcChoiceModel(models.Model):
    """Minimal stub model with a choices field, used for enum-compile tests.

    Registered under the "tests" app label so it resolves cleanly without a
    matching database migration.
    """

    status = models.CharField(max_length=10, choices=[("a", "A"), ("b", "B")])

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class StubRegistry:
    """Minimal registry stand-in used to compile output fields in isolation.

    Mirrors just enough of the real registry API ("get_compiled" and
    "register_compiled") for the output compiler to introspect already-
    compiled model types.
    """

    def __init__(self) -> None:
        self._compiled: dict = {}

    def get_compiled(self, model_cls: type) -> object | None:
        """Return the compiled GraphQL type registered for a model class.

        Args:
            model_cls: The Django model class to look up.

        Returns:
            compiled: The registered compiled type, or None if unregistered.
        """
        return self._compiled.get(model_cls)

    def register_compiled(self, model_cls: type, gql_type: object) -> None:
        """Register a compiled GraphQL type for a model class.

        Args:
            model_cls: The Django model class being registered.
            gql_type: The compiled GraphQL type to associate with it.
        """
        self._compiled[model_cls] = gql_type


# ---------------------------------------------------------------------------
# _gfk_flat_resolver — every attr arm + null root
# ---------------------------------------------------------------------------


def test_gfk_flat_resolver_app_label_arm() -> None:
    """The "app_label" resolver must read "root._meta.app_label".

    Contract: GFK flat sub-fields ship broken if the "app_label" arm reads
    the wrong attribute off the content-object root.
    """
    from django_graphex.core.output_compiler import _gfk_flat_resolver

    resolve = _gfk_flat_resolver("app_label")
    obj = OcAuthor()  # a real model instance → has ._meta.app_label == "tests"
    assert resolve(obj, None) == "tests"


def test_gfk_flat_resolver_id_arm() -> None:
    """The "id" resolver must read "root.id".

    Contract: GFK flat sub-fields ship broken if the "id" arm reads the
    wrong attribute off the content-object root.
    """
    from django_graphex.core.output_compiler import _gfk_flat_resolver

    resolve = _gfk_flat_resolver("id")
    obj = OcAuthor(id=7)
    assert resolve(obj, None) == 7


def test_gfk_flat_resolver_model_name_arm() -> None:
    """The "model_name" resolver must read "root._meta.model.__name__".

    Contract: GFK flat sub-fields ship broken if the "model_name" arm reads
    the wrong attribute off the content-object root.
    """
    from django_graphex.core.output_compiler import _gfk_flat_resolver

    resolve = _gfk_flat_resolver("model_name")
    assert resolve(OcAuthor(), None) == "OcAuthor"


def test_gfk_flat_resolver_null_root_yields_none() -> None:
    """A null content object must yield None for every GFK flat sub-field.

    Contract: null-safety on the GFK flat resolvers ships broken if a null
    root raises instead of returning None.
    """
    from django_graphex.core.output_compiler import _gfk_flat_resolver

    assert _gfk_flat_resolver("app_label")(None, None) is None


# ---------------------------------------------------------------------------
# _compile_generic_foreign_key — camel key + resolver (object and dict roots)
# ---------------------------------------------------------------------------


def test_compile_gfk_resolver_reads_object_and_dict() -> None:
    """The GFK field resolver must read the accessor off object AND dict roots.

    Contract: generic foreign key resolution ships broken if it only
    supports one of the two row shapes (ORM instance vs plain dict).
    """
    from django_graphex.core.output_compiler import _compile_generic_foreign_key

    class _FakeGFK:
        name = "content_object"

    field_map = _compile_generic_foreign_key(_FakeGFK())
    assert "contentObject" in field_map
    gql_field = field_map["contentObject"]
    assert isinstance(gql_field, GraphQLField)
    assert gql_field.type.name == "GenericForeignKeyType"

    resolve = gql_field.resolve
    sentinel = OcAuthor(id=1)

    class _Row:
        content_object = sentinel

    # object root
    assert resolve(_Row(), None) is sentinel
    # dict root
    assert resolve({"content_object": sentinel}, None) is sentinel
    # missing key → None
    assert resolve({}, None) is None


# ---------------------------------------------------------------------------
# _is_many_relation — reverse O2O excluded, reverse FK included
# ---------------------------------------------------------------------------


def test_is_many_relation_reverse_o2o_is_to_one() -> None:
    """A reverse "OneToOneRel" must classify as to-ONE (False), not to-many.

    Contract: relation cardinality detection ships broken if a reverse
    one-to-one field is wrongly treated as a to-many list field.
    """
    from django_graphex.core.output_compiler import _is_many_relation

    reverse_o2o = OcAuthor._meta.get_field("oc_profile")
    assert _is_many_relation(reverse_o2o) is False


def test_is_many_relation_reverse_fk_is_to_many() -> None:
    """A reverse FK ("ManyToOneRel") must classify as to-many (True).

    Contract: relation cardinality detection ships broken if a reverse
    foreign key is wrongly treated as a to-one scalar field.
    """
    from django_graphex.core.output_compiler import _is_many_relation

    reverse_fk = OcAuthor._meta.get_field("oc_books")
    assert _is_many_relation(reverse_fk) is True


# ---------------------------------------------------------------------------
# _compile_choices_enum_field — no usable choices → None
# ---------------------------------------------------------------------------


def test_compile_choices_enum_field_returns_none_without_choices() -> None:
    """A field with no usable choices must return None so the caller falls back.

    Contract: enum compilation ships broken if a plain (non-choices) field
    is wrongly wrapped as an enum instead of signaling "no enum here".
    """
    from django_graphex.core.output_compiler import _compile_choices_enum_field
    from django_graphex.registry import get_global_registry

    # A plain CharField with no choices → build_choices_enum_type returns None.
    plain = OcBook._meta.get_field("title")
    assert _compile_choices_enum_field(plain, get_global_registry()) is None


# ---------------------------------------------------------------------------
# _inner_output_type — choices enum, MRO scalar map, unknown → None
# ---------------------------------------------------------------------------


def test_inner_output_type_scalar_via_mro() -> None:
    """A plain CharField base field maps through "DJANGO_TO_GQL" to String.

    Contract: scalar inner-type resolution ships broken if the MRO walk
    over the scalar map stops matching a plain CharField.
    """
    from django_graphex.core.output_compiler import _inner_output_type

    char = OcBook._meta.get_field("title")
    assert _inner_output_type(char, StubRegistry(), None) is GraphQLString


def test_inner_output_type_choices_base_returns_enum() -> None:
    """A bound choices base field resolves to the shared "GraphQLEnumType".

    Contract: choices-enum inner-type resolution ships broken if a choices
    field falls through to the scalar map instead of the shared enum.
    """
    from graphql import GraphQLEnumType

    from django_graphex.core.output_compiler import _inner_output_type
    from django_graphex.registry import get_global_registry

    status = OcChoiceModel._meta.get_field("status")
    result = _inner_output_type(status, StubRegistry(), get_global_registry())
    assert isinstance(result, GraphQLEnumType)


def test_inner_output_type_unknown_returns_none() -> None:
    """A field whose class is in no MRO mapping must yield None (drop).

    Contract: unrecognized field types ship broken if resolution raises or
    returns a bogus type instead of signaling "drop this field".
    """
    from django_graphex.core.output_compiler import _inner_output_type

    class _Unknown:
        choices = None
        model = None

        def get_internal_type(self):
            return "TotallyUnknownField"

    assert _inner_output_type(_Unknown(), StubRegistry(), None) is None


# ---------------------------------------------------------------------------
# _get_range_composite_type bound resolver — object / dict / null arms
# ---------------------------------------------------------------------------


def test_range_composite_bound_resolver_arms() -> None:
    """The composite Range resolver reads ".lower"/".upper" off object/dict/null.

    Contract: the bound Range composite resolvers ship broken if they stop
    supporting any of the three root shapes they must handle.
    """
    from django_graphex.core.output_compiler import _get_range_composite_type

    composite = _get_range_composite_type(GraphQLInt)
    assert isinstance(composite, GraphQLObjectType)
    lower_resolve = composite.fields["lower"].resolve
    upper_resolve = composite.fields["upper"].resolve

    class _Range:
        lower = 1
        upper = 9

    # object root
    assert lower_resolve(_Range(), None) == 1
    assert upper_resolve(_Range(), None) == 9
    # dict root
    assert lower_resolve({"lower": 3, "upper": 4}, None) == 3
    # null root → None
    assert lower_resolve(None, None) is None


def test_range_composite_type_is_memoized_per_bound_scalar() -> None:
    """The composite Range type is cached per bound scalar (same instance reused).

    Contract: Range composite-type memoization ships broken if repeated
    calls for the same bound scalar rebuild a new GraphQL type each time.
    """
    from django_graphex.core.output_compiler import _get_range_composite_type

    first = _get_range_composite_type(GraphQLInt)
    second = _get_range_composite_type(GraphQLInt)
    assert first is second


# ---------------------------------------------------------------------------
# _to_graphql_field — scalar resolver dict-path, no related model, choices
# fall-through without shared registry
# ---------------------------------------------------------------------------


def test_scalar_field_resolver_reads_dict_and_object() -> None:
    """The scalar default resolver reads the value off a dict AND an object root.

    Contract: the default scalar field resolver ships broken if it stops
    supporting either the dict-row or the ORM-instance row shape.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    field_map = _to_graphql_field(OcBook._meta.get_field("title"), StubRegistry())
    resolve = field_map["title"].resolve
    # dict root
    assert resolve({"title": "GEB"}, None) == "GEB"

    # object root
    class _Row:
        title = "SICP"

    assert resolve(_Row(), None) == "SICP"


def test_relation_with_no_related_model_returns_empty() -> None:
    """A relation field whose related model resolves to None must yield {}.

    Contract: relation compilation ships broken if it crashes (instead of
    dropping the field) when the related model cannot be resolved.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    class _RelNoTarget:
        name = "thing"
        is_relation = True
        related_model = None
        field = None  # no reverse field either

        def get_internal_type(self):
            # Not an Array/Range field — flow reaches the relation arm.
            return "ForeignKey"

    assert _to_graphql_field(_RelNoTarget(), StubRegistry()) == {}


def test_choices_field_without_shared_registry_falls_through_to_scalar() -> None:
    """A choices field with graphene_registry=None maps as the scalar, not an enum.

    The choices arm is gated on "graphene_registry is not None"; with no
    shared registry it must fall through to the "DJANGO_TO_GQL" scalar
    (String here).
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    field_map = _to_graphql_field(
        OcChoiceModel._meta.get_field("status"), StubRegistry(), graphene_registry=None
    )
    assert "status" in field_map
    gql_type = field_map["status"].type
    # plain CharField → GraphQLString (the enum branch was skipped).
    assert gql_type is GraphQLString


# ---------------------------------------------------------------------------
# _compile_choices_enum_field — resolver dict/object arms
# ---------------------------------------------------------------------------


def test_choices_enum_field_resolver_reads_dict_and_object() -> None:
    """The choices-enum field default resolver reads the value off dict/object roots.

    Contract: the choices-enum field resolver ships broken if it stops
    supporting either the dict-row or the ORM-instance row shape.
    """
    from graphql import GraphQLEnumType

    from django_graphex.core.output_compiler import _compile_choices_enum_field
    from django_graphex.registry import get_global_registry

    status = OcChoiceModel._meta.get_field("status")
    gql_field = _compile_choices_enum_field(status, get_global_registry())
    assert gql_field is not None
    assert isinstance(gql_field.type, GraphQLEnumType)

    resolve = gql_field.resolve
    # dict root
    assert resolve({"status": "a"}, None) == "a"

    # object root
    class _Row:
        status = "b"

    assert resolve(_Row(), None) == "b"


# ---------------------------------------------------------------------------
# _to_graphql_field — to-ONE relation resolver (registered target)
# ---------------------------------------------------------------------------


def test_to_one_relation_resolver_reads_dict_and_object() -> None:
    """A registered to-ONE FK compiles a resolver reading the accessor off the row.

    Contract: to-ONE relation resolution ships broken if the compiled
    resolver stops reading the FK accessor off both dict and object rows.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    registry = StubRegistry()
    author_type = GraphQLObjectType("OcAuthor", fields=lambda: {})
    registry.register_compiled(OcAuthor, author_type)

    fk = OcBook._meta.get_field("author")
    field_map = _to_graphql_field(fk, registry)
    assert "author" in field_map
    resolve = field_map["author"].resolve

    sentinel = OcAuthor(id=1)

    class _Row:
        author = sentinel

    # object root
    assert resolve(_Row(), None) is sentinel
    # dict root
    assert resolve({"author": sentinel}, None) is sentinel
    # missing key → None
    assert resolve({}, None) is None


# ---------------------------------------------------------------------------
# compile_output_fields — get_fields exception fallback to concrete_fields
# ---------------------------------------------------------------------------


def test_compile_output_fields_get_fields_exception_fallback() -> None:
    """When get_fields raises, the compiler falls back to concrete_fields.

    Contract: output-field compilation ships broken if it stops tolerating
    a raising "get_fields" and no longer falls back to "concrete_fields".

    Raises:
        RuntimeError: Raised by the fake "get_fields" stub below to force
            the fallback path; caught internally by the compiler under test.
    """
    from django_graphex.core import output_compiler

    char = OcBook._meta.get_field("title")

    class _FakeMeta:
        concrete_fields = [char]

        def get_fields(self, include_parents=False):
            raise RuntimeError("boom — exercise the fallback arm")

    class _FakeModel:
        _meta = _FakeMeta()

    fields = output_compiler.compile_output_fields(_FakeModel, StubRegistry())
    # The concrete field still compiled via the fallback path.
    assert "title" in fields


# ---------------------------------------------------------------------------
# _compile_array_field / _compile_range_field — resolver arms + inner-None drop
# ---------------------------------------------------------------------------


class _FakeArrayField(models.Field):
    """psycopg-free stand-in for a PostgreSQL ArrayField (output compiler only)."""

    def __init__(self, base_field, **kwargs):
        self.base_field = base_field
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self):
        return "ArrayField"


def test_compile_array_field_resolver_reads_dict_and_object() -> None:
    """The compiled ArrayField resolver reads the accessor off dict/object roots.

    Contract: ArrayField resolution ships broken if the compiled resolver
    stops supporting either the dict-row or the ORM-instance row shape.
    """
    from django_graphex.core.output_compiler import _compile_array_field

    field = _FakeArrayField(models.CharField(max_length=20))
    field.name = "tags"

    field_map = _compile_array_field(field, StubRegistry(), None)
    resolve = field_map["tags"].resolve
    # dict root
    assert resolve({"tags": ["a", "b"]}, None) == ["a", "b"]

    # object root
    class _Row:
        tags = ["x"]

    assert resolve(_Row(), None) == ["x"]


def test_compile_array_field_with_unknown_inner_is_dropped() -> None:
    """An ArrayField whose base field maps to nothing must be dropped (empty dict).

    Contract: ArrayField compilation ships broken if an unmappable base
    field crashes instead of dropping the field silently.
    """
    from django_graphex.core.output_compiler import _compile_array_field

    class _UnknownBase:
        choices = None
        model = None

        def get_internal_type(self):
            return "UnknownBase"

    field = _FakeArrayField.__new__(_FakeArrayField)
    field.base_field = _UnknownBase()
    field.name = "weird"

    assert _compile_array_field(field, StubRegistry(), None) == {}


class _FakeRangeField(models.Field):
    """psycopg-free stand-in for a PostgreSQL IntegerRangeField."""

    def __init__(self, **kwargs):
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self):
        return "IntegerRangeField"


def test_compile_range_field_resolver_reads_dict_and_object() -> None:
    """The compiled RangeField resolver reads the accessor off dict/object roots.

    Contract: RangeField resolution ships broken if the compiled resolver
    stops supporting either the dict-row or the ORM-instance row shape.
    """
    from django_graphex.core.output_compiler import _compile_range_field

    field = _FakeRangeField()
    field.name = "age_range"

    field_map = _compile_range_field(field)
    assert "ageRange" in field_map
    # The field resolver returns the range OBJECT read off the row by field name;
    # the composite's own lower/upper resolvers then read the bounds.
    resolve = field_map["ageRange"].resolve

    class _Range:
        lower = 1
        upper = 9

    class _Row:
        age_range = _Range()

    # object root → returns the range object verbatim.
    assert resolve(_Row(), None).lower == 1
    # dict root → returns the value under the field name.
    payload = {"lower": 3, "upper": 4}
    assert resolve({"age_range": payload}, None) == payload


def test_compile_output_fields_skips_unnamed_field() -> None:
    """A field with neither name nor attname must be skipped (continue).

    Contract: output-field compilation ships broken if an unnamed field
    crashes the loop instead of being silently skipped.
    """
    from django_graphex.core import output_compiler

    class _Nameless:
        is_relation = False

        def get_internal_type(self):
            return "CharField"

    char = OcBook._meta.get_field("title")

    class _FakeMeta:
        def get_fields(self, include_parents=False):
            return [_Nameless(), char]

    class _FakeModel:
        _meta = _FakeMeta()

    fields = output_compiler.compile_output_fields(_FakeModel, StubRegistry())
    # The nameless field produced no entry; the named one did.
    assert "title" in fields
    assert len(fields) == 1
