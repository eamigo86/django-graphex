# GraphQL Directives

GraphQL directives in `django-graphex` allow you to transform field values at query execution time. They provide a powerful way to format, manipulate, and transform data without modifying your underlying models or resolvers.

## Middleware requirement (required for ALL directives)

!!! warning "Middleware is required"

    **Every directive — built-in and custom — requires `GraphQLDirectiveMiddleware`
    to be registered in your settings.** Without it, directives parse and validate
    in the schema but are silently ignored at execution time (no error, no transform).

    Add it to your settings before using any directive:

    ```python
    GRAPHENE = {
        "SCHEMA": "myapp.schema.schema",
        "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],
    }
    ```

    And pass `all_directives` (or your combined directive list) to the schema:

    ```python
    from django_graphex import all_directives

    schema = graphene.Schema(
        query=Query,
        mutation=Mutation,
        directives=all_directives,
    )
    ```

    The middleware coerces directive arguments and dispatches transforms to the
    registered directive class. Both the schema `directives=` list **and** the
    middleware entry are required — either alone does nothing.

## Overview

Directives are applied to fields in your GraphQL queries and are processed after the field value is resolved. They enable you to:

- :material-format-text: **Format strings**: Transform text case, encoding, and structure
- :material-calendar: **Format dates**: Display dates in various formats and relative time
- :material-calculator: **Format numbers**: Apply number formatting and currency display
- :material-shuffle-variant: **Manipulate lists**: Transform and sample list data

## Usage

Directives are applied in GraphQL queries using the `@directive_name` syntax:

```graphql
query {
  user {
    name @uppercase
    email @lowercase
    joinDate @date(format: "MMMM DD, YYYY")
    balance @currency(symbol: "€")
  }
}
```

## String Directives

String directives provide various text transformation capabilities:

### Case Conversion

Transform text case with these directives:

=== "Uppercase & Lowercase"

    ```graphql
    query GetUser {
      user {
        name @uppercase        # "JOHN DOE"
        email @lowercase       # "john.doe@example.com"
        bio @capitalize        # "Hello world" → "Hello world"
        title @title_case       # "hello world" → "Hello World"
        status @swap_case       # "Hello" → "hELLO"
      }
    }
    ```

=== "Code Style Conversion"

    ```graphql
    query GetData {
      post {
        title @camel_case       # "My Blog Post" → "myBlogPost"
        slug @snake_case        # "My Blog Post" → "my_blog_post"
        url @kebab_case         # "My Blog Post" → "my-blog-post"
      }
    }
    ```

### String Manipulation

=== "Trimming and Padding"

    ```graphql
    query GetContent {
      post {
        content @strip                    # Remove whitespace
        title @strip(chars: ".")          # Remove specific characters
        code @center(width: 20)           # Center text in 20 characters
        header @center(width: 30, fillchar: "-")  # Center with dashes
      }
    }
    ```

=== "Find and Replace"

    ```graphql
    query GetPost {
      post {
        content @replace(old: "GraphQL", new: "GQL")
        text @replace(old: " ", new: "_", count: 3)  # Replace first 3 spaces
      }
    }
    ```

=== "Truncate and Slugify"

    ```graphql
    query GetPost {
      post {
        # Cut on a word boundary, append "…" (default)
        summary @truncate(length: 80)              # "A long summary…"
        # Cut mid-word with a custom suffix
        teaser @truncate(length: 10, killwords: true, end: "...")
        # URL-safe slug (Django slugify)
        title @slugify                             # "My Post!" → "my-post"
      }
    }
    ```

    | Directive | Args | Behavior |
    |-----------|------|----------|
    | `@truncate` | `length: Int!`, `end: String = "…"`, `killwords: Boolean = false` | Shorten to `length`, appending `end`; break on a word boundary unless `killwords`. |
    | `@slugify` | — | Convert to a URL-safe slug. |

### Default Values

Provide fallback values for empty or null fields:

=== "Default Directive"

    ```graphql
    query GetUser {
      user {
        firstName @default(to: "Anonymous")
        lastName @default(to: "User")
        bio @default(to: "No bio available")
      }
    }
    ```

=== "Example Response"

    ```json
    {
      "data": {
        "user": {
          "firstName": "John",        // Original value
          "lastName": "Anonymous",    // Default applied (was null)
          "bio": "No bio available"  // Default applied (was empty)
        }
      }
    }
    ```

### Encoding Directives

Handle base64 encoding and decoding. Supports any Unicode input — non-ASCII
characters (accented letters, emoji, etc.) are encoded as UTF-8 before
base64 encoding:

