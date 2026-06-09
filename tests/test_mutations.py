# -*- coding: utf-8 -*-
"""Tests for django_graphex.mutation module."""

import graphene
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from django_graphex import DjangoModelMutation

from .models import Author, Post


class PostMutation(DjangoModelMutation):
    """Mutation exercising partial updates against a required FK."""

    class Meta:
        model = Post


class UserMutation(DjangoModelMutation):
    """Test mutation for User model."""

    class Meta:
        model = User
        description = "User mutation"


class UserMutationWithCustomName(DjangoModelMutation):
    """Test mutation with custom model name."""

    class Meta:
        model = User
        model_operations = ("create", "update")
        lookup_field = "username"


class TestQuery(graphene.ObjectType):
    """Test query for mutations."""

    hello = graphene.String(default_value="Hello World!")

    def resolve_hello(self, info):
        return "Hello World!"


class TestMutations(graphene.ObjectType):
    """Test mutations."""

    user_create = UserMutation.CreateField()
    user_update = UserMutation.UpdateField()
    user_delete = UserMutation.DeleteField()

    user_custom_create = UserMutationWithCustomName.CreateField()
    user_custom_update = UserMutationWithCustomName.UpdateField()

    post_update = PostMutation.UpdateField()


test_schema = graphene.Schema(query=TestQuery, mutation=TestMutations)


class DjangoModelMutationTest(TestCase):
    """Test cases for DjangoModelMutation."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )

    def test_create_mutation(self):
        """Test create mutation."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCreate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["username"], "newuser")
        self.assertEqual(data["user"]["email"], "new@example.com")
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertEqual(len(errors), 0)

    def test_update_mutation(self):
        """Test update mutation."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userUpdate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["firstName"], "Updated")
        self.assertEqual(data["user"]["lastName"], "Name")

    def test_partial_update_keeps_required_fk(self):
        """A partial update must not require (or clear) an untouched FK.

        Regression: omitted relational inputs arrive as an explicit ``null``
        (the update input gives them a ``None`` default), which previously made
        a required FK fail validation with "This field may not be null".
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["postUpdate"]
        self.assertTrue(data["ok"], msg=data.get("errors"))
        self.assertEqual(data["post"]["title"], "Edited")
        # The untouched required FK is preserved, not cleared.
        post.refresh_from_db()
        self.assertEqual(post.author_id, author.id)

    def test_delete_mutation(self):
        """Test delete mutation."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userDelete"]
        self.assertTrue(data["ok"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertEqual(len(errors), 0)

        # Verify user was deleted
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_create_mutation_with_validation_errors(self):
        """Test create mutation with validation errors."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCreate"]
        self.assertFalse(data["ok"])
        self.assertIsNone(data["user"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_update_nonexistent_user(self):
        """Test updating a non-existent user."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userUpdate"]
        self.assertFalse(data["ok"])
        self.assertIsNone(data["user"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_delete_nonexistent_user(self):
        """Test deleting a non-existent user."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userDelete"]
        self.assertFalse(data["ok"])
        # Handle case where errors field might be None or empty list
        errors = data.get("errors") or []
        self.assertGreater(len(errors), 0)

    def test_custom_lookup_field_mutation(self):
        """Test mutation with custom lookup field."""
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
        result = test_schema.execute(mutation, context_value=request)

        self.assertIsNone(result.errors)
        data = result.data["userCustomUpdate"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["firstName"], "CustomUpdated")

    def test_mutation_meta_attributes(self):
        """Test mutation meta attributes."""
        self.assertEqual(UserMutation._meta.description, "User mutation")
        self.assertEqual(UserMutation._meta.model, User)

        # Test field creation
        create_field = UserMutation.CreateField()
        update_field = UserMutation.UpdateField()
        delete_field = UserMutation.DeleteField()

        self.assertIsInstance(create_field, graphene.Field)
        self.assertIsInstance(update_field, graphene.Field)
        self.assertIsInstance(delete_field, graphene.Field)

    def test_mutation_with_limited_operations(self):
        """Test mutation with limited model operations."""
        # model_operations = ("create", "update") -> only those two are built.
        create_field = UserMutationWithCustomName.CreateField()
        update_field = UserMutationWithCustomName.UpdateField()

        self.assertIsInstance(create_field, graphene.Field)
        self.assertIsInstance(update_field, graphene.Field)

        # delete was excluded from model_operations, so building the field
        # raises rather than silently exposing an unsupported operation.
        with self.assertRaises(AttributeError):
            UserMutationWithCustomName.DeleteField()

        # MutationFields only yields the enabled operations.
        fields = UserMutationWithCustomName.MutationFields()
        self.assertEqual(len(fields), 2)

    def test_unknown_model_operation_is_rejected(self):
        """An invalid model_operations entry fails fast at class creation."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):

            class BadMutation(DjangoModelMutation):
                class Meta:
                    model = User
                    model_operations = ("create", "frobnicate")
