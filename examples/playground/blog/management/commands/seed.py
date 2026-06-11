"""Seed the playground with sample data (idempotent-ish: clears first)."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

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


class Command(BaseCommand):
    help = "Populate the database with demo authors, posts, comments and notes."

    def handle(self, *args, **options):
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
        for a in range(5):
            author = Author.objects.create(
                name=f"Author {a}",
                bio=f"Bio of author {a}",
                user=user if a == 0 else None,
            )
            for p in range(4):  # 5 authors x 4 posts -> nested N+1 demo
                post = Post.objects.create(
                    title=f"Author {a} Post {p}",
                    body=f"Body of post {p} by author {a}.",
                    status=statuses[(a + p) % 3],
                    author=author,
                    category=categories[(a + p) % len(categories)],
                )
                post.tags.add(tags[p % len(tags)])
                for c in range(3):  # nested comments
                    Comment.objects.create(
                        post=post, author_name=f"Commenter {c}", text=f"Comment {c}"
                    )

        for n in range(3):
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
                "Seeded: 5 authors, 20 posts, 60 comments, 3 notes, "
                "2 accounts, 2 invoices, 4 attachments. "
                "Login: demo / demo12345 (superuser)."
            )
        )
