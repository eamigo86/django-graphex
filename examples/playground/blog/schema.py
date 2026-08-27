"""GraphQL schema wiring every django-graphex feature.

- Public queries: single object, lists with the 3 paginations, filtering,
  nested lists (results/totalCount, N+1-safe), directives.
- Private queries (require auth): "me" and "myNotes" (scoped to the user).
- Mutations: Note create/update/delete via DjangoModelType + permissions.
- Nested writes: "postWithCommentsCreate", gated by the child's own permission
  ("CommentModelType") the way 2.2.0 requires.
- Subscriptions: public "postSubscription" and private "noteSubscription".
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Count, Model, QuerySet
from django.utils import timezone
from graphql import GraphQLError, GraphQLInt, GraphQLResolveInfo, GraphQLString

from django_graphex.core import (
    BooleanField,
    CharField,
    Field,
    Mutation,
    ObjectType,
    field,
)
from django_graphex.directives import all_directives
from django_graphex.fields import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoNestedListObjectField,
    DjangoObjectField,
)
from django_graphex.filtering import filter_field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.paginations import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.permissions import (
    AllowAny,  # noqa: F401 — available for permission_classes experimentation
    BasePermission,
    IsAdmin,  # noqa: F401 — available for permission_classes experimentation
    IsAdminOrReadOnly,  # noqa: F401 — available for permission_classes experimentation
    IsAuthenticated,  # noqa: F401 — available for permission_classes experimentation
    IsAuthenticatedOrReadOnly,
)
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.subscriptions import Subscription
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
    DjangoUnionType,
)
from django_graphex.uploads import Base64FileInput

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
    """GraphQL type for the auth user, exposed by the private "me" query.

    Demonstrates a DjangoObjectType over the project user model with a small
    filter allowlist.
    """

    class Meta:
        """Bind the type to the user model and its filterable fields.

        Filtering allows an exact id lookup and a substring "username" lookup.
        """

        model = User
        filter_fields = {"id": ("exact",), "username": ("icontains",)}


class CategoryType(DjangoObjectType):
    """GraphQL type for a post category.

    Demonstrates exact and icontains lookups on the "name" field.
    """

    class Meta:
        """Bind the type to the Category model and its filterable fields.

        Filtering on "name" allows both exact and substring lookups.
        """

        model = Category
        filter_fields = {"id": ("exact",), "name": ("exact", "icontains")}


class CommentType(DjangoObjectType):
    """GraphQL type for a post comment.

    Demonstrates a substring lookup over the free-text "text" field.
    """

    class Meta:
        """Bind the type to the Comment model and its filterable fields.

        Filtering targets the free-text "text" field with a substring lookup.
        """

        model = Comment
        filter_fields = {"id": ("exact",), "text": ("icontains",)}


class TagType(DjangoObjectType):
    """GraphQL type for a post tag.

    Registering this type makes "Post.tags" (a many-to-many) resolve as a
    nested list with the uniform results/totalCount shape, plus filtering and
    pagination.
    """

    class Meta:
        """Bind the type to the Tag model and its filterable fields.

        Filtering on "name" allows both exact and substring lookups.
        """

        model = Tag
        filter_fields = {"id": ("exact",), "name": ("exact", "icontains")}


class PostType(DjangoObjectType):
    """GraphQL type for a blog post, the richest type in this schema.

    Showcases a "@filter_field" custom search argument, a "get_queryset" hook
    scoping visibility by auth state, an enum derived from the "status"
    TextChoices field, and per-type depth/cost limits.
    """

    class Meta:
        """Bind the type to Post and configure filtering and depth/cost limits.

        The "status" TextChoices field becomes a GraphQL enum automatically.
        "max_depth" rejects any query nesting more than N levels below a
        PostType field and combines with MAX_QUERY_DEPTH (most-restrictive
        wins); "complexity" is the cost weight for CostLimitValidationRule
        (default is 1). Both are enforced by the validation rules wired in
        GraphQLView.
        """

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
        # max_depth: reject any query that nests *more than N levels below* a
        # PostType field; this combines with MAX_QUERY_DEPTH (most-restrictive wins).
        # complexity: cost weight for CostLimitValidationRule (default is 1).
        max_depth = 4
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
    def search(
        cls, queryset: QuerySet, info: GraphQLResolveInfo, value: str
    ) -> QuerySet:
        """Filter posts whose title OR body contains the search term.

        This is the "@filter_field" showcase: a custom GraphQL filter argument
        that is not a plain model-field lookup. The decorator supplies the
        classmethod semantics, so the method is written with a leading "cls" but
        must not be stacked with "@classmethod".

        Args:
            queryset: The base queryset to narrow, already scoped by
                "get_queryset".
            info: The GraphQL resolve info for the current request.
            value: The search term supplied under the "search" filter argument.

        Returns:
            queryset: The queryset filtered to posts whose title or body
                contains "value".
        """
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
    def get_queryset(cls, queryset: QuerySet, info: GraphQLResolveInfo) -> QuerySet:
        """Scope every top-level Post query by the requester's auth state.

        This hook runs on all four top-level field types (single, list,
        paginated, list-object) before the query optimizer, so anonymous
        callers see only published posts while authenticated callers see all.

        Args:
            queryset: The base Post queryset to scope.
            info: The GraphQL resolve info carrying the request context.

        Returns:
            queryset: The full queryset for authenticated users, or only
                published posts for anonymous ones.
        """
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
    """List type for posts, returning the results/totalCount wrapper.

    Uses limit/offset pagination and is also reused as the child type of the
    nested "posts" list on AuthorType.
    """

    class Meta:
        """Bind the list type to Post with limit/offset pagination.

        The ordering allowlist rejects relation-spanning and non-existent terms
        to prevent column-oracle attacks. For example, requesting
        "results(ordering: 'author__user__password')" raises a GraphQLError for
        relation-spanning ordering, and "results(ordering: 'nonexistent')"
        raises a GraphQLError for an invalid ordering field.
        """

        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")


# AuthorType is declared AFTER PostListType because it references it directly as
# the type of its explicit nested `posts` field (DjangoNestedListObjectField).
class AuthorType(DjangoObjectType):
    """GraphQL type for an author, showcasing query optimization.

    Declared AFTER PostListType because it references it directly as the type
    of its explicit nested "posts" field (DjangoNestedListObjectField).
    Exposes a selection-driven "postCount" annotation and an "optimize_posts"
    per-field hook.
    """

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
        """Bind the type to the Author model, its projection and its filters.

        "exclude_fields" projects "Author.bio" away, and the library treats that
        as a SECURITY boundary rather than an output shape: the column is
        unreadable, unorderable and unfilterable through this type. See
        "tests/test_projection_boundary.py", which pins all three axes, and the
        README section "The projection boundary" for the queries to paste into
        GraphiQL.

        Filtering allows an exact id lookup and a substring "name" lookup.
        Adding "bio" here would raise "ImproperlyConfigured" while the schema
        builds — a "filter_fields" entry naming a projected-away column is a
        contradiction between two "Meta" options, so it is refused rather than
        dropped in silence.
        """

        model = Author
        exclude_fields = ("bio",)
        filter_fields = {"id": ("exact",), "name": ("icontains",)}

    @staticmethod
    def optimize_posts(
        queryset: QuerySet, info: GraphQLResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Per-field optimize hook for the "posts" nested list.

        Composes on top of the optimizer-built child queryset for the "posts"
        prefetch, and is called ONCE per query (not once per author). The name is
        "optimize_" plus the snake_case GraphQL field name, declared on the
        PARENT type (AuthorType). It MUST return a queryset; a non-queryset
        return logs a WARNING and is ignored.

        Here the hook forces a stable secondary ordering on every author's posts,
        a composition that layers cleanly on top of whatever ".only()" narrowing
        and window slicing the optimizer already built.

        Why not "select_related('category')" here? It is the textbook hook
        example, and it works fine when the client also selects "category
        { name }". But the optimizer applies its ".only()" column narrowing to
        this child queryset AFTER the hook runs. When "category" is NOT in the
        selection, "category_id" is deferred, and "select_related('category')"
        on a deferred relation raises a Django "FieldError". The hook cannot see
        that future ".only()" plan, so a bare "select_related" would make "posts
        { results { title } }" (no category) blow up. We use an ordering
        composition instead so EVERY query stays runnable; the README spells out
        the "select_related" variant and its rule.

        Args:
            queryset: The optimizer-built child queryset for the "posts"
                prefetch.
            info: The GraphQL resolve info for the current request.
            **kwargs: Optimizer extras; carries "filter_value" (the field's
                filter input or None) and "is_window" (True only on the DB-side
                windowed path).

        Returns:
            queryset: The child queryset with a stable secondary ordering
                applied.
        """
        return queryset.order_by("-id", "title")


