# Performance Tips

### Database Optimization

=== "Efficient Queries with select_related"

    ```python
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            pagination = LimitOffsetGraphqlPagination(default_limit=10)

        @classmethod
        def get_queryset(cls, queryset, info):
            return queryset.select_related(
                'author', 'author__profile', 'category'
            ).prefetch_related(
                'tags', 'comments__author'
            )
    ```

=== "Custom Resolver Optimization"

    ```python
    from django_graphex import ObjectType

    class Query(ObjectType):
        popular_posts = DjangoFilterListField(PostType)

        def resolve_popular_posts(self, info, **kwargs):
            return Post.objects.filter(
                status='published',
                view_count__gte=100
            ).select_related(
                'author', 'category'
            ).prefetch_related(
                'tags'
            ).order_by('-view_count')
    ```

These comprehensive examples demonstrate the full power of `django-graphex` in building feature-rich GraphQL APIs with Django. The combination of filtering, pagination, mutations, and directives provides a robust foundation for modern web applications.
