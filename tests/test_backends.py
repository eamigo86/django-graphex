# -*- coding: utf-8 -*-
"""The serializer-backend seam: abstract API, resolve_backend, backend_for_nested."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.backends import (
    SerializerBackend,
    backend_for_nested,
    resolve_backend,
)
from django_graphex.native.backend import PydanticBackend
from tests.models import Author


def test_serializer_backend_abstract_methods_raise():
    backend = SerializerBackend()
    with pytest.raises(NotImplementedError):
        backend.get_model()
    with pytest.raises(NotImplementedError):
        backend.save_object(None, None, None, {})
    with pytest.raises(NotImplementedError):
        backend.to_representation(None)
    with pytest.raises(NotImplementedError):
        backend.output_field_names()


def test_resolve_backend_returns_pydantic_backend():
    backend = resolve_backend(Author)
    assert isinstance(backend, PydanticBackend)
    assert backend.get_model() is Author


def test_resolve_backend_requires_model():
    with pytest.raises(ImproperlyConfigured):
        resolve_backend(None)


def test_backend_for_nested_model_spec():
    backend = backend_for_nested(Author)
    assert isinstance(backend, PydanticBackend)
    assert backend.get_model() is Author


def test_backend_for_nested_rejects_non_model():
    with pytest.raises(ImproperlyConfigured):
        backend_for_nested("tests.Author")  # a string, not a model class
    with pytest.raises(ImproperlyConfigured):
        backend_for_nested(object)