class AuthorListType(DjangoListObjectType):
    """List type for authors, returning the results/totalCount wrapper.

    Demonstrates page-number pagination, distinct from the limit/offset and
    cursor styles used by the other list types.
    """

    class Meta:
        """Bind the list type to Author with page-number pagination.

        The page size is fixed at ten authors per page.
        """

        model = Author
        pagination = PageGraphqlPagination(page_size=10)


class CommentListType(DjangoListObjectType):
    """List type for comments, returning the results/totalCount wrapper.

    Demonstrates cursor pagination, which exposes a non-opaque pageInfo.
    """

    class Meta:
        """Bind the list type to Comment with cursor pagination.

        Cursor pagination exposes a non-opaque pageInfo.
        """

        model = Comment
        pagination = CursorGraphqlPagination(ordering="-created")


# --------------------------------------------------------------------------- #
# Typed GenericForeignKey union (v1.2.0+).                                     #
#                                                                              #
# Declaration order is LOAD-BEARING: members -> union -> owner LAST.           #
#   1. AccountType / InvoiceType  — the two DjangoObjectType members.          #
#   2. AttachmentTargetUnion      — a DjangoUnionType over those members.      #
#   3. AttachmentType             — the owner; its Meta.unions maps the         #
#      `target` GFK to the union. If the owner were declared before the union   #
#      the converter would WARN and fall back to the flat GenericForeignKeyType. #
#                                                                              #
# Members are explicit (Meta.types); resolve_type is provided by           #
# DjangoUnionType (it maps a resolved Account/Invoice row to its registered     #
# type via the registry). Clients select per-member fields with inline         #
# fragments: `target { ... on AccountType { balance } ... on InvoiceType { … }}`.#
# --------------------------------------------------------------------------- #
class AccountType(DjangoObjectType):
    """GraphQL type for an account.

    One of the two members of the typed attachment-target union.
    """

    class Meta:
        """Bind the type to the Account model.

        No filter fields are declared; this type is used only as a union member.
        """

        model = Account


