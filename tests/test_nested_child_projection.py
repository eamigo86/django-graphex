"""A nested child input must be the CHILD's own declared input surface.

"Meta.nested_fields" never derived the child's input from the child's declared
host. It minted an unprojected input straight from the Django model and parked
it in the shared "(child_model, op)" registry slot, so the outcome depended on
which class was declared first:

* parent declared first -- the minted generic ignored the child's
  "exclude_fields", and the child's OWN mutation then reused that same poisoned
  slot, so a field the child host excluded became writable through both the
  parent's nested payload and the child's own root field,
* child declared first -- the projection survived, but the parent reused the
  child's own input, whose back-reference foreign key is still required, so
  graphql-core rejected every nested create before a resolver ran.

Invariants asserted here, in BOTH declaration orders:

* the nested element input carries the child host's projection,
* the child's own input keeps its projection and its required back-reference
  foreign key,
* a nested create works over the wire,
* one child nested under two parents relaxes each parent's own foreign key,
* a nested-only parent never writes the child's shared registry slot.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import RequestFactory
from graphql import GraphQLField, GraphQLSchema, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedProjEntry,
    NestedProjJournal,
    NestedProjLeft,
    NestedProjLoose,
    NestedProjLooseItem,
    NestedProjNote,
    NestedProjPost,
    NestedProjRight,
    NestedProjShared,
)


# --------------------------------------------------------------------------- #
# Hosts, declared at MODULE level so the two declaration orders are fixed.     #
# pytest-randomly shuffles test order, so declaring them inside the test bodies #
# would make "which host was declared first" a coin flip.                       #
# --------------------------------------------------------------------------- #
class NestedProjPostType(DjangoModelType):
    """PARENT DECLARED FIRST: the nesting host comes before the child's own.

    Declaration order is the only variable in this module, and this is the half that
    poisoned the shared slot: the parent materialised a child input before any child
    host existed to project it.
    """

    class Meta:
        """Bind the type to "NestedProjPost" with "entries" nested.

        The "nested_fields" entry is what mints the child element input; declaring no
        projection here keeps the child's own host the only source of one.
        """

        model = NestedProjPost
        nested_fields = {"entries": NestedProjEntry}


class NestedProjEntryMutation(DjangoModelMutation):
    """The child's own mutation, declared AFTER its nesting parent.

    This is the class that used to inherit the parent's unprojected input out of the
    shared registry slot, which is how "secret" became writable on the child's own root
    field.
    """

    class Meta:
        """Bind the mutation to "NestedProjEntry", hiding "secret".

        "exclude_fields" is the declaration BOTH surfaces have to honour: the child's
        own input and the parent's nested element.
        """

        model = NestedProjEntry
        model_operations = ("create",)
        exclude_fields = ("secret",)


class NestedProjNoteType(DjangoModelType):
    """CHILD DECLARED FIRST: the child's own host comes before the parent.

    The mirror order, with the opposite failure: the projection survived and it was the
    required back-reference foreign key the parent inherited with it.
    """

    class Meta:
        """Bind the type to "NestedProjNote", hiding "private".

        Declared before any parent exists, so the child's input is already in the
        registry when the nesting host is compiled.
        """

        model = NestedProjNote
        exclude_fields = ("private",)


class NestedProjJournalMutation(DjangoModelMutation):
    """The nesting parent, declared AFTER the child's own host.

    Its element must be DERIVED from the child host rather than reused from it, which is
    exactly the distinction the child-first order tests.
    """

    class Meta:
        """Bind the mutation to "NestedProjJournal" with "notes" nested.

        "model_operations" narrows the host to "create" so the schema carries the one
        nested surface under test and nothing else.
        """

        model = NestedProjJournal
        model_operations = ("create",)
        nested_fields = {"notes": NestedProjNote}


class NestedProjLeftMutation(DjangoModelMutation):
    """One of two parents nesting the SAME child model.

    "NestedProjShared" carries a required foreign key to each parent, so only a per-
    parent element type can relax the right one.
    """

    class Meta:
        """Bind the mutation to "NestedProjLeft" with "shared" nested.

        Paired with the right-hand host below; both nest the same child, which is what
        forces two distinct element types out of one model.
        """

        model = NestedProjLeft
        model_operations = ("create",)
        nested_fields = {"shared": NestedProjShared}


class NestedProjRightMutation(DjangoModelMutation):
    """The other parent nesting the same child model.

    Declared second on purpose: if the element type were shared, this is the host that
    would inherit the wrong parent's relaxation.
    """

    class Meta:
        """Bind the mutation to "NestedProjRight" with "shared" nested.

        Identical to the left host apart from the model, so any difference the tests
        observe comes from the nesting parent alone.
        """

        model = NestedProjRight
        model_operations = ("create",)
        nested_fields = {"shared": NestedProjShared}


class NestedProjLooseMutation(DjangoModelMutation):
    """A parent nesting a child that declares no host of its own.

    With no child host to overwrite the shared slot afterwards, registry pollution
    leaves no trace in the schema -- it can only be caught by inspecting the registry
    directly.
    """

    class Meta:
        """Bind the mutation to "NestedProjLoose" with "items" nested.

        The unprojected half of the memo pair; the sibling host below declares
        "only_fields" so the two parent inputs keep distinct names.
        """

        model = NestedProjLoose
        model_operations = ("create",)
        nested_fields = {"items": NestedProjLooseItem}


class NestedProjLooseProjectedMutation(DjangoModelMutation):
    """A SECOND host on the same parent model, nesting the same child.

    Its projection keeps the parent input names distinct; the child element
    type is shared, which is what pins the memo key.
    """

    class Meta:
        """Bind the mutation to "NestedProjLoose", projected, with "items" nested.

        Same model and same nested child as the plain host, so the memo key is exercised
        by two hosts that agree on everything the child element is derived from.
        """

        model = NestedProjLoose
        model_operations = ("create",)
        only_fields = ("title", "items")
        nested_fields = {"items": NestedProjLooseItem}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
class _Q(ObjectType):
    """Minimal native query root so every schema has at least one field."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = field(GraphQLString)


