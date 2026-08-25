# Query Examples

These examples build on the illustrative blog schema defined in
[Sample Application](blog-schema.md) — see `examples/playground/` in the repo for a
complete runnable project. They cover single objects, filtered lists,
pagination and complex filtering.

### Basic Object Queries

=== "Get Single Post"

    ```graphql
    query GetPost($id: ID!) {
      post(id: $id) {
        id
        title
        slug
        content
        status
        viewCount
        createdAt
        author {
          id
          username
          firstName
          lastName
          profile {
            bio
            avatar
            location
          }
        }
        category {
          id
          name
          slug
          description
        }
        tags {
          results {
            id
            name
            color
          }
        }
        comments {
          results {
            id
            content
            author {
              username
            }
            createdAt
            isApproved
            parent {
              id
              content
            }
          }
          totalCount
        }
      }
    }
    ```

    !!! tip "To-many relations are list types, not plain lists"
        `tags` and `comments` compile to `TagListType` / `CommentListType`, so
        the sub-selection goes through `results` (which itself accepts `limit`,
        `offset` and `ordering`) plus an optional `totalCount`. Only to-one
        relations — `author`, `category`, `profile`, `parent` — are selected
        directly.

=== "Response"

    ```json
    {
      "data": {
        "post": {
          "id": "1",
          "title": "Getting Started with GraphQL and Django",
          "slug": "getting-started-graphql-django",
          "content": "GraphQL is a powerful query language...",
          "status": "PUBLISHED",
          "viewCount": 1245,
          "createdAt": "2023-12-01T10:30:00",
          "author": {
            "id": "1",
            "username": "john_doe",
            "firstName": "John",
            "lastName": "Doe",
            "profile": {
              "bio": "Full-stack developer passionate about GraphQL",
              "avatar": "/media/avatars/john.jpg",
              "location": "San Francisco, CA"
            }
          },
          "category": {
            "id": "1",
            "name": "Technology",
            "slug": "technology",
            "description": "Latest in tech trends and tutorials"
          },
          "tags": {
            "results": [
              {
                "id": "1",
                "name": "GraphQL",
                "color": "#e10098"
              },
              {
                "id": "2",
                "name": "Django",
                "color": "#092e20"
              }
            ]
          },
          "comments": {
            "results": [
              {
                "id": "1",
                "content": "Great tutorial! Very helpful.",
                "author": {
                  "username": "reader1"
                },
                "createdAt": "2023-12-01T14:20:00",
                "isApproved": true,
                "parent": null
              }
            ],
            "totalCount": 1
          }
        }
      }
    }
    ```

### Filtered Lists

=== "Filter Posts by Category and Status"

    ```graphql
    query GetTechPosts {
      posts(filter: {
        status: { exact: PUBLISHED }
        category: { name: { exact: "Technology" } }
        createdAt: { gte: "2023-01-01" }
      }) {
        id
        title
        excerpt
        author {
          username
        }
        createdAt
        viewCount
      }
    }
    ```

=== "Search Posts"

    ```graphql
    query SearchPosts {
      allPosts(filter: { status: { exact: PUBLISHED } }) {
        results(limit: 10, ordering: "-view_count") {
          id
          title
          excerpt
          viewCount
          author {
            username
          }
          category {
            name
          }
        }
        totalCount
      }
    }
    ```

=== "Filter by Multiple Tags"

    ```graphql
    query GetPostsByTags {
      allPosts(filter: {
        # Relation filters nest into the related type's own filter input,
        # so the pk lookup lives under `id`, not directly on `tags`.
        tags: { id: { in: ["1", "3", "5"] } }   # GraphQL, React, Python
        status: { exact: PUBLISHED }
      }) {
        results(limit: 20) {
          id
          title
          tags {
            results {
              name
              color
            }
          }
        }
        totalCount
      }
    }
    ```

### Paginated Queries

=== "Limit/Offset Pagination"

    ```graphql
    query GetPostsPaginated($limit: Int!, $offset: Int!) {
      allPosts(filter: { status: { exact: PUBLISHED } }) {
        results(
          limit: $limit,
          offset: $offset,
          ordering: "-published_at"
        ) {
          id
          title
          excerpt
          publishedAt
          author {
            username
          }
          category {
            name
          }
          viewCount
        }
        totalCount
      }
    }
    ```

=== "Page-Based Pagination"

    ```graphql
    query GetUsersPage($page: Int!, $pageSize: Int) {
      allUsers(filter: { isActive: { exact: true } }) {
        results(page: $page, pageSize: $pageSize) {
          id
          username
          firstName
          lastName
          email
          dateJoined
          profile {
            location
            website
          }
        }
        totalCount
      }
    }
    ```

### Complex Filtering

=== "Advanced Post Search"

    ```graphql
    query AdvancedPostSearch(
      $categories: [ID!],
      $tags: [ID!],
      $authorName: String,
      $minViews: Int,
      $publishedAfter: DateTime,
      $publishedBefore: DateTime
    ) {
      allPosts(filter: {
        category: { id: { in: $categories } }
        tags: { id: { in: $tags } }
        author: { username: { icontains: $authorName } }
        viewCount: { gte: $minViews }
        publishedAt: { range: [$publishedAfter, $publishedBefore] }
        status: { exact: PUBLISHED }
      }) {
        results(limit: 20, ordering: "-published_at") {
          id
          title
          excerpt
          publishedAt
          viewCount
          author {
            username
            firstName
            lastName
          }
          category {
            name
            slug
          }
          tags {
            results {
              name
              color
            }
          }
        }
        totalCount
      }
    }
    ```

=== "Variables"

    ```json
    {
      "categories": ["1", "2"],
      "tags": ["1", "3"],
      "authorName": "john",
      "minViews": 100,
      "publishedAfter": "2023-01-01T00:00:00Z",
      "publishedBefore": "2023-12-31T23:59:59Z"
    }
    ```

