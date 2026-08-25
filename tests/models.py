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
    """Author twin for the nested-input-types module.

    Forward-FK target of "NestedInpPost.author"; isolated so the module's
    generated companion type names never collide with the shared Author.
    """

    name = models.CharField(max_length=100)
    bio = models.TextField(default="")


class NestedInpTag(DummyModel):
    """Tag twin for the nested-input-types module.

    M2M target of "NestedInpPost.tags"; isolated so the module's generated
    companion type names never collide with the shared Tag.
    """

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
    """Comment twin for the nested-input-types module.

    Reverse-FK child minting the "comments" accessor on "NestedInpPost";
    isolated so the module's generated names never collide with the shared
    Comment.
    """

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


# --- Dedicated models for the relation permission-bypass regression test ---- #
class PermRelPost(DummyModel):
    """Post-like model owning a perm-gated reverse-FK relation.

    Paired with "PermRelComment" so the permission-scoped-schema tests can
    traverse "postRetrieve { comments { results { secretText } } }" with a
    caller that holds only the "view_permrelpost" permission. Kept separate
    from the shared "Post" model so the module never touches shared registry
    slots.
    """

    title = models.CharField(max_length=200)


class PermRelComment(DummyModel):
    """Comment-like model reachable ONLY through "PermRelPost.comments".

    Its "secret_text" column is the payload the relation-traversal bypass
    leaked: a caller without "view_permrelcomment" must not be able to read it
    through the parent's nested-list relation field.
    """

    post = models.ForeignKey(
        PermRelPost, related_name="comments", on_delete=models.CASCADE
    )
    secret_text = models.TextField(default="")


class PermRelAuthor(DummyModel):
    """Author-like model reachable through a to-ONE relation on "PermRelArticle".

    Backs the "no permission_classes anywhere" baseline: its type declares no
    permission classes, so relation traversal from it must keep behaving
    exactly as it did before the relation labels were introduced.
    """

    secret_name = models.CharField(max_length=100, default="")


class PermRelArticle(DummyModel):
    """Article-like model owning a forward FK to "PermRelAuthor".

    Its "articles" reverse relation is the nested list the permission-class-free
    baseline traverses.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        PermRelAuthor, related_name="articles", on_delete=models.CASCADE
    )


# --- Dedicated models for the filter-input shape-fork regression test ------ #
# tests/core/test_filter_input_shape_fork.py filters the SAME model from two
# contexts: as a ROOT list (its own "filter_fields") and as a NESTED relation
# reached through a column its own type does not declare ("author__email").
# Both contexts must converge on ONE "<Model>FilterInput" instance, so the
# family is kept separate from the shared Author/Post slots (the test also
# builds schemas in BOTH declaration orders).
class FilterForkAuthor(DummyModel):
    """Author-like relation target for the filter-input shape-fork test.

    Declares both "name" (the column its own root type filters on) and
    "email" (the column only the nested relation context filters on), which
    is what forks the "FilterForkAuthorFilterInput" shape.
    """

    name = models.CharField(max_length=100)
    email = models.EmailField(default="")


class FilterForkPost(DummyModel):
    """Post-like owner filtering "FilterForkAuthor" through a nested relation.

    Its "filter_fields" reach through "author__email", a column the author's
    own root type does not expose.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        FilterForkAuthor, related_name="posts", on_delete=models.CASCADE
    )


# --- Dedicated models for the 2.0.1 subscription security regressions ------ #
# tests/subscriptions/test_security_2_0_1.py needs models it can subscribe to
# WITHOUT touching the shared "User"/"Post" slots: the projection test registers
# a live signal binding (which would leak extra group sends into every other
# subscription test if it were wired on "User"), and the private-subscription
# transport test registers an output type (last-registration-wins), which would
# fork the shared "Post" type for whatever test runs next.
class SecretRecord(DummyModel):
    """Subscription target for the private-subscription transport tests.

    Deliberately relation-free and unprojected: the transport tests only need a
    model whose subscription field can be declared private.
    """

    title = models.CharField(max_length=200)


class SecretLedger(DummyModel):
    """Subscription target for the "only_fields"/"exclude_fields" projection tests.

    Carries one public column ("label"), one sensitive column ("secret") and one
    orderable column ("created") so the projection can be proven on BOTH the
    declared filter set and the broadcast event payload, and so the client
    filter lookup allow list can be proven against a real date/time column
    (ordered lookups and date-part transforms both resolve on it).
    """

    label = models.CharField(max_length=100)
    secret = models.CharField(max_length=128, default="")
    created = models.DateTimeField(null=True)


# --- Dedicated models for the 2.1.0 subscription filter-input API ---------- #
# tests/subscriptions/test_subscription_filter_input.py asserts GENERATED TYPE
# NAMES byte-for-byte ("SubFilterCommentFilterInput" vs
# "SubFilterCommentSubscriptionFilterInput") and mounts both a query filter
# input and a subscription on the SAME model. Sharing "Post"/"Comment" would
# make those assertions depend on which sibling module registered the shared
# slot first under randomized collection order. Same isolation pattern as
# SecretRecord/SecretLedger.
class SubFilterTag(DummyModel):
    """M2M target for "SubFilterPost".

    A to-many field still renders in the generated subscription filter input,
    and is the one shape whose "exact" keeps its ORM suffix (the payload value
    is a LIST of primary keys, which the in-memory equality gate cannot decide).
    """

    label = models.CharField(max_length=50)


class SubFilterPost(DummyModel):
    """Subscription target carrying a choices column and a sensitive column.

    "status" has choices so the generated lookups input is proven to reuse the
    shared choices enum; "secret" is the column the "Meta.exclude_fields"
    projection test keeps out of the generated input type.
    """

    STATUS_CHOICES = (("open", "Open"), ("urgent", "Urgent"), ("closed", "Closed"))

    title = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    secret = models.CharField(max_length=128, default="")
    tags = models.ManyToManyField(SubFilterTag, related_name="posts", blank=True)


class SubFilterComment(DummyModel):
    """Comment on a "SubFilterPost".

    Its forward FK "post" is what the end-to-end SSE test scopes on, so the
    delivered/dropped split proves the nested filter input really flattened
    into a working ORM lookup.
    """

    post = models.ForeignKey(
        SubFilterPost, related_name="comments", on_delete=models.CASCADE
    )
    text = models.TextField(default="")


