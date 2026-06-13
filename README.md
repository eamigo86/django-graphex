# django-graphex

![Codecov](https://img.shields.io/codecov/c/github/eamigo86/django-graphex)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-graphex)
![Django Versions](https://img.shields.io/pypi/frameworkversions/django/django-graphex?label=django&color=0C4B33)
![PyPI](https://img.shields.io/pypi/v/django-graphex?color=blue)
![PyPI - License](https://img.shields.io/pypi/l/django-graphex)
![Downloads](https://img.shields.io/pepy/dt/django-graphex)
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)

**GraphQL for Django, powered by [graphene](https://graphene-python.org/) and
[Pydantic](https://docs.pydantic.dev/).** Define your GraphQL API straight from your
Django models — no DRF, no `graphene-django`, no `django-filter`.

- **Model-first types & mutations** — `DjangoModelType` / `DjangoModelMutation`
  give you query, list and create/update/delete from a single `Meta.model`,
  validated and persisted with **Pydantic v2** + the Django ORM (FK existence,
  uniqueness, `unique_together`, partial updates, `choices` → Enum).
- **Logical filtering** — one nested `filter:` argument with `and` / `or` / `not`,
  per-field lookups, relation descent and plain-pk/UUID filtering (no `django-filter`).
- **Pagination** — limit/offset, page and keyset **cursor** paginators with a
  uniform `results` / `totalCount` shape (and an automatic N+1 query optimizer).
- **Custom validation** — DRF-style inline `validate_<field>()` / `validate()` or a
  `Meta.pydantic_model`.
- **Permissions, security & directives** — permission classes, depth & cost limits,
  introspection control, and string/number/date/list directives.
- **Subscriptions** — real-time GraphQL over Django Channels 4 (optional extra).

> **Coming from `graphene-django` or `graphene-django-extras`?** See the
> [Migration Guide](https://eamigo86.github.io/django-graphex/migration/) for a
> step-by-step upgrade with before/after examples.

## Requirements

- **Python:** 3.12+ (3.13, 3.14 supported)
- **Django:** 4.2+ (4.2, 5.0, 5.1, 5.2, 6.0 supported)
- **graphene:** >=3.3,<4
- **pydantic:** >=2,<3

## Installation

```bash
# uv (recommended)
uv add django-graphex
# real-time subscriptions (adds Django Channels 4):
uv add "django-graphex[subscriptions]"
```

```bash
# pip
pip install django-graphex
pip install "django-graphex[subscriptions]"
```

The base install never imports `channels`; only the `subscriptions` extra does.

## Quick start

```python
import graphene
from django.contrib.auth.models import User
from django_graphex import (
    DjangoListObjectType, DjangoListObjectField, DjangoObjectField, DjangoModelMutation,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination


class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination()
        filter_fields = {"username": ("icontains", "exact"), "is_active": ("exact",)}


class UserMutation(DjangoModelMutation):      # define once -> create/update/delete
    class Meta:
        model = User


class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType)


class Mutation(graphene.ObjectType):
    user_create = UserMutation.CreateField()
    user_update = UserMutation.UpdateField()
    user_delete = UserMutation.DeleteField()


schema = graphene.Schema(query=Query, mutation=Mutation)
```

Query it with the nested `filter:` argument (`and` / `or` / `not`):

```graphql
{
  users(filter: { is_active: { exact: true }, username: { icontains: "jo" } }) {
    results(limit: 10, ordering: "-date_joined") { id username }
    totalCount
  }
}
```

## Configuration

All settings live under a single `DJANGO_GRAPHEX` dict (every key is optional):

```python
# settings.py
DJANGO_GRAPHEX = {
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": 20,
    "MAX_PAGE_SIZE": 50,
    # Response caching. Default is False (disabled).
    # WARNING: cache keys are identity-salted per user (v1.2.1+), but shared
    # caches can still leak data if misconfigured. Review the caching guide
    # before enabling in production: docs/usage/caching.md
    "CACHE_ACTIVE": True,
}
```

To use directives, add the middleware and pass `all_directives` to the schema:

```python
GRAPHENE = {"MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"]}

from django_graphex import all_directives
schema = graphene.Schema(query=Query, mutation=Mutation, directives=all_directives)
```

## Playground

A fully wired example project lives in [`examples/playground/`](examples/playground/). It exercises every major feature end-to-end — types, paginators, filtering, mutations, permissions, subscriptions, and the query optimizer — and installs the library from this repo checkout (editable, no PyPI release needed).

## Documentation

📚 **[Full documentation](https://eamigo86.github.io/django-graphex/)** — including the
[Quick Start](https://eamigo86.github.io/django-graphex/quickstart/),
[Model backend](https://eamigo86.github.io/django-graphex/usage/backends/),
[Filtering](https://eamigo86.github.io/django-graphex/usage/filtering/),
[Pagination](https://eamigo86.github.io/django-graphex/usage/pagination/),
[Subscriptions](https://eamigo86.github.io/django-graphex/usage/subscriptions/),
[Settings](https://eamigo86.github.io/django-graphex/usage/settings/) and the
[Migration Guide](https://eamigo86.github.io/django-graphex/migration/).

## License

MIT License — see the [LICENSE](LICENSE) file.
