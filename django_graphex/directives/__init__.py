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

all_directives = (
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


all_directives = [d() for d in all_directives] + [*default_directives]
