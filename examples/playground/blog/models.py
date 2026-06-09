"""Blog models: a small relational graph to exercise the library.

Relations let us demo nested lists / N+1 (Author -> posts, Post -> comments),
and Post.status is a TextChoices field (a GraphQL enum is generated from it).
"""

from django.conf import settings
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
