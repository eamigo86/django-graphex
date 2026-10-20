# Using GraphQL Directives

Directive recipes against the [Sample Application](blog-schema.md) schema. For
the full directive reference see [Directives](../../directives.md).

### String Formatting

=== "Format Post Content"

    ```graphql
    query GetPostFormatted {
      post(id: "1") {
        title @uppercase
        excerpt @capitalize
        author {
          username @title_case
          email @lowercase
        }
        content @strip
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "post": {
          "title": "GETTING STARTED WITH GRAPHQL AND DJANGO",
          "excerpt": "Learn the basics of integrating graphql with django",
          "author": {
            "username": "John Doe",
            "email": "john@example.com"
          },
          "content": "GraphQL is a powerful query language for APIs..."
        }
      }
    }
    ```

### Case Conversion

For a post whose title resolves to `HTTPServer`, the three case directives
produce consistent value spellings without renaming the `title` schema field:

```graphql
query PostLabels {
  post(id: "1") {
    camel: title @camel_case
    snake: title @snake_case
    kebab: title @kebab_case
  }
}
```

The response values are `httpServer`, `http_server`, and `http-server`.
Spaces, underscores, hyphens, camelCase and PascalCase are also recognized;
for example, `order_total` yields `orderTotal`, `order_total`, and
`order-total`. These directives change values, not field names.

### Number Formatting

=== "Format View Count"

    ```graphql
    query GetPostStats {
      allPosts(filter: { status: { exact: PUBLISHED } }) {
        results {
          id
          title
          viewCount @number(as: ",.0f")
          createdAt @date(format: "YYYY-MM-DD")
        }
        totalCount
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "allPosts": {
          "results": [
            {
              "id": "1",
              "title": "Getting Started with GraphQL",
              "viewCount": "1,245",
              "createdAt": "2023-12-01"
            },
            {
              "id": "2",
              "title": "Advanced Django Techniques",
              "viewCount": "892",
              "createdAt": "2023-11-28"
            }
          ],
          "totalCount": 2
        }
      }
    }
    ```

### Date Formatting

For a text value such as `"2026-01-10"`, querying
`@date(format: "iso")` now returns `"2026-01-10T00:00:00"` rather than a
timestamp with the server's current time. Partial text such as
`"2026-01-10 14:30"` returns `"2026-01-10T14:30:00"`; a time-only text
value still uses today's date. Explicit seconds and offsets are not replaced
in the input. Absolute output formats display originally aware Python
datetimes and text with an explicit numeric offset or `Z` in Django's active
timezone. In `America/New_York`, `"2026-01-01T03:30:00+02:00"` with
`@date(format: "iso")` displays as `"2025-12-31T20:30:00"`; `iso` still
omits the output offset and microseconds. Genuinely timezone-less text keeps
its written wall clock but now attaches Django's active timezone for absolute
and relative formats, regardless of `USE_TZ`. With a UTC default and Madrid
active in July, `"2026-07-10 14:30"` yields `"14:30 +0200"` for
`@date(format: "HH:mm ZZ")`; its `iso` output still hides the offset. Relative
wording may change because the comparison uses that active-zone wall clock.
Numeric-offset/Z text retains its previous relative behavior; named UTC/GMT
and unknown timezone names keep their prior handling and warnings. A
time-only value still inherits the parser's current date, not necessarily
the active-zone date around midnight.

Clock-adjacent `+00:00` and `+0000` are explicit offsets for absolute formats:
`"2026-01-10T00:30:00+0000"` displays as `"2026-01-09T19:30:00"` in
`America/New_York` with `format: "iso"`, matching the equivalent `Z` text.

If `publishedAt` is nullable and the resolver returns `null`, the formatted
response still contains `"publishedAt": null`. Applying `@date` does not
manufacture a date or an invalid-format placeholder. Declare a date field
non-null only when its resolver always supplies a value; otherwise GraphQL
reports the nullability violation and bubbles null to the nearest nullable
parent.

=== "Format Dates"

    ```graphql
    query GetPostDates {
      post(id: "1") {
        title
        createdAt @date(format: "MMMM DD, YYYY")
        publishedAt @date(format: "DD/MM/YYYY HH:mm")
        updatedAt @date(format: "iso")
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "post": {
          "title": "Getting Started with GraphQL and Django",
          "createdAt": "December 01, 2023",
          "publishedAt": "01/12/2023 14:30",
          "updatedAt": "2023-12-01T14:30:00"
        }
      }
    }
    ```

    !!! note "ISO format"
        `@date(format: "iso")` outputs the real ISO 8601 format
        (`%Y-%m-%dT%H:%M:%S` — e.g. `"2023-12-01T14:30:00"`). Prior to v1.2.1
        the output incorrectly used `%Y-%b-%dT%H:%M:%S` (abbreviated month name
        such as `"2023-Dec-01T14:30:00"`), which is not valid ISO 8601.

