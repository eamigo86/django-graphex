# Installation

## Basic Installation

For installing django-graphex, just run this command in your shell:

```bash
pip install django-graphex
```

This pulls in the core dependencies (`graphene`, `graphql-relay`, `pydantic`,
`python-dateutil`) — **not** `graphene-django` and **not** `djangorestframework`
(the package depends on neither). Filtering is built on Django's ORM lookups +
`Q` objects, so there is **no `django-filter` dependency**.

Validation and persistence use the built-in **native (Pydantic) backend**
(`Meta.model`) — see [Model backend (Pydantic)](usage/backends.md).

## Subscriptions (optional extra)

Real-time GraphQL subscriptions run over [Channels](https://channels.readthedocs.io)
and are shipped as an optional extra. The base install never pulls in Channels:

```bash
pip install "django-graphex[subscriptions]"
```

This adds `channels` and `channels-redis`. See the
[Subscriptions guide](usage/subscriptions.md) for the ASGI wiring.

## Requirements

- **Python**: 3.12, 3.13, 3.14
- **Django**: 4.0, 4.2, 5.0, 5.1, 5.2, 6.0
- **graphene**: >=3.3,<4
- **pydantic**: >=2,<3

!!! info "Version Support"
    - **Minimum Python version**: 3.12+
    - **Minimum Django version**: 4.0+
    - Full compatibility tested with all combinations of supported versions

## Development Installation

If you want to contribute to the project, install it with
[uv](https://docs.astral.sh/uv/):

```bash
# Clone the repository
git clone https://github.com/eamigo86/django-graphex.git
cd django-graphex

# Install all dependencies (including the dev group) into a managed venv
uv sync

# Run the tests / quality checks
uv run pytest
make quality
```

## Verify Installation

You can verify the installation by importing the package:

```python
import django_graphex
print(django_graphex.__version__)
```
