"""Blog models: a small relational graph to exercise the library.

Relations let us demo nested lists / N+1 (Author -> posts, Post -> comments),
and Post.status is a TextChoices field (a GraphQL enum is generated from it).

The ``Account`` / ``Invoice`` / ``Attachment`` trio at the bottom backs the
v1.2.0 typed-``GenericForeignKey`` demo: ``Attachment.target`` is a GFK that the
schema exposes as a ``DjangoUnionType`` (see ``blog/schema.py``). ``django.
contrib.contenttypes`` is already in ``INSTALLED_APPS`` so no settings change is
needed — only a migration (``make migrate`` / ``make reset``).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Author(models.Model):
    # Linked to a Django user so "my posts" can be scoped per request.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authors",
    )
    name = models.CharField(max_length=100)
    bio = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    # On Django 5.0+ you may pass the enum directly (choices=Status); using
    # `.choices` keeps it working on every supported Django version.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="posts")
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posts",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")
    created = models.DateTimeField(auto_now_add=True)
    # Reverse side of the GenericForeignKey on Attachment. Lets a Post expose its
    # attachments and demonstrates the GenericRelation prefetch + .only() narrowing.
    attachments = GenericRelation("Attachment")

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author_name = models.CharField(max_length=100)
    text = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment #{self.pk} on post {self.post_id}"


class Note(models.Model):
    """A per-user note: backs the DjangoModelType mutations / permissions /

    per-request scoping ("my notes") / private subscription demos.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


# --------------------------------------------------------------------------- #
# Typed GenericForeignKey demo (v1.2.0).                                       #
# Account and Invoice are the two GFK member models; Attachment.target points  #
# at either of them. schema.py exposes `target` as a DjangoUnionType so clients #
# select per-member fields via inline fragments.                               #
# --------------------------------------------------------------------------- #
class Account(models.Model):
    label = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.label


class Invoice(models.Model):
    number = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.number


class Attachment(models.Model):
    """A caption attached to either an Account or an Invoice via a GFK.

    ``target`` is a GenericForeignKey: the optimizer routes it through a
    per-content-type GenericPrefetch (one .only()-narrowed queryset per content
    type) on Django 5.0+, batched across all parents (no N+1).
    """

    caption = models.CharField(max_length=200)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return self.caption
