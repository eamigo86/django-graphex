# -*- coding: utf-8 -*-
"""Nested-aware INPUT type resolution for ``Meta.nested_fields`` mutations.

A ``DjangoModelMutation``/``DjangoModelType`` with non-empty ``nested_fields``
must build a DISTINCT, collision-free input type whose nested relations are
exposed as object inputs (``[<Child>CreateInput!]``), never the generic
``[ID!]`` -- regardless of whether the plain mutation for the same model is
declared first or second. The fix builds the nested input with
``skip_registry=True`` so the generic ``(model, op)`` registry slot stays
pristine for plain mutations and the converter's child lookups.

Both ``DjangoModelMutation`` and ``DjangoModelType`` always use the GLOBAL
registry (neither honours a ``Meta.registry`` override for the mutation input
path), so assertions read the names off freshly-built schemas. Where the exact
``(model, op)`` registry slot must be inspected, the test uses models declared
ONLY in this file (``OrderParent``/``OrderChild``) so no sibling test module can
have pre-populated that slot.
"""

from django.test import RequestFactory, TestCase
from graphql import GraphQLString, graphql_sync

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoModelMutation,
    DjangoModelType,
    ObjectType,
    field,
)
from django_graphex.mutation import _nested_input_name
from django_graphex.registry import get_global_registry

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
def _request():
    """A real request context for execution (resolver reads ``.META``)."""
    return RequestFactory().post("/graphql/", content_type="application/json")


