"""Library-agnostic blog domain for the GraphQL benchmark.

Pure Django models — no GraphQL library imports. Every benchmarked library
(django-graphex, graphene-django, strawberry-graphql-django, ariadne) builds
its schema on top of THESE SAME models against THE SAME seeded database, so the
comparison is apples-to-apples: same rows, same relations, same indexes.

Relational shape (chosen to exercise the classic GraphQL N+1 stressor):

    Author 1--* Post *--* Tag
                  |
                  *--* Comment

`Post.status` is a plain CharField with choices (draft/published); each library
maps it to whatever it maps CharFields-with-choices to (enum or string) — the
benchmark only ever reads it as a scalar, so representation differences are
irrelevant to fairness.
"""

from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    bio = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name


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


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    author = models.ForeignKey(
        Author, on_delete=models.CASCADE, related_name="posts"
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posts",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    views_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="comments"
    )
    author_name = models.CharField(max_length=100)
    text = models.TextField()
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment #{self.pk} on post {self.post_id}"
