# -*- coding: utf-8 -*-
"""Atomic, relation-aware nested create/update via NestedFieldsMixin."""

from types import SimpleNamespace

from django.test import TestCase

from django_graphex import DjangoModelType
from tests.models import Author, Category, Post, Tag


class PostForwardType(DjangoModelType):
    class Meta:
        model = Post
        nested_fields = {"author": Author}


class PostM2MType(DjangoModelType):
    class Meta:
        model = Post
        nested_fields = {"tags": Tag}


class AuthorReverseType(DjangoModelType):
    class Meta:
        model = Author
        nested_fields = {"posts": Post}


def _info():
    """Minimal resolve info: only `context.META`/`FILES` are read by CRUD."""
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls, data):
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.create(None, _info(), **kwargs)


def _update(type_cls, data):
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.update(None, _info(), **kwargs)


class ForwardFKTest(TestCase):
    def test_creates_and_links_forward_fk_child(self):
        result = _create(
            PostForwardType, {"title": "Hello", "author": {"name": "Neil"}}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Author.objects.count(), 1)
        post = Post.objects.get()
        self.assertEqual(post.title, "Hello")
        self.assertEqual(post.author.name, "Neil")

    def test_parent_failure_rolls_back_child(self):
        # `title` is required -> parent invalid; the forward author must NOT
        # remain persisted (atomic rollback).
        result = _create(PostForwardType, {"author": {"name": "Orphan"}})
        self.assertFalse(result.ok)
        self.assertEqual(Author.objects.count(), 0)
        self.assertEqual(Post.objects.count(), 0)

    def test_nested_validation_error_is_prefixed(self):
        result = _create(PostForwardType, {"title": "x", "author": {"name": "a" * 200}})
        self.assertFalse(result.ok)
        fields = {e.field for e in result.errors}
        self.assertIn("author.name", fields)
        self.assertEqual(Author.objects.count(), 0)


class M2MTest(TestCase):
    def test_creates_and_adds_m2m_children(self):
        author = Author.objects.create(name="A")
        result = _create(
            PostM2MType,
            {
                "title": "Tagged",
                "author": author.id,
                "tags": [{"label": "django"}, {"label": "graphql"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Tag.objects.count(), 2)
        post = Post.objects.get()
        self.assertEqual(
            set(post.tags.values_list("label", flat=True)), {"django", "graphql"}
        )


class ReverseFKTest(TestCase):
    def test_creates_reverse_fk_children_linked_to_parent(self):
        result = _create(
            AuthorReverseType,
            {"name": "Writer", "posts": [{"title": "P1"}, {"title": "P2"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        author = Author.objects.get()
        self.assertEqual(author.posts.count(), 2)
        self.assertEqual(
            set(author.posts.values_list("title", flat=True)), {"P1", "P2"}
        )

    def test_reverse_child_failure_rolls_back_parent(self):
        result = _create(
            AuthorReverseType,
            {"name": "Writer", "posts": [{"title": "ok"}, {"body": "no title"}]},
        )
        self.assertFalse(result.ok)
        self.assertEqual(Author.objects.count(), 0)
        self.assertEqual(Post.objects.count(), 0)


class UpsertTest(TestCase):
    def test_update_with_child_pk_updates_existing_child(self):
        author = Author.objects.create(name="Old")
        category = Category.objects.create(title="C")
        post = Post.objects.create(title="T", author=author, category=category)

        result = _update(
            PostForwardType,
            {"id": post.id, "author": {"id": author.id, "name": "New"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Author.objects.count(), 1)  # no new author
        author.refresh_from_db()
        self.assertEqual(author.name, "New")


class EmptyPayloadTest(TestCase):
    def test_empty_m2m_payload_is_noop(self):
        author = Author.objects.create(name="A")
        result = _create(
            PostM2MType, {"title": "NoTags", "author": author.id, "tags": []}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Tag.objects.count(), 0)
        self.assertEqual(Post.objects.get().tags.count(), 0)
