# -*- coding: utf-8 -*-
"""A declaration over a GENERIC relation's name is masked like any other.

The masked-column stamp once carried a carve-out for a declared RELATION, on
the theory that the relation's TARGET type answers for the key behind it. A
"GenericForeignKey" has no target model at all -- "related_model" is "None" --
so the carve-out's model comparison read "None is None" and cleared ANY
declaration standing over a GFK's name, including one publishing nothing
traversable.

The carve-out is gone: a declaration served by a resolver of its own is a mask
whatever the model holds under that name. This module keeps the generic shape
pinned, because it is the one where an "absent versus absent" comparison can
still look like agreement to whoever reintroduces such a rule.
"""

from __future__ import annotations

from typing import Any

from django_graphex.core import CharField
from django_graphex.core.output_compiler import MASKED_COLUMN_EXT
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

from .models import Track2GfkComment

_RGFK = Registry()


class MaskedGfkCommentType(DjangoObjectType):
    """Comment node that re-publishes its GFK's name over a redaction.

    "only_fields" drops the model-derived "target", and the declared attribute
    below puts the name back with a resolver that never reads the relation.
    """

    target = CharField()

    class Meta:
        """Configuration for "MaskedGfkCommentType".

        Drops the model-derived "target" so the declared attribute above is the
        only thing publishing that name.
        """

        model = Track2GfkComment
        registry = _RGFK
        only_fields = ("id", "body")

    def resolve_target(self, info: Any) -> str:
        """Return a constant in place of the generic relation.

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The redaction marker that stands in for the relation.
        """
        return "[redacted]"


class TestAGenericRelationIsNotAPublishedRelation:
    """A GFK names no target type, so no declaration can publish one.

    Nothing stands behind a generic relation to answer for a key, which is why
    a rule that hands declarations the benefit of the doubt cannot be written
    here at all.
    """

    def test_the_masked_generic_relation_is_stamped(self) -> None:
        """The declaration must carry the masked-column stamp.

        If this breaks, something cleared a resolver-backed leaf because the
        relation's absent target model matched the type's absent model.
        """
        compiled = MaskedGfkCommentType._meta.graphql_output_type
        field = compiled.fields["target"]
        assert (field.extensions or {}).get(MASKED_COLUMN_EXT) is True
