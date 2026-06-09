# -*- coding: utf-8 -*-
"""Tests for django_graphex.registry module."""

from django.test import TestCase

from django_graphex import DjangoObjectType
from django_graphex.registry import Registry, get_global_registry

from .models import Author, BasicModel


class RegistryTest(TestCase):
    """Test cases for registry module."""

    def test_get_global_registry(self):
        """Test get_global_registry function."""
        registry = get_global_registry()

        # Should return a registry object
        self.assertIsNotNone(registry)

    def test_registry_model_registration(self):
        """A DjangoObjectType registers itself and is retrievable by model."""
        local_registry = Registry()

        class LocalType(DjangoObjectType):
            class Meta:
                model = BasicModel
                registry = local_registry

        # The metaclass registers the type on creation; it round-trips by model.
        self.assertIs(local_registry.get_type_for_model(BasicModel), LocalType)

    def test_register_rejects_non_object_type(self):
        """register() only accepts DjangoObjectType/DjangoInputObjectType."""
        registry = Registry()
        with self.assertRaises(TypeError):
            registry.register(BasicModel)

    def test_register_rejects_foreign_registry(self):
        """A type whose registry differs from the target cannot be registered."""
        registry_a = Registry()
        registry_b = Registry()

        class ForeignType(DjangoObjectType):
            class Meta:
                model = Author
                registry = registry_a

        with self.assertRaises(ValueError):
            registry_b.register(ForeignType)

    def test_register_list_type_round_trip(self):
        """register_list_type stores one canonical list type per model."""
        registry = Registry()
        sentinel = object()
        registry.register_list_type(BasicModel, sentinel)
        self.assertIs(registry.get_list_type_for_model(BasicModel), sentinel)
        self.assertIsNone(registry.get_list_type_for_model(Author))

    def test_registry_singleton(self):
        """Test that registry is singleton."""
        registry1 = get_global_registry()
        registry2 = get_global_registry()

        # Should return the same instance
        self.assertEqual(id(registry1), id(registry2))

    def test_registry_enum_and_directive_stores(self):
        """Enums and directives live in their own namespaces."""
        registry = Registry()
        sentinel_enum = object()
        sentinel_directive = object()

        registry.register_enum("MyEnum", sentinel_enum)
        registry.register_directive("my_directive", sentinel_directive)

        self.assertIs(registry.get_type_for_enum("MyEnum"), sentinel_enum)
        self.assertIs(registry.get_directive("my_directive"), sentinel_directive)
        # Unknown keys return None rather than raising.
        self.assertIsNone(registry.get_type_for_enum("absent"))
        self.assertIsNone(registry.get_directive("absent"))

    def test_registry_string_representation(self):
        """Test registry string representation."""
        registry = get_global_registry()

        # Should have string representation
        str_repr = str(registry)
        self.assertIsInstance(str_repr, str)

        # Should have repr
        repr_str = repr(registry)
        self.assertIsInstance(repr_str, str)


class RegistryKeyCollisionTest(TestCase):
    """Keying by model class avoids name-based collisions (area 1)."""

    def test_same_class_name_different_models_do_not_collide(self):
        # Two distinct classes that share a __name__ (e.g. blog.Post and
        # forum.Post) must register independently -- not overwrite each other.
        registry = Registry()
        post_a = type("Post", (), {})
        post_b = type("Post", (), {})

        registry.register_list_type(post_a, "list_a")
        registry.register_list_type(post_b, "list_b")

        self.assertEqual(registry.get_list_type_for_model(post_a), "list_a")
        self.assertEqual(registry.get_list_type_for_model(post_b), "list_b")

    def test_enums_do_not_collide_with_types(self):
        # An enum keyed "post" lives in its own namespace, separate from a model
        # type for a class named "Post".
        registry = Registry()
        model = type("Post", (), {})
        registry.register_list_type(model, "list_type")
        registry.register_enum("post", "enum_type")

        self.assertEqual(registry.get_type_for_enum("post"), "enum_type")
        self.assertEqual(registry.get_list_type_for_model(model), "list_type")

    def test_output_and_input_actions_are_separate(self):
        registry = Registry()
        model = type("Thing", (), {})
        # Drive _types via get/round-trip using the (model, for_input) key space.
        registry._types[(model, None)] = "output"
        registry._types[(model, "create")] = "create_input"

        self.assertEqual(registry.get_type_for_model(model), "output")
        self.assertEqual(
            registry.get_type_for_model(model, for_input="create"), "create_input"
        )

    def test_register_rejects_non_object_type(self):
        with self.assertRaises(TypeError):
            Registry().register(str)

    def test_register_rejects_foreign_registry(self):
        class AuthorType(DjangoObjectType):
            class Meta:
                model = Author

        # AuthorType is bound to the global registry, not this fresh one.
        with self.assertRaises(ValueError):
            Registry().register(AuthorType)
