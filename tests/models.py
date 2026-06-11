from __future__ import unicode_literals

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class DummyModel(models.Model):
    """
    Base for test models that sets app_label, so they play nicely.
    """

    class Meta:
        app_label = "tests"
        abstract = True


class BasicModel(DummyModel):
    text = models.CharField(
        max_length=100,
        verbose_name=_("Text comes here"),
        help_text=_("Text description."),
    )


# --- Relational models used by the query-optimization tests --------------- #
class Category(DummyModel):
    title = models.CharField(max_length=100)


class Author(DummyModel):
    name = models.CharField(max_length=100)
    bio = models.TextField(default="")

    @property
    def display_name(self):
        """Computed property that reads ``name`` (only() full-model safety)."""
        return "Author: {}".format(self.name)


class Tag(DummyModel):
    label = models.CharField(max_length=50)


class Post(DummyModel):
    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(Author, related_name="posts", on_delete=models.CASCADE)
    category = models.ForeignKey(
        Category, related_name="posts", null=True, on_delete=models.SET_NULL
    )
    tags = models.ManyToManyField(Tag, related_name="posts", blank=True)
    co_authors = models.ManyToManyField(
        Author, related_name="coauthored_posts", blank=True
    )
    views = models.PositiveIntegerField(default=0)


class Comment(DummyModel):
    """Reverse-FK from Post for aggregate annotation targets (phase-d)."""

    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    body = models.TextField(default="")


class AuthorProfile(DummyModel):
    """One-to-one with Author; used for grandchild-select survival test (phase-d).

    Named AuthorProfile (not Profile) to avoid collision with the Profile model
    defined in test_optimizer_coverage.py.
    """

    author = models.OneToOneField(
        Author, related_name="author_profile", on_delete=models.CASCADE
    )
    bio = models.TextField(default="")


# --- Model used by the DjangoModelType queryset-hook tests ------------ #
class HookModel(DummyModel):
    text = models.CharField(max_length=100)


# --- UUID primary-key models used by the plain-pk filtering tests ---------- #
class UUIDThing(DummyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)


class UUIDItem(DummyModel):
    label = models.CharField(max_length=100)
    thing = models.ForeignKey(UUIDThing, related_name="items", on_delete=models.CASCADE)


# --- Track 2: union / interface MVP models -------------------------------- #
# Concrete member models referenced by a GFK union and an interface. Kept here
# (not inline in the test module) so they share the "tests" app_label and play
# nicely with the schema build, mirroring the existing relational models above.
# Names are ``Track2``-prefixed to avoid colliding with same-named models that
# other test modules register in the shared "tests" app (e.g. Account).
class Track2Account(DummyModel):
    """A GFK-union member model."""

    balance = models.IntegerField(default=0)
    label = models.CharField(max_length=50, default="")


class Track2Invoice(DummyModel):
    """A second GFK-union member model (distinct table from Track2Account)."""

    amount = models.IntegerField(default=0)
    note = models.CharField(max_length=50, default="")


class Track2AccountProxy(Track2Account):
    """A PROXY of ``Track2Account`` sharing its concrete table.

    Used by the GFK-union content-type de-dup tests: a proxy and its concrete
    base map to DIFFERENT ContentTypes under ``for_concrete_model=False`` but to
    the SAME ContentType under ``for_concrete_model=True`` (the GFK default).
    This is exactly the case where the de-dup must mirror the GFK's
    ``for_concrete_model`` to avoid Django's duplicate-content-type ValueError.
    """

    class Meta:
        app_label = "tests"
        proxy = True


# GFK owner for the union-converter test. A standalone model (not the phase-d
# ``Comment`` above, which other optimizer tests depend on) carrying a single
# GenericForeignKey ``target`` whose explicit members are the Track2 members.
class Track2GfkComment(DummyModel):
    body = models.TextField(default="")
    target_ct = models.ForeignKey(
        ContentType, null=True, on_delete=models.CASCADE, related_name="+"
    )
    target_id = models.PositiveIntegerField(null=True)
    target = GenericForeignKey("target_ct", "target_id")


# Interface members (abstract-base field sharing): two concrete models sharing
# a ``name`` field exposed through an interface.
class Track2Book(DummyModel):
    name = models.CharField(max_length=100)
    pages = models.IntegerField(default=0)


class Track2Magazine(DummyModel):
    name = models.CharField(max_length=100)
    issue = models.IntegerField(default=0)
