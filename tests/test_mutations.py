"""Tests for django_graphex.mutation module."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.http import HttpRequest
from django.test import RequestFactory, TestCase
from graphql import (
    ExecutionResult,
    GraphQLField,
    GraphQLResolveInfo,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema

from ._schema_isolation import isolated_pair
from .models import Author, Post

_RMUT = Registry()


class PostMutation(DjangoModelMutation):
    """Mutation exercising partial updates against a required FK.

    Used by "test_partial_update_keeps_required_fk".
    """

    class Meta:
        """Bind the mutation to "Post" under the isolated registry "_RMUT".

        No other options are needed for this mutation.
        """

        model = Post
        registry = _RMUT


class UserMutation(DjangoModelMutation):
    """Test mutation for User model.

    Used by the bulk of the CRUD tests below.
    """

    class Meta:
        """Bind the mutation to "User" with a description, under "_RMUT".

        The description is asserted directly in "test_mutation_meta_attributes".
        """

        model = User
        description = "User mutation"
        registry = _RMUT


class UserMutationWithCustomName(DjangoModelMutation):
    """Test mutation with custom model name.

    Used by the limited-operations tests.
    """

    class Meta:
        """Bind the mutation to "User" with limited operations.

        Only "create" and "update" are enabled; "delete" is intentionally
        excluded.
        """

        model = User
        model_operations = ("create", "update")
        registry = _RMUT


class TestQuery(ObjectType):
    """Test query for mutations.

    Provides the minimal root query field required alongside the mutation
    root.
    """

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = field(GraphQLString)

    def resolve_hello(self, info: GraphQLResolveInfo) -> str:
        """Resolve the "hello" field to a fixed greeting.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The literal greeting string "Hello World!".
        """
        return "Hello World!"


class TestMutations(ObjectType):
    """Test mutations.

    Root mutation exposing every field kind under test in this module.
    """

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    user_create = UserMutation.CreateField()
    user_update = UserMutation.UpdateField()
    user_delete = UserMutation.DeleteField()

    user_custom_create = UserMutationWithCustomName.CreateField()
    user_custom_update = UserMutationWithCustomName.UpdateField()

    post_update = PostMutation.UpdateField()


test_schema = DjangoGraphQLSchema(
    query=TestQuery, mutation=TestMutations, registries=isolated_pair(_RMUT)
)


def _execute(mutation: str, context_value: HttpRequest) -> ExecutionResult:
    """Run a mutation against the native schema (drop-in for "schema.execute").

    Args:
        mutation: The GraphQL mutation document to execute.
        context_value: The Django request passed through as GraphQL context.

    Returns:
        The graphql-core execution result.
    """
    return graphql_sync(
        test_schema.graphql_schema, mutation, context_value=context_value
    )


class DjangoModelMutationTest(TestCase):
    """Test cases for DjangoModelMutation.

    Covers create/update/delete, validation errors, and Meta wiring.
    """

    def setUp(self) -> None:
        """Set up a request factory and one persisted "testuser".

        Shared as fixture data by every test in this class.
        """
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )

    def test_create_mutation(self) -> None:
        """ "userCreate" persists a new user and returns it with no errors.

        This test breaks if the generated create mutation stops persisting
        the user or stops returning the created fields.
        """
        mutation = """
            mutation {
                userCreate(newUser: {
                    username: "newuser"
                    email: "new@example.com"
                    firstName: "New"
                    lastName: "User"
                    password: "testpassword123"
                }) {
                    user {
                        id
                        username
                        email
                        firstName
                        lastName
                    }
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCreate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["username"], "newuser")
        self.assertEqual(data["user"]["email"], "new@example.com")
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertEqual(len(errors), 0)

    def test_update_mutation(self) -> None:
        """ "userUpdate" persists changes to an existing user's editable fields.

        This test breaks if the generated update mutation stops applying
        changes to "firstName"/"lastName".
        """
        mutation = f"""
            mutation {{
                userUpdate(newUser: {{
                    id: {self.user.id}
                    firstName: "Updated"
                    lastName: "Name"
                }}) {{
                    user {{
                        id
                        username
                        firstName
                        lastName
                    }}
                    ok
                    errors {{
                        field
                        messages
                    }}
                }}
            }}
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userUpdate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["firstName"], "Updated")
        self.assertEqual(data["user"]["lastName"], "Name")

    def test_partial_update_keeps_required_fk(self) -> None:
        """A partial update must not require (or clear) an untouched FK.

        An OMITTED relational input is ABSENT from the coerced payload (the
        coercion layer delivers only client-sent keys; omitted != null), so a
        required FK the client did not touch is neither re-validated nor
        cleared. (An EXPLICIT "null" on a required field WOULD fail
        validation with a clean ErrorType — see
        "tests.test_explicit_null_and_json_input".) This test breaks if that
        omitted-vs-null distinction regresses.
        """
        author = Author.objects.create(name="Original")
        post = Post.objects.create(title="Original", body="b", author=author)

        mutation = f"""
            mutation {{
                postUpdate(newPost: {{ id: {post.id} title: "Edited" }}) {{
                    ok
                    post {{ id title }}
                    errors {{ field messages }}
                }}
            }}
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["postUpdate"]
        self.assertTrue(data["ok"], msg=data.get("errors"))
        self.assertEqual(data["post"]["title"], "Edited")
        # The untouched required FK is preserved, not cleared.
        post.refresh_from_db()
        self.assertEqual(post.author_id, author.id)

    def test_delete_mutation(self) -> None:
        """ "userDelete" removes the target user and returns ok with no errors.

        This test breaks if the generated delete mutation stops removing
        the row or stops reporting success.
        """
        mutation = f"""
            mutation {{
                userDelete(id: {self.user.id}) {{
                    ok
                    errors {{
                        field
                        messages
                    }}
                }}
            }}
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userDelete"]
        self.assertTrue(data["ok"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertEqual(len(errors), 0)

        # Verify user was deleted
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_create_mutation_with_validation_errors(self) -> None:
        """ "userCreate" with a duplicate username fails and reports validation errors.

        This test breaks if the uniqueness check on "username" stops firing
        during create.
        """
        # Create user with same username first
        User.objects.create_user(username="duplicate", email="dup@example.com")

        mutation = """
            mutation {
                userCreate(newUser: {
                    username: "duplicate"
                    email: "invalid-email"
                    password: "testpass123"
                }) {
                    user {
                        id
                    }
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCreate"]
        self.assertFalse(data["ok"])
        self.assertIsNone(data["user"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_update_nonexistent_user(self) -> None:
        """ "userUpdate" against a non-existent id fails gracefully with errors.

        This test breaks if updating a missing user stops returning a
        not-ok result and instead raises or silently no-ops.
        """
        mutation = """
            mutation {
                userUpdate(newUser: {
                    id: 99999
                    firstName: "Updated"
                }) {
                    user {
                        id
                    }
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userUpdate"]
        self.assertFalse(data["ok"])
        self.assertIsNone(data["user"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_delete_nonexistent_user(self) -> None:
        """ "userDelete" against a non-existent id fails gracefully with errors.

        This test breaks if deleting a missing user stops returning a
        not-ok result and instead raises.
        """
        mutation = """
            mutation {
                userDelete(id: 99999) {
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userDelete"]
        self.assertFalse(data["ok"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_update_on_a_create_update_only_mutation(self) -> None:
        """A mutation restricted to ("create", "update") still updates by "id".

        This test breaks if narrowing "model_operations" stops leaving the
        operations it does list fully working.
        """
        mutation = f"""
            mutation {{
                userCustomUpdate(newUser: {{
                    id: {self.user.id}
                    username: "testuser"
                    firstName: "CustomUpdated"
                }}) {{
                    user {{
                        username
                        firstName
                    }}
                    ok
                    errors {{
                        field
                        messages
                    }}
                }}
            }}
        """

        request = self.factory.post("/graphql/", content_type="application/json")
        result = _execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCustomUpdate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["firstName"], "CustomUpdated")

    def test_mutation_meta_attributes(self) -> None:
        """ "UserMutation._meta" carries the declared description and model, and builds every field kind.

        This test breaks if "Meta.description"/"Meta.model" stop being
        read onto "_meta", or if any of create/update/delete stop building
        a "GraphQLField".
        """
        self.assertEqual(UserMutation._meta.description, "User mutation")
        self.assertEqual(UserMutation._meta.model, User)

        # Test field creation
        create_field = UserMutation.CreateField()
        update_field = UserMutation.UpdateField()
        delete_field = UserMutation.DeleteField()

        self.assertIsInstance(create_field, GraphQLField)
        self.assertIsInstance(update_field, GraphQLField)
        self.assertIsInstance(delete_field, GraphQLField)

    def test_mutation_with_limited_operations(self) -> None:
        """A mutation with "model_operations = ('create', 'update')" builds only those two fields.

        This test breaks if a disabled operation ("delete" here) stops
        raising when its field builder is invoked, or if "MutationFields"
        stops yielding exactly the enabled operations.
        """
        # model_operations = ("create", "update") -> only those two are built.
        create_field = UserMutationWithCustomName.CreateField()
        update_field = UserMutationWithCustomName.UpdateField()

        self.assertIsInstance(create_field, GraphQLField)
        self.assertIsInstance(update_field, GraphQLField)

        # delete was excluded from model_operations, so building the field
        # raises rather than silently exposing an unsupported operation.
        with self.assertRaises(AttributeError):
            UserMutationWithCustomName.DeleteField()

        # MutationFields only yields the enabled operations.
        fields = UserMutationWithCustomName.MutationFields()
        self.assertEqual(len(fields), 2)

    def test_unknown_model_operation_is_rejected(self) -> None:
        """An invalid "model_operations" entry fails fast at class creation.

        This test breaks if declaring an unsupported operation name (here
        "frobnicate") stops raising "ImproperlyConfigured" immediately at
        class-definition time.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):

            class BadMutation(DjangoModelMutation):
                """Throwaway mutation declaring an invalid operation name."""

                class Meta:
                    """Bind the mutation to "User" with an invalid operation in the tuple."""

                    model = User
                    model_operations = ("create", "frobnicate")
