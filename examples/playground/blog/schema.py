"""GraphQL schema wiring every django-graphex feature.

- Public queries: single object, lists with the 3 paginations, filtering,
  nested lists (results/totalCount, N+1-safe), directives.
- Private queries (require auth): "me" and "myNotes" (scoped to the user).
- Mutations: Note create/update/delete via DjangoModelType + permissions.
- Subscriptions: public "postSubscription" and private "noteSubscription".
"""

import os

import graphene  # transitional: only the `class args` argument form (graphene.Argument)
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Count
from django.utils import timezone
from graphql import GraphQLBoolean, GraphQLInt, GraphQLString

from django_graphex import (
    AllowAny,  # noqa: F401 — available for permission_classes experimentation
    AnnotatedField,
    Base64FileInput,
    BasePermission,
    CursorGraphqlPagination,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoGraphQLSchema,
    DjangoInputObjectType,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoModelMutation,
    DjangoModelType,
    DjangoNestedListObjectField,
    DjangoObjectField,
    DjangoObjectType,
    DjangoUnionType,
    IsAdmin,  # noqa: F401 — available for permission_classes experimentation
    IsAdminOrReadOnly,  # noqa: F401 — available for permission_classes experimentation
    IsAuthenticated,  # noqa: F401 — available for permission_classes experimentation
    IsAuthenticatedOrReadOnly,
    LimitOffsetGraphqlPagination,
    Mutation,
    ObjectType,
    PageGraphqlPagination,
    all_directives,
    field,
    filter_field,
)
from django_graphex.subscriptions import Subscription

from .models import (
    Account,
    Attachment,
    Author,
    Category,
    Comment,
    Document,
    Invoice,
    Note,
    Post,
    Tag,
)

User = get_user_model()


# --------------------------------------------------------------------------- #
# Object types (single objects)                                               #
# --------------------------------------------------------------------------- #
class UserType(DjangoObjectType):
    class Meta:
        model = User
        filter_fields = {"id": ("exact",), "username": ("icontains",)}


class CategoryType(DjangoObjectType):
    class Meta:
        model = Category
        filter_fields = {"id": ("exact",), "name": ("exact", "icontains")}


class CommentType(DjangoObjectType):
    class Meta:
        model = Comment
        filter_fields = {"id": ("exact",), "text": ("icontains",)}


class TagType(DjangoObjectType):
    # Registering this type makes Post.tags (a M2M) resolve as a nested list with
    # the uniform results/totalCount shape, filtering and pagination.
    class Meta:
        model = Tag
        filter_fields = {"id": ("exact",), "name": ("exact", "icontains")}


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        # `status` (a TextChoices field) becomes a GraphQL enum automatically.
        filter_fields = {
            "id": ("exact",),
            "title": ("icontains",),
            "status": ("exact",),
            "author": ("exact",),
        }
        # Per-type depth/cost hints (DepthLimitValidationRule /
        # CostLimitValidationRule, both wired in GraphQLView).
        # max_deep: reject any query that nests *more than N levels below* a
        # PostType field; this combines with MAX_QUERY_DEPTH (most-restrictive wins).
        # complexity: cost weight for CostLimitValidationRule (default is 1).
        max_deep = 4
        complexity = 2

    # ---- @filter_field showcase (v1.3.0) ------------------------------------- #
    # A custom GraphQL filter argument that isn't a plain model-field lookup.
    # The arg name (`search`) becomes the GraphQL argument; the method returns
    # a filtered queryset. The decorator handles classmethod semantics — do NOT
    # stack @classmethod.
    #
    # Try it:
    #   { posts(filter: { search: "django" }) { results { id title } totalCount } }
    #
    # Composition order at query time:
    #   1. Standard lookups (id, title, status, author from filter_fields)
    #   2. @filter_field methods in declaration order  ← search runs here
    #   3. filter_queryset (see get_queryset below)    ← applied last
    @filter_field(GraphQLString, description="Full-text search over title and body")
    def search(cls, queryset, info, value):
        """Filter posts whose title OR body contains the search term."""
        from django.db.models import Q

        return queryset.filter(Q(title__icontains=value) | Q(body__icontains=value))

    # ---- get_queryset scoping showcase (v1.2.2) ------------------------------ #
    # Before v1.2.2 this hook was documented but never called on list, paginated,
    # or list-object fields — only on single-object (DjangoObjectField) lookups.
    # v1.2.2 fix (#58): get_queryset is now invoked on ALL four top-level field
    # types before the query optimizer runs.
    # Try it: anonymous request → only PUBLISHED posts returned.
    #         authenticated request (log in via /admin) → all posts visible.
    @classmethod
    def get_queryset(cls, queryset, info):
        user = getattr(info.context, "user", None)
        if user is not None and user.is_authenticated:
            # Authenticated users see every post regardless of status.
            return queryset
        # Anonymous users only see published posts.
        return queryset.filter(status=Post.Status.PUBLISHED)


