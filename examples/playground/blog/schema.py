"""GraphQL schema wiring every django-graphex feature.

- Public queries: single object, lists with the 3 paginations, filtering,
  nested lists (results/totalCount, N+1-safe), directives.
- Private queries (require auth): "me" and "myNotes" (scoped to the user).
- Mutations: Note create/update/delete via DjangoModelType + permissions.
- Subscriptions: public "postSubscription" and private "noteSubscription".
"""

import graphene
from django.contrib.auth import get_user_model
from django.utils import timezone

from django_graphex import (
    BasePermission,
    CursorGraphqlPagination,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoInputObjectType,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoModelMutation,
    DjangoModelType,
    DjangoObjectField,
    DjangoObjectType,
    ExtraGraphQLSchema,
    IsAuthenticatedOrReadOnly,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
    all_directives,
)
from django_graphex.subscriptions import Subscription

from .models import Author, Category, Comment, Note, Post, Tag

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


class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        filter_fields = {"id": ("exact",), "name": ("icontains",)}


# --------------------------------------------------------------------------- #
# List types (results + totalCount). Also used for nested lists.              #
# Each uses a different paginator so you can try all three.                   #
# --------------------------------------------------------------------------- #
class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")


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
# Custom permission — demonstrates BasePermission subclassing.               #
# AllowAny, IsAuthenticated, IsAdmin, IsAdminOrReadOnly are all imported      #
# above and are available to use on any DjangoModelType.                      #
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
    # Other built-in options: AllowAny, IsAuthenticated, IsAdmin,
    # IsAdminOrReadOnly, or a custom BasePermission subclass like IsOwnerOrReadOnly.
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
class PublicQuery(graphene.ObjectType):
    """Anyone can run these."""

    server_time = graphene.String(description="A public scalar field.")

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


class PrivateQuery(graphene.ObjectType):
    """Require an authenticated user (enforced by AuthenticatedFieldsMiddleware)."""

    me = graphene.Field(UserType, description="The current user.")
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


# A model-derived input type. DjangoModelMutation builds these for you, but you
# can also declare one explicitly and use it as an argument on a hand-written
# graphene mutation when you need full control over the resolver.
class CategoryInput(DjangoInputObjectType):
    class Meta:
        model = Category
        only_fields = ("name",)


class CreateCategory(graphene.Mutation):
    """A hand-written mutation taking an explicit DjangoInputObjectType."""

    class Arguments:
        data = CategoryInput(required=True)

    ok = graphene.Boolean()
    category = graphene.Field(CategoryType)

    def mutate(self, info, data):
        category = Category.objects.create(name=data.name)
        return CreateCategory(ok=True, category=category)


class RootMutation(graphene.ObjectType):
    note_create, note_delete, note_update = NoteModelType.MutationFields()
    post_create = PostMutation.CreateField()
    post_update = PostMutation.UpdateField()
    post_delete = PostMutation.DeleteField()
    comment_create = CommentMutation.CreateField()
    comment_update = CommentMutation.UpdateField()
    comment_delete = CommentMutation.DeleteField()
    # Hand-written mutation using an explicit DjangoInputObjectType argument.
    create_category = CreateCategory.Field()


# --------------------------------------------------------------------------- #
# Subscriptions: a public subset and a (disjoint) private subset.             #
# --------------------------------------------------------------------------- #
class PublicSubscriptions(graphene.ObjectType):
    """Anyone may subscribe to these."""

    post_subscription = PostSubscription.Field()
    comment_subscription = CommentSubscription.Field()


class PrivateSubscriptions(graphene.ObjectType):
    """Require an authenticated user (enforced by AuthenticatedFieldsMiddleware)."""

    note_subscription = NoteModelType.SubscriptionField()


# --------------------------------------------------------------------------- #
# Schema. Each root is split into a public subset and a (disjoint) private     #
# subset; ExtraGraphQLSchema unions them and protects the private fields. In a #
# multi-app project you would aggregate per-app subsets, e.g.                   #
#   class RootSubscription(blog.PublicSubscriptions, shop.PublicSubscriptions,  #
#                          graphene.ObjectType): pass                           #
# and pass those aggregates here instead.                                       #
# --------------------------------------------------------------------------- #
schema = ExtraGraphQLSchema(
    query=PublicQuery,
    private_query=PrivateQuery,
    mutation=RootMutation,
    subscription=PublicSubscriptions,
    private_subscription=PrivateSubscriptions,
    directives=all_directives,
)