=== "Base64 Operations"

    ```graphql
    query GetData {
      apiKey @base64(op: "encode")      # Encode to base64
      token @base64(op: "decode")       # Decode from base64
    }
    ```

=== "Example"

    ```json
    // Input: "hello world"
    // With @base64(op: "encode"): "aGVsbG8gd29ybGQ="
    // With @base64(op: "decode"): Original string from base64
    // Non-ASCII input (e.g. "Ñoño") is encoded as UTF-8 — no crash.
    ```

## Number Directives

Format numeric values with precision and style:

### Basic Number Formatting

The `as` argument accepts any Python numeric format spec. Format specs with
a width or precision exceeding 100 are rejected with a field error to
prevent memory exhaustion from client-supplied oversized specs (e.g.
`"1000000.5f"`).

=== "Number Directive"

    ```graphql
    query GetStats {
      product {
        price @number(as: ".2f")        # "123.45"
        weight @number(as: ".3f")       # "12.500"
        rating @number(as: ".1f")       # "4.2"
      }
    }
    ```

### Currency Formatting

Format numbers as currency with customizable symbols:

=== "Currency Examples"

    ```graphql
    query GetPrices {
      product {
        priceUSD @currency                    # "$123.45" (default)
        priceEUR @currency(symbol: "€")       # "€123.45"
        priceGBP @currency(symbol: "£")       # "£123.45"
        priceJPY @currency(symbol: "¥")       # "¥123.45"
      }
    }
    ```

=== "Response Example"

    ```json
    {
      "data": {
        "product": {
          "priceUSD": "$1,234.56",
          "priceEUR": "€1,234.56",
          "priceGBP": "£1,234.56",
          "priceJPY": "¥1,234.56"
        }
      }
    }
    ```

## Date Directives

Powerful date and time formatting with multiple options:

### Standard Date Formats

=== "Common Formats"

    ```graphql
    query GetPost {
      post {
        createdAt @date(format: "YYYY-MM-DD")         # "2023-12-01"
        updatedAt @date(format: "MMMM DD, YYYY")      # "December 01, 2023"
        publishedAt @date(format: "DD/MM/YYYY HH:mm") # "01/12/2023 14:30"
        timestamp @date(format: "iso")                # "2023-12-01T14:30:00"
        jsDate @date(format: "javascript")            # "Fri Dec 01 2023 14:30:00"
      }
    }
    ```

### Relative Time Formatting

=== "Time Ago Formats"

    ```graphql
    query GetActivity {
      post {
        createdAt @date(format: "time ago")       # "2 hours ago" / "in 3 days"
        updatedAt @date(format: "time ago 2d")    # Shows "Yesterday", "Tomorrow", or date
      }
    }
    ```

=== "Relative Time Examples"

    ```json
    {
      "data": {
        "post": {
          "createdAt": "2 hours ago",
          "updatedAt": "Yesterday"    // or "Dec 01, 2023" if more than 2 days
        }
      }
    }
    ```

### Custom Date Patterns

Build custom date formats using these tokens:

| Token | Description | Example |
|-------|-------------|---------|
| `YYYY` | 4-digit year | 2023 |
| `YY` | 2-digit year | 23 |
| `MMMM` | Full month name | December |
| `MMM` | Short month name | Dec |
| `MM` | Month number (padded) | 12 |
| `DD` | Day of month (padded) | 01 |
| `dddd` | Full day name | Friday |
| `ddd` | Short day name | Fri |
| `HH` | Hour (24h, padded) | 14 |
| `hh` | Hour (12h, padded) | 02 |
| `mm` | Minutes (padded) | 30 |
| `ss` | Seconds (padded) | 45 |
| `A` | AM/PM | PM |

=== "Custom Format Examples"

    ```graphql
    query GetEvents {
      event {
        startDate @date(format: "dddd, MMMM DD, YYYY")    # "Friday, December 01, 2023"
        endDate @date(format: "DD-MM-YY HH:mm A")         # "01-12-23 02:30 PM"
        created @date(format: "YYYY/MM/DD")               # "2023/12/01"
      }
    }
    ```

## List Directives

Transform and manipulate list data:

### Shuffle Directive

Randomly reorder list elements:

=== "Shuffle Lists"

    ```graphql
    query GetRandomPosts {
      posts {
        tags @shuffle {
          name
          color
        }
      }
    }
    ```

### Sample Directive

Get a random sample from a list:

=== "Sample Lists"

    ```graphql
    query GetSampleTags {
      post {
        tags @sample(k: 3) {  # Get 3 random tags
          name
          color
        }
      }
    }
    ```

### Unique Directive

De-duplicate a list while preserving order:

=== "Unique Lists"

    ```graphql
    query GetTags {
      post {
        tags @unique  # ["a", "b", "a", "c"] → ["a", "b", "c"]
      }
    }
    ```