# --------------------------------------------------------------------------- #
# List types (results + totalCount). Also used for nested lists.              #
# Each uses a different paginator so you can try all three.                   #
# --------------------------------------------------------------------------- #
class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        # Safe ordering (v1.2.x): the ordering allowlist rejects relation-spanning
        # and non-existent terms to prevent column-oracle attacks.
        # Try in GraphQL:
        #   posts { results(ordering: "author__user__password") { title } }
        #     → GraphQLError: 'Relation-spanning ordering is not permitted'
        #   posts { results(ordering: "nonexistent") { title } }
        #     → GraphQLError: 'Invalid ordering field'
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")


# AuthorType is declared AFTER PostListType because it references it directly as
# the type of its explicit nested `posts` field (DjangoNestedListObjectField).
class AuthorType(DjangoObjectType):
    # ---- Query-optimization showcase (v1.1.0+) --------------------------- #
    # AnnotatedField: a selection-driven DB annotation. The optimizer adds
    # `.annotate(_gqx_ann_post_count=Count('posts'))` ONLY when `postCount` is in
    # the selection; when it is not selected, no extra SQL is emitted. The default
    # resolver reads the value straight off the row (no resolve_post_count needed).
    post_count = AnnotatedField(GraphQLInt, Count("posts"))

    # Explicit nested list (instead of the auto-generated one) so we can attach a
    # per-field optimize hook below. Reuses PostListType's pagination + filtering.
    posts = DjangoNestedListObjectField(PostListType, accessor="posts")

    class Meta:
        model = Author
        filter_fields = {"id": ("exact",), "name": ("icontains",)}

    @staticmethod
    def optimize_posts(queryset, info, **kwargs):
        """Per-field optimize hook for the `posts` nested list.

        Composes on top of the optimizer-built child queryset for the `posts`
        prefetch, and is called ONCE per query (not once per author). The name is
        `optimize_` + the snake_case GraphQL field name, declared on the PARENT
        type (AuthorType). It MUST return a QuerySet (a non-QuerySet return logs a
        WARNING and is ignored). kwargs carries `filter_value` (the field's filter
        input or None) and `is_window` (True only on the DB-side windowed path).

        Here the hook forces a stable secondary ordering on every author's posts —
        a composition that layers cleanly on top of whatever `.only()` narrowing
        and window slicing the optimizer already built.

            return queryset.order_by("-id", "title")

        ------------------------------------------------------------------ #
        Why not `select_related("category")` here?                          #
        ------------------------------------------------------------------ #
        It is the textbook hook example, and it works fine *when the client
        also selects* `category { name }`. But the optimizer applies its
        `.only()` column narrowing to this child queryset AFTER the hook runs.
        When `category` is NOT in the selection, `category_id` is deferred —
        and `select_related("category")` on a deferred relation raises a Django
        ``FieldError``. The hook cannot see that future `.only()` plan, so a bare
        `select_related` would make `posts { results { title } }` (no category)
        blow up. We use an ordering composition instead so EVERY query stays
        runnable; the README spells out the `select_related` variant and its rule.
        """
        return queryset.order_by("-id", "title")


class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        pagination = PageGraphqlPagination(page_size=10)


class CommentListType(DjangoListObjectType):
    class Meta:
        model = Comment
        # Cursor pagination exposes a non-opaque pageInfo.
        pagination = CursorGraphqlPagination(ordering="-created")


