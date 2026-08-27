"""Blog models: a small relational graph to exercise the library.

Relations let us demo nested lists / N+1 (Author -> posts, Post -> comments),
and Post.status is a TextChoices field (a GraphQL enum is generated from it).

The "Account" / "Invoice" / "Attachment" trio at the bottom backs the
v1.2.0 typed-"GenericForeignKey" demo: "Attachment.target" is a GFK that the
schema exposes as a "DjangoUnionType" (see "blog/schema.py"). The app
"django.contrib.contenttypes" is already in "INSTALLED_APPS" so no settings
change is needed — only a migration ("make migrate" / "make reset").
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Category(models.Model):
    """A post category, referenced by "Post.category" as a nullable foreign key.

    Demonstrates a to-one relation that generates a nested GraphQL object field
    on "PostType".
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        """Model metadata.

        Overrides the plural verbose name so the admin reads "categories"
        instead of the default "categorys".
        """

        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Tag(models.Model):
    """A tag linked to posts through a many-to-many relation.

    Demonstrates how a "ManyToManyField" ("Post.tags") is exposed as a nested
    paginated list on both sides of the relation.
    """

    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Author(models.Model):
    """A post author, optionally linked to a Django user.

    The nullable "user" foreign key lets the schema scope "my posts" to the
    request's authenticated user, demonstrating per-request query narrowing.
    """

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
    """A blog post owned by an author, with tags, comments and a status enum.

    The "status" "TextChoices" field is surfaced as a generated GraphQL enum,
    and the "posts" reverse relations (from "Author" and "Category") drive the
    nested-list / N+1 demonstrations.
    """

    class Status(models.TextChoices):
        """Publication state of a post, generated as a GraphQL enum.

        Members map to the "draft", "published" and "archived" string values
        persisted in the "status" column.
        """

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
    """A comment on a post, exposed as the "comments" nested list on "PostType".

    Backs the second-level nesting (Author -> posts -> comments) used to
    demonstrate multi-page nested queries and N+1 avoidance.

    "internal_note" is the projection fixture: an ordinary editable column that
    the schema hides on reads AND writes (see "CommentType" and
    "CommentModelType" in "blog/schema.py"), so a reader can watch one
    projection travel through the output type, the filter input, the write
    input AND the nested child input a "Meta.nested_fields" parent exposes.

    The subscription surface is the fourth place it has to be hidden, and the
    only one that does NOT inherit it: see "CommentSubscription.Meta", which
    restates the exclusion because a model-bound subscription is measured
    against its own "Meta" alone.
    """

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author_name = models.CharField(max_length=100)
    text = models.TextField()
    # Moderation scratchpad. Nothing the playground ships can write it -- no
    # admin registration, no seed value, and every write input projects it
    # away -- so it stays empty unless you set it from a shell or a migration.
    # That is deliberate: it exists to be a column you can watch NOT come back.
    internal_note = models.TextField(blank=True, default="")
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
    """One member of the typed-GFK union, targeted by "Attachment.target".

    Together with "Invoice" it forms the "AttachmentTargetUnion" that the
    schema exposes as a "DjangoUnionType" (v1.2.0 demo).
    """

    label = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.label


class Invoice(models.Model):
    """The other member of the typed-GFK union, targeted by "Attachment.target".

    Paired with "Account" under "AttachmentTargetUnion" so clients select
    per-member fields through inline fragments.
    """

    number = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.number


class Attachment(models.Model):
    """A caption attached to either an Account or an Invoice via a GFK.

    The "target" GenericForeignKey is routed by the optimizer through a
    per-content-type GenericPrefetch (one .only()-narrowed queryset per content
    type) on Django 5.0+, batched across all parents (no N+1).
    """

    caption = models.CharField(max_length=200)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return self.caption


# --------------------------------------------------------------------------- #
# File upload demos. ONE column, TWO ways in:                                  #
#   - base64 inside the JSON body   -> uploadDocument  (v1.3.0)                #
#   - a multipart part on the write host -> documentCreate / documentUpdate    #
#     (2.2.0, the release that feature is named for)                           #
# Both land on Document.attached_file. See blog/schema.py.                     #
#                                                                              #
# The column is named with TWO words on purpose: a multipart part is matched   #
# against the camelCase alias the SDL publishes AND the snake_case model       #
# attribute, and a one-word name spells those identically, so it can never     #
# show the reader that both work.                                              #
# --------------------------------------------------------------------------- #
class Document(models.Model):
    """A simple document with a file attachment — demos both upload paths.

    Example GraphQL mutation (the base64 path)::

        mutation {
            uploadDocument(
                name: "my-report.pdf"
                file: {
                    filename: "report.pdf"
                    contentType: "application/pdf"
                    data: "<base64 string here>"
                }
            ) { ok name }
        }
    """

    name = models.CharField(max_length=200)
    attached_file = models.FileField(upload_to="documents/", blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
