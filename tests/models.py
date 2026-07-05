"""Django models shared across the top-level test suite.

Registered once under the "tests" app label so every test module can build
schemas and queries against a stable, shared model surface instead of
redefining near-duplicate models per file. Grouped by the feature area that
introduced them (relational query-optimization, UUID primary keys, GFK
unions, nested-input fixes, and various numbered-issue regressions).
"""

from __future__ import unicode_literals

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class DummyModel(models.Model):
    """Abstract base for test models that sets a shared "app_label".

    Every concrete test model in this module inherits from this base so it
    registers under the "tests" app instead of needing its own app config.
    """

    class Meta:
        """Meta configuration for DummyModel.

        Declares the shared "app_label" and marks the base itself abstract so
        it is never migrated as its own table.
        """

        app_label = "tests"
        abstract = True


class BasicModel(DummyModel):
    """A minimal model with a single text field, used by generic schema tests.

    Kept intentionally small so schema-building tests have a low-surface
    model to exercise without pulling in relations.
    """

    text = models.CharField(
        max_length=100,
        verbose_name=_("Text comes here"),
        help_text=_("Text description."),
    )


# --- Relational models used by the query-optimization tests --------------- #
class Category(DummyModel):
    """A simple category model related to "Post" for optimizer tests.

    Posts reference this model through a nullable foreign key, so it also
    exercises optional-relation prefetch/select_related paths.
    """

    title = models.CharField(max_length=100)


class Author(DummyModel):
    """An author with a name and bio, related to "Post" and "AuthorProfile".

    Also referenced by "Post.co_authors" as a many-to-many, so it exercises
    both forward-FK and M2M optimizer paths.
    """

    name = models.CharField(max_length=100)
    bio = models.TextField(default="")

    @property
    def display_name(self) -> str:
        """Read "name" to build a display label (only() full-model safety check).

        Returns:
            The author's name prefixed with "Author: ".
        """
        return "Author: {}".format(self.name)


class Tag(DummyModel):
    """A label used to tag "Post" instances in a many-to-many relation.

    Exists solely to give "Post.tags" a target model for M2M optimizer tests.
    """

    label = models.CharField(max_length=50)


class Post(DummyModel):
    """A blog post with an author, optional category, tags, and co-authors.

    Combines a required forward FK ("author"), a nullable forward FK
    ("category"), and two M2M relations ("tags", "co_authors") so the
    query-optimization tests can exercise every relation shape from one model.
    """

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
    """Reverse-FK from "Post", used as an aggregate annotation target (phase-d).

    Its "comments" related_name lets optimizer tests annotate "Post" with
    aggregates (e.g. counts) computed over this reverse relation.
    """

    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    body = models.TextField(default="")


class AuthorProfile(DummyModel):
    """One-to-one with "Author"; used for the grandchild-select survival test (phase-d).

    Named AuthorProfile (not Profile) to avoid collision with the Profile model
    defined in test_optimizer_coverage.py.
    """

    author = models.OneToOneField(
        Author, related_name="author_profile", on_delete=models.CASCADE
    )
    bio = models.TextField(default="")


# --- Model used by the DjangoModelType queryset-hook tests ------------ #
class HookModel(DummyModel):
    """A minimal model used to test the "DjangoModelType" queryset hook.

    Kept separate from "ScopedArticle" so the two hook test suites (queryset
    hook vs. security "get_queryset" hook) do not collide on model identity.
    """

    text = models.CharField(max_length=100)