# --------------------------------------------------------------------------- #
# Typed GenericForeignKey union (v1.2.0+).                                     #
#                                                                              #
# Declaration order is LOAD-BEARING: members -> union -> owner LAST.           #
#   1. AccountType / InvoiceType  — the two DjangoObjectType members.          #
#   2. AttachmentTargetUnion      — a DjangoUnionType over those members.      #
#   3. AttachmentType             — the owner; its Meta.gfk_unions maps the     #
#      `target` GFK to the union. If the owner were declared before the union   #
#      the converter would WARN and fall back to the flat GenericForeignKeyType. #
#                                                                              #
# Members are explicit (Meta.gfk_types); resolve_type is provided by           #
# DjangoUnionType (it maps a resolved Account/Invoice row to its registered     #
# type via the registry). Clients select per-member fields with inline         #
# fragments: `target { ... on AccountType { balance } ... on InvoiceType { … }}`.#
# --------------------------------------------------------------------------- #
class AccountType(DjangoObjectType):
    class Meta:
        model = Account


class InvoiceType(DjangoObjectType):
    class Meta:
        model = Invoice


class AttachmentTargetUnion(DjangoUnionType):
    class Meta:
        gfk_types = (AccountType, InvoiceType)


class AttachmentType(DjangoObjectType):
    class Meta:
        model = Attachment
        # Map the `target` GenericForeignKey to the typed union. On Django 5.0+
        # with OPTIMIZE_ONLY_FIELDS the optimizer routes `target` through a
        # GenericPrefetch with one .only()-narrowed queryset per content type
        # (Account fetches `balance`, Invoice fetches `amount`) — batched across
        # all attachments, no N+1.
        gfk_unions = {"target": AttachmentTargetUnion}


class AttachmentListType(DjangoListObjectType):
    class Meta:
        model = Attachment
        pagination = LimitOffsetGraphqlPagination(default_limit=10)


# --------------------------------------------------------------------------- #
# Custom permission — demonstrates BasePermission subclassing.               #
# AllowAny, IsAuthenticated, IsAdmin, and IsAdminOrReadOnly are imported      #
# above so you can assign them on any DjangoModelType.permission_classes      #
# without adding extra imports yourself.                                      #
# --------------------------------------------------------------------------- #
class IsOwnerOrReadOnly(BasePermission):
    """Authenticated users may read; only the owner may write.

    A real "is owner" check would compare instance.owner == request.user.
    Here we check authentication as a simple stand-in for any custom rule —
    the point is the pattern: override has_<action>_permission per-action.
    """

    def has_create_permission(self, info, model, **kwargs):
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)

    def has_update_permission(self, info, model, **kwargs):
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)

    def has_delete_permission(self, info, model, **kwargs):
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)


# --------------------------------------------------------------------------- #
# Serializer type: Note CRUD + permissions + per-request scoping             #
# --------------------------------------------------------------------------- #
class NoteModelType(DjangoModelType):
    # Anyone may read; only authenticated users may create/update/delete.
    # Swap to AllowAny, IsAuthenticated, IsAdmin, IsAdminOrReadOnly, or a
    # custom BasePermission subclass like IsOwnerOrReadOnly (all imported at
    # the top of this file) to experiment with different permission gates.
    permission_classes = [IsAuthenticatedOrReadOnly]

    class Meta:
        model = Note
        pagination = LimitOffsetGraphqlPagination(default_limit=10)
        filter_fields = {"id": ("exact",), "title": ("icontains",)}
        # Define once -> queries, mutations AND the subscription come from here.
        stream = "notes"
        serialize_data = True
        # Top-tier optimization (optional): route note notifications to a
        # per-owner group so a save only wakes that owner's subscribers instead
        # of everyone on the stream. Mirrors the `owner` key of subscription_scope.
        subscription_index_fields = ("owner",)

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        """Scope notes to the current user (used by the private "myNotes")."""
        user = getattr(info.context, "user", None)
        if user is not None and user.is_authenticated:
            return qs.filter(owner=user)
        return qs.none()

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        """Server-forced scope: only this user's note notifications.

        Evaluated at subscribe time; enforced per event at delivery (in memory,
        since ``owner`` is in the serialized payload). The client cannot widen or
        drop it.
        """
        user = getattr(info.context, "user", None)
        if user is not None and user.is_authenticated:
            return {"owner": user.pk}
        return None

    @classmethod
    def create(cls, root, info, **kwargs):
        """Set the current user as the note owner, then create normally."""
        user = getattr(info.context, "user", None)
        data = kwargs.get(cls._meta.input_field_name)
        if user is not None and user.is_authenticated and isinstance(data, dict):
            data["owner"] = user.pk
        return super().create(root, info, **kwargs)


