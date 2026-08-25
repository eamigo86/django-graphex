# Sample Application Setup

!!! note "Illustrative tutorial"
    This is a **standalone tutorial** that uses its own hypothetical blog models
    (`UserProfile`, `excerpt`, `slug`, `view_count`, `QueryFields`, `UserMutation`, …).
    The models exist only to show framework concepts — they are **not** derived from
    any real project file in this repository.

    For a complete, runnable project you can clone and run immediately, see
    [`examples/playground/`](https://github.com/eamigo86/django-graphex/tree/main/examples/playground)
    in the repo.  The playground uses different (simpler) models but exercises the
    same features shown here, so it is a good companion reference when the
    tutorial examples need context.

Let's start with a blog application to demonstrate the features:

=== "models.py"

    ```python
    from django.db import models
    from django.contrib.auth.models import User

    class Category(models.Model):
        name = models.CharField(max_length=100)
        slug = models.SlugField(unique=True)
        description = models.TextField(blank=True)
        created_at = models.DateTimeField(auto_now_add=True)

        def __str__(self):
            return self.name

    class Tag(models.Model):
        name = models.CharField(max_length=50)
        color = models.CharField(max_length=7, default="#000000")  # Hex color

        def __str__(self):
            return self.name

    class Post(models.Model):
        STATUS_CHOICES = [
            ('draft', 'Draft'),
            ('published', 'Published'),
            ('archived', 'Archived'),
        ]

        title = models.CharField(max_length=200)
        slug = models.SlugField(unique=True)
        content = models.TextField()
        excerpt = models.TextField(blank=True)
        status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
        author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
        category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='posts')
        tags = models.ManyToManyField(Tag, blank=True, related_name='posts')
        featured_image = models.ImageField(upload_to='posts/', blank=True)
        view_count = models.PositiveIntegerField(default=0)
        created_at = models.DateTimeField(auto_now_add=True)
        updated_at = models.DateTimeField(auto_now=True)
        published_at = models.DateTimeField(null=True, blank=True)

        class Meta:
            ordering = ['-created_at']

        def __str__(self):
            return self.title

    class Comment(models.Model):
        post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
        author = models.ForeignKey(User, on_delete=models.CASCADE)
        content = models.TextField()
        parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
        is_approved = models.BooleanField(default=False)
        created_at = models.DateTimeField(auto_now_add=True)

        class Meta:
            ordering = ['created_at']

        def __str__(self):
            return f"Comment by {self.author.username} on {self.post.title}"

    class UserProfile(models.Model):
        # related_name="profile" is what exposes `UserType.profile` and what
        # makes UserMutation's nested_fields={'profile': UserProfile} match.
        # Without it the accessor is `userprofile` and both silently change shape.
        user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
        bio = models.TextField(blank=True)
        avatar = models.ImageField(upload_to='avatars/', blank=True)
        website = models.URLField(blank=True)
        location = models.CharField(max_length=100, blank=True)
        birth_date = models.DateField(null=True, blank=True)
        social_links = models.JSONField(default=dict, blank=True)

        def __str__(self):
            return f"{self.user.username}'s Profile"
    ```

=== "types.py"

    ```python
    from django_graphex.types import DjangoObjectType, DjangoListObjectType
    from django_graphex.paginations import (
        LimitOffsetGraphqlPagination, PageGraphqlPagination
    )
    from django.contrib.auth.models import User
    from .models import Category, Tag, Post, Comment, UserProfile

    # Basic Object Types
    class UserType(DjangoObjectType):
        class Meta:
            model = User
            description = "User type with basic information"
            filter_fields = {
                'username': ('exact', 'icontains'),
                'email': ('exact', 'icontains'),
                'first_name': ('icontains',),
                'last_name': ('icontains',),
                'is_active': ('exact',),
                'date_joined': ('exact', 'gte', 'lte'),
            }

    class CategoryType(DjangoObjectType):
        class Meta:
            model = Category
            description = "Blog category"
            filter_fields = {
                'id': ('exact', 'in'),
                'name': ('exact', 'icontains'),
                'slug': ('exact',),
            }

    class TagType(DjangoObjectType):
        class Meta:
            model = Tag
            description = "Post tag"
            filter_fields = {
                'id': ('exact', 'in'),
                'name': ('exact', 'icontains'),
                'color': ('exact',),
            }

    class UserProfileType(DjangoObjectType):
        class Meta:
            model = UserProfile
            description = "Extended user profile information"

    class CommentType(DjangoObjectType):
        class Meta:
            model = Comment
            description = "Post comment"
            filter_fields = {
                'author__username': ('exact', 'icontains'),
                'is_approved': ('exact',),
                'created_at': ('exact', 'gte', 'lte'),
            }

    # Every type registered for a model contributes to that model's single
    # `<Model>FilterInput`, so keep the filter_fields of PostType and
    # PostListType identical — otherwise the compiled input silently offers
    # the union of both and the two lists filter differently than they read.
    POST_FILTER_FIELDS = {
        'title': ('exact', 'icontains'),
        'status': ('exact',),
        'author__username': ('exact', 'icontains'),
        'category__name': ('exact', 'icontains'),
        'tags__name': ('exact', 'icontains'),
        'created_at': ('exact', 'gte', 'lte'),
        'published_at': ('exact', 'gte', 'lte', 'range'),
        'view_count': ('exact', 'gte', 'lte'),
    }

    class PostType(DjangoObjectType):
        class Meta:
            model = Post
            description = "Blog post with full content and metadata"
            filter_fields = POST_FILTER_FIELDS

    # List Object Types with Pagination
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            description = "Paginated list of blog posts"
            pagination = LimitOffsetGraphqlPagination(
                default_limit=10,
                max_limit=50,
                ordering="-published_at"
            )
            filter_fields = POST_FILTER_FIELDS

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            description = "Paginated list of users"
            pagination = PageGraphqlPagination(
                page_size=20,
                page_size_query_param="pageSize"
            )
            filter_fields = {
                'username': ('exact', 'icontains'),
                'email': ('exact', 'icontains'),
                'is_active': ('exact',),
                'date_joined': ('exact', 'gte', 'lte'),
            }

    class CommentListType(DjangoListObjectType):
        class Meta:
            model = Comment
            description = "Paginated list of comments"
            pagination = LimitOffsetGraphqlPagination(default_limit=25)
    ```

=== "types_modeltype.py"

    !!! info "This module and `types.py` can live side by side"
        A `DjangoModelType` generates its own list container, and since **2.2.0**
        that container is named `<Model>ListGenericType` — `PostListGenericType`,
        `UserListGenericType`. The hand-declared containers in `types.py` keep the
        `<Model>ListType` name, so the two never collide and both modules can be
        imported, and mounted, in the same schema.

        If you remember the old rule ("never declare both"), it applied to 2.1.x
        and earlier, where the generated container was also called
        `<Model>ListType` and the schema build failed with *"Schema must contain
        uniquely named types"*. See the
        [type-name reference](../types.md#auto-generated-query-fields).

    ```python
    from django_graphex.types import DjangoModelType
    from django_graphex.paginations import LimitOffsetGraphqlPagination
    from django.contrib.auth.models import User
    from .models import Post

    # Model Types for CRUD Operations — each generates its own
    # UserListGenericType / PostListGenericType internally.
    class UserModelType(DjangoModelType):
        class Meta:
            model = User
            description = "User operations"
            pagination = LimitOffsetGraphqlPagination(default_limit=25)
            filter_fields = {
                'username': ('exact', 'icontains'),
                'email': ('exact', 'icontains'),
                'is_active': ('exact',),
            }

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            description = "Post operations"
            pagination = LimitOffsetGraphqlPagination(default_limit=10)
            filter_fields = {
                'title': ('exact', 'icontains'),
                'status': ('exact',),
                'author__username': ('exact', 'icontains'),
            }
    ```

=== "mutations.py"

    ```python
    from django_graphex.mutation import DjangoModelMutation
    from django.contrib.auth.models import User
    from .models import Category, Tag, Post, Comment, UserProfile

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            description = "User CRUD operations"
            nested_fields = {
                'profile': UserProfile
            }

    class CategoryMutation(DjangoModelMutation):
        class Meta:
            model = Category
            description = "Category CRUD operations"

    class TagMutation(DjangoModelMutation):
        class Meta:
            model = Tag
            description = "Tag CRUD operations"

    class PostMutation(DjangoModelMutation):
        class Meta:
            model = Post
            description = "Post CRUD operations"
            exclude_fields = ('view_count',)  # Don't allow direct manipulation

    class CommentMutation(DjangoModelMutation):
        class Meta:
            model = Comment
            description = "Comment CRUD operations"
    ```

=== "custom filtering"

    Standard lookups (`exact`, `icontains`, ranges, relation paths, …) come
    straight from each type's `Meta.filter_fields` and are queried through the
    nested `filter:` argument — no `FilterSet` classes. For bespoke logic such as
    a free-text search across several columns, override `filter_queryset` /
    `get_queryset` on a `DjangoModelType` (see
    [Custom queryset & per-request filtering](../types.md#custom-queryset-per-request-filtering)):

    ```python
    from django.db.models import Q
    from django_graphex.types import DjangoModelType
    from .models import Post

    class PostSearchType(DjangoModelType):
        class Meta:
            model = Post
            filter_fields = {
                'status': ('exact',),
                'author__username': ('exact', 'icontains'),
                'view_count': ('gte', 'lte'),
            }

        @classmethod
        def filter_queryset(cls, qs, info, **kwargs):
            # free-text "search" across title/content/excerpt, taken from the
            # request (declared filter_fields above still apply on top of this)
            term = info.context.GET.get("q") if hasattr(info.context, "GET") else None
            if term:
                qs = qs.filter(
                    Q(title__icontains=term)
                    | Q(content__icontains=term)
                    | Q(excerpt__icontains=term)
                )
            return qs
    ```

=== "schema.py"

    !!! tip "Two approaches, not an either-or"
        Variant A wires each type by hand: you declare the node, the container
        and the mutation, and mount them on exactly the fields you want. Variant B
        lets a `DjangoModelType` generate the same surface from one declaration.
        Both are shown below as self-contained schemas so each reads on its own,
        but nothing stops a project from using them together — hand-written types
        for the models that need bespoke wiring, `DjangoModelType` for the
        boilerplate ones.

        Per model, still pick one. Two hosts over one model is allowed only while
        neither declares a projection: the moment a `DjangoModelType` adds
        `only_fields` / `exclude_fields` / `include_fields` for a model a
        `DjangoObjectType` already registered, the build stops with
        `ImproperlyConfigured` — because the projection would otherwise be
        dropped and the field it hides would stay exposed.

        Since **2.2.0** the generated container is named `<Model>ListGenericType`,
        so it no longer collides with the `<Model>ListType` you declare yourself.
        On 2.1.x and earlier both carried the same name and the schema build
        failed with *"Schema must contain uniquely named types"* — that
        restriction is gone.

    ```python title="Variant A — manual types (UserListType / PostListType)"
    from django_graphex.directives import all_directives
    from django_graphex.fields import DjangoObjectField, DjangoFilterListField, DjangoFilterPaginateListField, DjangoListObjectField
    from django_graphex.core import ObjectType
    from django_graphex.paginations import LimitOffsetGraphqlPagination
    from django_graphex.schema import DjangoGraphQLSchema
    from .types import (
        UserType, CategoryType, TagType, PostType, CommentType,
        UserListType, PostListType, CommentListType,
    )
    from .mutations import (
        UserMutation, CategoryMutation, TagMutation,
        PostMutation, CommentMutation
    )

    class Query(ObjectType):
        # Single object queries
        user = DjangoObjectField(UserType, description="Get a single user")
        post = DjangoObjectField(PostType, description="Get a single post")
        category = DjangoObjectField(CategoryType, description="Get a single category")
        tag = DjangoObjectField(TagType, description="Get a single tag")
        comment = DjangoObjectField(CommentType, description="Get a single comment")

        # List queries with different approaches
        all_posts = DjangoListObjectField(PostListType, description="All posts with pagination")
        all_users = DjangoListObjectField(UserListType, description="All users with pagination")
        all_comments = DjangoListObjectField(CommentListType, description="All comments with pagination")

        # Filter-only lists (no pagination)
        posts = DjangoFilterListField(PostType, description="Filter posts without pagination")
        users = DjangoFilterListField(UserType, description="Filter users without pagination")
        categories = DjangoFilterListField(CategoryType, description="All categories")
        tags = DjangoFilterListField(TagType, description="All tags")

        # Filtered and paginated lists
        posts_paginated = DjangoFilterPaginateListField(
            PostType,
            pagination=LimitOffsetGraphqlPagination(default_limit=10),
            description="Posts with filtering and pagination"
        )

    class Mutation(ObjectType):
        # User mutations
        create_user, delete_user, update_user = UserMutation.MutationFields()

        # Category mutations
        create_category, delete_category, update_category = CategoryMutation.MutationFields()

        # Tag mutations
        create_tag, delete_tag, update_tag = TagMutation.MutationFields()

        # Post mutations
        create_post, delete_post, update_post = PostMutation.MutationFields()

        # Comment mutations
        create_comment, delete_comment, update_comment = CommentMutation.MutationFields()

    schema = DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        directives=all_directives
    )
    ```

    ```python title="Variant B — DjangoModelType (all-in-one)"
    from django_graphex.directives import all_directives
    from django_graphex.fields import DjangoObjectField, DjangoFilterListField, DjangoListObjectField
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    # This variant is the mixed shape the tip above describes: `DjangoModelType`
    # for User and Post, Variant A's hand-written types for the models that are
    # mounted as-is. Importing both modules is safe — the generated container is
    # `<Model>ListGenericType`, so it never collides with a hand-written
    # `<Model>ListType`.
    from .types import CategoryType, TagType, CommentType, CommentListType
    from .types_modeltype import UserModelType, PostModelType
    from .mutations import CategoryMutation, TagMutation, CommentMutation

    class Query(ObjectType):
        # Single object queries for types without a DjangoModelType
        category = DjangoObjectField(CategoryType, description="Get a single category")
        tag = DjangoObjectField(TagType, description="Get a single tag")
        comment = DjangoObjectField(CommentType, description="Get a single comment")

        # Filter-only / filtered-paginated lists for the remaining types
        categories = DjangoFilterListField(CategoryType, description="All categories")
        tags = DjangoFilterListField(TagType, description="All tags")
        all_comments = DjangoListObjectField(CommentListType, description="All comments with pagination")

        # DjangoModelType-driven queries — retrieve + list generated together
        # (each type also generates its own <Model>ListGenericType container)
        user_retrieve, user_list = UserModelType.QueryFields()
        post_retrieve, post_list = PostModelType.QueryFields()

    class Mutation(ObjectType):
        # Category / tag / comment mutations (no DjangoModelType for these)
        create_category, delete_category, update_category = CategoryMutation.MutationFields()
        create_tag, delete_tag, update_tag = TagMutation.MutationFields()
        create_comment, delete_comment, update_comment = CommentMutation.MutationFields()

        # DjangoModelType-driven mutations
        user_create, user_delete, user_update = UserModelType.MutationFields()
        post_create, post_delete, post_update = PostModelType.MutationFields()

    schema = DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        directives=all_directives
    )
    ```