# --- UUID primary-key models used by the plain-pk filtering tests ---------- #
class UUIDThing(DummyModel):
    """A model with a UUID primary key, used by plain-pk filtering tests.

    Overrides the default auto-incrementing "id" with a "UUIDField" so
    filtering tests can exercise UUID-typed primary-key lookups.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)


class UUIDItem(DummyModel):
    """A model related to "UUIDThing" by foreign key, for plain-pk filtering tests.

    Lets filtering tests traverse from a UUID primary key across a relation.
    """

    label = models.CharField(max_length=100)
    thing = models.ForeignKey(UUIDThing, related_name="items", on_delete=models.CASCADE)


# --- Track 2: union / interface MVP models -------------------------------- #
# Concrete member models referenced by a GFK union and an interface. Kept here
# (not inline in the test module) so they share the "tests" app_label and play
# nicely with the schema build, mirroring the existing relational models above.
# Names are ``Track2``-prefixed to avoid colliding with same-named models that
# other test modules register in the shared "tests" app (e.g. Account).
class Track2Account(DummyModel):
    """A GFK-union member model.

    One of the concrete member models referenced by the GFK union and
    interface MVP tests (Track 2).
    """

    balance = models.IntegerField(default=0)
    label = models.CharField(max_length=50, default="")


class Track2Invoice(DummyModel):
    """A second GFK-union member model (distinct table from Track2Account).

    Paired with "Track2Account" so union tests exercise resolving a GFK to
    two structurally different concrete models.
    """

    amount = models.IntegerField(default=0)
    note = models.CharField(max_length=50, default="")


class Track2AccountProxy(Track2Account):
    """A PROXY of "Track2Account" sharing its concrete table.

    Used by the GFK-union content-type de-dup tests: a proxy and its concrete
    base map to DIFFERENT ContentTypes under "for_concrete_model=False" but to
    the SAME ContentType under "for_concrete_model=True" (the GFK default).
    This is exactly the case where the de-dup must mirror the GFK's
    "for_concrete_model" to avoid Django's duplicate-content-type ValueError.
    """

    class Meta:
        """Meta configuration for Track2AccountProxy.

        Marks the class as a Django proxy model sharing "Track2Account"'s
        concrete table under the "tests" app label.
        """

        app_label = "tests"
        proxy = True


class Track2Order(DummyModel):
    """A GFK-union member model carrying a forward FK head ("customer").

    Used to exercise the member-level "child_select" merge in
    "_collect_gfk_union_buckets": when a union member's narrowed plan pulls a
    forward-FK relation (here "customer"), "_compute_child_only" populates
    "PrefetchPlan.child_select" with that head, so two split inline fragments
    over this member merge their select_related heads.
    """

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


class Track2GfkComment(DummyModel):
    """A GFK owner model for the union-converter test.

    A standalone model (not the phase-d "Comment" above, which other
    optimizer tests depend on) carrying a single GenericForeignKey "target"
    whose explicit members are the Track2 members.
    """

    body = models.TextField(default="")
    target_ct = models.ForeignKey(
        ContentType, null=True, on_delete=models.CASCADE, related_name="+"
    )
    target_id = models.PositiveIntegerField(null=True)
    target = GenericForeignKey("target_ct", "target_id")


class Track2Book(DummyModel):
    """An interface member model sharing a "name" field with "Track2Magazine".

    Exercises abstract-base field sharing when both models are exposed
    through the same GraphQL interface.
    """

    name = models.CharField(max_length=100)
    pages = models.IntegerField(default=0)


class Track2Magazine(DummyModel):
    """An interface member model sharing a "name" field with "Track2Book".

    Exercises abstract-base field sharing when both models are exposed
    through the same GraphQL interface.
    """

    name = models.CharField(max_length=100)
    issue = models.IntegerField(default=0)


# --- nested-input-type-fix models ----------------------------------------- #
class NestedTreeNode(DummyModel):
    """A self-referential model used by the nested-input-type-fix tests.

    Nesting a category into itself exercises the single-level recursion
    guard (the on-demand GENERIC child stops at "[ID!]").
    """

    label = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )


class SnakeParent(DummyModel):
    """Parent whose reverse-FK accessor is a multi-word snake_case name.

    The GraphQL surface camelCases it ("blogComments") and graphene
    deserializes it back to the Django attribute "blog_comments" -- which
    must match the nested_fields dict key so "data.pop(field)" finds the
    object payload (ISSUE 7).
    """

    title = models.CharField(max_length=100)


class SnakeChild(DummyModel):
    """Child model related to "SnakeParent" via the "blog_comments" reverse accessor.

    Together with "SnakeParent" reproduces the camelCase/snake_case mismatch
    that ISSUE 7 fixed in the nested-mutation field lookup.
    """

    text = models.CharField(max_length=100)
    snake_parent = models.ForeignKey(
        SnakeParent,
        related_name="blog_comments",
        on_delete=models.CASCADE,
    )


class OrderParent(DummyModel):
    """Parent model used only by the nested-FIRST ordering test.

    The GLOBAL registry slot for "(OrderParent, "create")" is controlled
    entirely within that one test (no sibling test module touches these
    models).
    """

    title = models.CharField(max_length=100)


class OrderChild(DummyModel):
    """Child model related to "OrderParent" via the "kids" reverse accessor.

    Together with "OrderParent" isolates the nested-FIRST ordering test's
    global registry slot from other test modules.
    """

    text = models.CharField(max_length=100)
    order_parent = models.ForeignKey(
        OrderParent,
        related_name="kids",
        on_delete=models.CASCADE,
    )


class CustomPKProduct(DummyModel):
    """A model with a slug primary key, used by the delete-pk-attname fix tests (#18).

    The PK is a slug CharField (not "id"), which exercises the
    "old_obj._meta.pk.attname" fix in mutation.py and types.py delete().
    """

    slug = models.CharField(max_length=100, primary_key=True)
    title = models.CharField(max_length=200)


# --- Model used by the DjangoObjectType.get_queryset hook tests (#58) ------- #
# A separate model (not HookModel) so the fix tests don't collide with the
# DjangoModelType queryset-hook tests that also use HookModel.
class ScopedArticle(DummyModel):
    """Article model for testing the DjangoObjectType.get_queryset security hook.

    A separate model (not "HookModel") so these fix tests don't collide with
    the DjangoModelType queryset-hook tests that also use "HookModel".
    """

    title = models.CharField(max_length=200)
    is_public = models.BooleanField(default=True)


# --- Models for issue #52: enum key collision + self-referential O2O ---------- #
# Two concrete models sharing the same class name via object_name (``Item``) but
# in the same Django app (app_label="tests"). We simulate the cross-app collision
# by using *two distinct classes* with identical ``object_name`` and ``app_label``
# but different choices on the same field name ``status``.
# The real-world collision is ``app_a.Item`` vs ``app_b.Item``; here we test the
# equivalent by injecting mock _meta onto the fields inside the test.
#
# We also add a genuine self-referential OneToOneField model (Person.spouse).


class PersonWithSpouse(DummyModel):
    """Model with a genuine self-referential OneToOneField.

    Used to verify that converter.py's MTI-parent-link guard does NOT drop a
    real self-referential O2O (spouse) from output and input types (#52-B).
    """

    name = models.CharField(max_length=100)
    spouse = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        related_name="spouse_of",
        on_delete=models.SET_NULL,
    )


class EnumCollisionItemA(DummyModel):
    """First 'Item'-like model with status choices A/B (for #52-A enum collision).

    Simulates a cross-app enum-name collision ("app_a.Item" vs "app_b.Item")
    against "EnumCollisionItemB" by giving two distinct classes the same
    "status" field name but different choice sets.
    """

    STATUS_CHOICES = [("a", "Alpha"), ("b", "Beta")]
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)


class EnumCollisionItemB(DummyModel):
    """Second 'Item'-like model with status choices X/Y/Z (for #52-A enum collision).

    Simulates a cross-app enum-name collision ("app_a.Item" vs "app_b.Item")
    against "EnumCollisionItemA" by giving two distinct classes the same
    "status" field name but different choice sets.
    """

    STATUS_CHOICES = [("x", "Xray"), ("y", "Yankee"), ("z", "Zulu")]
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)


# --- Models for issue #65: Meta-option hygiene -------------------------------- #


class MetaHygieneWidget(DummyModel):
    """Model used by issue #65 tests.

    Has several fields to exercise include_fields, only_fields/exclude_fields
    omitting id, and queryset filtering. Kept multi-field so those Meta-option
    combinations have enough surface to be meaningfully distinguished.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    is_active = models.BooleanField(default=True)


# --- Model for S-ROOTS-d: scalar-type coverage (date/binary/uuid/json/etc.) -- #
# Exercises every converter SCALAR dispatcher that the native output_compiler
# already derives directly from the model, so the silent-drop guard can assert
# every scalar kind survives the converter native-aware skip with the SAME SDL
# scalar name (CustomDate / CustomDateTime / CustomTime / String for Binary / …).
class ScalarKindsModel(DummyModel):
    """Carries one field of every converter scalar dispatcher kind.

    Exercises every converter SCALAR dispatcher that the native
    output_compiler already derives directly from the model, so the
    silent-drop guard can assert every scalar kind survives the converter
    native-aware skip with the same SDL scalar name (CustomDate /
    CustomDateTime / CustomTime / String for Binary / etc.).
    """

    char = models.CharField(max_length=50)
    text = models.TextField(default="")
    integer = models.IntegerField(default=0)
    big_integer = models.BigIntegerField(default=0)
    boolean = models.BooleanField(default=False)
    floating = models.FloatField(default=0.0)
    decimal = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    duration = models.DurationField(null=True)
    uuid_field = models.UUIDField(default=uuid.uuid4)
    date = models.DateField(null=True)
    datetime = models.DateTimeField(null=True)
    time = models.TimeField(null=True)
    binary = models.BinaryField(null=True)
    json_field = models.JSONField(null=True)
    # A relation so the silent-drop guard also proves a FK survives the skip.
    author = models.ForeignKey(
        Author, related_name="scalar_kinds", null=True, on_delete=models.SET_NULL
    )


# --- Dedicated model for the error-messages delete-mutation test ----------- #
# tests/test_error_messages.py builds a DjangoModelType over this model to
# exercise the generated delete mutation's not-found message. DjangoModelType
# ALWAYS self-registers on the GLOBAL registry (it rejects Meta.registry), so a
# DjangoModelType over a SHARED model (e.g. Author) would compile that model's
# output type and auto-derive globally-named companion list types
# (Author.posts -> a global "PostListType") that collide with same-named types
# other modules build. A dedicated, relation-free model keeps that test's global
# footprint uniquely named and collision-free.
class ErrMsgDeleteModel(DummyModel):
    """Relation-free model backing the error-messages delete-mutation test.

    Kept isolated (no reverse relations) so the DjangoModelType built over it in
    tests/test_error_messages.py leaves only uniquely-named companion types on
    the global registry.
    """

    title = models.CharField(max_length=200)


# tests/core/test_django_builder_deprecation.py builds a PAGINATED DjangoModelType
# and calls QueryFields() over it. DjangoModelType ALWAYS self-registers on the
# GLOBAL registry (it rejects Meta.registry), so a paginated type over a model
# that is ALSO a relation target (e.g. ScalarKindsModel, which Author references
# via a reverse FK) auto-derives a globally-named "<Model>ListType" companion —
# and that same container is ALSO minted, differently shaped, when a sibling
# module force-resolves the referencing model's reverse relation. The two collide
# ("multiple types named '<Model>ListType'") under some shuffled run orders. A
# dedicated, relation-free model keeps that test's global list container uniquely
# named and collision-free.
class DeprecationListModel(DummyModel):
    """Relation-free model backing the QueryFields deprecation-reason SDL test.

    Kept isolated (no forward or reverse relations) so the paginated
    DjangoModelType built over it in tests/core/test_django_builder_deprecation.py
    mints a globally-named "DeprecationListModelListType" container that no other
    test type or relation can also build, keeping the assertion order-independent.
    """


class DeprecationRetrieveModel(DummyModel):
    """Relation-free model backing the RetrieveField deprecation-reason SDL test.

    Same isolation rationale as "DeprecationListModel": a dedicated model keeps
    the auto-derived companion type names unique so the assertion stays
    order-independent under randomized test collection.
    """


class DeprecationCreateModel(DummyModel):
    """Relation-free model backing the CreateField deprecation-reason SDL test.

    Same isolation rationale as "DeprecationListModel": a dedicated model keeps
    the auto-derived companion type names unique so the assertion stays
    order-independent under randomized test collection.
    """

    label = models.CharField(max_length=100)


# Dedicated family for tests/test_nested_input_types.py: that module builds
# many DjangoModelMutation/DjangoModelType classes with nested_fields on the
# GLOBAL registry, so sharing Post/Comment/Tag/Author made its auto-derived
# companion names (PostListType, ...) collide with sibling modules under
# randomized collection order — the Python-version-dependent shuffle meant a
# green local run could still fail in CI. Same isolation pattern as
# NestedObj*/NestedIntegrity*/OptimizerPerf*.
class NestedInpAuthor(DummyModel):
    """Author twin for the nested-input-types module (forward-FK target)."""

    name = models.CharField(max_length=100)
    bio = models.TextField(default="")


class NestedInpTag(DummyModel):
    """Tag twin for the nested-input-types module (M2M target)."""

    label = models.CharField(max_length=50)


class NestedInpPost(DummyModel):
    """Post twin for the nested-input-types module.

    Mirrors the relation shapes the module exercises: forward FK "author",
    M2M "tags", and the reverse-FK "comments" accessor minted by
    "NestedInpComment".
    """

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(
        NestedInpAuthor, related_name="posts", on_delete=models.CASCADE
    )
    tags = models.ManyToManyField(NestedInpTag, related_name="posts", blank=True)


class NestedInpComment(DummyModel):
    """Comment twin for the nested-input-types module (reverse-FK child)."""

    post = models.ForeignKey(
        NestedInpPost, related_name="comments", on_delete=models.CASCADE
    )
    body = models.TextField(default="")


# --- Dedicated models for test_nested_objects.py -------------------------- #
# tests/test_nested_objects.py builds several module-level DjangoModelType
# subclasses (forward-FK, many-to-many, reverse-FK) over the SHARED "Post" /
# "Author" / "Tag" models. DjangoModelType ALWAYS self-registers on the GLOBAL
# registry (it rejects both Meta.registry and Meta.skip_registry — issue #65's
# hygiene guard), so wrapping a shared model here auto-derives globally-named
# companion output types (e.g. "PostGenericType", "AuthorGenericType") that
# collide with same-named companions other test modules build over the same
# shared models. Dedicated, uniquely-named models with unique related_names
# keep this module's global footprint collision-free while preserving the
# exact forward-FK / M2M / reverse-FK relation shapes under test.
class NestedObjAuthor(DummyModel):
    """Dedicated author-like model for the nested-objects forward/reverse-FK tests.

    A stand-in for "Author" used only by tests/test_nested_objects.py so its
    DjangoModelType companions never collide with the shared "Author" model's
    companions.
    """

    name = models.CharField(max_length=100)


class NestedObjTag(DummyModel):
    """Dedicated tag-like model for the nested-objects many-to-many tests.

    A stand-in for "Tag" used only by tests/test_nested_objects.py so its
    DjangoModelType companions never collide with the shared "Tag" model's
    companions.
    """

    label = models.CharField(max_length=50)


class NestedObjPost(DummyModel):
    """Dedicated post-like model for the nested-objects tests.

    A stand-in for "Post" used only by tests/test_nested_objects.py. Carries a
    forward FK to "NestedObjAuthor" (related_name "nested_obj_posts") and an
    M2M to "NestedObjTag" (related_name "nested_obj_posts") so the forward-FK,
    reverse-FK, and M2M code paths under test all execute against models
    uniquely named for this module.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(
        NestedObjAuthor, related_name="nested_obj_posts", on_delete=models.CASCADE
    )
    tags = models.ManyToManyField(
        NestedObjTag, related_name="nested_obj_posts", blank=True
    )


# --- Dedicated models for test_nested_integrity.py ------------------------ #
# tests/test_nested_integrity.py builds several module-level DjangoModelType
# subclasses over the SHARED "Post" / "Author" / "AuthorProfile" models,
# exercising the M2M raw-pk check, the reverse-FK ownership (child-steal)
# guard, the reverse-O2O list-arity guard, and the forward-FK list-arity
# guard. For the same reason as above (DjangoModelType's global-registry
# hygiene guard), a dedicated model set with unique related_names keeps this
# module's companion types collision-free.
class NestedIntegrityAuthor(DummyModel):
    """Dedicated author-like model for the nested-integrity tests.

    A stand-in for "Author" used only by tests/test_nested_integrity.py so
    its DjangoModelType companions never collide with the shared "Author"
    model's companions.
    """

    name = models.CharField(max_length=100)


class NestedIntegrityTag(DummyModel):
    """Dedicated tag-like model for the nested-integrity M2M raw-pk tests.

    A stand-in for "Tag" used only by tests/test_nested_integrity.py so its
    DjangoModelType companions never collide with the shared "Tag" model's
    companions.
    """

    label = models.CharField(max_length=50)


class NestedIntegrityPost(DummyModel):
    """Dedicated post-like model for the nested-integrity tests.

    A stand-in for "Post" used only by tests/test_nested_integrity.py. Carries
    a forward FK to "NestedIntegrityAuthor" (related_name
    "nested_integrity_posts") and an M2M to "NestedIntegrityTag"
    (related_name "nested_integrity_posts") so the M2M raw-pk check, the
    reverse-FK ownership guard, and the forward-FK list-arity guard all
    execute against models uniquely named for this module.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        NestedIntegrityAuthor,
        related_name="nested_integrity_posts",
        on_delete=models.CASCADE,
    )
    tags = models.ManyToManyField(
        NestedIntegrityTag, related_name="nested_integrity_posts", blank=True
    )


class NestedIntegrityProfile(DummyModel):
    """Dedicated profile-like model for the nested-integrity reverse-O2O tests.

    A stand-in for "AuthorProfile" used only by tests/test_nested_integrity.py.
    The reverse accessor is named "author_profile" (via related_name) to match
    the "nested_fields" key the test declares; this does not collide with the
    shared "Author.author_profile" accessor because it is declared on a
    different target model ("NestedIntegrityAuthor", not "Author").
    """

    author = models.OneToOneField(
        NestedIntegrityAuthor,
        related_name="author_profile",
        on_delete=models.CASCADE,
    )
    bio = models.TextField(default="")


# --- Dedicated models for test_optimizer_perf.py --------------------------- #
# tests/test_optimizer_perf.py builds two module-level DjangoModelType
# subclasses ("PostMutType", "PostMutTypeFiltered") over the SHARED "Post"
# model to exercise the mutation re-read optimization (select_related survives
# perform_mutate's re-read). The file's OTHER DjangoObjectType classes are all
# function-local with isolated registries and are already safe; only these two
# module-level DjangoModelType subclasses need a dedicated, uniquely-named
# model to avoid the same global-registry companion collision described above.
class OptimizerPerfAuthor(DummyModel):
    """Dedicated author-like model for the optimizer-perf re-read tests.

    A stand-in for "Author" used only by the module-level "PostMutType" /
    "PostMutTypeFiltered" DjangoModelType subclasses in
    tests/test_optimizer_perf.py.
    """

    name = models.CharField(max_length=100)


class OptimizerPerfCategory(DummyModel):
    """Dedicated category-like model for the optimizer-perf re-read tests.

    A stand-in for "Category" used only by the module-level "PostMutType" /
    "PostMutTypeFiltered" DjangoModelType subclasses in
    tests/test_optimizer_perf.py.
    """

    title = models.CharField(max_length=100)


class OptimizerPerfPost(DummyModel):
    """Dedicated post-like model for the optimizer-perf re-read tests.

    A stand-in for "Post" used only by the module-level "PostMutType" /
    "PostMutTypeFiltered" DjangoModelType subclasses in
    tests/test_optimizer_perf.py. Carries the same forward-FK shape
    ("author", "category") the re-read select_related assertions exercise.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        OptimizerPerfAuthor,
        related_name="optimizer_perf_posts",
        on_delete=models.CASCADE,
    )
    category = models.ForeignKey(
        OptimizerPerfCategory,
        related_name="optimizer_perf_posts",
        null=True,
        on_delete=models.SET_NULL,
    )


# --- Dedicated models for the library-level registry-isolation leak test ---- #
class IsoLeakCategory(DummyModel):
    """Category-like model for the registry-isolation leak regression test.

    Owns a "posts" reverse relation (from "IsoLeakPost") so a local-registry
    node for it exposes a "<Model>ListType" container -- the exact shape whose
    leak into the global shared registry produced the duplicate-name collision.
    Kept separate from "Category" so the test never touches shared model slots.
    """

    title = models.CharField(max_length=100)


class IsoLeakPost(DummyModel):
    """Post-like model with a nullable FK to "IsoLeakCategory".

    Mirrors the "Post" -> "Category" forward-FK shape (and its "posts" reverse
    relation) that the registry-isolation leak test exercises, without reusing
    the shared "Post"/"Category" models.
    """

    title = models.CharField(max_length=200)
    category = models.ForeignKey(
        IsoLeakCategory,
        related_name="posts",
        null=True,
        on_delete=models.SET_NULL,
    )
