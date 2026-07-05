"""Seed the playground with sample data (idempotent-ish: clears first).

The dataset is intentionally large enough to exercise multi-page nested
queries. With the default "DEFAULT_PAGE_SIZE" / "default_limit" of 10, a
nested list that holds <= 10 rows always fits in a single page, so the DB-side
"ROW_NUMBER() OVER (PARTITION BY ...)" window-pagination path and multi-page
nested filtering are never reached. The defaults below (15 authors x 12 posts
each) push every author's "posts" list past one page, so a query asking for
"results(offset: 10, ...)" on a nested list returns a genuine second page.

Counts are configurable so the demo can be scaled up or down without editing
the file:

    python manage.py seed                       # defaults: 15 authors x 12 posts
    python manage.py seed --authors 25 --posts 15
    python manage.py seed --scale 2             # doubles authors + posts
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser

from blog.models import (
    Account,
    Attachment,
    Author,
    Category,
    Comment,
    Invoice,
    Note,
    Post,
    Tag,
)

User = get_user_model()

# Defaults sized so each author's nested ``posts`` list spans MORE THAN ONE page
# at the playground's default page size of 10 (so window pagination + multi-page
# nested filtering are actually exercised by the example queries).
DEFAULT_AUTHORS = 15
DEFAULT_POSTS_PER_AUTHOR = 12
DEFAULT_COMMENTS_PER_POST = 3
DEFAULT_NOTES = 12


class Command(BaseCommand):
    """Management command that populates the playground database with demo data.

    Clears the blog tables and recreates authors, posts, comments, notes and the
    typed-GFK account/invoice/attachment fixtures, sized so nested "posts" lists
    span multiple pages at the default page size (exercising window pagination).
    """

    help = "Populate the database with demo authors, posts, comments and notes."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the command-line options that scale the generated dataset.

        Args:
            parser: The argument parser to which the "--authors", "--posts",
                "--comments", "--notes" and "--scale" options are added.
        """
        parser.add_argument(
            "--authors",
            type=int,
            default=DEFAULT_AUTHORS,
            help=f"Number of authors to create (default {DEFAULT_AUTHORS}).",
        )
        parser.add_argument(
            "--posts",
            type=int,
            default=DEFAULT_POSTS_PER_AUTHOR,
            help=(
                "Number of posts per author (default "
                f"{DEFAULT_POSTS_PER_AUTHOR}). Keep this > the page size (10) so "
                "nested `posts` lists span multiple pages."
            ),
        )
        parser.add_argument(
            "--comments",
            type=int,
            default=DEFAULT_COMMENTS_PER_POST,
            help=f"Number of comments per post (default {DEFAULT_COMMENTS_PER_POST}).",
        )
        parser.add_argument(
            "--notes",
            type=int,
            default=DEFAULT_NOTES,
            help=f"Number of private notes for the demo user (default {DEFAULT_NOTES}).",
        )
        parser.add_argument(
            "--scale",
            type=int,
            default=1,
            help=(
                "Convenience multiplier applied to --authors and --posts "
                "(default 1). E.g. --scale 2 doubles both."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Rebuild the demo dataset from the resolved option counts.

        Deletes existing blog rows, creates a demo superuser, then bulk-creates
        authors, posts, tags, comments, notes and the typed-GFK fixtures before
        writing a summary line to stdout.

        Args:
            args: Positional arguments forwarded by Django's command runner
                (unused).
            options: Parsed option values, including "authors", "posts",
                "comments", "notes" and "scale".
        """
        n_authors = max(1, options["authors"] * options["scale"])
        n_posts = max(1, options["posts"] * options["scale"])
        n_comments = max(0, options["comments"])
        n_notes = max(0, options["notes"])

        Attachment.objects.all().delete()
        Account.objects.all().delete()
        Invoice.objects.all().delete()
        Comment.objects.all().delete()
        Post.objects.all().delete()
        Author.objects.all().delete()
        Category.objects.all().delete()
        Tag.objects.all().delete()
        Note.objects.all().delete()

        # A demo user (also useful to log into /admin for private queries).
        # Reset the password/flags on every seed so re-running is idempotent even
        # against a pre-existing `demo` user.
        user, _created = User.objects.get_or_create(
            username="demo", defaults={"email": "demo@example.com"}
        )
        user.set_password("demo12345")
        user.is_staff = True
        user.is_superuser = True
        user.save()

        categories = [Category.objects.create(name=n) for n in ("Tech", "Life", "News")]
        tags = [Tag.objects.create(name=n) for n in ("django", "graphql", "python")]

        statuses = [Post.Status.DRAFT, Post.Status.PUBLISHED, Post.Status.ARCHIVED]

        # Bulk-create for speed: build all posts/comments in memory, then write
        # them in a couple of round-trips instead of one INSERT per row. (M2M tag
        # links still need per-post .add() since bulk_create skips m2m.)
        total_posts = 0
        total_comments = 0
        for a in range(n_authors):
            author = Author.objects.create(
                name=f"Author {a}",
                bio=f"Bio of author {a}",
                user=user if a == 0 else None,
            )
            posts = Post.objects.bulk_create(
                [
                    Post(
                        title=f"Author {a} Post {p}",
                        body=f"Body of post {p} by author {a}.",
                        status=statuses[(a + p) % 3],
                        author=author,
                        category=categories[(a + p) % len(categories)],
                    )
                    for p in range(n_posts)
                ]
            )
            total_posts += len(posts)

            # Attach a tag per post (M2M -- one .add() per post; bulk_create skips m2m).
            for p, post in enumerate(posts):
                post.tags.add(tags[p % len(tags)])

            comments = []
            for post in posts:
                comments.extend(
                    Comment(
                        post=post,
                        author_name=f"Commenter {c}",
                        text=f"Comment {c}",
                    )
                    for c in range(n_comments)
                )
            if comments:
                Comment.objects.bulk_create(comments)
                total_comments += len(comments)

        for n in range(n_notes):
            Note.objects.create(
                title=f"Demo note {n}", body="A private note.", owner=user
            )

        # Typed-GFK demo: a mix of Account and Invoice targets so the GFK union
        # query returns BOTH member types and the per-content-type GenericPrefetch
        # path is exercised (Django 5.0+). NOTE: every Attachment.target must be an
        # AttachmentTargetUnion member (Account or Invoice) — a Post target would
        # break the `attachments { target { ... } }` union query at resolve time
        # ("PostType is not a possible type for AttachmentTargetUnion"). The reverse
        # `GenericRelation` (Post.attachments) is wired on the model side; it is not
        # populated here precisely to keep the union demo runnable.
        accounts = [
            Account.objects.create(label="Checking", balance="1200.50"),
            Account.objects.create(label="Savings", balance="9800.00"),
        ]
        invoices = [
            Invoice.objects.create(number="INV-001", amount="250.00"),
            Invoice.objects.create(number="INV-002", amount="999.99"),
        ]
        targets = [accounts[0], invoices[0], accounts[1], invoices[1]]
        for i, target in enumerate(targets):
            Attachment.objects.create(caption=f"Attachment {i}", target=target)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: {n_authors} authors, {total_posts} posts "
                f"({n_posts}/author), {total_comments} comments, {n_notes} notes, "
                "2 accounts, 2 invoices, 4 attachments. "
                "Login: demo / demo12345 (superuser). "
                "Each author's `posts` list spans multiple pages at page size 10 — "
                "try `results(offset: 10, ...)` on a nested list."
            )
        )