# --- Models dedicated to the subscription delivery regressions -------------- #
# Kept apart from "CustomPKProduct" (the mutation delete-pk fixtures) so mounting
# a subscription over them cannot disturb the shared output registry slots those
# tests assert on.
class SubSlugPkItem(DummyModel):
    """Subscription target whose primary key is a slug, not "id".

    The broadcast payload of an "id_only" subscription is keyed by the real
    primary-key field name, so this model is what proves a non-"id" pk is
    delivered instead of a null on a non-nullable event field.
    """

    slug = models.SlugField(primary_key=True)
    title = models.CharField(max_length=200, default="")


class SubVariablesNote(DummyModel):
    """Subscription target for the parameterised-subscription delivery tests.

    Its own model so the GraphQL variables / operation-name delivery tests do
    not share a subscription stream (or an event type) with any other module.
    """

    title = models.CharField(max_length=200, default="")


# --- Dedicated models for the aliased / nested-window optimizer regressions - #
class AliasWinAuthor(DummyModel):
    """Author-like root for the aliased nested-list optimizer regressions.

    Owns "posts" so a query can alias the same nested-list accessor twice with
    different filters or pagination windows. Kept separate from the shared
    "Author" model so those tests never touch shared registry slots.
    """

    name = models.CharField(max_length=100)


class AliasWinPost(DummyModel):
    """Post-like middle level owning both "comments" and a related_name-less FK.

    "comments" gives the tests a second nested-list level so a window can be
    nested under a windowed parent, while "AliasWinNote" points here WITHOUT a
    "related_name" so the reverse accessor is "aliaswinnote_set".
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        AliasWinAuthor, related_name="posts", on_delete=models.CASCADE
    )


class AliasWinComment(DummyModel):
    """Comment on an "AliasWinPost", the innermost windowed nested list.

    Gives the alias/window regressions a second nested-list level so a window
    can be nested under a windowed parent.
    """

    text = models.CharField(max_length=200)
    post = models.ForeignKey(
        AliasWinPost, related_name="comments", on_delete=models.CASCADE
    )


class AliasWinNote(DummyModel):
    """Note whose FK declares NO "related_name".

    The reverse accessor is therefore "aliaswinnote_set" while
    "_meta.get_field" only knows it as "aliaswinnote" -- the exact mismatch
    that made the "optimize_<field>" prefetch hook resolve the wrong model.
    """

    body = models.CharField(max_length=200)
    post = models.ForeignKey(AliasWinPost, on_delete=models.CASCADE)


# --- Ordering-with-the-default-paginator regression models ---------------- #
class DefaultOrderTeam(DummyModel):
    """Parent of "DefaultOrderMember", used for the NESTED ordering path.

    Exists so the nested list field ("team { members(ordering: ...) }") can be
    exercised with the same default paginator the root list fields use.
    """

    label = models.CharField(max_length=50)


class DefaultOrderMember(DummyModel):
    """Row ordered by the client through the "ordering" pagination argument.

    "sort_key" is a genuine multi-word snake_case attname, so the camelCase
    wire spelling ("sortKey") round-trips through the ordering normalizer.
    """

    name = models.CharField(max_length=50)
    sort_key = models.IntegerField(default=0)
    team = models.ForeignKey(
        DefaultOrderTeam,
        related_name="members",
        null=True,
        on_delete=models.CASCADE,
    )


# --- Relation-scoping regression models (S6) ------------------------------ #
class ScopedAuthor(DummyModel):
    """Parent of "ScopedPost", used to reach a scoped type through a relation.

    Exists so a hand-mounted "DjangoFilterListField" can be nested under a
    parent object type and exercise the related fast path.
    """

    name = models.CharField(max_length=100)


class ScopedPost(DummyModel):
    """Row whose object type declares a row-level "get_queryset" scope.

    Reached both at the top level and through "ScopedAuthor.created_posts", so
    the hook can be asserted on BOTH paths.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        ScopedAuthor,
        related_name="created_posts",
        null=True,
        on_delete=models.CASCADE,
    )


# --- Dedicated models for the 2.1.0 CRUD/permission security regressions --- #
# tests/test_security_2_1_0_crud.py proves the write path is scoped by
# "filter_queryset", that a falsy permission denies, and that a projection
# option is rejected when the output type is reused from the registry. Each
# defect gets its OWN model: the projection test must register a
# "DjangoObjectType" for its model FIRST (last-registration-wins would fork the
# shared slot for whatever test runs next under randomized order), and the
# scoping test declares a "DjangoModelType" whose "filter_queryset" would leak
# into any sibling module sharing the same model.
class CrudScopedDoc(DummyModel):
    """Tenant-owned row used by the cross-tenant write tests.

    "tenant" is the scoping column the type's "filter_queryset" narrows on, and
    "body" is the payload an out-of-scope update would overwrite.
    """

    tenant = models.CharField(max_length=50)
    body = models.CharField(max_length=200)


class CrudPermDoc(DummyModel):
    """Row guarded by a permission class that returns a falsy non-False value.

    Relation-free on purpose: the permission tests only need a model whose CRUD
    fields can be mounted and called.
    """

    name = models.CharField(max_length=100)


class CrudLeakDoc(DummyModel):
    """Row carrying a sensitive column kept out with "exclude_fields".

    "secret" is the column the projection must remove from the output type; it
    stays readable through the manager so the test can prove the value really
    exists in the database.
    """

    label = models.CharField(max_length=100)
    secret = models.CharField(max_length=128, default="")


class CrudFreshDoc(DummyModel):
    """Row whose output type is built by its own "DjangoModelType".

    Deliberately left without a hand-written "DjangoObjectType" so the
    projection guard can be proven NOT to fire when nothing is registered yet.
    """

    label = models.CharField(max_length=100)
    secret = models.CharField(max_length=128, default="")


class CrudNodeDoc(DummyModel):
    """Row fetched through "DjangoObjectType.get_node".

    Carries the "is_public" column the type's "get_queryset" hook scopes on, so
    the by-pk node lookup can be proven to honor the same scope the list and
    single-object resolvers do.
    """

    title = models.CharField(max_length=100)
    is_public = models.BooleanField(default=True)


class BinaryDoc(DummyModel):
    """Row carrying the field types whose Python value is not JSON-safe.

    "attachment" yields a "FieldFile" and "blob" yields "bytes" (or "memoryview"
    once reloaded), so it pins the subscription serializer against the model
    kinds that used to crash every broadcast.
    """

    label = models.CharField(max_length=100)
    attachment = models.FileField(upload_to="docs/", blank=True)
    blob = models.BinaryField(default=b"")