class InvoiceType(DjangoObjectType):
    """GraphQL type for an invoice.

    One of the two members of the typed attachment-target union.
    """

    class Meta:
        """Bind the type to the Invoice model.

        No filter fields are declared; this type is used only as a union member.
        """

        model = Invoice


class AttachmentTargetUnion(DjangoUnionType):
    """Typed union over the two possible attachment targets.

    "resolve_type" is provided by DjangoUnionType, which maps a resolved
    Account or Invoice row to its registered type via the registry. Clients
    select per-member fields with inline fragments.
    """

    class Meta:
        """List the explicit union member types.

        Members are given explicitly so the converter can register each one.
        """

        types = (AccountType, InvoiceType)


class AttachmentType(DjangoObjectType):
    """GraphQL type for an attachment whose "target" is a typed GFK union.

    The owner is declared LAST in the union block: if it were declared before
    the union, the converter would warn and fall back to the flat
    GenericForeignKeyType.
    """

    class Meta:
        """Bind the type to Attachment and map "target" to the typed union.

        On Django 5.0+ with OPTIMIZE_ONLY_FIELDS the optimizer routes "target"
        through a GenericPrefetch with one ".only()"-narrowed queryset per
        content type (Account fetches "balance", Invoice fetches "amount"),
        batched across all attachments, with no N+1.

        "content_type" and "object_id" are excluded on purpose. They are the
        two raw columns the GenericForeignKey is built from, and "target"
        already exposes what they point at, typed. Leaving "content_type" in
        would also make the compiler log a warning on every management command:
        its target model "ContentType" has no registered DjangoObjectType, so
        the relation is dropped from the type anyway. Excluding it keeps the
        output identical and the log quiet. The columns stay on the model, so
        the GenericPrefetch above is unaffected.
        """

        model = Attachment
        unions = {"target": AttachmentTargetUnion}
        exclude_fields = ("content_type", "object_id")


