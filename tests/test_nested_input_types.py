"""Nested-aware INPUT type resolution for "Meta.nested_fields" mutations.

A "DjangoModelMutation"/"DjangoModelType" with non-empty "nested_fields"
must build a DISTINCT, collision-free input type whose nested relations are
exposed as object inputs ("[<Child>CreateInput!]"), never the generic
"[ID!]" -- regardless of whether the plain mutation for the same model is
declared first or second. The fix builds the nested input with
"skip_registry=True" so the generic "(model, op)" registry slot stays
pristine for plain mutations and the converter's child lookups.

Both "DjangoModelMutation" and "DjangoModelType" always use the GLOBAL
registry (neither honours a "Meta.registry" override for the mutation input
path), so assertions read the names off freshly-built schemas. Where the exact
"(model, op)" registry slot must be inspected, the test uses models declared
ONLY in this file ("OrderParent"/"OrderChild") so no sibling test module can
have pre-populated that slot.
"""

from __future__ import annotations

from typing import Any

from django.test import RequestFactory, TestCase
from graphql import (
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation, _nested_input_name
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from .models import (
    Author,
    Comment,
    NestedTreeNode,
    OrderChild,
    OrderParent,
    Post,
    SnakeChild,
    SnakeParent,
    Tag,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _request() -> Any:
    """Build a real request context for execution (the resolver reads ".META").

    Returns:
        A Django test request suitable for GraphQL "context_value".
    """
    return RequestFactory().post("/graphql/", content_type="application/json")


class _Q(ObjectType):
    """Minimal native query root so every schema has at least one field."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = field(GraphQLString)


def _native_schema(**mutation_fields: Any) -> GraphQLSchema:
    """Build a native "DjangoGraphQLSchema" from a map of mutation fields.

    Mirrors the legacy "graphene.Schema(query=Q, mutation=M)" harness but on
    the native path: graphene can no longer assemble a schema from the
    re-parented native "DjangoModelMutation"/"DjangoModelType" (their
    "*Field()" builders return raw graphql-core "GraphQLField"s), so the
    converted tests assemble through the native schema instead.

    Args:
        **mutation_fields: The mutation root's fields, keyed by field name.

    Returns:
        The graphql-core "GraphQLSchema" ("graphql_schema") so callers keep
        using ".mutation_type" exactly as before.
    """
    mutation_cls = type("_M", (ObjectType,), {"__test__": False, **mutation_fields})
    return DjangoGraphQLSchema(query=_Q, mutation=mutation_cls).graphql_schema


def _arg_input_type(field: GraphQLField) -> Any:
    """Unwrap a (NonNull) input argument to its underlying named input type.

    Args:
        field: The GraphQL field whose first (and typically only) argument
            carries the input type to unwrap.

    Returns:
        The underlying named input type, with any NonNull wrapper stripped.
    """
    arg_type = field.args[next(iter(field.args))].type
    return arg_type.of_type if hasattr(arg_type, "of_type") else arg_type


def _named_arg_input_type(field: GraphQLField, arg_name: str) -> Any:
    """Unwrap a named (NonNull) input argument to its underlying named input type.

    Args:
        field: The GraphQL field whose argument is inspected.
        arg_name: The name of the argument to unwrap.

    Returns:
        The underlying named input type, with any NonNull wrapper stripped.
    """
    arg_type = field.args[arg_name].type
    return arg_type.of_type if hasattr(arg_type, "of_type") else arg_type


def _field_type_str(input_type: GraphQLInputObjectType, field_name: str) -> str:
    """Render an input type's field type as its GraphQL SDL string.

    Args:
        input_type: The GraphQL input object type to inspect.
        field_name: The name of the field whose type is rendered.

    Returns:
        The field's type rendered as a string, e.g. "[ID!]".
    """
    return str(input_type.fields[field_name].type)


def _meta_arg_input_name(host: type, op: str, arg_name: str) -> str:
    """Read the compiled nested input type NAME off a host's "_meta.arguments".

    Under the native backend "_meta.arguments[op][arg_name]" is a graphql-core
    "GraphQLArgument" (not a graphene "Argument"); its ".type" is a
    "GraphQLNonNull" wrapping the "GraphQLInputObjectType", which carries
    ".name" (graphene exposed it as "._meta.name").

    Args:
        host: The "DjangoModelMutation" or "DjangoModelType" subclass to read.
        op: The operation name, e.g. "create" or "update".
        arg_name: The argument name under that operation.

    Returns:
        The compiled input type's name.
    """
    arg = host._meta.arguments[op][arg_name]
    input_type = arg.type.of_type if hasattr(arg.type, "of_type") else arg.type
    return input_type.name


# --------------------------------------------------------------------------- #
# 1. Bug repro: generic-FIRST ordering                                         #
# --------------------------------------------------------------------------- #
class GenericFirstOrderingTest(TestCase):
    """The user-facing bug: plain PostMutation declared before the nested one.

    Confirms the nested input stays distinct from the plain one regardless of
    declaration order.
    """

    def _build_schema(self) -> GraphQLSchema:
        """Build a schema with a plain "PostMutation" declared before the nested one.

        Returns:
            The assembled graphql-core schema exposing both "postCreate" and
            "postWithCommentsCreate".
        """

        class PostMutation(DjangoModelMutation):
            """Plain "Post" mutation with no nested fields."""

            class Meta:
                """Bind the mutation to "Post" with no nested fields."""

                model = Post

        class PostWithCommentsMutation(DjangoModelMutation):
            """ "Post" mutation exposing "comments" as a nested field."""

            class Meta:
                """Bind the mutation to "Post" create with "comments" nested."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        return _native_schema(
            post_create=PostMutation.CreateField(),
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
        )

    def test_nested_mutation_exposes_object_list_input(self) -> None:
        """The nested mutation exposes a distinct object-list input, while the plain one keeps [ID!].

        This test breaks if the nested and plain input types stop being
        distinct, or if either stops using its expected "comments" field shape
        ("[ID!]" for plain, an object list for nested).
        """
        gql = self._build_schema()
        mt = gql.mutation_type
        nested_input = _arg_input_type(mt.fields["postWithCommentsCreate"])
        plain_input = _arg_input_type(mt.fields["postCreate"])

        # The nested input is a DISTINCT, deterministically named type.
        self.assertEqual(nested_input.name, "PostCreateNestedCommentsType")
        # comments is now an OBJECT-list input, not [ID!] (the bug).
        comments_type = _field_type_str(nested_input, "comments")
        self.assertNotEqual(comments_type, "[ID!]")
        self.assertIn("Comment", comments_type)
        self.assertTrue(comments_type.startswith("["))

        # The plain mutation is byte-identical to today: generic name, [ID!].
        self.assertEqual(plain_input.name, "PostCreateGenericType")
        self.assertEqual(_field_type_str(plain_input, "comments"), "[ID!]")

    def test_child_element_type_is_comment_create_input(self) -> None:
        """The nested "comments" list element type carries "Comment"'s own fields.

        This test breaks if the list element type stops resolving to the
        Comment create input, e.g. by degrading to a bare "ID" reference.
        """
        gql = self._build_schema()
        nested_input = _arg_input_type(
            gql.mutation_type.fields["postWithCommentsCreate"]
        )
        # Drill into the list element type and assert it carries Comment fields.
        list_type = nested_input.fields["comments"].type.of_type  # [X!] -> X!
        element = list_type.of_type if hasattr(list_type, "of_type") else list_type
        self.assertIn("body", element.fields)  # tests.Comment has post/body


# --------------------------------------------------------------------------- #
# 2. nested-FIRST ordering: the generic slot stays generic                     #
# --------------------------------------------------------------------------- #
class NestedFirstOrderingTest(TestCase):
    """ "skip_registry=True" means the nested build never writes (model, op).

    Uses dedicated "OrderParent"/"OrderChild" models so the GLOBAL
    "(OrderParent, 'create')" slot is controlled entirely by this test.
    """

    def test_generic_slot_unwritten_by_nested_then_plain_gets_id(self) -> None:
        """The nested-first build leaves the generic registry slot empty until a plain mutation writes it.

        This test breaks if building a nested mutation first starts writing
        the generic "(OrderParent, 'create')" registry slot, which would make
        a later plain mutation reuse the nested (object-list) input instead
        of building its own generic ("[ID!]") one.
        """
        registry = get_global_registry()
        # Precondition: no sibling test has populated this slot.
        self.assertIsNone(registry.get_type_for_model(OrderParent, for_input="create"))

        # Nested mutation declared FIRST.
        class OrderParentNestedMutation(DjangoModelMutation):
            """ "OrderParent" mutation exposing "kids" as a nested field."""

            class Meta:
                """Bind the mutation to "OrderParent" create with "kids" nested."""

                model = OrderParent
                model_operations = ("create",)
                nested_fields = {"kids": OrderChild}

        # The nested build used skip_registry=True -> the GENERIC slot is still
        # EMPTY (the on-demand child built (OrderChild, "create"), not parent).
        self.assertIsNone(registry.get_type_for_model(OrderParent, for_input="create"))

        # Plain mutation declared SECOND -> it builds + registers the GENERIC.
        class OrderParentMutation(DjangoModelMutation):
            """Plain "OrderParent" mutation with no nested fields."""

            class Meta:
                """Bind the mutation to "OrderParent" with no nested fields."""

                model = OrderParent

        generic = registry.get_type_for_model(OrderParent, for_input="create")
        self.assertIsNotNone(generic)
        self.assertEqual(generic._meta.name, "OrderParentCreateGenericType")

        # Build a schema and assert: nested mutation -> object list; plain -> ID.
        gql = _native_schema(
            order_parent_nested_create=OrderParentNestedMutation.CreateField(),
            order_parent_create=OrderParentMutation.CreateField(),
        )
        nested_input = _arg_input_type(
            gql.mutation_type.fields["orderParentNestedCreate"]
        )
        plain_input = _arg_input_type(gql.mutation_type.fields["orderParentCreate"])
        self.assertEqual(nested_input.name, "OrderParentCreateNestedKidsType")
        self.assertNotEqual(_field_type_str(nested_input, "kids"), "[ID!]")
        self.assertEqual(plain_input.name, "OrderParentCreateGenericType")
        self.assertEqual(_field_type_str(plain_input, "kids"), "[ID!]")


# --------------------------------------------------------------------------- #
# 3. DjangoModelType (types.py mirror site)                                    #
# --------------------------------------------------------------------------- #
class DjangoModelTypeSiteTest(TestCase):
    """Coverage confirming the "DjangoModelType" nested gate mirrors the mutation gate.

    Verifies the same distinct-input behavior applies to types, not just
    mutations.
    """

    def test_model_type_nested_field_builds_object_input(self) -> None:
        """A "DjangoModelType" with nested fields builds the distinct nested input, not the generic one.

        This test breaks if the "types.py" nested gate stops mirroring the
        mutation gate's "skip_registry=True" distinct-input behavior.
        """

        # The DjangoModelType gate (types.py) mirrors the mutation gate: a nested
        # host builds the distinct skip_registry=True input.
        class PostWithCommentsType(DjangoModelType):
            """ "Post" type exposing "comments" as a nested field.

            Used to build the nested input this test inspects.
            """

            class Meta:
                """Bind the type to "Post" with "comments" declared as nested.

                No extra options are needed for this test.
                """

                model = Post
                nested_fields = {"comments": Comment}

        name = _meta_arg_input_name(PostWithCommentsType, "create", "new_post")
        self.assertEqual(name, "PostCreateNestedCommentsType")


# --------------------------------------------------------------------------- #
# 4. Determinism: different nested_fields => different names                    #
# --------------------------------------------------------------------------- #
class DeterministicNameTest(TestCase):
    """Coverage confirming distinct "nested_fields" sets produce distinct, non-generic names.

    Uses "comments" vs "tags" as the two structurally different sets.
    """

    def test_comments_vs_tags_get_distinct_names_neither_generic(self) -> None:
        """Two types nesting different single fields get distinct, non-generic input names.

        This test breaks if the nested input name stops encoding the nested
        field set, causing two structurally different nested inputs to
        collide on the same name.
        """

        class PostWithCommentsType(DjangoModelType):
            """ "Post" type exposing "comments" as a nested field.

            Used to build the nested input this test inspects.
            """

            class Meta:
                """Bind the type to "Post" with "comments" declared as nested.

                No extra options are needed for this test.
                """

                model = Post
                nested_fields = {"comments": Comment}

        class PostWithTagsType(DjangoModelType):
            """ "Post" type exposing "tags" as a nested field.

            Used to build the nested input this test inspects.
            """

            class Meta:
                """Bind the type to "Post" with "tags" declared as nested.

                No extra options are needed for this test.
                """

                model = Post
                nested_fields = {"tags": Tag}

        comments_name = _meta_arg_input_name(PostWithCommentsType, "create", "new_post")
        tags_name = _meta_arg_input_name(PostWithTagsType, "create", "new_post")
        self.assertEqual(comments_name, "PostCreateNestedCommentsType")
        self.assertEqual(tags_name, "PostCreateNestedTagsType")
        self.assertNotEqual(comments_name, tags_name)
        self.assertNotIn("Generic", comments_name)
        self.assertNotIn("Generic", tags_name)


# --------------------------------------------------------------------------- #
# 5. Projection collision: same nested_fields, different only_fields            #
# --------------------------------------------------------------------------- #
class ProjectionCollisionTest(TestCase):
    """Coverage for the projection-aware name suffix that prevents duplicate-type collisions.

    Covers both the suffixed and the empty-projection (no-suffix) cases.
    """

    def test_same_nested_fields_different_projection_distinct_names(self) -> None:
        """Same model and "nested_fields" with different "only_fields" still get distinct names.

        This test breaks if the projection-aware name suffix stops being
        appended, which would collide both inputs on
        "PostCreateNestedCommentsType" and raise a duplicate-type error at
        schema assembly.
        """

        # Same model + same nested_fields, DIFFERENT only_fields. Without the
        # projection-aware name suffix both would be PostCreateNestedCommentsType
        # and graphene would raise a duplicate-type error at schema assembly.
        class PostNestedAMutation(DjangoModelMutation):
            """ "Post" mutation nesting "comments" with the "title" projection."""

            class Meta:
                """Bind the mutation to "Post" create, nesting "comments", projected to "title"."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}
                only_fields = ("title", "comments")

        class PostNestedBMutation(DjangoModelMutation):
            """ "Post" mutation nesting "comments" with the "body" projection."""

            class Meta:
                """Bind the mutation to "Post" create, nesting "comments", projected to "body"."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}
                only_fields = ("body", "comments")

        name_a = _meta_arg_input_name(PostNestedAMutation, "create", "new_post")
        name_b = _meta_arg_input_name(PostNestedBMutation, "create", "new_post")
        # Both encode comments but the projection suffix keeps them distinct.
        self.assertTrue(name_a.startswith("PostCreateNestedCommentsType_p"))
        self.assertTrue(name_b.startswith("PostCreateNestedCommentsType_p"))
        self.assertNotEqual(name_a, name_b)

        # The schema must assemble with NO duplicate-type error.
        gql = _native_schema(
            a=PostNestedAMutation.CreateField(),
            b=PostNestedBMutation.CreateField(),
        )
        self.assertIsNotNone(gql)

    def test_empty_projection_has_no_suffix(self) -> None:
        """A nested mutation with no projection keeps the plain, suffix-free name.

        This test breaks if the projection-suffix logic starts appending a
        "_p<hex>" suffix even when "only_fields"/"exclude_fields" are empty.
        """

        class PostNestedMutation(DjangoModelMutation):
            """ "Post" mutation nesting "comments" with no field projection."""

            class Meta:
                """Bind the mutation to "Post" create with "comments" nested, unprojected."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        name = _meta_arg_input_name(PostNestedMutation, "create", "new_post")
        self.assertEqual(name, "PostCreateNestedCommentsType")  # no _p<hex> suffix


# --------------------------------------------------------------------------- #
# 6. Update operation also gets the nested input                               #
# --------------------------------------------------------------------------- #
class UpdateOperationTest(TestCase):
    """Coverage confirming the "update" operation also gets the nested object-list input.

    Also confirms the update child element exposes its pk for upsert.
    """

    def test_update_arg_is_object_list_not_id(self) -> None:
        """The update mutation's nested "comments" argument is an object-list input exposing "id".

        This test breaks if the update path stops building the nested input
        (falling back to "[ID!]"), or if the update child element stops
        exposing "id" for upsert.
        """

        class PostWithCommentsMutation(DjangoModelMutation):
            """ "Post" mutation exposing "comments" as nested for create and update."""

            class Meta:
                """Bind the mutation to "Post" create/update with "comments" nested."""

                model = Post
                model_operations = ("create", "update")
                nested_fields = {"comments": Comment}

        gql = _native_schema(
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
            post_with_comments_update=PostWithCommentsMutation.UpdateField(),
        )
        update_input = _named_arg_input_type(
            gql.mutation_type.fields["postWithCommentsUpdate"], "newPost"
        )
        self.assertEqual(update_input.name, "PostUpdateNestedCommentsType")
        # The update child input must be the object-list, not [ID!].
        comments_type = _field_type_str(update_input, "comments")
        self.assertNotEqual(comments_type, "[ID!]")
        self.assertIn("Comment", comments_type)
        # The update child element exposes the pk (`id`) for upsert.
        element = update_input.fields["comments"].type.of_type.of_type
        self.assertIn("id", element.fields)


# --------------------------------------------------------------------------- #
# 7. Child-input identity end-to-end (converter correctness)                    #
# --------------------------------------------------------------------------- #
class ChildInputIdentityTest(TestCase):
    """Coverage confirming the nested child input carries the child model's own fields.

    Verifies converter correctness end-to-end through a real schema build.
    """

    def test_nested_comment_element_accepts_comment_fields(self) -> None:
        """The nested "comments" list element type exposes "Comment"'s own fields.

        This test breaks if the child element type stops resolving to the
        actual "Comment" create input even when a dedicated "CommentMutation"
        is registered alongside the parent.
        """

        class PostWithCommentsMutation(DjangoModelMutation):
            """ "Post" mutation exposing "comments" as a nested field."""

            class Meta:
                """Bind the mutation to "Post" create with "comments" nested."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        class CommentMutation(DjangoModelMutation):
            """Plain "Comment" mutation, registered alongside the nested parent."""

            class Meta:
                """Bind the mutation to "Comment" with no nested fields."""

                model = Comment

        gql = _native_schema(
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
            comment_create=CommentMutation.CreateField(),
        )
        nested_input = _arg_input_type(
            gql.mutation_type.fields["postWithCommentsCreate"]
        )
        element = nested_input.fields["comments"].type.of_type.of_type
        # tests.Comment exposes body (and the post FK).
        self.assertIn("body", element.fields)


# --------------------------------------------------------------------------- #
# 8. Build-on-demand: child has NO explicit mutation/type declared              #
# --------------------------------------------------------------------------- #
class BuildOnDemandTest(TestCase):
    """Coverage confirming the nested child input is built on demand when no child mutation exists.

    The child input must never be silently dropped or degraded to "[ID!]".
    """

    def test_child_generic_input_built_when_no_child_mutation(self) -> None:
        """A nested field builds its child input on demand when no "CommentMutation" is registered.

        This test breaks if the absence of an explicit child mutation causes
        the nested field to be silently dropped or degraded to "[ID!]"
        instead of building a generic child input on demand.
        """

        # NO CommentMutation / CommentType registered anywhere in this schema.
        class PostWithCommentsMutation(DjangoModelMutation):
            """ "Post" mutation exposing "comments" as a nested field."""

            class Meta:
                """Bind the mutation to "Post" create with "comments" nested."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        gql = _native_schema(
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
        )
        nested_input = _arg_input_type(
            gql.mutation_type.fields["postWithCommentsCreate"]
        )
        comments_type = _field_type_str(nested_input, "comments")
        # The field must NOT be silently dropped; it is an object-list input.
        self.assertIn("comments", nested_input.fields)
        self.assertNotEqual(comments_type, "[ID!]")
        self.assertIn("Comment", comments_type)


# --------------------------------------------------------------------------- #
# 9. Self-reference termination (single-level recursion guard)                  #
# --------------------------------------------------------------------------- #
class SelfReferenceTerminationTest(TestCase):
    """Coverage for the single-level recursion guard on self-referential nested fields.

    Confirms the schema builds without a RecursionError.
    """

    def test_self_nested_builds_and_grandchild_is_id(self) -> None:
        """A self-referential nested field builds without recursing past one level.

        This test breaks if a "children"-nests-"children" self-reference
        stops terminating at the grandchild level, either by raising a
        "RecursionError" or by failing to degrade the grandchild's own
        "children" field back to "[ID!]".
        """

        class TreeMutation(DjangoModelMutation):
            """Self-referential tree mutation nesting "children" of the same model."""

            class Meta:
                """Bind the mutation to "NestedTreeNode" create, nesting "children"."""

                model = NestedTreeNode
                model_operations = ("create",)
                nested_fields = {"children": NestedTreeNode}

        # Schema must build without RecursionError.
        gql = _native_schema(tree_create=TreeMutation.CreateField())
        nested_input = _arg_input_type(gql.mutation_type.fields["treeCreate"])
        # The parent's `children` is the nested object-list...
        children_type = _field_type_str(nested_input, "children")
        self.assertNotEqual(children_type, "[ID!]")
        # ...but the GRANDCHILD (the generic child's own `children`) terminates
        # at [ID!] -- the on-demand child is built with empty nested_fields.
        element = nested_input.fields["children"].type.of_type.of_type
        self.assertEqual(str(element.fields["children"].type), "[ID!]")


# --------------------------------------------------------------------------- #
# 10. snake_case multi-word nested key e2e round-trip                           #
# --------------------------------------------------------------------------- #
class SnakeCaseNestedKeyTest(TestCase):
    """Coverage for a multi-word snake_case nested key's end-to-end camelCase round-trip.

    Exercises schema shape plus a real mutation execution.
    """

    def test_multiword_snake_case_nested_field_persists(self) -> None:
        """A multi-word snake_case nested field camelCases on the wire and persists on the Django attr.

        This test breaks if the camelCase surface name stops matching
        "blogComments", or if the resolver stops mapping the camelCase
        payload key back to the Django "blog_comments" attribute before
        saving.
        """

        class SnakeParentMutation(DjangoModelMutation):
            """ "SnakeParent" mutation nesting the multi-word "blog_comments" field."""

            class Meta:
                """Bind the mutation to "SnakeParent" create, nesting "blog_comments"."""

                model = SnakeParent
                model_operations = ("create",)
                nested_fields = {"blog_comments": SnakeChild}

        gql = _native_schema(
            snake_parent_create=SnakeParentMutation.CreateField(),
        )
        nested_input = _arg_input_type(gql.mutation_type.fields["snakeParentCreate"])
        # GraphQL surface camelCases the accessor.
        self.assertIn("blogComments", nested_input.fields)
        self.assertNotEqual(_field_type_str(nested_input, "blogComments"), "[ID!]")

        # Execute the mutation: the object payload must round-trip to the Django
        # attr `blog_comments` so the backend's data.pop(field) matches.
        mutation = """
            mutation {
              snakeParentCreate(newSnakeparent: {
                title: "P"
                blogComments: [{ text: "hi" }, { text: "yo" }]
              }) {
                ok
                errors { field messages }
              }
            }
        """
        result = graphql_sync(gql, mutation, context_value=_request())
        self.assertIsNone(result.errors, msg=result.errors)
        self.assertTrue(result.data["snakeParentCreate"]["ok"])
        self.assertEqual(SnakeParent.objects.count(), 1)
        parent = SnakeParent.objects.get()
        self.assertEqual(
            set(parent.blog_comments.values_list("text", flat=True)), {"hi", "yo"}
        )


# --------------------------------------------------------------------------- #
# 11. Forward-FK nested child                                                   #
# --------------------------------------------------------------------------- #
class ForwardFKNestedChildTest(TestCase):
    """Coverage for a nested forward-FK child resolving to an object input, not a bare ID.

    Complements the M2M and reverse-relation nested-child coverage.
    """

    def test_forward_fk_nested_child_is_object_input(self) -> None:
        """A nested forward-FK field resolves to an "Author" object input, not a bare "ID".

        This test breaks if a forward-FK nested field stops resolving to the
        child's own object input and degrades to a plain "ID" reference.
        """

        class PostForwardMutation(DjangoModelMutation):
            """ "Post" mutation exposing "author" as a nested forward-FK field."""

            class Meta:
                """Bind the mutation to "Post" create with "author" nested."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"author": Author}

        gql = _native_schema(
            post_forward_create=PostForwardMutation.CreateField(),
        )
        nested_input = _arg_input_type(gql.mutation_type.fields["postForwardCreate"])
        author_type = _field_type_str(nested_input, "author")
        self.assertNotEqual(author_type, "ID")
        self.assertIn("Author", author_type)


# --------------------------------------------------------------------------- #
# 12. M2M nested child                                                          #
# --------------------------------------------------------------------------- #
class M2MNestedChildTest(TestCase):
    """Coverage for a nested many-to-many child resolving to an object-list input.

    Confirms both the create and update operations expose the object-list
    shape.
    """

    def test_m2m_nested_child_is_object_list_input(self) -> None:
        """Both create and update expose "tags" as an object-list input, not "[ID!]".

        This test breaks if a nested M2M field stops resolving to the child's
        own object-list input on either operation.
        """

        class PostM2MMutation(DjangoModelMutation):
            """ "Post" mutation exposing "tags" as a nested M2M field for create and update."""

            class Meta:
                """Bind the mutation to "Post" create/update with "tags" nested."""

                model = Post
                model_operations = ("create", "update")
                nested_fields = {"tags": Tag}

        gql = _native_schema(
            post_m2m_create=PostM2MMutation.CreateField(),
            post_m2m_update=PostM2MMutation.UpdateField(),
        )
        create_input = _named_arg_input_type(
            gql.mutation_type.fields["postM2mCreate"], "newPost"
        )
        update_input = _named_arg_input_type(
            gql.mutation_type.fields["postM2mUpdate"], "newPost"
        )
        self.assertNotEqual(_field_type_str(create_input, "tags"), "[ID!]")
        self.assertIn("Tag", _field_type_str(create_input, "tags"))
        # Update uses the update child input (object list, not [ID!]).
        self.assertNotEqual(_field_type_str(update_input, "tags"), "[ID!]")
        self.assertIn("Tag", _field_type_str(update_input, "tags"))


# --------------------------------------------------------------------------- #
# 13. E2E: create parent + inline children atomically                          #
# --------------------------------------------------------------------------- #
class E2ENestedCreateTest(TestCase):
    """Coverage for an end-to-end create of a parent with inline nested children.

    Executes a real mutation and verifies the children were persisted
    atomically alongside the parent.
    """

    def test_create_post_with_inline_comments_atomically(self) -> None:
        """Creating a post with inline nested comments persists both atomically.

        This test breaks if the nested create mutation stops persisting the
        inline "comments" alongside the parent "post" in one atomic operation.
        """

        class PostWithCommentsMutation(DjangoModelMutation):
            """ "Post" mutation exposing "comments" as a nested field."""

            class Meta:
                """Bind the mutation to "Post" create with "comments" nested."""

                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        gql = _native_schema(
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
        )
        author = Author.objects.create(name="A")
        mutation = """
            mutation ($author: ID!) {
              postWithCommentsCreate(newPost: {
                title: "Hello"
                author: $author
                comments: [{ body: "first" }, { body: "second" }]
              }) {
                ok
                errors { field messages }
              }
            }
        """
        result = graphql_sync(
            gql,
            mutation,
            variable_values={"author": str(author.id)},
            context_value=_request(),
        )
        self.assertIsNone(result.errors, msg=result.errors)
        self.assertTrue(result.data["postWithCommentsCreate"]["ok"])
        self.assertEqual(Post.objects.count(), 1)
        post = Post.objects.get()
        self.assertEqual(
            set(post.comments.values_list("body", flat=True)), {"first", "second"}
        )


# --------------------------------------------------------------------------- #
# 14. NC-1: camelCase-delimiter-ambiguity collision in the nested input name   #
# --------------------------------------------------------------------------- #
class NestedInputNameDelimiterCollisionTest(TestCase):
    """ "_nested_input_name" must keep STRUCTURALLY-DIFFERENT key sets apart.

    "to_camel_case" strips EVERY underscore, so the multi-field JOIN delimiter
    "_" collapses into field-internal snake_case underscores. Before the fix
    a single multi-word key {"blog_comments"} and a two-field set
    {"blog", "comments"} both produced "PostCreateNestedBlogCommentsType".
    graphene then de-duplicates by NAME (keeps the first, silently drops the
    second's fields, raises NO error), so a client mutation is validated against
    the wrong input type and the shadowed mutation's fields vanish.

    The fix appends a literal "_n<6hex>" suffix (a hash of the sorted-key
    TUPLE) AFTER camelCasing whenever the keys are ambiguous, so the two names
    diverge. Multi-word snake_case nested fields are a first-class supported
    case (ISSUE 7), so this collision is reachable in real schemas.
    """

    def test_single_multiword_key_differs_from_two_field_set(self) -> None:
        """A single multi-word key and a structurally different two-field set get distinct names.

        This test breaks if the keys-hash disambiguator stops being appended,
        letting {"blog_comments"} and {"blog", "comments"} collapse onto the
        same name again.
        """
        single = _nested_input_name(Post, "create", {"blog_comments": Comment})
        pair = _nested_input_name(Post, "create", {"blog": Tag, "comments": Comment})
        # Before the fix BOTH collapsed to "PostCreateNestedBlogCommentsType".
        self.assertNotEqual(
            single,
            pair,
            msg="multi-word key and two-field set must NOT share a name",
        )
        # Both still keep the human-readable, camelCased stem.
        self.assertTrue(single.startswith("PostCreateNestedBlogCommentsType"))
        self.assertTrue(pair.startswith("PostCreateNestedBlogCommentsType"))
        # The disambiguator is the keys-hash suffix.
        self.assertIn("_n", single)
        self.assertIn("_n", pair)

    def test_underscore_internal_vs_split_keys_differ(self) -> None:
        """A key with an internal underscore differs from the equivalent split-key set.

        This test breaks if the minimal ambiguous pair {"a_b"} vs {"a", "b"}
        stops producing distinct names.
        """
        # The minimal ISSUE example: {"a_b"} vs {"a", "b"} -> ...NestedABType.
        single = _nested_input_name(Post, "create", {"a_b": Comment})
        pair = _nested_input_name(Post, "create", {"a": Tag, "b": Comment})
        self.assertNotEqual(single, pair)

    def test_single_word_key_keeps_suffix_free_human_name(self) -> None:
        """A single, unambiguous key keeps the plain human-readable name with no suffix.

        This test breaks if the common, unambiguous case (one key, no
        internal underscore) starts getting a disambiguator suffix it
        does not need, which would be a byte-for-byte naming regression.
        """
        # The common case (one key, no internal underscore) is unambiguous and
        # MUST stay byte-identical to today -- no suffix, no regression.
        self.assertEqual(
            _nested_input_name(Post, "create", {"comments": Comment}),
            "PostCreateNestedCommentsType",
        )
        self.assertEqual(
            _nested_input_name(Post, "create", {"tags": Tag}),
            "PostCreateNestedTagsType",
        )

    def test_name_is_deterministic_and_order_independent(self) -> None:
        """The same key set in any iteration order produces the identical name.

        This test breaks if the name-building logic starts depending on
        dict iteration order, which would trip graphene's duplicate-type
        guard across repeated builds of the same nested input.
        """
        # Idempotent: same key set in any order yields the same name, so repeated
        # builds of the SAME nested input never trip graphene's duplicate guard.
        a = _nested_input_name(Post, "create", {"blog": Tag, "comments": Comment})
        b = _nested_input_name(Post, "create", {"comments": Comment, "blog": Tag})
        self.assertEqual(a, b)

    def test_keys_suffix_composes_with_projection_suffix(self) -> None:
        """An ambiguous key set combined with a projection carries both disambiguator suffixes.

        This test breaks if the keys-hash and projection-hash suffixes stop
        composing, causing two differently-projected ambiguous nested inputs
        to collide on the same name.
        """
        # An ambiguous key set AND a non-empty projection carry BOTH suffixes;
        # two different projections still diverge on the _p segment.
        proj_a = _nested_input_name(
            Post, "create", {"blog_comments": Comment}, only_fields=("title",)
        )
        proj_b = _nested_input_name(
            Post, "create", {"blog_comments": Comment}, only_fields=("body",)
        )
        for name in (proj_a, proj_b):
            self.assertIn("_n", name)
            self.assertIn("_p", name)
        self.assertNotEqual(proj_a, proj_b)

    def test_two_structurally_distinct_nested_mutations_both_survive_schema(
        self,
    ) -> None:
        """Two nested mutations whose key sets camelCase to the same stem both keep their own fields.

        This test breaks if the schema assembly silently shadows one of the
        two structurally distinct nested inputs, dropping its fields instead
        of keeping both under distinct names.
        """

        # End-to-end teeth: two nested mutations whose key sets camelCase to the
        # SAME stem must BOTH keep their own input type (with their own fields)
        # in the assembled schema -- proving graphene did not silently shadow one.
        class SnakeMultiWordMutation(DjangoModelMutation):
            """ "SnakeParent" mutation nesting the multi-word "blog_comments" field."""

            class Meta:
                """Bind the mutation to "SnakeParent" create, nesting "blog_comments"."""

                model = SnakeParent
                model_operations = ("create",)
                nested_fields = {"blog_comments": SnakeChild}

        class PostTwoFieldMutation(DjangoModelMutation):
            """ "Post" mutation nesting two fields whose camelCased join would collide."""

            class Meta:
                """Bind the mutation to "Post" create, nesting "comments" and "tags"."""

                model = Post
                model_operations = ("create",)
                # Two real Post relations whose names, joined+camelCased, would
                # collide with a single "tagsComments"-style multi-word key.
                nested_fields = {"comments": Comment, "tags": Tag}

        gql = _native_schema(
            snake_create=SnakeMultiWordMutation.CreateField(),
            post_two_create=PostTwoFieldMutation.CreateField(),
        )

        snake_input = _arg_input_type(gql.mutation_type.fields["snakeCreate"])
        post_input = _arg_input_type(gql.mutation_type.fields["postTwoCreate"])

        # Distinct named types -- no name collision.
        self.assertNotEqual(snake_input.name, post_input.name)
        # The multi-word single-key input keeps its one nested object field.
        self.assertIn("blogComments", snake_input.fields)
        self.assertNotEqual(_field_type_str(snake_input, "blogComments"), "[ID!]")
        # The two-field input keeps BOTH nested object fields -- neither was
        # silently dropped by a shadowing de-dup.
        self.assertIn("comments", post_input.fields)
        self.assertIn("tags", post_input.fields)
        self.assertNotEqual(_field_type_str(post_input, "comments"), "[ID!]")
        self.assertNotEqual(_field_type_str(post_input, "tags"), "[ID!]")
        # The two-field input carries the keys-hash suffix (it is ambiguous).
        self.assertIn("_n", post_input.name)