class UploadDoc(DummyModel):
    """Row dedicated to the multipart upload path on both mutation hosts.

    Its "attachment" carries a deliberately SHORT "max_length" so the storage
    path branch of the file scalar can be proven to still enforce the column
    width -- a plain string longer than the column would otherwise reach the
    database.
    """

    label = models.CharField(max_length=50)
    attachment = models.FileField(upload_to="uploads/", max_length=40, blank=True)


class ProjectedUploadDoc(DummyModel):
    """Row for the host that projects its file column off the mutation input.

    Dedicated rather than shared with "UploadDoc": the output-type reuse guard
    refuses a projection on a model another host already registered, so the
    projected host needs a model nobody else claims.
    """

    label = models.CharField(max_length=50)
    attachment = models.FileField(upload_to="uploads/", max_length=40, blank=True)


# --- audit-FK ambiguity models (nested-list relation scoping) -------------- #
class AuditEditor(DummyModel):
    """A parent model reached by TWO distinct foreign keys from one child.

    Paired with "AuditArticle" so the nested-list relation scoping can be
    proven against a child that points back at the same parent more than once
    ("created_by" and "updated_by"), the audit-column shape that made
    "get_extra_filters" AND every relation together.
    """

    name = models.CharField(max_length=100)


class AuditArticle(DummyModel):
    """A child carrying two foreign keys to the SAME parent model.

    "created_by" and "updated_by" both target "AuditEditor", so scoping a
    nested list on one of them must not also require the other to match.
    """

    title = models.CharField(max_length=100)
    created_by = models.ForeignKey(
        AuditEditor, related_name="created_articles", on_delete=models.CASCADE
    )
    updated_by = models.ForeignKey(
        AuditEditor, related_name="updated_articles", on_delete=models.CASCADE
    )


# --- multi-table-inheritance models ---------------------------------------- #
class MtiPlace(DummyModel):
    """A CONCRETE parent for multi-table inheritance.

    Concrete (not abstract), so a subclass gets its own table plus an implicit
    "place_ptr" parent link instead of copied columns. Also the target of
    "MtiReview.place", which gives the parent a reverse to-many relation the
    child inherits.
    """

    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200, blank=True)


class MtiRestaurant(MtiPlace):
    """A multi-table-inheritance child of "MtiPlace".

    Its own table holds only "serves_pizza" and the "place_ptr" primary key,
    so every other readable field ("id", "name", "address", "reviews") comes
    from the parent table.
    """

    serves_pizza = models.BooleanField(default=False)


class MtiReview(DummyModel):
    """A review pointing at the MTI PARENT model.

    The reverse accessor "reviews" lives on "MtiPlace" and is inherited by
    "MtiRestaurant", which is what makes the parent's to-many relation
    reachable from the child type.
    """

    place = models.ForeignKey(
        MtiPlace, related_name="reviews", on_delete=models.CASCADE
    )
    rating = models.IntegerField(default=0)


# --- non-editable relation models ------------------------------------------ #
class NonEditableOwner(DummyModel):
    """Target of a server-managed, "editable=False" foreign key.

    Only referenced through "NonEditableThing.owner", so it stays minimal.
    """

    name = models.CharField(max_length=100)


class NonEditableTag(DummyModel):
    """Target of a server-managed, "editable=False" many-to-many.

    Only referenced through "NonEditableThing.tags", so it stays minimal.
    """

    name = models.CharField(max_length=100)


class NonEditableThing(DummyModel):
    """A model whose relations are set by the server, never by the client.

    "owner" and "tags" carry "editable=False" exactly like a "created_by" or
    "tenant" column populated in "save()"; "audit_note" is the scalar control
    that was already excluded from mutation input.
    """

    label = models.CharField(max_length=100)
    owner = models.ForeignKey(
        NonEditableOwner,
        related_name="things",
        on_delete=models.CASCADE,
        null=True,
        editable=False,
    )
    tags = models.ManyToManyField(
        NonEditableTag, related_name="things", blank=True, editable=False
    )
    audit_note = models.CharField(max_length=100, blank=True, editable=False)


# --- nested child permission models ----------------------------------------- #
# DEDICATED to "test_nested_child_permissions" and
# "test_permission_scoped_nested_input". The nested host registry is model-keyed
# and every declared host must allow a nested write, so sharing a model with
# another module would make the outcome depend on import order (the suite runs
# under pytest-randomly).
class NestedPermCategory(DummyModel):
    """A shared lookup row a "NestedPermAuthor" points at through a forward FK.

    Its own host denies every write, so it is the forward face of the link-path
    boundary: attaching an existing row must stay allowed.
    """

    name = models.CharField(max_length=100)


class NestedPermTag(DummyModel):
    """A shared label many authors may link, the many-to-many link-path face.

    Reached through "NestedPermAuthor.tags", where attaching an existing tag has to stay
    ungated: the row belongs to every parent that links it, so writing it from one
    parent's payload would be cross-tenant.
    """

    label = models.CharField(max_length=50)


class NestedPermAuthor(DummyModel):
    """The nesting parent every child in this group is written through.

    It carries a reverse FK, a forward FK and a many-to-many at once, so a single host
    drives the gated relations and the ungated link paths from one payload.
    """

    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        NestedPermCategory,
        related_name="authors",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(NestedPermTag, related_name="authors", blank=True)


class NestedPermPost(DummyModel):
    """A reverse-FK child whose own host denies every write.

    The primary case: a create or an update arriving through "author.posts" has to raise
    the child's own denial and roll the whole mutation back.
    """

    author = models.ForeignKey(
        NestedPermAuthor, related_name="posts", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=200)


class NestedPermNote(DummyModel):
    """A reverse-FK child whose host declares no "permission_classes" at all.

    The inertness control: the gate must leave it byte-identical to today.
    """

    author = models.ForeignKey(
        NestedPermAuthor, related_name="notes", on_delete=models.CASCADE
    )
    body = models.CharField(max_length=200)


class NestedPermHatchNote(DummyModel):
    """A reverse-FK child writable ONLY through its parent.

    Drives the "nested_parent" escape hatch: its policy grants "create" exactly
    when the kwarg is present.
    """

    author = models.ForeignKey(
        NestedPermAuthor, related_name="hatch_notes", on_delete=models.CASCADE
    )
    body = models.CharField(max_length=200)


class NestedPermScopedNote(DummyModel):
    """A reverse-FK child whose host hides other tenants' rows.

    The "owner" column is what the host's "filter_queryset" scopes on.
    """

    author = models.ForeignKey(
        NestedPermAuthor, related_name="scoped_notes", on_delete=models.CASCADE
    )
    body = models.CharField(max_length=200)
    owner = models.CharField(max_length=50, default="")