def _request() -> Any:
    """Build a real request context for execution (the resolver reads ".META").

    Returns:
        A Django test request suitable for GraphQL "context_value".
    """
    return RequestFactory().post("/graphql/", content_type="application/json")


def _schema(**mutation_fields: Any) -> GraphQLSchema:
    """Assemble a native schema from a map of mutation fields.

    Args:
        **mutation_fields: The mutation root's fields, keyed by field name.

    Returns:
        The assembled graphql-core schema.
    """
    mutation_cls = type("_M", (ObjectType,), {"__test__": False, **mutation_fields})
    return DjangoGraphQLSchema(query=_Q, mutation=mutation_cls).graphql_schema


def _input_of(gql_field: GraphQLField) -> Any:
    """Unwrap a mutation field's first argument to its named input type.

    Args:
        gql_field: The mutation field whose input argument is unwrapped.

    Returns:
        The named input object type behind the argument.
    """
    arg_type = gql_field.args[next(iter(gql_field.args))].type
    return arg_type.of_type if hasattr(arg_type, "of_type") else arg_type


def _element(input_type: Any, field_name: str) -> Any:
    """Unwrap a nested input field to its element input type.

    Args:
        input_type: The parent input object type.
        field_name: The nested field to unwrap (list or single object).

    Returns:
        The named child input object type.
    """
    unwrapped = input_type.fields[field_name].type
    while hasattr(unwrapped, "of_type"):
        unwrapped = unwrapped.of_type
    return unwrapped


def _arg_name(gql_field: GraphQLField) -> str:
    """Return a mutation field's single input argument name.

    Args:
        gql_field: The mutation field to read.

    Returns:
        The wire name of its input argument.
    """
    return next(iter(gql_field.args))