# --------------------------------------------------------------------------- #
# Subscriptions                                                               #
# --------------------------------------------------------------------------- #
class PostSubscription(Subscription):
    class Meta:
        model = Post
        stream = "posts"
        serialize_data = True  # full payload in notifications


class CommentSubscription(Subscription):
    # Demonstrates per-subscriber `filters`: on a post-detail page, subscribe
    # with `filters: {post: <id>}` to receive only that post's comments.
    class Meta:
        model = Comment
        stream = "comments"
        serialize_data = True


# --------------------------------------------------------------------------- #
# Queries                                                                     #
# --------------------------------------------------------------------------- #
class PublicQuery(ObjectType):
    """Anyone can run these."""

    server_time = field(GraphQLString, description="A public scalar field.")

    # Single object by id (generic field).
    post = DjangoObjectField(PostType, description="A single post by id.")

    # Lists, one per paginator:
    posts = DjangoListObjectField(
        PostListType, description="Posts (limit/offset pagination + filtering)."
    )
    authors = DjangoListObjectField(
        AuthorListType,
        description="Authors (page pagination); each has a nested `posts` list.",
    )
    comments = DjangoListObjectField(
        CommentListType, description="Comments (cursor pagination + pageInfo)."
    )
    # Typed GFK union demo: each Attachment's `target` resolves to AccountType or
    # InvoiceType, selectable per-member via inline fragments.
    attachments = DjangoListObjectField(
        AttachmentListType,
        description="Attachments; each `target` is a typed GenericForeignKey union.",
    )

    # A plain filtered list (no pagination wrapper).
    categories = DjangoFilterListField(CategoryType)

    # A flat filtered + paginated list: same filtering as the list types, but the
    # pagination args (limit/offset) live on this field directly and it returns a
    # plain list of PostType instead of the results/totalCount wrapper.
    posts_flat = DjangoFilterPaginateListField(
        PostType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10),
        description="Posts as a flat filtered + paginated list (no wrapper).",
    )

    def resolve_server_time(self, info):
        return timezone.now().isoformat()


class PrivateQuery(ObjectType):
    """Require an authenticated user (enforced by AuthenticatedFieldsMiddleware)."""

    me = field(UserType, description="The current user.")
    # NoteModelType.filter_queryset scopes this list to the current user; the
    # field's own resolver (cls.list) runs, so no resolve_* method is needed.
    my_notes = NoteModelType.ListField(description="Notes owned by the current user.")

    def resolve_me(self, info):
        user = getattr(info.context, "user", None)
        return user if (user and user.is_authenticated) else None


# --------------------------------------------------------------------------- #
# Mutations                                                                   #
# --------------------------------------------------------------------------- #
class PostMutation(DjangoModelMutation):
    """Public Post CRUD.

    Lets you trigger the public ``postSubscription`` from ``/graphql``: a
    ``postCreate`` runs in the ASGI process, fires Django's ``post_save`` signal
    and the subscription engine broadcasts the notification to subscribers.
    """

    class Meta:
        model = Post


class CommentMutation(DjangoModelMutation):
    """Public Comment CRUD -- drives ``commentSubscription`` from ``/graphql``."""

    class Meta:
        model = Comment


class PostWithCommentsMutation(DjangoModelMutation):
    """Nested-write demo: create a Post together with one or more Comments.

    ``Meta.nested_fields`` tells django-graphex that the ``comments`` accessor
    (a reverse FK from Comment.post) should be handled as nested input.  The
    ``NestedFieldsMixin`` detects the relation direction automatically:

    * It classifies ``comments`` as ``reverse_many`` (one_to_many).
    * After saving the parent Post it calls ``_attach_children``, which
      iterates the list, injects ``post=<saved_post>`` into each child payload,
      and saves each Comment via the native backend — all inside one
      ``transaction.atomic()`` block.

    The auto-generated input type for the ``create`` operation therefore
    exposes ``comments`` as a list-of-object argument.  No hand-written
    resolver or serializer is needed.
    """

    class Meta:
        model = Post
        # Only expose the create operation; plain postCreate / postUpdate /
        # postDelete remain available from PostMutation above.
        model_operations = ("create",)
        nested_fields = {"comments": Comment}


# A model-derived input type. DjangoModelMutation builds these for you, but you
# can also declare one explicitly and use it as an argument on a hand-written
# graphene mutation when you need full control over the resolver.
class CategoryInput(DjangoInputObjectType):
    class Meta:
        model = Category
        only_fields = ("name",)


