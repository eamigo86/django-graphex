"""Deterministic bulk seed for the GraphQL benchmark.

Everything is generated from random.Random(42) so every library benchmarks
against a byte-identical database. Rows are created with bulk_create in
batches to keep the whole seed well under two minutes.

Scale:
    1,000 authors
       20 categories
      100 tags
   10,000 posts        (10 per author, ~80% published)
   50,000 comments     (5 per post)
   ~30,000 post-tag links (~3 tags per post, via the M2M through table)

The seed is idempotent-by-truncation: it clears the tables first so re-running
run_all.sh always starts from the same state.
"""

import random

from django.core.management.base import BaseCommand
from django.db import transaction

from benchapp.models import Author, Category, Comment, Post, Tag

SEED = 42
N_AUTHORS = 1_000
N_CATEGORIES = 20
N_TAGS = 100
POSTS_PER_AUTHOR = 10
COMMENTS_PER_POST = 5
TAGS_PER_POST = 3
PUBLISHED_RATIO = 0.80
BATCH = 2_000


class Command(BaseCommand):
    """Seed the shared benchmark database deterministically.

    Every adapter receives the same relation shape and generated values.
    """

    help = "Seed the benchmark database with a deterministic blog dataset."

    def add_arguments(self, parser: object) -> None:
        """Register benchmark seed command options.

        Args:
            parser: Argument parser supplied by Django.
        """
        parser.add_argument(
            "--authors",
            type=int,
            default=N_AUTHORS,
            help=(
                "Number of authors to seed (default: %(default)s). "
                "Posts/author and comments/post ratios stay fixed."
            ),
        )

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Replace benchmark rows with one deterministic dataset.

        Args:
            *args: Unused positional command arguments.
            **options: Parsed command options, including the author count.
        """
        rng = random.Random(SEED)
        n_authors = options["authors"]

        # Clear existing data (idempotent re-seed). Order respects FKs.
        Comment.objects.all().delete()
        Post.tags.through.objects.all().delete()
        Post.objects.all().delete()
        Tag.objects.all().delete()
        Category.objects.all().delete()
        Author.objects.all().delete()

        # ---- Authors --------------------------------------------------------
        authors = [
            Author(
                name=f"Author {i}",
                email=f"author{i}@bench.example",
                bio=f"Bio for author {i}. " * (1 + rng.randint(0, 3)),
            )
            for i in range(n_authors)
        ]
        Author.objects.bulk_create(authors, batch_size=BATCH)
        author_ids = list(
            Author.objects.order_by("id").values_list("id", flat=True)
        )

        # ---- Categories -----------------------------------------------------
        categories = [Category(name=f"Category {i}") for i in range(N_CATEGORIES)]
        Category.objects.bulk_create(categories, batch_size=BATCH)
        category_ids = list(
            Category.objects.order_by("id").values_list("id", flat=True)
        )

        # ---- Tags -----------------------------------------------------------
        tags = [Tag(name=f"Tag {i}") for i in range(N_TAGS)]
        Tag.objects.bulk_create(tags, batch_size=BATCH)
        tag_ids = list(Tag.objects.order_by("id").values_list("id", flat=True))

        # ---- Posts ----------------------------------------------------------
        posts = []
        post_seq = 0
        for author_id in author_ids:
            for _ in range(POSTS_PER_AUTHOR):
                published = rng.random() < PUBLISHED_RATIO
                posts.append(
                    Post(
                        author_id=author_id,
                        category_id=rng.choice(category_ids),
                        title=f"Post {post_seq}",
                        body=f"Body of post {post_seq}. " * (2 + rng.randint(0, 5)),
                        status=(
                            Post.Status.PUBLISHED
                            if published
                            else Post.Status.DRAFT
                        ),
                        views_count=rng.randint(0, 10_000),
                    )
                )
                post_seq += 1
        Post.objects.bulk_create(posts, batch_size=BATCH)
        post_ids = list(Post.objects.order_by("id").values_list("id", flat=True))

        # ---- Comments -------------------------------------------------------
        comments = []
        for post_id in post_ids:
            for c in range(COMMENTS_PER_POST):
                comments.append(
                    Comment(
                        post_id=post_id,
                        author_name=f"Commenter {rng.randint(0, 9999)}",
                        text=f"Comment {c} on post {post_id}. "
                        * (1 + rng.randint(0, 2)),
                        is_approved=rng.random() < 0.9,
                    )
                )
        Comment.objects.bulk_create(comments, batch_size=BATCH)

        # ---- Post <-> Tag M2M (through table, bulk) -------------------------
        Through = Post.tags.through
        links = []
        for post_id in post_ids:
            chosen = rng.sample(tag_ids, TAGS_PER_POST)
            for tag_id in chosen:
                links.append(Through(post_id=post_id, tag_id=tag_id))
        Through.objects.bulk_create(links, batch_size=BATCH)

        # ---- Report ---------------------------------------------------------
        self.stdout.write(self.style.SUCCESS("Seed complete:"))
        self.stdout.write(f"  authors    : {Author.objects.count()}")
        self.stdout.write(f"  categories : {Category.objects.count()}")
        self.stdout.write(f"  tags       : {Tag.objects.count()}")
        self.stdout.write(f"  posts      : {Post.objects.count()}")
        self.stdout.write(f"  comments   : {Comment.objects.count()}")
        self.stdout.write(f"  post-tags  : {Through.objects.count()}")