# --------------------------------------------------------------------------- #
# 1. Parent declared FIRST                                                     #
# --------------------------------------------------------------------------- #
class TestParentDeclaredFirst:
    """The child's declared projection must survive a parent-first declaration.

    This is the order that poisoned the shared registry slot: the parent minted a
    generic child input first and the child's own mutation reused it, so the excluded
    column became writable on BOTH surfaces.
    """

    def _schema(self) -> GraphQLSchema:
        """Assemble the parent-first schema.

        Returns:
            A schema exposing both the parent's nested create and the child's own.
        """
        return _schema(
            post_create=NestedProjPostType.CreateField(),
            entry_create=NestedProjEntryMutation.CreateField(),
        )

    def test_nested_element_drops_the_childs_excluded_field(self) -> None:
        """The parent's nested element input honours the child host's "exclude_fields".

        This test breaks if the nested child input is minted from the bare
        Django model instead of the child's declared host, which puts every
        writable column -- "secret" included -- on the parent's payload.
        """
        gql = self._schema()
        element = _element(_input_of(gql.mutation_type.fields["postCreate"]), "entries")

        assert "headline" in element.fields
        assert "secret" not in element.fields
        # The back-reference FK stays optional: the nested writer injects it.
        assert str(element.fields["post"].type) == "ID"

    def test_child_own_input_keeps_its_projection(self) -> None:
        """The child's OWN mutation input still hides the field its host excluded.

        This test breaks if the parent's nested build registers an unprojected
        input in the shared "(child, op)" slot, which the child's own mutation
        then reuses.
        """
        gql = self._schema()
        child_input = _input_of(gql.mutation_type.fields["entryCreate"])

        assert "headline" in child_input.fields
        assert "secret" not in child_input.fields

    def test_child_own_input_keeps_the_required_fk(self) -> None:
        """The child's own create input still requires its parent foreign key.

        This test breaks if the parent's nested build leaks its back-reference
        relaxation into the child's standalone surface.
        """
        gql = self._schema()
        child_input = _input_of(gql.mutation_type.fields["entryCreate"])

        assert str(child_input.fields["post"].type) == "ID!"

    @pytest.mark.django_db()
    def test_child_own_mutation_refuses_the_excluded_field_on_the_wire(self) -> None:
        """Writing the excluded field through the child's own mutation is rejected.

        This test breaks if the poisoned registry slot makes the excluded
        column settable: the write is accepted and committed.
        """
        gql = self._schema()
        post = NestedProjPost.objects.create(title="p")
        entry_create = gql.mutation_type.fields["entryCreate"]
        query = """
            mutation {{
              entryCreate({arg}: {{
                post: "{pk}"
                headline: "h"
                secret: "PWNED"
              }}) {{ ok }}
            }}
        """.format(arg=_arg_name(entry_create), pk=post.pk)

        result = graphql_sync(gql, query, context_value=_request())

        assert result.errors
        assert "secret" in str(result.errors[0])
        assert NestedProjEntry.objects.count() == 0