class CreateCategory(Mutation):
    """A hand-written mutation taking an explicit DjangoInputObjectType.

    Teaching note — unique-constraint violations
    --------------------------------------------
    ``Category.name`` has a unique constraint. Without the try/except below, a
    duplicate name raises an ``IntegrityError`` that Django bubbles up as HTTP
    500 — a hard crash with no useful message for the client.

    The idiomatic pattern for hand-written mutations is to catch the database
    error and return ``ok=False`` with a human-readable ``error`` string. This
    keeps the GraphQL response status 200 and hands the client structured error
    information.  (``DjangoModelMutation`` and ``DjangoModelType`` handle this
    automatically through their serialiser layer; hand-written mutations must
    do it explicitly.)

    Native 2.0 form (django_graphex.Mutation):
    - Arguments live on ``class args`` as ``graphene.Argument`` (the transitional
      argument form). The ``data`` argument's type is the compiled
      ``GraphQLInputObjectType`` of ``CategoryInput`` — referenced LAZILY via a
      thunk so it resolves at schema-build time (after the input compiler runs),
      not at class-definition time.
    - The output payload fields are declared via ``field()``.
    - ``mutate`` is a ``@classmethod`` returning ``cls(...)``.
    - Input-object arguments arrive as a plain ``dict`` (snake-case keys, the
      ``out_name`` contract), so read ``data["name"]`` — not attribute access.
    """

    class args:
        data = graphene.Argument(
            lambda: CategoryInput._meta.graphql_input_type, required=True
        )

    ok = field(GraphQLBoolean)
    category = field(CategoryType)
    error = field(GraphQLString)

    @classmethod
    def mutate(cls, root, info, **kwargs):
        data = kwargs["data"]
        name = data["name"]
        try:
            category = Category.objects.create(name=name)
        except IntegrityError:
            return cls(
                ok=False, category=None, error=f"Category '{name}' already exists."
            )
        # Pass every payload field explicitly (incl. error=None): native does not
        # auto-default unset payload fields, so an omitted field would leak the
        # class-level field() descriptor instead of resolving to null.
        return cls(ok=True, category=category, error=None)


# --------------------------------------------------------------------------- #
# Base64 file upload demo (v1.3.0).                                            #
#                                                                              #
# UploadDocument demonstrates the full Base64FileInput pattern:                #
#   1. Accept a Base64FileInput argument.                                      #
#   2. Call .to_uploaded_file(max_size=...) inside the resolver.               #
#   3. Assign the resulting SimpleUploadedFile to a model FileField.           #
#                                                                              #
# MAX_UPLOAD_SIZE and MAX_REQUEST_BODY_SIZE are set in config/settings.py so  #
# the guard fires in this playground. Unset either to see ImproperlyConfigured.#
#                                                                              #
# Try it in GraphiQL:                                                          #
#   import base64                                                              #
#   data = base64.b64encode(b"hello world").decode()                           #
#   mutation {                                                                 #
#       uploadDocument(                                                        #
#           name: "readme.txt"                                                 #
#           file: {filename: "readme.txt", data: "<data>", contentType: "text/plain"} #
#       ) { ok name }                                                          #
#   }                                                                          #
# --------------------------------------------------------------------------- #
class DocumentType(DjangoObjectType):
    class Meta:
        model = Document
        only_fields = ("id", "name", "created")