## Math Directives

Perform mathematical operations on numbers:

### Floor, Ceil, Round and Abs

=== "Rounding Operations"

    ```graphql
    query GetStats {
      product {
        rating @floor              # 4.7 → 4
        price @ceil                # 99.1 → 100
        score @round(precision: 1) # 4.27 → 4.3
        score @round               # 4.27 → 4
        delta @abs                 # -3.5 → 3.5
      }
    }
    ```

!!! note "String / Float fields and null"

    `@floor`, `@ceil`, `@round` and `@abs` work on both `Float` and `String`
    fields — when the field is a `String` the result comes back as a string. A
    `null` value passes through unchanged.

## Combining Directives

Chain multiple directives for complex transformations:

=== "Directive Chaining"

    ```graphql
    query GetFormattedData {
      user {
        firstName @default(to: "Anonymous") @title_case @strip
        email @lowercase @strip
        bio @default(to: "No bio") @capitalize @replace(old: ".", new: "!")
      }
      post {
        title @title_case @replace(old: "GraphQL", new: "GQL")
        viewCount @number(as: ",.0f")
        createdAt @date(format: "MMMM DD, YYYY")
      }
    }
    ```

=== "Example Response"

    ```json
    {
      "data": {
        "user": {
          "firstName": "Anonymous",
          "email": "user@example.com",
          "bio": "Welcome to my profile!"
        },
        "post": {
          "title": "Getting Started With GQL",
          "viewCount": "1,245",
          "createdAt": "December 01, 2023"
        }
      }
    }
    ```

## Custom Directives

While `django-graphex` provides many built-in directives, you can create
your own. A custom directive is a class that transforms the **resolved value** of
a field. The full recipe is four steps, shown end-to-end below.

> The example here is verified by the test suite
> (`tests/test_directives.py::CustomDirectiveTest`), so it stays in sync with the
> code.

### 1. Define the directive

Subclass `BaseExtraGraphQLDirective`, declare any arguments in `get_args()`, and
transform the value in `resolve()`. The directive **name is derived from the
class name** (the `GraphQLDirective` suffix is stripped and the rest is
snake_cased), so `MaskGraphQLDirective` becomes `@mask` (and, e.g.,
`CreditCardGraphQLDirective` would become `@credit_card`).

```python
# myapp/directives.py
from django_graphex.directives.base import BaseExtraGraphQLDirective
from graphql import GraphQLArgument, GraphQLNonNull, GraphQLInt, GraphQLString


class MaskGraphQLDirective(BaseExtraGraphQLDirective):
    """Keep the last `visible` characters, masking the rest."""

    @staticmethod
    def get_args():
        return {
            "visible": GraphQLArgument(
                GraphQLNonNull(GraphQLInt),
                description="Number of trailing characters to leave visible",
            ),
            "char": GraphQLArgument(
                GraphQLString, description="Masking character (default: '*')"
            ),
        }

    @staticmethod
    def resolve(value, args, directive, root, info, **kwargs):
        if not value:
            return value
        text = str(value)
        visible = args.get("visible") or 0
        char = args.get("char") or "*"
        if visible >= len(text):
            return text
        return char * (len(text) - visible) + text[len(text) - visible:]
```

The `resolve(value, args, directive, root, info, **kwargs)` signature receives the
already-resolved field `value` and the **coerced** `args` dict — read them with
`args.get("name")`, no AST parsing required.

### 2. Register it on the schema

Pass an **instance** alongside `all_directives` (which already bundles the
built-ins plus the standard `@skip` / `@include` / `@deprecated`):

```python
# myapp/schema.py
import graphene
from django_graphex import all_directives
from myapp.directives import MaskGraphQLDirective

schema = graphene.Schema(
    query=Query,
    directives=[*all_directives, MaskGraphQLDirective()],
)
```

`django_graphex.DjangoGraphQLSchema` accepts the same `directives=`
argument, so the snippet works with either schema class.

### 3. Enable the middleware

Custom directives are applied by `GraphQLDirectiveMiddleware`. Without it the
directive parses and validates but does nothing:

```python
# settings.py
GRAPHENE = {
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],
}
```

### 4. Use it

```graphql
query {
  card @mask(visible: 4)            # "4111111111111234" -> "************1234"
  card @mask(visible: 4, char: "#") #                   -> "############1234"
}
```

Because the middleware coerces arguments with `get_directive_values`, every
directive argument may also be supplied as a **GraphQL variable**:

```graphql
query Mask($n: Int!) {
  user { creditCard @mask(visible: $n) }
}
```

