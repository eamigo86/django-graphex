# Mutation Examples

These examples build on the schema from
[Sample Application](blog-schema.md): creating and updating records, file
uploads and error handling. For a complete runnable project see
`examples/playground/` in the repo.

### Creating Records

#### Create User with Profile

=== "Mutation"

    ```graphql
    mutation CreateUserWithProfile($userData: UserCreateGenericType!) {
      createUser(newUser: $userData) {
        ok
        user {
          id
          username
          email
          firstName
          lastName
          profile {
            bio
            location
            website
          }
        }
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Variables"

    ```json
    {
      "userData": {
        "username": "newuser123",
        "email": "newuser@example.com",
        "firstName": "Jane",
        "lastName": "Smith",
        "password": "securePassword123",
        "profile": {
          "bio": "I'm a web developer passionate about modern technologies",
          "location": "New York, NY",
          "website": "https://janesmith.dev"
        }
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "createUser": {
          "ok": true,
          "user": {
            "id": "42",
            "username": "newuser123",
            "email": "newuser@example.com",
            "firstName": "Jane",
            "lastName": "Smith",
            "profile": {
              "bio": "I'm a web developer passionate about modern technologies",
              "location": "New York, NY",
              "website": "https://janesmith.dev"
            }
          },
          "errors": []
        }
      }
    }
    ```

#### Create Post

=== "Mutation"

    ```graphql
    mutation CreatePost($postData: PostCreateGenericType!) {
      createPost(newPost: $postData) {
        ok
        post {
          id
          title
          slug
          content
          status
          author {
            username
          }
          category {
            name
          }
          tags {
            results { name }
          }
        }
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Variables"

    ```json
    {
      "postData": {
        "title": "Advanced GraphQL Techniques",
        "slug": "advanced-graphql-techniques",
        "content": "In this post, we'll explore advanced GraphQL patterns...",
        "excerpt": "Learn advanced GraphQL patterns and best practices",
        "status": "DRAFT",
        "category": "1",
        "tags": ["1", "2", "3"]
      }
    }
    ```

=== "Response"

    ```json
    {
      "data": {
        "createPost": {
          "ok": true,
          "post": {
            "id": "7",
            "title": "Advanced GraphQL Techniques",
            "slug": "advanced-graphql-techniques",
            "content": "In this post, we'll explore advanced GraphQL patterns...",
            "status": "DRAFT",
            "author": { "username": "admin" },
            "category": { "name": "Technology" },
            "tags": { "results": [{ "name": "graphql" }, { "name": "django" }, { "name": "api" }] }
          },
          "errors": []
        }
      }
    }
    ```

### Updating Records

=== "Update Post"

    ```graphql
    mutation UpdatePost($postData: PostUpdateGenericType!) {
      updatePost(newPost: $postData) {
        ok
        post {
          id
          title
          content
          status
          updatedAt
        }
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Variables"

    ```json
    {
      "postData": {
        "id": "1",
        "title": "Advanced GraphQL Techniques - Updated",
        "content": "Updated content with new examples...",
        "status": "PUBLISHED"
      }
    }
    ```

### File Uploads

=== "Update User Avatar"

    ```graphql
    mutation UpdateUserAvatar($userId: ID!, $avatar: Upload!) {
      updateUser(newUser: {id: $userId, profile: {avatar: $avatar}}) {
        ok
        user {
          id
          username
          profile {
            avatar
          }
        }
        errors {
          field
          messages
        }
      }
    }
    ```

### Error Handling

=== "Validation Error Example"

    ```json
    {
      "data": {
        "createPost": {
          "ok": false,
          "post": null,
          "errors": [
            {
              "field": "title",
              "messages": ["This field is required."]
            },
            {
              "field": "slug",
              "messages": ["Post with this slug already exists."]
            },
            {
              "field": "category",
              "messages": ["This field is required."]
            }
          ]
        }
      }
    }
    ```