class UploadDocument(Mutation):
    """Demo: upload a base64-encoded file and attach it to a Document record.

    .. note::
        ``MAX_UPLOAD_SIZE`` must be set in ``DJANGO_GRAPHEX`` before using
        ``Base64FileInput``. See ``config/settings.py``.

    Native 2.0 form (django_graphex.Mutation):
    - ``file`` is a ``Base64FileInput`` argument: its compiled
      ``GraphQLInputObjectType`` is referenced LAZILY via a thunk so it resolves
      at schema-build time (after the input compiler runs).
    - Input-object arguments arrive as a plain ``dict`` (snake-case keys, the
      ``out_name`` contract), so the ``file`` payload is rehydrated into a
      ``Base64FileInput`` instance (``Base64FileInput(**file)``) before calling
      ``.to_uploaded_file()``.
    - Output payload fields are declared via ``field()``.
    """

    class args:
        name = graphene.Argument(graphene.String, required=True)
        file = graphene.Argument(
            lambda: Base64FileInput._meta.graphql_input_type, required=True
        )

    ok = field(GraphQLBoolean)
    name = field(GraphQLString)
    error = field(GraphQLString)

    @classmethod
    def mutate(cls, root, info, **kwargs):
        name = kwargs["name"]
        file = kwargs["file"]
        try:
            # The input object arrives as a dict (out_name snake keys); rehydrate
            # it into a Base64FileInput so .to_uploaded_file() is available.
            upload_input = Base64FileInput(**file)
            # Decode: max_size here overrides (or supplements) the global cap.
            # The global MAX_UPLOAD_SIZE from settings also applies when
            # max_size is not passed — both are checked.
            uploaded = upload_input.to_uploaded_file()  # uses MAX_UPLOAD_SIZE
            doc = Document(name=name)
            doc.file.save(uploaded.name, uploaded, save=True)
            # Pass every payload field explicitly (incl. error=None): native does
            # not auto-default unset payload fields.
            return cls(ok=True, name=doc.name, error=None)
        except Exception as exc:  # noqa: BLE001
            return cls(ok=False, name=name, error=str(exc))


# --------------------------------------------------------------------------- #
# Native compile trigger (native backend only).                                 #
#                                                                              #
# Hand-written ``Mutation`` arguments below reference a COMPILED                #
# ``GraphQLInputObjectType`` (``CategoryInput`` / ``Base64FileInput``).  Those  #
# input types — and every ``DjangoObjectType`` output type — are compiled by    #
# ``compile_all_inputs`` / ``compile_all_outputs``.  In a project that lists     #
# ``django_graphex`` in ``INSTALLED_APPS`` its ``AppConfig.ready()`` runs these  #
# automatically at startup; this playground triggers them explicitly here,       #
# AFTER all type declarations and BEFORE ``RootMutation`` calls ``.Field()`` (so #
# the lazy argument thunks resolve to real compiled input types, not ``None``).  #
# Gated on the native backend: under the legacy graphene backend these native    #
# compilers must NOT run (graphene compiles its own types lazily).               #
# --------------------------------------------------------------------------- #
if os.environ.get("GDX_BACKEND", "graphene") == "native":
    from django_graphex.native.base import compile_all_inputs  # noqa: E402
    from django_graphex.native.registry_compiler import (  # noqa: E402
        compile_all_outputs,
    )

    compile_all_inputs()
    compile_all_outputs()


class RootMutation(ObjectType):
    note_create, note_delete, note_update = NoteModelType.MutationFields()
    post_create = PostMutation.CreateField()
    post_update = PostMutation.UpdateField()
    post_delete = PostMutation.DeleteField()
    comment_create = CommentMutation.CreateField()
    comment_update = CommentMutation.UpdateField()
    comment_delete = CommentMutation.DeleteField()
    # Hand-written mutation using an explicit DjangoInputObjectType argument.
    create_category = CreateCategory.Field()
    # Nested-write demo: single operation creates the Post + its Comment(s).
    post_with_comments_create = PostWithCommentsMutation.CreateField()
    # Base64 file upload demo (v1.3.0).
    upload_document = UploadDocument.Field()


# --------------------------------------------------------------------------- #
# Subscriptions: a public subset and a (disjoint) private subset.             #
# --------------------------------------------------------------------------- #
class PublicSubscriptions(ObjectType):
    """Anyone may subscribe to these."""

    post_subscription = PostSubscription.Field()
    comment_subscription = CommentSubscription.Field()


class PrivateSubscriptions(ObjectType):
    """Require an authenticated user (enforced by AuthenticatedFieldsMiddleware)."""

    note_subscription = NoteModelType.SubscriptionField()


# --------------------------------------------------------------------------- #
# Schema. Each root is split into a public subset and a (disjoint) private     #
# subset; DjangoGraphQLSchema unions them and protects the private fields. In a #
# multi-app project you would aggregate per-app subsets, e.g.                   #
#   class RootSubscription(blog.PublicSubscriptions, shop.PublicSubscriptions,  #
#                          ObjectType): pass                                     #
# and pass those aggregates here instead.                                       #
# --------------------------------------------------------------------------- #
schema = DjangoGraphQLSchema(
    query=PublicQuery,
    private_query=PrivateQuery,
    mutation=RootMutation,
    subscription=PublicSubscriptions,
    private_subscription=PrivateSubscriptions,
    directives=all_directives,
)