!!! note "How it works (and two gotchas)"

    - These are **execution / value-transform** directives. They run on
      `FIELD`, `FRAGMENT_SPREAD` and `INLINE_FRAGMENT` locations and post-process
      whatever the resolver returned — they are *not* schema/SDL type-system
      directives and do not change resolution logic.
    - Both steps are required: the directive must be in the schema's
      `directives=` list **and** the middleware must be enabled. Instantiating the
      directive also self-registers it so the middleware can find it by name.


## Schema Integration

Add directives to your GraphQL schema:

=== "Schema Setup"

    ```python
    import graphene
    from django_graphex import all_directives

    class Query(graphene.ObjectType):
        # Your query fields here
        pass

    schema = graphene.Schema(
        query=Query,
        directives=all_directives  # Include all built-in directives
    )
    ```

=== "Custom Directives"

    ```python
    from django_graphex import all_directives
    from .directives import MaskGraphQLDirective

    # all_directives already includes the built-in @skip / @include /
    # @deprecated directives, so just append your own.
    custom_directives = [
        *all_directives,
        MaskGraphQLDirective()
    ]

    schema = graphene.Schema(
        query=Query,
        directives=custom_directives
    )
    ```

## Middleware Integration

Enable directive processing with middleware:

=== "Django Settings"

    ```python
    GRAPHENE = {
        'SCHEMA': 'myapp.schema.schema',
        'MIDDLEWARE': [
            'django_graphex.GraphQLDirectiveMiddleware',
        ],
    }
    ```

## Real-World Examples

### Blog Post Formatting

=== "Blog Query"

    ```graphql
    query GetBlogPost {
      post(id: "1") {
        title @title_case
        content @strip
        excerpt @default(to: "No excerpt available") @capitalize
        author {
          name @title_case
          email @lowercase
          bio @default(to: "No bio") @strip
        }
        publishedAt @date(format: "MMMM DD, YYYY")
        updatedAt @date(format: "time ago")
        viewCount @number(as: ",.0f")
        tags @sample(k: 5) {
          name @uppercase
        }
      }
    }
    ```

### E-commerce Product Display

=== "Product Query"

    ```graphql
    query GetProduct {
      product(id: "123") {
        name @title_case
        description @strip @default(to: "No description available")
        price @currency(symbol: "$")
        originalPrice @currency(symbol: "$")
        discount @number(as: ".0%")
        weight @number(as: ".2f")
        dimensions @replace(old: "x", new: " × ")
        createdAt @date(format: "YYYY-MM-DD")
        lastModified @date(format: "time ago")
        reviews @shuffle {
          rating @number(as: ".1f")
          comment @strip @default(to: "No comment")
          createdAt @date(format: "MMM DD, YYYY")
        }
      }
    }
    ```

### User Profile Display

=== "Profile Query"

    ```graphql
    query GetUserProfile {
      user {
        username @lowercase
        displayName @default(to: "Anonymous User") @title_case
        email @lowercase
        bio @default(to: "No bio available") @strip @capitalize
        location @title_case
        website @lowercase
        socialLinks {
          twitter @replace(old: "https://twitter.com/", new: "@")
          linkedin @lowercase
        }
        joinDate @date(format: "MMMM YYYY")
        lastActive @date(format: "time ago")
        postCount @number(as: ",.0f")
        followerCount @number(as: ",.0f")
      }
    }
    ```

## Performance Considerations

!!! tip "Performance Tips"

    1. **Directive Order**: Directives are processed in order, so place expensive operations last
    2. **Caching**: Directive results aren't cached by default - consider caching formatted values
    3. **Complex Formatting**: For heavy date/time operations, consider pre-formatting in resolvers
    4. **List Operations**: Be cautious with shuffle/sample on very large lists

## Error Handling

Directives handle errors gracefully:

=== "Error Examples"

    ```graphql
    query {
      post {
        invalidDate @date(format: "YYYY-MM-DD")     # Returns "INVALID FORMAT STRING"
        nullValue @currency                         # Returns "$0.00"
        emptyString @default(to: "fallback")        # Returns "fallback"
      }
    }
    ```

## Best Practices

!!! tip "Directive Best Practices"

    1. **Use Defaults**: Always provide fallback values for nullable fields
    2. **Format Consistently**: Use the same date/number formats across your app
    3. **Chain Wisely**: Order directive chains logically (clean → transform → format)
    4. **Test Edge Cases**: Test with null, empty, and invalid values
    5. **Document Usage**: Document custom directive usage in your API documentation
    6. **Consider Performance**: Use directives for display formatting, not heavy processing

GraphQL directives in `django-graphex` provide a powerful, flexible way to format and transform your API responses, making your GraphQL API more user-friendly and consistent across different client applications.