class NestedPermBlog(DummyModel):
    """The nesting parent of the permission-scoped-schema input-pruning tests.

    Only its create root is mounted, so "NestedPermEntry" underneath is reachable
    through this parent's payload and nowhere else.
    """

    title = models.CharField(max_length=200)


class NestedPermEntry(DummyModel):
    """A child reachable ONLY through "NestedPermBlog.entries".

    It has no root field of its own, so its write label can reach the pruner
    only if the schema label-set accounts for nested INPUT labels too.
    """

    blog = models.ForeignKey(
        NestedPermBlog, related_name="entries", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=200)


# --- nested child projection models ----------------------------------------- #
# DEDICATED to "test_nested_child_projection". The nested child input is derived
# from the child's DECLARED hosts and the host registry is model-keyed, so
# sharing a model with another module would make the projection depend on import
# order (the suite runs under pytest-randomly).
class NestedProjPost(DummyModel):
    """The nesting parent of the parent-declared-first fixture.

    Declared before its child has a host of its own, which is the order that used to
    mint an unprojected child input into the shared registry slot.
    """

    title = models.CharField(max_length=200)


class NestedProjEntry(DummyModel):
    """A reverse-FK child whose own host keeps "secret" off the input surface.

    "secret" is the column that became writable on BOTH the parent's nested payload and
    the child's own root once the poisoned slot was reused.
    """

    post = models.ForeignKey(
        NestedProjPost, related_name="entries", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=200)
    secret = models.CharField(max_length=200, blank=True, default="")


class NestedProjJournal(DummyModel):
    """The nesting parent of the child-declared-first fixture.

    Declared after "NestedProjNote", so the parent inherits an existing child input
    whose required back-reference made every nested create unsatisfiable before a
    resolver could run.
    """

    title = models.CharField(max_length=200)


class NestedProjNote(DummyModel):
    """A reverse-FK child declared BEFORE its parent, hiding "private".

    In that order the projection survived, so what the tests pin here is that the nested
    element actually works over the wire.
    """

    journal = models.ForeignKey(
        NestedProjJournal, related_name="notes", on_delete=models.CASCADE
    )
    text = models.CharField(max_length=200)
    private = models.CharField(max_length=200, blank=True, default="")


class NestedProjLeft(DummyModel):
    """One of the two parents nesting the same child.

    Paired with "NestedProjRight" so a single child model has to yield two element
    types, one relaxed per parent.
    """

    name = models.CharField(max_length=100)


class NestedProjRight(DummyModel):
    """The other parent nesting the same child.

    Declared second, so a shared element type would relax the LEFT parent's foreign key
    and leave this one demanding a value the writer injects anyway.
    """

    name = models.CharField(max_length=100)


class NestedProjShared(DummyModel):
    """A child nested under two different parents, with a required FK to each.

    Two required back-references is what makes the per-parent relaxation observable:
    whichever one is still "ID!" names the parent that lost out.
    """

    left = models.ForeignKey(
        NestedProjLeft, related_name="shared", on_delete=models.CASCADE
    )
    right = models.ForeignKey(
        NestedProjRight, related_name="shared", on_delete=models.CASCADE
    )
    label = models.CharField(max_length=100)


class NestedProjLoose(DummyModel):
    """A nesting parent whose child declares no host of its own.

    Hosted twice -- once plain, once projected -- so the per-parent child element memo
    can be exercised by two hosts on one parent model.
    """

    title = models.CharField(max_length=200)


class NestedProjLooseItem(DummyModel):
    """A child with NO declared host: the no-regression floor.

    With nothing to overwrite the shared registry slot afterwards, pollution leaves no
    trace in the schema and can only be caught by looking at the registry itself.
    """

    loose = models.ForeignKey(
        NestedProjLoose, related_name="items", on_delete=models.CASCADE
    )
    text = models.CharField(max_length=200)


# --- nested-write hardening models ------------------------------------------ #
# DEDICATED to "test_nested_child_hardening". Every fixture below turns on a
# model-keyed global (the nested host list, the materialized-input guard), so
# sharing a model with another module would make the outcome depend on import
# order (the suite runs under pytest-randomly).
class NestedHardDisjointOwner(DummyModel):
    """The nesting parent of the contradictory-projection fixture.

    Its nested create input is where the two hosts' allowances meet, and an intersection
    there used to abort the entire schema build.
    """

    name = models.CharField(max_length=100)