class AttachmentListType(DjangoListObjectType):
    """List type for attachments, returning the results/totalCount wrapper.

    Each attachment's "target" resolves to a member of the typed GFK union.
    """

    class Meta:
        """Bind the list type to Attachment with limit/offset pagination.

        The default page limit is ten attachments.
        """

        model = Attachment
        pagination = LimitOffsetGraphqlPagination(default_limit=10)


# --------------------------------------------------------------------------- #
# Custom permission — demonstrates BasePermission subclassing. Assigned on    #
# "CommentModelType" below, which is what gates the nested write.             #
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

    def has_create_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs: Any
    ) -> bool:
        """Gate the "create" action on the requester being authenticated.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras (unused by this stand-in check).

        Returns:
            allowed: True when the request comes from an authenticated user.
        """
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)

    def has_update_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs: Any
    ) -> bool:
        """Gate the "update" action on the requester being authenticated.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras (unused by this stand-in check).

        Returns:
            allowed: True when the request comes from an authenticated user.
        """
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)

    def has_delete_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs: Any
    ) -> bool:
        """Gate the "delete" action on the requester being authenticated.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras (unused by this stand-in check).

        Returns:
            allowed: True when the request comes from an authenticated user.
        """
        user = getattr(getattr(info, "context", None), "user", None)
        return bool(user and user.is_authenticated)


