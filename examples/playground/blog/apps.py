"""App configuration for the "blog" demo application.

Registers the blog models (authors, posts, comments, notes and the typed-GFK
trio) that the playground schema exposes over GraphQL.
"""

from django.apps import AppConfig


class BlogConfig(AppConfig):
    """Django app config for the playground "blog" application.

    Sets the default primary-key field to "BigAutoField" and binds the app
    label used by Django's app registry and migrations.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "blog"
