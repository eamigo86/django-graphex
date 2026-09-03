# django-graphex Documentation

![Codecov](https://img.shields.io/codecov/c/github/eamigo86/django-graphex){ .md-badge }
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-graphex){ .md-badge }
![Django Versions](https://img.shields.io/pypi/frameworkversions/django/django-graphex?label=django&color=0C4B33){ .md-badge }
![PyPI](https://img.shields.io/pypi/v/django-graphex?color=blue){ .md-badge }
![PyPI - License](https://img.shields.io/pypi/l/django-graphex){ .md-badge }
![Downloads](https://img.shields.io/pepy/dt/django-graphex){ .md-badge }
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json){ .md-badge }

django-graphex builds on graphql-core and Pydantic to make Django GraphQL APIs easy, without Relay:

1. **Allow pagination and filtering on Queries**
2. **Allow defining Pydantic-backed Mutations directly from Django models**
3. **Allow using Directives on Queries and Fragments**
4. **Optional GraphQL Subscriptions over Django Channels 4**

!!! info "Upgrading to 3.1"
    Start with the [3.0 → 3.1 upgrade guide](UPGRADE-3.1.md) for the cache and
    permission changes, then read the published [3.1.0 changelog](changelog.md#310--2026-09-02)
    for the complete 24-finding traceability table.

!!! note "Subscription Support"
    GraphQL subscriptions now live here as the optional
    `django-graphex[subscriptions]` extra (built on Django Channels 4).
    The standalone
    [graphene-django-subscriptions](https://github.com/eamigo86/graphene-django-subscriptions)
    package is now a deprecated compatibility shim that re-exports from here.

## Key Features

### 🔍 Fields
- **DjangoObjectField** - Single object queries with automatic ID filtering
- **DjangoFilterListField** - List queries with filtering
- **DjangoFilterPaginateListField** - List queries with filtering and pagination
- **DjangoListObjectField** - :material-star: *Recommended for Queries*

### 🧬 Types
- **DjangoListObjectType** - :material-star: *Recommended for Types*
- **DjangoInputObjectType** - Input types for mutations
- **DjangoModelType** - :material-star: *Recommended for quick setup*

### ⚡ Mutations
- **DjangoModelMutation** - :material-star: *Recommended for Mutations*

### 📄 Pagination
- **LimitOffsetGraphqlPagination** - Offset-based pagination
- **PageGraphqlPagination** - Page-based pagination
- **CursorGraphqlPagination** - Keyset (cursor) pagination with `pageInfo`

### 🎯 Directives
- **String formatting** - Case transformation, encoding, manipulation
- **Number formatting** - Currency, mathematical operations
- **Date formatting** - Custom date formats with python-dateutil
- **List operations** - Shuffle, sample operations

## Quick Example

```python title="Basic Usage"
from django.contrib.auth import get_user_model
from django.urls import path
from django_graphex.fields import DjangoObjectField
from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.views import AuthenticatedGraphQLView

User = get_user_model()

class UserType(DjangoObjectType):
    class Meta:
        model = User
        only_fields = ("id", "username", "first_name", "last_name")

class Query(ObjectType):
    user = DjangoObjectField(UserType)

schema = DjangoGraphQLSchema(query=Query)
urlpatterns = [
    path("graphql/", AuthenticatedGraphQLView.as_view(schema=schema)),
]
```

Disable response caching on this authenticated, session-aware path:

```python title="settings.py"
DJANGO_GRAPHEX = {"CACHE_ACTIVE": False}
```

The account example is intentionally read-only. Registration belongs in a
separate mutation that accepts only ordinary account data and calls
`User.objects.create_user(username=..., password=...)`; never expose staff,
superuser, group or permission inputs. The [Quick Start](quickstart.md) provides
the executable version. Use generated CRUD for ordinary application models.

## Getting Started

Ready to dive in? Check out our [Installation Guide](installation.md) to get started, or jump straight to the [Quick Start](quickstart.md) for a hands-on tutorial.

## Community & Support

- **GitHub Issues**: [Report a bug or request a feature](https://github.com/eamigo86/django-graphex/issues/new/choose)
- **PyPI Package**: [Install from PyPI](https://pypi.org/project/django-graphex/)
- **Source Code**: [View on GitHub](https://github.com/eamigo86/django-graphex)

## License

`django-graphex` is open source under the
[MIT License](https://github.com/eamigo86/django-graphex/blob/main/LICENSE) —
free to use, modify and distribute, provided the original copyright notice
(© Ernesto Pérez Amigo) is preserved in all copies.