# --------------------------------------------------------------------------- #
# Serializer type: Note CRUD + permissions + per-request scoping             #
# --------------------------------------------------------------------------- #
class NoteModelType(DjangoModelType):
    """Serializer-backed Note type: CRUD, permissions and per-request scoping.

    A single declaration drives the queries, mutations and the subscription for
    notes. It is read-open but write-restricted to authenticated users, and it
    scopes every list and notification to the current user.
    """

    # Anyone may read; only authenticated users may create/update/delete.
    # Swap to AllowAny, IsAuthenticated, IsAdmin, IsAdminOrReadOnly, or a
    # custom BasePermission subclass like IsOwnerOrReadOnly (all imported at
    # the top of this file) to experiment with different permission gates.
    permission_classes = [IsAuthenticatedOrReadOnly]

    class Meta:
        """Configure Note CRUD, pagination, filtering and the notes stream.

        Declaring "stream" once means queries, mutations AND the subscription
        all come from here. "subscription_index_fields" is an optional top-tier
        optimization: it routes note notifications to a per-owner group so a
        save only wakes that owner's subscribers instead of everyone on the
        stream, mirroring the "owner" key of "subscription_scope".
        """

        model = Note
        pagination = LimitOffsetGraphqlPagination(default_limit=10)
        filter_fields = {"id": ("exact",), "title": ("icontains",)}
        stream = "notes"
        payload_mode = "full"
        subscription_index_fields = ("owner",)

    @classmethod
    def filter_queryset(
        cls, qs: QuerySet, info: GraphQLResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Scope notes to the current user (used by the private "myNotes").

        Args:
            qs: The base Note queryset to scope.
            info: The GraphQL resolve info carrying the request context.
            **kwargs: Extra arguments available for scoping (unused here).

        Returns:
            qs: Only the current user's notes when authenticated, otherwise an
                empty queryset.
        """
        user = getattr(info.context, "user", None)
        if user is not None and user.is_authenticated:
            return qs.filter(owner=user)
        return qs.none()

    @classmethod
    def _subscriber(cls, info: GraphQLResolveInfo) -> Any:
        """Return the subscribing user, denying the subscribe when anonymous.

        The auth gate for "noteSubscription". Both subscribe hooks route
        through here so the gate cannot be half-applied: a scope with no user
        to scope by would otherwise mean NO scope at all, i.e. every user's
        notes.

        Args:
            info: The GraphQL resolve info for the subscribe request.

        Returns:
            user: The authenticated subscriber.

        Raises:
            GraphQLError: If the request carries no authenticated user.
        """
        user = getattr(info.context, "user", None)
        if user is None or not user.is_authenticated:
            raise GraphQLError(
                "Authentication required.",
                extensions={"code": "UNAUTHENTICATED", "status_code": 401},
            )
        return user

    @classmethod
    def authorize(cls, info: GraphQLResolveInfo, action: str, **kwargs: Any) -> None:
        """Authorize a CRUD action, requiring auth for "subscribe".

        "permission_classes" alone is not enough here: "subscribe" is a READ
        action, so "IsAuthenticatedOrReadOnly" lets anonymous callers through.
        The generated subscription's "authorize_subscription" hook calls this
        method, and it runs BEFORE any Channels group is joined.

        Args:
            info: The GraphQL resolve info for the current request.
            action: The action being authorized (e.g. "create", "subscribe").
            **kwargs: Extra arguments passed to the permission checks.

        Raises:
            GraphQLError: If the action is not allowed.
        """
        if action == "subscribe":
            cls._subscriber(info)
        super().authorize(info, action, **kwargs)

    @classmethod
    def subscription_scope(cls, info: GraphQLResolveInfo, **kwargs: Any) -> dict | None:
        """Server-forced scope: only this user's note notifications.

        Evaluated at subscribe time; enforced per event at delivery (in memory,
        since "owner" is in the serialized payload). The client cannot widen or
        drop it. Fails closed like the sibling "filter_queryset": with no
        authenticated user there is no scope to force, so the subscribe is
        denied rather than served unscoped.

        Args:
            info: The GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments (unused here).

        Returns:
            scope: A filter mapping restricting notifications to this user's
                notes.

        Raises:
            GraphQLError: If the request carries no authenticated user.
        """
        return {"owner": cls._subscriber(info).pk}

    @classmethod
    def create(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelType:
        """Set the current user as the note owner, then create normally.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info carrying the request context.
            **kwargs: Resolver arguments including the input data.

        Returns:
            response: A success response carrying the created note, or an error
                response.
        """
        user = getattr(info.context, "user", None)
        data = kwargs.get(cls._meta.input_field_name)
        if user is not None and user.is_authenticated and isinstance(data, dict):
            data["owner"] = user.pk
        return super().create(root, info, **kwargs)


# --------------------------------------------------------------------------- #
# Subscriptions                                                               #
# --------------------------------------------------------------------------- #
class PostSubscription(Subscription):
    """Public subscription broadcasting post changes on the "posts" stream.

    Any client may subscribe; each notification carries the full post payload.
    """

    class Meta:
        """Bind the subscription to Post with a full-payload notification.

        "payload_mode" of "full" embeds the whole post in each notification.
        """

        model = Post
        stream = "posts"
        payload_mode = "full"


class CommentSubscription(Subscription):
    """Public subscription over comments, demonstrating per-subscriber filters.

    On a post-detail page, subscribe with the generated input object argument
    "filter: { post: { exact: <id> } }" to receive only that post's comments.
    """

    class Meta:
        """Bind the subscription to Comment with a full-payload notification.

        Notifications flow on the "comments" stream.
        """

        model = Comment
        stream = "comments"
        payload_mode = "full"


# --------------------------------------------------------------------------- #
# Queries                                                                     #
# --------------------------------------------------------------------------- #
class PublicQuery(ObjectType):
    """Root query fields anyone can run.

    Bundles a scalar field, single-object lookup, the three paginated list
    styles, a typed GFK union list, a plain filtered list and a flat filtered +
    paginated list, so each top-level query pattern is demonstrated once.
    """

    # Low-level substrate: ``field()`` is the graphql-core-typed primitive the
    # capitalized descriptors (``Field`` / ``CharField`` / ...) are built on. It
    # stays public and is the escape hatch for any graphql-core type that has no
    # named shortcut. Prefer ``CharField(description=...)`` in new code; ``field()``
    # is shown here on purpose to document the substrate.
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

    def resolve_server_time(self, info: GraphQLResolveInfo) -> str:
        """Resolve the "serverTime" field to the current time.

        Args:
            info: The GraphQL resolve info for the current request.

        Returns:
            timestamp: The current server time as an ISO 8601 string.
        """
        return timezone.now().isoformat()


class PrivateQuery(ObjectType):
    """Root query fields that require an authenticated user.

    Enforced by AuthenticatedFieldsMiddleware. Exposes the current user and
    the user's own notes.
    """

    me = field(UserType, description="The current user.")
    # NoteModelType.filter_queryset scopes this list to the current user; the
    # field's own resolver (cls.list) runs, so no resolve_* method is needed.
    my_notes = NoteModelType.ListField(description="Notes owned by the current user.")

    def resolve_me(self, info: GraphQLResolveInfo) -> User | None:
        """Resolve the "me" field to the authenticated user, if any.

        Args:
            info: The GraphQL resolve info carrying the request context.

        Returns:
            user: The current user when authenticated, otherwise None.
        """
        user = getattr(info.context, "user", None)
        return user if (user and user.is_authenticated) else None


# --------------------------------------------------------------------------- #
# Mutations                                                                   #
# --------------------------------------------------------------------------- #
class PostMutation(DjangoModelMutation):
    """Public Post CRUD.

    Lets you trigger the public "postSubscription" from "/graphql": a
    "postCreate" runs in the ASGI process, fires Django's "post_save" signal and
    the subscription engine broadcasts the notification to subscribers.
    """

    class Meta:
        """Bind the mutation to the Post model.

        All CRUD operations (create, update, delete) are generated.
        """

        model = Post


class CommentModelType(DjangoModelType):
    """Comment CRUD behind a permission — the child host of the nested write.

    A "DjangoModelType" rather than a "DjangoModelMutation" because
    "permission_classes" lives on the type: this class is what makes the
    comment gate exist at all. It drives "commentSubscription" from "/graphql"
    the same way PostMutation drives "postSubscription", and reads keep coming
    from "CommentType" / "CommentListType".

    Since 2.2.0 this gate is also the nested one. "PostWithCommentsMutation"
    carries no permission of its own, yet a caller denied "commentCreate" here
    is denied the identical write through "postWithCommentsCreate" too — the
    nested writer runs the child's own hosts, and the denial rolls the parent
    Post back with it. Before 2.2.0 the parent was a door into a child the
    caller could not write directly.
    """

    permission_classes = [IsOwnerOrReadOnly]

    class Meta:
        """Bind the type to Comment and serve the write operations only.

        "model_operations" leaves out "list" / "retrieve" because the reads are
        already served by "CommentType" / "CommentListType"; what is declared
        here is a pure write host.
        """

        model = Comment
        model_operations = ("create", "update", "delete")


class PostWithCommentsMutation(DjangoModelMutation):
    """Nested-write demo: create a Post together with one or more Comments.

    "Meta.nested_fields" tells django-graphex that the "comments" accessor
    (a reverse FK from Comment.post) should be handled as nested input. The
    "NestedFieldsMixin" detects the relation direction automatically:

    - It classifies "comments" as "reverse_many" (one-to-many).
    - After saving the parent Post it calls "_attach_children", which iterates
      the list, injects "post=<saved_post>" into each child payload, and saves
      each Comment via the native backend, all inside one "transaction.atomic()"
      block.

    The auto-generated input type for the "create" operation therefore exposes
    "comments" as a list-of-object argument. No hand-written resolver or
    serializer is needed.

    Authorization (2.2.0): this mutation declares no permission of its own, and
    it does not need one for the children. Each inline comment is authorized by
    the child's own host — "CommentModelType" and its "IsOwnerOrReadOnly" — so
    the caller denied "commentCreate" is denied it here too, and the parent Post
    rolls back with the denial. The nested "comments" input is stamped with the
    child's permission as well, which is what "PERMISSION_SCOPED_SCHEMA" prunes
    it by on "/graphql/secure/".
    """

    class Meta:
        """Bind to Post, expose only "create", and declare the nested field.

        Only the create operation is exposed; plain postCreate / postUpdate /
        postDelete remain available from PostMutation above.
        """

        model = Post
        model_operations = ("create",)
        nested_fields = {"comments": Comment}


# A model-derived input type. DjangoModelMutation builds these for you, but you
# can also declare one explicitly and use it as an argument on a hand-written
# native ``Mutation`` when you need full control over the resolver.
class CategoryInput(DjangoInputObjectType):
    """Model-derived input type exposing only the category "name" field.

    Declared explicitly so it can be used as an argument on the hand-written
    "CreateCategory" mutation.
    """

    class Meta:
        """Bind the input type to Category, exposing only "name".

        Restricting "only_fields" keeps the generated input surface minimal.
        """

        model = Category
        only_fields = ("name",)


class CreateCategory(Mutation):
    """A hand-written mutation taking an explicit DjangoInputObjectType.

    Teaching note on unique-constraint violations: "Category.name" has a unique
    constraint. Without the try/except in "mutate", a duplicate name raises an
    "IntegrityError" that Django bubbles up as HTTP 500, a hard crash with no
    useful message for the client. The idiomatic pattern for hand-written
    mutations is to catch the database error and return "ok=False" with a
    human-readable "error" string. This keeps the GraphQL response status 200
    and hands the client structured error information. ("DjangoModelMutation"
    and "DjangoModelType" handle this automatically through their serializer
    layer; hand-written mutations must do it explicitly.)

    Descriptor API form (django_graphex.core):

    - Arguments live on "class Arguments". The "data" argument is declared with
      "Field(CategoryInput, required=True)", the unified Django-style descriptor
      used in an argument position. It takes the "DjangoInputObjectType" CLASS
      directly and resolves its compiled "GraphQLInputObjectType" LAZILY at
      "Field()" build time (after "compile_all_inputs" runs). This replaces the
      older "lambda: GraphQLArgument(...)" thunk with one readable line; the
      thunk still works (see the low-level substrate note in the docs) but the
      unified "Field" is the primary idiom.
    - The output payload fields use the same capitalized descriptors:
      "BooleanField" / "CharField" scalar shortcuts, and "Field(CategoryType)"
      for the object ref.
    - "mutate" is a classmethod returning "cls(...)".
    - Input-object arguments arrive as a plain "dict" (snake-case keys, the
      "out_name" contract), so read "data['name']", not attribute access.
    """

    class Arguments:
        """GraphQL arguments for the mutation: the category input payload.

        "data" is the required CategoryInput carrying the new category "name".
        """

        data = Field(CategoryInput, required=True)

    ok = BooleanField()
    category = Field(CategoryType)
    error = CharField()

    @classmethod
    def mutate(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> "CreateCategory":
        """Create a category, returning a structured error on duplicate names.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current request.
            **kwargs: Resolver arguments; "data" carries the category input
                dict.

        Returns:
            payload: A payload with "ok=True" and the created category, or
                "ok=False" and a human-readable "error" when the name already
                exists.
        """
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
#       ) { ok name document { id name created } }                            #
#   }                                                                          #
# --------------------------------------------------------------------------- #
class DocumentType(DjangoObjectType):
    """GraphQL type for an uploaded document.

    Read back through the "document" field of the "uploadDocument" payload,
    which is what mounts this type on the schema. A "DjangoObjectType" that no
    field ever returns is registered but never reaches the schema type map, so
    it cannot be queried or introspected.
    """

    class Meta:
        """Bind the type to Document, exposing only id, name and created.

        The stored file field itself is intentionally not exposed.
        """

        model = Document
        only_fields = ("id", "name", "created")


class UploadDocument(Mutation):
    """Demo: upload a base64-encoded file and attach it to a Document record.

    Note: "MAX_UPLOAD_SIZE" must be set in "DJANGO_GRAPHEX" before using
    "Base64FileInput". See "config/settings.py".

    Descriptor API form (django_graphex.core):

    - Arguments are declared with the unified Django-style descriptors: "name"
      is a bare scalar argument via the "CharField(required=True)" shortcut;
      "file" takes the "Base64FileInput" CLASS via "Field(Base64FileInput,
      required=True)", whose compiled "GraphQLInputObjectType" resolves LAZILY
      at "Field()" build time (after "compile_all_inputs" runs), replacing the
      older "lambda: GraphQLArgument(...)" thunk.
    - Input-object arguments arrive as a plain "dict" (snake-case keys, the
      "out_name" contract), so the "file" payload is rehydrated into a
      "Base64FileInput" instance ("Base64FileInput(**file)") before calling
      ".to_uploaded_file()".
    - Output payload fields use the same "BooleanField" / "CharField" scalar
      shortcuts, plus "Field(DocumentType)" for the stored record — the same
      object-ref idiom "CreateCategory" uses, and what puts "DocumentType" on
      the schema.
    """

    class Arguments:
        """GraphQL arguments: the document name and the base64 file payload.

        "name" is a required scalar; "file" is the required Base64FileInput.
        """

        name = CharField(required=True)
        file = Field(Base64FileInput, required=True)

    ok = BooleanField()
    name = CharField()
    document = Field(DocumentType)
    error = CharField()

    @classmethod
    def mutate(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> "UploadDocument":
        """Decode the uploaded file and save it to a new Document record.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current request.
            **kwargs: Resolver arguments; "name" is the document name and
                "file" is the base64 file input dict.

        Returns:
            payload: A payload with "ok=True", the saved document name and the
                stored record, or "ok=False" and the error message when
                decoding or saving fails.
        """
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
            return cls(ok=True, name=doc.name, document=doc, error=None)
        except Exception as exc:  # noqa: BLE001
            return cls(ok=False, name=name, document=None, error=str(exc))


# --------------------------------------------------------------------------- #
# Native compile trigger (native backend only).                                 #
#                                                                              #
# Hand-written "Mutation" arguments below reference a COMPILED                 #
# "GraphQLInputObjectType" ("CategoryInput" / "Base64FileInput"). Those input  #
# types — and every "DjangoObjectType" output type — are compiled by           #
# "compile_all_inputs" / "compile_all_outputs".                                #
#                                                                              #
# These two calls are MANDATORY, not a convenience. "django_graphex" IS in     #
# this project's INSTALLED_APPS (see "config/settings.py"), and its            #
# "AppConfig.ready()" does call both — but "ready()" runs BEFORE this module   #
# is imported, so it can only compile what was already imported by then.       #
# Every type declared in this file, plus "Base64FileInput" (the package never  #
# imports "django_graphex.uploads" itself), is compiled only here. Delete      #
# these calls and "RootMutation" raises at import time:                        #
#                                                                              #
#   TypeError: Can only create a wrapper for a GraphQLType, but got:           #
#   <class 'django_graphex.uploads.Base64FileInput'>                           #
#                                                                              #
# Placement is load-bearing too: AFTER all type declarations and BEFORE        #
# "RootMutation" calls ".Field()", so the argument-position "Field"            #
# descriptors resolve to real compiled input types, not "None". See            #
# "docs/usage/mutations.md" for the full rule.                                 #
# --------------------------------------------------------------------------- #
from django_graphex.core.base import compile_all_inputs  # noqa: E402
from django_graphex.core.registry_compiler import (  # noqa: E402
    compile_all_outputs,
)

compile_all_inputs()
compile_all_outputs()


class RootMutation(ObjectType):
    """Root mutation aggregating every mutation field in this schema.

    Combines the auto-generated Note and Post/Comment CRUD fields with the two
    hand-written mutations (category create and document upload) and the
    nested-write demo.
    """

    note_create, note_delete, note_update = NoteModelType.MutationFields()
    post_create = PostMutation.CreateField()
    post_update = PostMutation.UpdateField()
    post_delete = PostMutation.DeleteField()
    # Gated by CommentModelType.permission_classes — the same gate the nested
    # postWithCommentsCreate below now runs for each inline comment.
    comment_create, comment_delete, comment_update = CommentModelType.MutationFields()
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
    """Root subscription fields anyone may subscribe to.

    Groups the public post and comment subscriptions.
    """

    post_subscription = PostSubscription.Field()
    comment_subscription = CommentSubscription.Field()


class PrivateSubscriptions(ObjectType):
    """Root subscription fields that require an authenticated user.

    Enforced by AuthenticatedFieldsMiddleware. Exposes the per-user note
    subscription.
    """

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