# --------------------------------------------------------------------------- #
# 2. Child declared FIRST                                                      #
# --------------------------------------------------------------------------- #
class TestChildDeclaredFirst:
    """A child-first declaration must produce a nested surface that WORKS.

    The opposite order kept the projection but reused the child's own input verbatim,
    whose required back-reference foreign key made every nested create unsatisfiable
    before a resolver could run.
    """

    def _schema(self) -> GraphQLSchema:
        """Assemble the child-first schema.

        Returns:
            A schema exposing the parent's nested create.
        """
        return _schema(journal_create=NestedProjJournalMutation.CreateField())

    def test_nested_element_drops_the_excluded_field(self) -> None:
        """The nested element still honours the child host's projection.

        This test breaks if the parent's copy of the child input stops being
        derived from the child's declared host.
        """
        gql = self._schema()
        element = _element(
            _input_of(gql.mutation_type.fields["journalCreate"]), "notes"
        )

        assert "text" in element.fields
        assert "private" not in element.fields

    def test_nested_element_relaxes_the_back_reference_fk(self) -> None:
        """The nested element's foreign key back to the parent is optional.

        This test breaks if the parent reuses the child's OWN input, whose
        required "journal: ID!" makes every nested create unsatisfiable.
        """
        gql = self._schema()
        element = _element(
            _input_of(gql.mutation_type.fields["journalCreate"]), "notes"
        )

        assert str(element.fields["journal"].type) == "ID"

    @pytest.mark.django_db()
    def test_nested_create_persists_over_the_wire(self) -> None:
        """A nested create declared child-first actually works end to end.

        This test breaks if the nested element keeps the required
        back-reference foreign key: graphql-core rejects the payload before
        any resolver runs.
        """
        gql = self._schema()
        journal_create = gql.mutation_type.fields["journalCreate"]
        query = """
            mutation {{
              journalCreate({arg}: {{
                title: "j"
                notes: [{{ text: "n" }}]
              }}) {{ ok errors {{ field messages }} }}
            }}
        """.format(arg=_arg_name(journal_create))

        result = graphql_sync(gql, query, context_value=_request())

        assert result.errors is None, result.errors
        assert result.data["journalCreate"]["ok"], result.data
        assert NestedProjNote.objects.get().text == "n"


# --------------------------------------------------------------------------- #
# 3. One child, two parents                                                    #
# --------------------------------------------------------------------------- #
class TestOneChildTwoParents:
    """Each parent's nested element must relax ITS OWN back-reference.

    A single element type shared by two parents can only relax one foreign key, leaving
    the other parent's nested create demanding a value its writer was going to inject
    anyway.
    """

    def test_each_parent_relaxes_only_its_own_fk(self) -> None:
        """A child nested under two parents gets one element type per parent.

        This test breaks if both parents share a single child input: the first
        parent's relaxation is the only one applied, so the second parent's
        nested create demands a foreign key the writer injects anyway.
        """
        gql = _schema(
            left_create=NestedProjLeftMutation.CreateField(),
            right_create=NestedProjRightMutation.CreateField(),
        )
        under_left = _element(
            _input_of(gql.mutation_type.fields["leftCreate"]), "shared"
        )
        under_right = _element(
            _input_of(gql.mutation_type.fields["rightCreate"]), "shared"
        )

        assert str(under_left.fields["left"].type) == "ID"
        assert str(under_left.fields["right"].type) == "ID!"
        assert str(under_right.fields["right"].type) == "ID"
        assert str(under_right.fields["left"].type) == "ID!"


# --------------------------------------------------------------------------- #
# 4. Registry hygiene and the memo key                                         #
# --------------------------------------------------------------------------- #
class TestRegistryHygiene:
    """The nested build must never touch the shared "(child, op)" slot.

    Slot pollution is the root cause behind the parent-first failure and it is invisible
    from the schema: only the registry shows whether a later declaration will inherit a
    type it never asked for.
    """

    def test_nested_only_parent_leaves_the_childs_slot_empty(self) -> None:
        """Building a nested parent never registers a type for the child model.

        This test breaks if the nested path mints a child input into the
        shared registry slot, which is what let a later declaration reuse it.
        """
        _schema(loose_create=NestedProjLooseMutation.CreateField())

        registry = get_global_registry()
        assert (
            registry.get_type_for_model(NestedProjLooseItem, for_input="create") is None
        )

    def test_two_hosts_on_one_parent_share_one_child_element(self) -> None:
        """Two hosts on the same parent model reuse one child element type.

        This test breaks if the per-parent child input is not memoized: two
        same-named types reach the schema and assembly fails outright.
        """
        gql = _schema(
            loose_create=NestedProjLooseMutation.CreateField(),
            loose_projected_create=NestedProjLooseProjectedMutation.CreateField(),
        )
        plain = _element(_input_of(gql.mutation_type.fields["looseCreate"]), "items")
        projected = _element(
            _input_of(gql.mutation_type.fields["looseProjectedCreate"]), "items"
        )

        assert plain is projected
