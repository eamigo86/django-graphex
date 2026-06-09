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

### Number Formatting

=== "Format View Count"

    ```graphql
    query GetPostStats {
      posts(filter: { status: { exact: "published" } }) {
        id
        title
        viewCount @number(as: ",.0f")
        createdAt @date(format: "YYYY-MM-DD")
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "posts": [
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
        ]
      }
    }
    ```

### Date Formatting

=== "Format Dates"

    ```graphql
    query GetPostDates {
      post(id: "1") {
        title
        createdAt @date(format: "MMMM DD, YYYY")
        publishedAt @date(format: "DD/MM/YYYY HH:mm")
        updatedAt @date(format: "time ago")
      }
    }
    ```

