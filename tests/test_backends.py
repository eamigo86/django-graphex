# -*- coding: utf-8 -*-
"""The serializer-backend seam: abstract API, resolve_backend, backend_for_nested."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.backends import (
    SerializerBackend,
    backend_for_nested,
    resolve_backend,
)
from django_graphex.core.backend import PydanticBackend
from tests.models import Author


def test_serializer_backend_abstract_methods_raise() -> None:
    """Every "SerializerBackend" abstract method must raise NotImplementedError.

    Guards against a concrete subclass silently no-oping instead of
    overriding one of the four required backend methods.
    """
    backend = SerializerBackend()
    with pytest.raises(NotImplementedError):
        backend.get_model()
    with pytest.raises(NotImplementedError):
        backend.save_object(None, None, None, {})
    with pytest.raises(NotImplementedError):
        backend.to_representation(None)
    with pytest.raises(NotImplementedError):
        backend.output_field_names()


def test_resolve_backend_returns_pydantic_backend() -> None:
    """ "resolve_backend" must return a "PydanticBackend" bound to the given model.

    If this breaks, model-backed types would resolve to the wrong backend
    implementation or lose their model binding.
    """
    backend = resolve_backend(Author)
    assert isinstance(backend, PydanticBackend)
    assert backend.get_model() is Author


def test_resolve_backend_requires_model() -> None:
    """ "resolve_backend" must reject a None model with ImproperlyConfigured.

    Prevents a misconfigured type from silently resolving to a backend with
    no model bound.
    """
    with pytest.raises(ImproperlyConfigured):
        resolve_backend(None)


def test_backend_for_nested_model_spec() -> None:
    """ "backend_for_nested" must return a "PydanticBackend" bound to the given model.

    Covers the nested-input path separately from "resolve_backend" since it
    has its own validation branch.
    """
    backend = backend_for_nested(Author)
    assert isinstance(backend, PydanticBackend)
    assert backend.get_model() is Author


def test_backend_for_nested_rejects_non_model() -> None:
    """ "backend_for_nested" must reject non-model arguments (a string or "object").

    If this breaks, a nested input spec could silently accept a bogus model
    reference instead of failing fast with ImproperlyConfigured.
    """
    with pytest.raises(ImproperlyConfigured):
        backend_for_nested("tests.Author")  # a string, not a model class
    with pytest.raises(ImproperlyConfigured):
        backend_for_nested(object)