class _Q(ObjectType):
    """Minimal native query root so every schema has at least one field."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = field(GraphQLString)


def _native_schema(**mutation_fields):
    """Build a native ``DjangoGraphQLSchema`` from a map of mutation fields.

    Mirrors the legacy ``graphene.Schema(query=Q, mutation=M)`` harness but on
    the native path: graphene can no longer assemble a schema from the
    re-parented native ``DjangoModelMutation``/``DjangoModelType`` (their
    ``*Field()`` builders return raw graphql-core ``GraphQLField``s), so the
    converted tests assemble through the native schema instead. Returns the
    graphql-core ``GraphQLSchema`` (``.graphql_schema``) so callers keep using
    ``.mutation_type`` exactly as before.
    """
    mutation_cls = type("_M", (ObjectType,), {"__test__": False, **mutation_fields})
    return DjangoGraphQLSchema(query=_Q, mutation=mutation_cls).graphql_schema


def _arg_input_type(field):
    """Unwrap a (NonNull) input argument to its underlying named input type."""
    arg_type = field.args[next(iter(field.args))].type
    return arg_type.of_type if hasattr(arg_type, "of_type") else arg_type


def _named_arg_input_type(field, arg_name):
    arg_type = field.args[arg_name].type
    return arg_type.of_type if hasattr(arg_type, "of_type") else arg_type


def _field_type_str(input_type, field_name):
    return str(input_type.fields[field_name].type)


def _meta_arg_input_name(host, op, arg_name):
    """Read the compiled nested input type NAME off a host's ``_meta.arguments``.

    Under the native backend ``_meta.arguments[op][arg_name]`` is a graphql-core
    ``GraphQLArgument`` (not a graphene ``Argument``); its ``.type`` is a
    ``GraphQLNonNull`` wrapping the ``GraphQLInputObjectType``, which carries
    ``.name`` (graphene exposed it as ``._meta.name``).
    """
    arg = host._meta.arguments[op][arg_name]
    input_type = arg.type.of_type if hasattr(arg.type, "of_type") else arg.type
    return input_type.name


# --------------------------------------------------------------------------- #
# 1. Bug repro: generic-FIRST ordering                                         #
# --------------------------------------------------------------------------- #
class GenericFirstOrderingTest(TestCase):
    """The user-facing bug: plain PostMutation declared before the nested one."""

    def _build_schema(self):
        class PostMutation(DjangoModelMutation):
            class Meta:
                model = Post

        class PostWithCommentsMutation(DjangoModelMutation):
            class Meta:
                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        return _native_schema(
            post_create=PostMutation.CreateField(),
            post_with_comments_create=PostWithCommentsMutation.CreateField(),
        )

    def test_nested_mutation_exposes_object_list_input(self):
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

    def test_child_element_type_is_comment_create_input(self):
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
    """skip_registry=True => nested build never writes (model, op).

    Uses dedicated ``OrderParent``/``OrderChild`` models so the GLOBAL
    ``(OrderParent, "create")`` slot is controlled entirely by this test.
    """

    def test_generic_slot_unwritten_by_nested_then_plain_gets_id(self):
        registry = get_global_registry()
        # Precondition: no sibling test has populated this slot.
        self.assertIsNone(registry.get_type_for_model(OrderParent, for_input="create"))

        # Nested mutation declared FIRST.
        class OrderParentNestedMutation(DjangoModelMutation):
            class Meta:
                model = OrderParent
                model_operations = ("create",)
                nested_fields = {"kids": OrderChild}

        # The nested build used skip_registry=True -> the GENERIC slot is still
        # EMPTY (the on-demand child built (OrderChild, "create"), not parent).
        self.assertIsNone(registry.get_type_for_model(OrderParent, for_input="create"))

        # Plain mutation declared SECOND -> it builds + registers the GENERIC.
        class OrderParentMutation(DjangoModelMutation):
            class Meta:
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
    def test_model_type_nested_field_builds_object_input(self):
        # The DjangoModelType gate (types.py) mirrors the mutation gate: a nested
        # host builds the distinct skip_registry=True input.
        class PostWithCommentsType(DjangoModelType):
            class Meta:
                model = Post
                nested_fields = {"comments": Comment}

        name = _meta_arg_input_name(PostWithCommentsType, "create", "new_post")
        self.assertEqual(name, "PostCreateNestedCommentsType")


# --------------------------------------------------------------------------- #
# 4. Determinism: different nested_fields => different names                    #
# --------------------------------------------------------------------------- #
class DeterministicNameTest(TestCase):
    def test_comments_vs_tags_get_distinct_names_neither_generic(self):
        class PostWithCommentsType(DjangoModelType):
            class Meta:
                model = Post
                nested_fields = {"comments": Comment}

        class PostWithTagsType(DjangoModelType):
            class Meta:
                model = Post
                nested_fields = {"tags": Tag}

        comments_name = _meta_arg_input_name(
            PostWithCommentsType, "create", "new_post"
        )
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
    def test_same_nested_fields_different_projection_distinct_names(self):
        # Same model + same nested_fields, DIFFERENT only_fields. Without the
        # projection-aware name suffix both would be PostCreateNestedCommentsType
        # and graphene would raise a duplicate-type error at schema assembly.
        class PostNestedAMutation(DjangoModelMutation):
            class Meta:
                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}
                only_fields = ("title", "comments")

        class PostNestedBMutation(DjangoModelMutation):
            class Meta:
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

    def test_empty_projection_has_no_suffix(self):
        class PostNestedMutation(DjangoModelMutation):
            class Meta:
                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        name = _meta_arg_input_name(PostNestedMutation, "create", "new_post")
        self.assertEqual(name, "PostCreateNestedCommentsType")  # no _p<hex> suffix


# --------------------------------------------------------------------------- #
# 6. Update operation also gets the nested input                               #
# --------------------------------------------------------------------------- #
class UpdateOperationTest(TestCase):
    def test_update_arg_is_object_list_not_id(self):
        class PostWithCommentsMutation(DjangoModelMutation):
            class Meta:
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
    def test_nested_comment_element_accepts_comment_fields(self):
        class PostWithCommentsMutation(DjangoModelMutation):
            class Meta:
                model = Post
                model_operations = ("create",)
                nested_fields = {"comments": Comment}

        class CommentMutation(DjangoModelMutation):
            class Meta:
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
    def test_child_generic_input_built_when_no_child_mutation(self):
        # NO CommentMutation / CommentType registered anywhere in this schema.
        class PostWithCommentsMutation(DjangoModelMutation):
            class Meta:
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
    def test_self_nested_builds_and_grandchild_is_id(self):
        class TreeMutation(DjangoModelMutation):
            class Meta:
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
    def test_multiword_snake_case_nested_field_persists(self):
        class SnakeParentMutation(DjangoModelMutation):
            class Meta:
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
    def test_forward_fk_nested_child_is_object_input(self):
        class PostForwardMutation(DjangoModelMutation):
            class Meta:
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
    def test_m2m_nested_child_is_object_list_input(self):
        class PostM2MMutation(DjangoModelMutation):
            class Meta:
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
    def test_create_post_with_inline_comments_atomically(self):
        class PostWithCommentsMutation(DjangoModelMutation):
            class Meta:
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
    """``_nested_input_name`` must keep STRUCTURALLY-DIFFERENT key sets apart.

    ``to_camel_case`` strips EVERY underscore, so the multi-field JOIN delimiter
    ``"_"`` collapses into field-internal snake_case underscores. Before the fix
    a single multi-word key ``{"blog_comments"}`` and a two-field set
    ``{"blog", "comments"}`` both produced ``PostCreateNestedBlogCommentsType``.
    graphene then de-duplicates by NAME (keeps the first, silently drops the
    second's fields, raises NO error), so a client mutation is validated against
    the wrong input type and the shadowed mutation's fields vanish.

    The fix appends a literal ``_n<6hex>`` suffix (a hash of the sorted-key
    TUPLE) AFTER camelCasing whenever the keys are ambiguous, so the two names
    diverge. Multi-word snake_case nested fields are a first-class supported
    case (ISSUE 7), so this collision is reachable in real schemas.
    """

    def test_single_multiword_key_differs_from_two_field_set(self):
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

    def test_underscore_internal_vs_split_keys_differ(self):
        # The minimal ISSUE example: {"a_b"} vs {"a", "b"} -> ...NestedABType.
        single = _nested_input_name(Post, "create", {"a_b": Comment})
        pair = _nested_input_name(Post, "create", {"a": Tag, "b": Comment})
        self.assertNotEqual(single, pair)

    def test_single_word_key_keeps_suffix_free_human_name(self):
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

    def test_name_is_deterministic_and_order_independent(self):
        # Idempotent: same key set in any order yields the same name, so repeated
        # builds of the SAME nested input never trip graphene's duplicate guard.
        a = _nested_input_name(Post, "create", {"blog": Tag, "comments": Comment})
        b = _nested_input_name(Post, "create", {"comments": Comment, "blog": Tag})
        self.assertEqual(a, b)

    def test_keys_suffix_composes_with_projection_suffix(self):
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

    def test_two_structurally_distinct_nested_mutations_both_survive_schema(self):
        # End-to-end teeth: two nested mutations whose key sets camelCase to the
        # SAME stem must BOTH keep their own input type (with their own fields)
        # in the assembled schema -- proving graphene did not silently shadow one.
        class SnakeMultiWordMutation(DjangoModelMutation):
            class Meta:
                model = SnakeParent
                model_operations = ("create",)
                nested_fields = {"blog_comments": SnakeChild}

        class PostTwoFieldMutation(DjangoModelMutation):
            class Meta:
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
