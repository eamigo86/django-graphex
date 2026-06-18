# Installation

## Basic Installation

For installing django-graphex, run one of these in your shell:

```bash
# uv (recommended)
uv add django-graphex
```

```bash
# pip
pip install django-graphex
```

This pulls in the core dependencies (`graphql-core`, `pydantic`,
`python-dateutil`, `text-unidecode`) — **not** `graphene`, **not**
`graphene-django` and **not** `djangorestframework` (the package depends on
none of them). As of v2.0, `graphene` has been removed entirely; the schema is
built directly on `graphql-core`. Filtering is built on Django's ORM lookups +
`Q` objects, so there is **no `django-filter` dependency**.

!!! info "Upgrading from django-graphex 1.x?"
    v2.0 is a clean break: `graphene` is gone and the public API moved to the
    native `graphql-core` symbols (`ObjectType`, `field`, `Mutation`,
    `DjangoGraphQLSchema`). See the [2.0 Upgrade Guide](UPGRADE-2.0.md) for
    the full diff, and run the bundled codemod to rewrite most call sites
    automatically:

    ```bash
    python scripts/migrate_2_0.py --apply
    ```

Validation and persistence use the built-in **native (Pydantic) backend**
(`Meta.model`) — see [Model backend (Pydantic)](usage/backends.md).

## Subscriptions (optional extra)

Real-time GraphQL subscriptions run over [Channels](https://channels.readthedocs.io)
and are shipped as an optional extra. The base install never pulls in Channels:

```bash
# uv (recommended)
uv add "django-graphex[subscriptions]"
```

```bash
# pip
pip install "django-graphex[subscriptions]"
```

This adds `channels` and `channels-redis`. See the
[Subscriptions guide](usage/subscriptions.md) for the ASGI wiring.

## Add to `INSTALLED_APPS`

```python
# settings.py
INSTALLED_APPS = [
    # … your apps …
    "django.contrib.contenttypes",  # Django core; django-graphex uses it for GFK support
    "django_graphex",
]
```

Adding `django_graphex` is **optional for basic use** — importing the types,
fields and `GraphQLView` works without it — but it is **required to use the
[`graphql_schema`](usage/settings.md#exporting-the-schema) management command**
(Django only auto-discovers commands from installed apps), and it is
**recommended** in general: the app's `AppConfig.ready()` eagerly compiles the
schema at startup instead of lazily on the first request.

## Requirements

- **Python**: 3.12, 3.13, 3.14
- **Django**: 5.2 (LTS), 6.0
- **graphql-core**: >=3.2.11,<3.3
- **pydantic**: >=2,<3

!!! warning "Django 4.x / 5.0 / 5.1 users"
    **django-graphex 1.3.0+ requires Django >= 5.2.**
    If your project is still on **Django 4.2, 5.0, or 5.1**, use
    **django-graphex 1.2.3** — the last release that supports those versions:

    ```bash
    uv add "django-graphex==1.2.3"
    # or
    pip install "django-graphex==1.2.3"
    ```

!!! info "Version Support"
    - **Minimum Python version**: 3.12+
    - **Minimum Django version**: 5.2 (LTS) — Django 4.2, 5.0 and 5.1 are EOL and no longer supported
    - Each Django version is tested on the Python versions it officially supports

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

Confirm the installed version using the standard metadata API (no Django setup required):

```bash
python -c "from importlib.metadata import version; print(version('django-graphex'))"
```