class NestedHardDisjointKid(DummyModel):
    """A child whose two hosts project DISJOINT, non-overlapping surfaces.

    "headline" and "tagline" are allowed by one host each, so the merged surface tells
    an intersection and a union apart at a glance.
    """

    owner = models.ForeignKey(
        NestedHardDisjointOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    tagline = models.CharField(max_length=100, blank=True, default="")
    is_staff = models.BooleanField(default=False)


class NestedHardNameOwner(DummyModel):
    """A multi-word parent model name, which the generated type must preserve.

    The nested input type is named after the parent and that name is on the wire, so
    flattening its internal capitals renames a published type.
    """

    name = models.CharField(max_length=100)


class NestedHardNameKid(DummyModel):
    """The child whose per-parent input type name is pinned by the tests.

    It declares nothing of its own, leaving the generated name as the only thing the
    naming fixture can be reading.
    """

    owner = models.ForeignKey(
        NestedHardNameOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedHardVerbBlog(DummyModel):
    """The nesting parent of the create-through-update stamp fixture.

    Only its UPDATE root is mounted, so the create reachable through its payload has no
    front door of its own for a caller to be refused at.
    """

    title = models.CharField(max_length=200)


class NestedHardVerbEntry(DummyModel):
    """A child creatable through the PARENT's update payload ("id" is optional).

    That optional "id" is the whole reason a caller holding "change" but not "add" still
    has to lose the nested field.
    """

    blog = models.ForeignKey(
        NestedHardVerbBlog, related_name="entries", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=200)


class NestedHardOptOutBlog(DummyModel):
    """The nesting parent of the "required_perms" opt-out fixture.

    Its nested "entries" field is what an empty override on the child tried to make
    public to the pruner.
    """

    title = models.CharField(max_length=200)


class NestedHardOptOutEntry(DummyModel):
    """A child whose host opts its nested surface out of the pruner's stamp.

    An empty "required_perms" legitimately publishes that host's OWN roots; it must not
    publish someone else's nested write of the same model.
    """

    blog = models.ForeignKey(
        NestedHardOptOutBlog, related_name="entries", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=200)


class NestedHardOnlyBatch(DummyModel):
    """A parent whose "Meta.only_fields" names NOTHING but its nested relation.

    One ordinary Meta option is all it takes to reach an input object whose every field
    carries the child's write stamp.
    """

    title = models.CharField(max_length=200)


class NestedHardOnlyRow(DummyModel):
    """The child that is the parent's sole writable input field.

    Denying its write empties the parent's input object entirely, which is where the
    pruner used to fall back to the UNFILTERED field map.
    """

    batch = models.ForeignKey(
        NestedHardOnlyBatch, related_name="rows", on_delete=models.CASCADE
    )
    value = models.CharField(max_length=200)


class NestedHardKeeperBatch(DummyModel):
    """A sibling parent whose root must SURVIVE the empty-input cascade.

    It shares only the mutation root with the emptied parent, so it measures the blast
    radius: without it, deleting the whole mutation type would look like a correct fix.
    """

    title = models.CharField(max_length=200)


class NestedHardLateOwner(DummyModel):
    """The nesting parent of the late-host fixture.

    Its nested child input is materialized first, after which graphql-core's cached
    field map can never accept another host's projection.
    """

    name = models.CharField(max_length=100)


class NestedHardLateKid(DummyModel):
    """A child whose host is declared AFTER its nested input was materialized.

    The late host declares an exclusion, so accepting it in silence bakes the wider
    surface in for the whole process lifetime.
    """

    owner = models.ForeignKey(
        NestedHardLateOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedHardSigOwner(DummyModel):
    """The nesting parent of the closed-signature permission fixture.

    Ungated itself, so the only permission code a nested create runs is the child's and
    a crash can only have come from there.
    """

    name = models.CharField(max_length=100)


class NestedHardSigKid(DummyModel):
    """A child whose permission class spells its arguments out, no "**kwargs".

    Its policy GRANTS the write, so the fixture can only fail one way: an uncaught
    "TypeError" on the nested path.
    """

    owner = models.ForeignKey(
        NestedHardSigOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedHardQsOwner(DummyModel):
    """The nesting parent of the "Meta.queryset" scoping fixture.

    Its nested update payload is the only route to a row the child's declarative scope
    hides.
    """

    name = models.CharField(max_length=100)


class NestedHardQsKid(DummyModel):
    """A child whose host narrows its base queryset through "Meta.queryset".

    Scoping declaratively rather than through "filter_queryset" is what a nested lookup
    can easily miss, and missing it rewrites rows the child's own update refuses to
    touch.
    """

    owner = models.ForeignKey(
        NestedHardQsOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedHardLatePlainOwner(DummyModel):
    """The nesting parent of the harmless-late-host fixture.

    The control for the late-host guard: something has to prove that guard does not
    refuse every declaration arriving after a build.
    """

    name = models.CharField(max_length=100)


class NestedHardLatePlainKid(DummyModel):
    """A child whose late host declares no projection, so nothing is lost.

    Declaring a plain host for an already-nested model is ordinary, and turning that
    into an import-time crash would be worse than the defect.
    """

    owner = models.ForeignKey(
        NestedHardLatePlainOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedHardOverlapOwner(DummyModel):
    """The nesting parent of the overlapping-projection fixture.

    A parent of its own rather than the disjoint fixture's, because the nested child
    input is memoized per parent.
    """

    name = models.CharField(max_length=100)


class NestedHardOverlapKid(DummyModel):
    """A child whose two hosts project OVERLAPPING surfaces.

    An intersection survives here instead of emptying, so this is the case that would
    silently drop the columns only one host allows.
    """

    owner = models.ForeignKey(
        NestedHardOverlapOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    tagline = models.CharField(max_length=100, blank=True, default="")
    extra = models.CharField(max_length=100, blank=True, default="")


# --- nested-write round-4 models -------------------------------------------- #
# DEDICATED to "test_nested_child_round4". Same reason as the groups above: the
# nested host registry is model-keyed, so sharing a model with another module
# would make the projection and the permission stamp depend on import order (the
# suite runs under pytest-randomly).
class NestedR4ReadOwner(DummyModel):
    """The nesting parent of the read-host stamp fixture.

    Model-permission gated, so a caller can be granted the parent's writes exactly and
    then measured on the child's label alone.
    """

    name = models.CharField(max_length=100)


class NestedR4ReadKid(DummyModel):
    """A child whose only host is an ordinary READ host with a read label.

    The commonest shape in a real project, and the one whose view permission used to
    collapse the nested WRITE stamp down to a read.
    """

    owner = models.ForeignKey(
        NestedR4ReadOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR4PkOwner(DummyModel):
    """The nesting parent of the primary-key-only overlap fixture.

    The nested create built through it is where two allowances sharing nothing but the
    pk would leave behind a column the input cannot even emit.
    """

    name = models.CharField(max_length=100)


class NestedR4PkKid(DummyModel):
    """A child whose two hosts overlap ONLY on the primary key.

    The pk is the one column two otherwise unrelated projections are almost certain to
    share, which is what made an intersection look survivable.
    """

    owner = models.ForeignKey(
        NestedR4PkOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    tagline = models.CharField(max_length=100, blank=True, default="")


class NestedR4XOwner(DummyModel):
    """The nesting parent of the only-fields-versus-exclude-fields fixture.

    Its nested create is where the allowance union meets the prohibition union, and the
    order the two are applied in becomes visible.
    """

    name = models.CharField(max_length=100)


class NestedR4XKid(DummyModel):
    """A child whose one host exposes the field the other one hides.

    "headline" is allowed by one host and forbidden by the other, so the prohibition has
    to win or the security half of the merge is lost.
    """

    owner = models.ForeignKey(
        NestedR4XOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    tagline = models.CharField(max_length=100, blank=True, default="")


class NestedR4OpOwner(DummyModel):
    """The nesting parent of the split-surface fixture.

    It serves both write verbs, so the nested create and the nested update can be built
    and compared against each other.
    """

    name = models.CharField(max_length=100)


class NestedR4OpKid(DummyModel):
    """A child served by a create-only host and an update-only host.

    The two hosts project differently, so an operation-blind merge narrows the create
    and widens the update at the same time.
    """

    owner = models.ForeignKey(
        NestedR4OpOwner, related_name="kids", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=100)
    body = models.CharField(max_length=100, blank=True, default="")


class NestedR4BuildOwner(DummyModel):
    """The nesting parent whose schema build must surface the config error.

    Mounted on real roots inside the test, so its nested input is resolved through a
    graphql-core fields thunk rather than a direct call.
    """

    name = models.CharField(max_length=100)


class NestedR4BuildKid(DummyModel):
    """A child with contradictory projections, reached through a real build.

    "alpha" and "beta" are allowed by one host each; before the allowance union that
    pair aborted the entire schema assembly.
    """

    owner = models.ForeignKey(
        NestedR4BuildOwner, related_name="kids", on_delete=models.CASCADE
    )
    alpha = models.CharField(max_length=100)
    beta = models.CharField(max_length=100, blank=True, default="")


class NestedR4AuthOwner(DummyModel):
    """The nesting parent of the closed-signature "authorize" fixture.

    It drives the second of the two seams the nested extras cross, so both are exercised
    through the same nested-create path.
    """

    name = models.CharField(max_length=100)


class NestedR4AuthKid(DummyModel):
    """A child whose "authorize" override spells its arguments out.

    The shape a project wrote before "nested_parent" existed. It grants the write, so
    any failure is a crash rather than a denial.
    """

    owner = models.ForeignKey(
        NestedR4AuthOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR4PolicyOwner(DummyModel):
    """The nesting parent of the closed-signature "has_permission" fixture.

    Ungated itself, so a nested create through it runs the child's policy and nothing
    else.
    """

    name = models.CharField(max_length=100)


class NestedR4PolicyKid(DummyModel):
    """A child whose policy overrides "has_permission" with a closed signature.

    "has_permission" is the DOCUMENTED primary override point, and narrowing the extras
    only at the outer call site left it receiving them unfiltered.
    """

    owner = models.ForeignKey(
        NestedR4PolicyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR4LabelHost(DummyModel):
    """A host model for the plain "required_perms" class-attribute fixture.

    It is never nested under anything: it exists so a "DjangoModelType" can declare the
    guides' plain spelling, which used to raise at class-definition time.
    """

    name = models.CharField(max_length=100)


class NestedR5StampOwner(DummyModel):
    """The nesting parent of the host-label union fixture.

    Model-permission gated, so the three pruning cases in "test_nested_child_round5"
    differ only in which permissions the caller holds.
    """

    name = models.CharField(max_length=100)


class NestedR5StampKid(DummyModel):
    """A child whose WRITE host declares a stricter permission label.

    The label is not a verb the composite table produces, so finding it on the nested
    stamp proves the host override was unioned in rather than ignored.
    """

    owner = models.ForeignKey(
        NestedR5StampOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR5ExcOwner(DummyModel):
    """The nesting parent of the operation-blind exclusion fixture.

    Its nested UPDATE surface is where a prohibition declared by a create-only host
    still has to apply.
    """

    name = models.CharField(max_length=100)


class NestedR5ExcKid(DummyModel):
    """A child one of whose hosts forbids a column on its own operation only.

    "role" is excluded by the project's only write mutation, so a nested update that
    accepts it writes a column no other surface would.
    """

    owner = models.ForeignKey(
        NestedR5ExcOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    role = models.CharField(max_length=50, blank=True, default="")


class NestedR5ScopeOwner(DummyModel):
    """The nesting parent of the write-host scoping fixture.

    A nested update through it must reach a row that only a host serving no write would
    have hidden.
    """

    name = models.CharField(max_length=100)


class NestedR5ScopeKid(DummyModel):
    """A child whose CREATE-only host narrows a queryset it never updates.

    Splitting a child into a create host and an update host is the library's own idiom,
    so over-scoping here is collateral damage on projects that were never exposed.
    """

    owner = models.ForeignKey(
        NestedR5ScopeOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR5HideOwner(DummyModel):
    """The nesting parent of the hidden-row disclosure fixture.

    Two rows of it are created per test so a hidden child can belong to the OTHER parent
    -- the case where the ownership guard answers before the scope does.
    """

    name = models.CharField(max_length=100)


class NestedR5HideKid(DummyModel):
    """A child whose host hides the rows of every other tenant.

    Its "owner" foreign key is nullable so one model covers both an owned hidden row and
    an ownerless one, which have to produce identical errors.
    """

    owner = models.ForeignKey(
        NestedR5HideOwner,
        related_name="kids",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    headline = models.CharField(max_length=100)
    tenant = models.CharField(max_length=20, blank=True, default="a")


class NestedR5RegOwner(DummyModel):
    """The nesting parent whose child is materialized in ONE registry only.

    The first registry's nested input is built through it, and a host bound to a second
    registry must not narrow that surface afterwards.
    """

    name = models.CharField(max_length=100)


class NestedR5RegKid(DummyModel):
    """A child re-hosted against a SECOND registry after the first froze it.

    "secret" is what the late host would have excluded, and it has to survive: that host
    belongs to another schema entirely.
    """

    owner = models.ForeignKey(
        NestedR5RegOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR5TwinOwner(DummyModel):
    """The nesting parent of the duplicate-projection late-host fixture.

    Building through it freezes the child's nested input, which is the precondition the
    late-host guard needs before it can be tested at all.
    """

    name = models.CharField(max_length=100)


class NestedR5TwinKid(DummyModel):
    """A child whose late host repeats a projection already contributing.

    Excludes are unioned, so a repeat cannot move the built surface -- refusing it would
    buy nothing and break an ordinary declaration.
    """

    owner = models.ForeignKey(
        NestedR5TwinOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR5LateLabelOwner(DummyModel):
    """The nesting parent of the late "required_perms" fixture.

    Once its nested input is built, graphql-core has cached the field map and no newly
    declared label can ever reach it.
    """

    name = models.CharField(max_length=100)


class NestedR5LateLabelKid(DummyModel):
    """A child whose late host declares nothing but a permission label.

    A label narrows the nested stamp, so accepting it in silence leaves the surface
    reachable for exactly the callers the project meant to exclude.
    """

    owner = models.ForeignKey(
        NestedR5LateLabelOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR5LateOnlyOwner(DummyModel):
    """The nesting parent of the late "only_fields" fixture.

    The other narrowing axis, on a parent of its own so its materialization record
    cannot be armed by a neighbouring fixture's build.
    """

    name = models.CharField(max_length=100)


class NestedR5LateOnlyKid(DummyModel):
    """A child whose late host declares nothing but "only_fields".

    Ignoring the late allowance keeps the WIDER surface baked in for the process
    lifetime, the opposite of what the declaration asked for.
    """

    owner = models.ForeignKey(
        NestedR5LateOnlyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    extra = models.CharField(max_length=100, blank=True, default="")


class NestedR5PolicyOwner(DummyModel):
    """The nesting parent of the closed-signature nested-UPDATE fixture.

    Every earlier test of that contract drove a nested create, so this parent exists to
    cross the update forward instead.
    """

    name = models.CharField(max_length=100)


class NestedR5PolicyKid(DummyModel):
    """A child UPDATED through its parent under a closed-signature policy.

    Its policy grants the write, so the only way the fixture fails is an uncaught
    "TypeError" at the forward a nested update actually takes.
    """

    owner = models.ForeignKey(
        NestedR5PolicyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR6SplitOwner(DummyModel):
    """The nesting parent of the read/write projection-split fixture.

    The nested create built through it in "test_nested_child_round6" is where two
    allowances sharing no column have to union rather than intersect.
    """

    name = models.CharField(max_length=100)


class NestedR6SplitKid(DummyModel):
    """A child whose read card and write host project different columns.

    "slug" is a display column and "headline" a writable one, while "extra" is allowed
    by nobody -- so the union can be shown to still be a projection.
    """

    owner = models.ForeignKey(
        NestedR6SplitOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    slug = models.CharField(max_length=100, blank=True, default="")
    extra = models.CharField(max_length=100, blank=True, default="")


class NestedR6IsoOwner(DummyModel):
    """The nesting parent of the per-registry isolation fixture.

    Ungated on purpose: any narrowing or denial observed through it could only have come
    from the other registry's host.
    """

    name = models.CharField(max_length=100)


class NestedR6IsoKid(DummyModel):
    """A child hosted twice: once per registry, with opposite narrowing.

    The second registry's host narrows projection, label and scope at once, so a
    process-wide host list leaks on all three axes.
    """

    owner = models.ForeignKey(
        NestedR6IsoOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR6LateOwner(DummyModel):
    """The nesting parent DECLARED BEFORE its child's write host.

    A parent app importing a child app later is the ordinary order, so a stamp frozen at
    this class's definition time misses the label on the commonest layout there is.
    """

    name = models.CharField(max_length=100)


class NestedR6LateKid(DummyModel):
    """A child whose labelled write host is declared after the parent.

    Late but still before the build, so its projection always landed and the label is
    the half that used to be lost.
    """

    owner = models.ForeignKey(
        NestedR6LateOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR6OpsOwner(DummyModel):
    """The nesting parent of the operation-scoped label fixture.

    The nested CREATE surface built through it is an operation the child's only labelled
    host does not serve.
    """

    name = models.CharField(max_length=100)


class NestedR6OpsKid(DummyModel):
    """A child whose only labelled host serves nothing but "delete".

    A purge permission says nothing about creating the child, so unioning it into the
    create stamp locks out callers who may legitimately write.
    """

    owner = models.ForeignKey(
        NestedR6OpsOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR6PinKid(DummyModel):
    """A tenant-scoped row reached through a forward FK and an M2M.

    Both link branches of "_persist_child" resolve to a row this scope hides, which is
    the only reason attaching a row can be a disclosure.
    """

    headline = models.CharField(max_length=100)
    tenant = models.CharField(max_length=20, blank=True, default="a")


class NestedR6PinOwner(DummyModel):
    """A parent already linked to the hidden child on BOTH link relations.

    Being linked already is the point: a payload naming the row the parent holds is a
    write of that row rather than a link, and it falls straight through to the writer.
    """

    name = models.CharField(max_length=100)
    fwd = models.ForeignKey(
        NestedR6PinKid,
        related_name="fwd_owners",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(NestedR6PinKid, related_name="tag_owners", blank=True)


class NestedR6SigOwner(DummyModel):
    """The nesting parent of the late-twin signature fixture.

    The test materializes its nested UPDATE input first, which is the surface a late
    update-only host would otherwise have narrowed in silence.
    """

    name = models.CharField(max_length=100)


class NestedR6SigKid(DummyModel):
    """A child whose late hosts repeat a projection on a DIFFERENT operation.

    The same "only_fields" on another verb contributes to a surface the early host never
    touched, so the operations belong in the no-op signature.
    """

    owner = models.ForeignKey(
        NestedR6SigOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    extra = models.CharField(max_length=100, blank=True, default="")


class NestedR6LabelOwner(DummyModel):
    """The nesting parent of the late-twin label fixture.

    Its name appears only in the late-host refusal, which is what lets the test prove
    the error came from that guard and no other.
    """

    name = models.CharField(max_length=100)


class NestedR6LabelKid(DummyModel):
    """A child whose late host repeats a projection but adds a label.

    The projections match exactly, leaving "required_perms" as the only difference -- so
    a signature ignoring labels waves the host through.
    """

    owner = models.ForeignKey(
        NestedR6LabelOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR6LocalOwner(DummyModel):
    """A nesting parent bound to a LOCAL registry through "Meta.registry".

    The multi-schema shape that must still see the global hosts: missing them costs
    projection, scope, label and permission gate all at once.
    """

    name = models.CharField(max_length=100)


class NestedR6LocalKid(DummyModel):
    """A child whose only host lives in the OTHER (global) registry.

    "Meta.registry" is not an option on "DjangoModelType", so a child's type host can
    only ever live there -- which is why the lookup has to union the two registries.
    """

    owner = models.ForeignKey(
        NestedR6LocalOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")
    tenant = models.CharField(max_length=20, blank=True, default="a")


class NestedR7DefaultOwner(DummyModel):
    """The nesting parent of the declare-nothing default fixture.

    Its nested create input and its nested update path are where
    "test_nested_child_round7" checks that the new "model_operations" option is a pure
    opt-out.
    """

    name = models.CharField(max_length=100)


class NestedR7DefaultKid(DummyModel):
    """A child whose only host declares no "model_operations" at all.

    The shape every existing project already has: its exclusion and its tenant queryset
    both have to keep reaching the nested write path.
    """

    owner = models.ForeignKey(
        NestedR7DefaultOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")
    tenant = models.CharField(max_length=20, blank=True, default="a")


class NestedR7ReadOwner(DummyModel):
    """The nesting parent of the declared READ-host fixture.

    Mounted on that module's schema roots, so its nested input is resolved through a
    real build as well as inspected directly.
    """

    name = models.CharField(max_length=100)


class NestedR7ReadKid(DummyModel):
    """A child hosted by a declared read card and a separate write mutation.

    The card allows "secret" and hides other tenants; declaring it a read host is what
    keeps both out of the nested write surface.
    """

    owner = models.ForeignKey(
        NestedR7ReadOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")
    tenant = models.CharField(max_length=20, blank=True, default="a")


class NestedR7BareOwner(DummyModel):
    """The nesting parent of the no-host-at-all fixture.

    The only declaration in that fixture, so a nested payload built through it has to
    keep every writable column the child has.
    """

    name = models.CharField(max_length=100)


class NestedR7BareKid(DummyModel):
    """A plain related model with no declared host of its own.

    The no-regression floor for the no-allowance branch: inventing a projection here
    would delete columns from every existing nested payload.
    """

    owner = models.ForeignKey(
        NestedR7BareOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7NoServeOwner(DummyModel):
    """The nesting parent of the no-host-serves-this-operation fixture.

    A nested create through it has no serving host at all, which is the state the second
    no-allowance branch describes.
    """

    name = models.CharField(max_length=100)


class NestedR7NoServeKid(DummyModel):
    """A child whose only host serves nothing but "delete".

    That host declares both projection axes, so the merge has to drop its allowance and
    keep its prohibition: "secret" stays unwritable.
    """

    owner = models.ForeignKey(
        NestedR7NoServeOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7LastOwner(DummyModel):
    """The nesting parent of the prohibition-wins fixture.

    The surface a client would actually reach the forbidden column through, and the
    scope the crossed projection is merged for.
    """

    name = models.CharField(max_length=100)


class NestedR7LastKid(DummyModel):
    """A child one host allows a column of and another host forbids.

    Crossing the two axes on "secret" is what makes the merge ORDER observable:
    whichever axis is applied last decides whether the column ships.
    """

    owner = models.ForeignKey(
        NestedR7LastOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7CrossOwner(DummyModel):
    """A nesting parent bound to a LOCAL registry through "Meta.registry".

    Parent and host live in different registries here, the case a registry-scoped lookup
    turns into a completely ungated nested write.
    """

    name = models.CharField(max_length=100)


class NestedR7CrossKid(DummyModel):
    """A child whose only permission host can only live in the global registry.

    That host carries a deny-everything policy, so a lookup that misses it does not
    merely widen a projection -- it grants the write.
    """

    owner = models.ForeignKey(
        NestedR7CrossOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7PkOwner(DummyModel):
    """The nesting parent of the upsert-by-id fixture.

    The wire-level assertions and the end-to-end upsert both run through it, so the
    surface and the behaviour are pinned on one parent.
    """

    name = models.CharField(max_length=100)


class NestedR7PkKid(DummyModel):
    """A child whose write host projects a column list without the pk.

    An ordinary projection, since a pk is not a column a client writes -- but on an
    update surface it is how the row is named.
    """

    owner = models.ForeignKey(
        NestedR7PkOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    extra = models.CharField(max_length=100, blank=True, default="")


class NestedR7EmptyOwner(DummyModel):
    """The nesting parent of the emptied-projection fixture.

    Deliberately never mounted on its module's roots: doing so would raise the
    configuration error at import and take the whole file down.
    """

    name = models.CharField(max_length=100)


class NestedR7EmptyKid(DummyModel):
    """A child one host allows exactly the column another host forbids.

    Both declarations are legal on their own; together they leave a zero-field input
    object graphql-core refuses to build a schema from.
    """

    owner = models.ForeignKey(
        NestedR7EmptyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR7ThunkOwner(DummyModel):
    """A nesting parent whose hosts live in a NON-global registry only.

    Its already-built input argument is what the tests read, which walks the same thunk
    a real request walks.
    """

    name = models.CharField(max_length=100)


class NestedR7ThunkKid(DummyModel):
    """A child hosted only in the parent's own local registry.

    A thunk falling back to the global registry finds nothing here, so it mints an
    unprojected input AND an unlabelled field.
    """

    owner = models.ForeignKey(
        NestedR7ThunkOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7SigOwner(DummyModel):
    """The nesting parent of the exclusion-signature fixture.

    A parent of its own, because the late-host record is keyed per parent and sharing
    one would arm this fixture from a neighbouring build.
    """

    name = models.CharField(max_length=100)


class NestedR7SigKid(DummyModel):
    """A child whose two hosts differ ONLY in what they forbid.

    If exclusions drop out of the no-op signature the late host compares equal, is waved
    through, and its prohibition never reaches the frozen input.
    """

    owner = models.ForeignKey(
        NestedR7SigOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7SlotKid(DummyModel):
    """A model hosted twice, by two mutations projecting different columns.

    The first host to reach the shared "(model, operation)" input slot used to own the
    wire surface for every later one, so the second host's projection simply vanished.
    """

    headline = models.CharField(max_length=100)
    is_admin = models.BooleanField(default=False)


class NestedR7KeyOwner(DummyModel):
    """The nesting parent of the client-supplied primary key fixture.

    The nested update surface built through it is where "id" has to appear and the
    model's pk column name has to stay out.
    """

    name = models.CharField(max_length=100)


class NestedR7KeyKid(DummyModel):
    """A child whose primary key is supplied by the client, not generated.

    Its pk column is "code", which separates the wire name the identity exemption must
    key on from the column name it must not.
    """

    code = models.CharField(max_length=50, primary_key=True)
    owner = models.ForeignKey(
        NestedR7KeyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)


class NestedR7MatOwner(DummyModel):
    """A nesting parent on a local registry whose build freezes the surface.

    If the materialization record lands only in that registry, a late GLOBAL host is
    accepted in silence even though it can never reach the frozen input.
    """

    name = models.CharField(max_length=100)


class NestedR7MatKid(DummyModel):
    """A child whose global host arrives after a local parent's build.

    Deliberately hostless at import: the only host for it is declared inside the test,
    too late to contribute anything.
    """

    owner = models.ForeignKey(
        NestedR7MatOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")


class NestedR7OnlyOwner(DummyModel):
    """The nesting parent of the allowance-signature fixture.

    Its name appears in the refusal message, which is what proves the error came from
    the late-host guard and not the emptied-projection one.
    """

    name = models.CharField(max_length=100)


class NestedR7OnlyKid(DummyModel):
    """A child whose two hosts differ ONLY in what they allow.

    A late host widening the allowance is a real contribution, so a signature that
    ignores "only_fields" waves it through and the column it meant to allow never
    appears.
    """

    owner = models.ForeignKey(
        NestedR7OnlyOwner, related_name="kids", on_delete=models.CASCADE
    )
    headline = models.CharField(max_length=100)
    secret = models.CharField(max_length=100, blank=True, default="")
