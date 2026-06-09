from __future__ import unicode_literals

import uuid

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
