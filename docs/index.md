# django-graphex Documentation

![Codecov](https://img.shields.io/codecov/c/github/eamigo86/django-graphex){ .md-badge }
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-graphex){ .md-badge }
![Django Versions](https://img.shields.io/pypi/frameworkversions/django/django-graphex?label=django&color=0C4B33){ .md-badge }
![PyPI](https://img.shields.io/pypi/v/django-graphex?color=blue){ .md-badge }
![PyPI - License](https://img.shields.io/pypi/l/django-graphex){ .md-badge }
![Downloads](https://img.shields.io/pepy/dt/django-graphex){ .md-badge }
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json){ .md-badge }

django-graphex builds on graphene and Pydantic to make Django GraphQL APIs easy, without Relay:

1. **Allow pagination and filtering on Queries**
2. **Allow defining Pydantic-backed Mutations directly from Django models**
3. **Allow using Directives on Queries and Fragments**
4. **Optional GraphQL Subscriptions over Django Channels 4**

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
- **DjangoListObjectField** - ⭐ *Recommended for Queries*

### 🧬 Types
- **DjangoListObjectType** - ⭐ *Recommended for Types*
- **DjangoInputObjectType** - Input types for mutations
- **DjangoModelType** - ⭐ *Recommended for quick setup*

### ⚡ Mutations
- **DjangoModelMutation** - ⭐ *Recommended for Mutations*

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
from django_graphex import (
    DjangoListObjectType,
    DjangoModelMutation,
    LimitOffsetGraphqlPagination
)

class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
```

## Getting Started

Ready to dive in? Check out our [Installation Guide](installation.md) to get started, or jump straight to the [Quick Start](quickstart.md) for a hands-on tutorial.

## Community & Support

- **GitHub Issues**: [Report a bug or request a feature](https://github.com/eamigo86/django-graphex/issues/new/choose)
- **PyPI Package**: [Install from PyPI](https://pypi.org/project/django-graphex/)
- **Source Code**: [View on GitHub](https://github.com/eamigo86/django-graphex)
