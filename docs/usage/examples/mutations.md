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

There is no `Upload` scalar. A file column is published as `String`, and the
file itself rides in the `multipart/form-data` body as a part named after the
field — either the camelCase alias the SDL publishes or the model's snake_case
attribute, both match — see
[Automatic multipart uploads](../mutations.md#automatic-multipart-uploads).

The part can only address a field on the model the mutation is bound to, so an
avatar living on a nested `Profile` is **not** reachable this way. Update the
child through its own mutation:

=== "Update User Avatar"

    ```graphql
    # POST multipart/form-data
    #   part "operations": this document plus its variables
    #   part "avatar":     the image bytes
    mutation UpdateProfileAvatar($profileId: ID!) {
      updateProfile(newProfile: {id: $profileId}) {
        ok
        profile {
          id
          avatar
        }
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Nested, via base64"

    ```graphql
    # Base64FileInput travels inside the GraphQL variables, so it nests.
    # It is opt-in: see Mutations -> File upload support.
    mutation UpdateUserAvatar($userId: ID!, $avatar: Base64FileInput!) {
      updateUser(newUser: {id: $userId, profile: {avatar: $avatar}}) {
        ok
        user {
          id
          username
          profile {
            avatar
          }
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

