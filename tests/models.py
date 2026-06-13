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


# A GFK-union member model carrying a FORWARD FK head. Used to exercise the
# member-level ``child_select`` merge in ``_collect_gfk_union_buckets``: when a
# union member's narrowed plan pulls a forward-FK relation (here ``customer``),
# ``_compute_child_only`` populates ``PrefetchPlan.child_select`` with that head,
# so two split inline fragments over this member merge their select_related heads.
class Track2Order(DummyModel):
    customer = models.ForeignKey(
        Track2Account, related_name="orders", on_delete=models.CASCADE
    )
    # A SECOND forward FK so two split fragments over this member can pull
    # DISTINCT select_related heads (``customer`` vs ``invoice``); that divergence
    # is what makes the member-level ``child_select`` merge actually APPEND.
    invoice = models.ForeignKey(
        Track2Invoice,
        related_name="orders",
        null=True,
        on_delete=models.SET_NULL,
    )
    total = models.IntegerField(default=0)
    ref = models.CharField(max_length=50, default="")


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


# --- nested-input-type-fix models ----------------------------------------- #
# A self-referential model: a category nested into itself exercises the
# single-level recursion guard (the on-demand GENERIC child stops at [ID!]).
class NestedTreeNode(DummyModel):
    label = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )


# A parent whose reverse-FK accessor is a MULTI-WORD snake_case name. The
# GraphQL surface camelCases it (``blogComments``) and graphene deserializes it
# back to the Django attr ``blog_comments`` -- which must match the nested_fields
# dict key so ``data.pop(field)`` finds the object payload (ISSUE 7).
class SnakeParent(DummyModel):
    title = models.CharField(max_length=100)


class SnakeChild(DummyModel):
    text = models.CharField(max_length=100)
    snake_parent = models.ForeignKey(
        SnakeParent,
        related_name="blog_comments",
        on_delete=models.CASCADE,
    )


# A parent/child pair used ONLY by the nested-FIRST ordering test, so the
# GLOBAL registry slot for ``(OrderParent, "create")`` is controlled entirely
# within that one test (no sibling test module touches these models).
class OrderParent(DummyModel):
    title = models.CharField(max_length=100)


class OrderChild(DummyModel):
    text = models.CharField(max_length=100)
    order_parent = models.ForeignKey(
        OrderParent,
        related_name="kids",
        on_delete=models.CASCADE,
    )


# --- Custom-PK model used by the delete-pk-attname fix tests (#18) --------- #
# The PK is a slug CharField (not ``id``), which exercises the
# ``old_obj._meta.pk.attname`` fix in mutation.py and types.py delete().
class CustomPKProduct(DummyModel):
    slug = models.CharField(max_length=100, primary_key=True)
    title = models.CharField(max_length=200)


# --- Model used by the DjangoObjectType.get_queryset hook tests (#58) ------- #
# A separate model (not HookModel) so the fix tests don't collide with the
# DjangoModelType queryset-hook tests that also use HookModel.
class ScopedArticle(DummyModel):
    """Article model for testing the DjangoObjectType.get_queryset security hook."""

    title = models.CharField(max_length=200)
    is_public = models.BooleanField(default=True)
