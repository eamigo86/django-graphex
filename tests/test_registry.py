# -*- coding: utf-8 -*-
"""Tests for django_graphex.registry module."""

from __future__ import annotations

from django.test import TestCase

from django_graphex.registry import Registry, get_global_registry
from django_graphex.types import DjangoObjectType

from .models import Author, BasicModel


class RegistryTest(TestCase):
    """Test cases for the "Registry" class and the global registry singleton.

    Covers registration, rejection of invalid inputs, and the enum/
    directive/list-type namespaces.
    """

    def test_get_global_registry(self) -> None:
        """Assert "get_global_registry" returns a usable registry instance.

        If this fails, code relying on the process-wide registry singleton
        would have nothing to register types against.
        """
        registry = get_global_registry()

        # Should return a registry object
        self.assertIsNotNone(registry)

    def test_registry_model_registration(self) -> None:
        """Assert a "DjangoObjectType" registers itself and round-trips by model.

        If this fails, a model type declared with a custom registry would
        not be retrievable by its backing model, breaking any lookup that
        maps a Django model to its GraphQL type.
        """
        local_registry = Registry()

        class LocalType(DjangoObjectType):
            class Meta:
                model = BasicModel
                registry = local_registry

        # The metaclass registers the type on creation; it round-trips by model.
        self.assertIs(local_registry.get_type_for_model(BasicModel), LocalType)

    def test_register_rejects_non_object_type(self) -> None:
        """Assert "register" only accepts DjangoObjectType/DjangoInputObjectType.

        If this fails, arbitrary classes (including plain Django models)
        could be registered as GraphQL types, corrupting the registry.

        Raises:
            TypeError: Not raised by the test itself; asserted via
                "assertRaises" around the invalid "register" call.
        """
        registry = Registry()
        with self.assertRaises(TypeError):
            registry.register(BasicModel)

    def test_register_rejects_foreign_registry(self) -> None:
        """Assert a type bound to a different registry cannot be re-registered.

        If this fails, a type created against one registry could be
        silently adopted by another, breaking registry isolation.

        Raises:
            ValueError: Not raised by the test itself; asserted via
                "assertRaises" around the cross-registry "register" call.
        """
        registry_a = Registry()
        registry_b = Registry()

        class ForeignType(DjangoObjectType):
            class Meta:
                model = Author
                registry = registry_a

        with self.assertRaises(ValueError):
            registry_b.register(ForeignType)

    def test_register_list_type_round_trip(self) -> None:
        """Assert "register_list_type" stores one canonical list type per model.

        If this fails, list types would not be retrievable by their model,
        or would leak across unrelated models.
        """
        registry = Registry()
        sentinel = object()
        registry.register_list_type(BasicModel, sentinel)
        self.assertIs(registry.get_list_type_for_model(BasicModel), sentinel)
        self.assertIsNone(registry.get_list_type_for_model(Author))

    def test_registry_singleton(self) -> None:
        """Assert "get_global_registry" always returns the same instance.

        If this fails, different parts of the codebase could end up
        registering types against different registry instances, splitting
        the schema's type graph.
        """
        registry1 = get_global_registry()
        registry2 = get_global_registry()

        # Should return the same instance
        self.assertEqual(id(registry1), id(registry2))

    def test_registry_enum_and_directive_stores(self) -> None:
        """Assert enums and directives live in their own, independent namespaces.

        If this fails, registering an enum or directive could collide with
        entries in another namespace, or unknown keys could raise instead
        of returning None.
        """
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


class RegistryKeyCollisionTest(TestCase):
    """Keying by model class avoids name-based collisions (area 1).

    Same-named classes, enum keys, and input/output key spaces must all
    stay independent of each other.
    """

    def test_same_class_name_different_models_do_not_collide(self) -> None:
        """Assert two classes sharing a __name__ register independently.

        If this fails, distinct models that happen to share a class name
        (for example, "blog.Post" and "forum.Post") would overwrite each
        other's list-type registration.
        """
        # Two distinct classes that share a __name__ (e.g. blog.Post and
        # forum.Post) must register independently -- not overwrite each other.
        registry = Registry()
        post_a = type("Post", (), {})
        post_b = type("Post", (), {})

        registry.register_list_type(post_a, "list_a")
        registry.register_list_type(post_b, "list_b")

        self.assertEqual(registry.get_list_type_for_model(post_a), "list_a")
        self.assertEqual(registry.get_list_type_for_model(post_b), "list_b")

    def test_enums_do_not_collide_with_types(self) -> None:
        """Assert an enum key does not collide with a same-named model type.

        If this fails, an enum registered under a name (for example,
        "post") could be shadowed by, or shadow, an unrelated list type
        for a model class named "Post".
        """
        # An enum keyed "post" lives in its own namespace, separate from a model
        # type for a class named "Post".
        registry = Registry()
        model = type("Post", (), {})
        registry.register_list_type(model, "list_type")
        registry.register_enum("post", "enum_type")

        self.assertEqual(registry.get_type_for_enum("post"), "enum_type")
        self.assertEqual(registry.get_list_type_for_model(model), "list_type")

    def test_output_and_input_actions_are_separate(self) -> None:
        """Assert output and per-action input types are keyed independently.

        If this fails, an input type registered for one action (for
        example, "create") could collide with or shadow the plain output
        type for the same model.
        """
        registry = Registry()
        model = type("Thing", (), {})
        # Drive _types via get/round-trip using the (model, for_input) key space.
        registry._types[(model, None)] = "output"
        registry._types[(model, "create")] = "create_input"

        self.assertEqual(registry.get_type_for_model(model), "output")
        self.assertEqual(
            registry.get_type_for_model(model, for_input="create"), "create_input"
        )

    def test_register_rejects_non_object_type(self) -> None:
        """Assert registering a plain, non-GraphQL-type class raises "TypeError".

        If this fails, arbitrary classes could be registered as GraphQL
        types, corrupting the registry.

        Raises:
            TypeError: Not raised by the test itself; asserted via
                "assertRaises" around the invalid "register" call.
        """
        with self.assertRaises(TypeError):
            Registry().register(str)

    def test_register_rejects_foreign_registry(self) -> None:
        """Assert registering a type bound to a different registry raises.

        If this fails, a type created against the global registry could
        be silently adopted by an unrelated fresh registry instance.

        Raises:
            ValueError: Not raised by the test itself; asserted via
                "assertRaises" around the cross-registry "register" call.
        """

        class AuthorType(DjangoObjectType):
            class Meta:
                model = Author

        # AuthorType is bound to the global registry, not this fresh one.
        with self.assertRaises(ValueError):
            Registry().register(AuthorType)
