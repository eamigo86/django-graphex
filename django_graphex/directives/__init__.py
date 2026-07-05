"""GraphQL directives for data transformation and formatting."""

from __future__ import annotations

from graphql.type.directives import specified_directives as default_directives

from .date import DateGraphQLDirective
from .list import (
    SampleGraphQLDirective,
    ShuffleGraphQLDirective,
    UniqueGraphQLDirective,
)
from .numbers import (
    AbsGraphQLDirective,
    CeilGraphQLDirective,
    FloorGraphQLDirective,
    RoundGraphQLDirective,
)
from .string import (
    Base64GraphQLDirective,
    CamelCaseGraphQLDirective,
    CapitalizeGraphQLDirective,
    CenterGraphQLDirective,
    CurrencyGraphQLDirective,
    DefaultGraphQLDirective,
    KebabCaseGraphQLDirective,
    LowercaseGraphQLDirective,
    NumberGraphQLDirective,
    ReplaceGraphQLDirective,
    SlugifyGraphQLDirective,
    SnakeCaseGraphQLDirective,
    StripGraphQLDirective,
    SwapCaseGraphQLDirective,
    TitleCaseGraphQLDirective,
    TruncateGraphQLDirective,
    UppercaseGraphQLDirective,
)

# Tuple of the 25 custom directive CLASSES.  Kept as a private name so that
# ``all_directives`` (below) only ever holds the runtime list of INSTANCES,
# giving mypy a single consistent type for the exported name.
_DIRECTIVE_CLASSES: tuple[type, ...] = (
    # date
    DateGraphQLDirective,
    # list
    ShuffleGraphQLDirective,
    SampleGraphQLDirective,
    UniqueGraphQLDirective,
    # numbers
    FloorGraphQLDirective,
    CeilGraphQLDirective,
    RoundGraphQLDirective,
    AbsGraphQLDirective,
    # string
    DefaultGraphQLDirective,
    Base64GraphQLDirective,
    NumberGraphQLDirective,
    CurrencyGraphQLDirective,
    LowercaseGraphQLDirective,
    UppercaseGraphQLDirective,
    CapitalizeGraphQLDirective,
    CamelCaseGraphQLDirective,
    SnakeCaseGraphQLDirective,
    KebabCaseGraphQLDirective,
    SwapCaseGraphQLDirective,
    StripGraphQLDirective,
    TitleCaseGraphQLDirective,
    CenterGraphQLDirective,
    ReplaceGraphQLDirective,
    TruncateGraphQLDirective,
    SlugifyGraphQLDirective,
)

# List of 30 directive *instances*: 25 custom + 5 spec GraphQL directives
# (graphql-core's ``specified_directives`` bundle: skip, include, deprecated,
# specifiedBy, oneOf). Typed as ``list`` so callers that do
# ``all_directives + [custom()]`` or ``schema = Schema(..., directives=all_directives)``
# get correct inference.
all_directives: list = [d() for d in _DIRECTIVE_CLASSES] + [*default_directives]
