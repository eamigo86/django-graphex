# Frontend Integration Examples

> **Illustrative tutorial** — the models here (`Post`, `Category`, `Tag`, `UserProfile`) are a self-contained example used throughout these docs. For a complete, runnable project see [`examples/playground/`](../../../../examples/playground/) in the repo.

### React with Apollo Client

=== "Posts List Component"

    ```javascript
    import React, { useState } from 'react';
    import { gql, useQuery } from '@apollo/client';

    const GET_POSTS = gql`
      query GetPosts(
        $limit: Int!,
        $offset: Int!,
        $category: String,
        $status: String
      ) {
        allPosts(filter: {
          category: { name: { exact: $category } }
          status: { exact: $status }
        }) {
          results(
            limit: $limit,
            offset: $offset,
            ordering: "-published_at"
          ) {
            id
            title
            excerpt
            publishedAt @date(format: "MMMM DD, YYYY")
            viewCount @number(as: ",.0f")
            author {
              username
              profile {
                avatar
              }
            }
            category {
              name
              slug
            }
            tags {
              name
              color
            }
          }
          totalCount
        }
      }
    `;

    function PostsList() {
      const [filters, setFilters] = useState({
        search: '',
        category: '',
        status: 'published'
      });
      const [pagination, setPagination] = useState({
        page: 0,
        limit: 10
      });

      const { loading, error, data, refetch } = useQuery(GET_POSTS, {
        variables: {
          ...filters,
          limit: pagination.limit,
          offset: pagination.page * pagination.limit
        }
      });

      const handleSearch = (searchTerm) => {
        setFilters(prev => ({ ...prev, search: searchTerm }));
        setPagination(prev => ({ ...prev, page: 0 }));
      };

      const handlePageChange = (newPage) => {
        setPagination(prev => ({ ...prev, page: newPage }));
      };

      if (loading) return <div>Loading posts...</div>;
      if (error) return <div>Error: {error.message}</div>;

      const posts = data?.allPosts?.results || [];
      const totalCount = data?.allPosts?.totalCount || 0;
      const totalPages = Math.ceil(totalCount / pagination.limit);

      return (
        <div className="posts-list">
          {/* Search and Filters */}
          <div className="filters">
            <input
              type="text"
              placeholder="Search posts..."
              value={filters.search}
              onChange={(e) => handleSearch(e.target.value)}
            />
            <select
              value={filters.category}
              onChange={(e) => setFilters(prev => ({
                ...prev,
                category: e.target.value
              }))}
            >
              <option value="">All Categories</option>
              <option value="Technology">Technology</option>
              <option value="Design">Design</option>
            </select>
          </div>

          {/* Posts Grid */}
          <div className="posts-grid">
            {posts.map(post => (
              <article key={post.id} className="post-card">
                <h2>{post.title}</h2>
                <p>{post.excerpt}</p>
                <div className="post-meta">
                  <span>By {post.author.username}</span>
                  <span>{post.publishedAt}</span>
                  <span>{post.viewCount} views</span>
                </div>
                <div className="post-tags">
                  {post.tags.map(tag => (
                    <span
                      key={tag.name}
                      style={{ color: tag.color }}
                    >
                      #{tag.name}
                    </span>
                  ))}
                </div>
              </article>
            ))}
          </div>

          {/* Pagination */}
          <div className="pagination">
            <button
              disabled={pagination.page === 0}
              onClick={() => handlePageChange(pagination.page - 1)}
            >
              Previous
            </button>

            <span>
              Page {pagination.page + 1} of {totalPages}
            </span>

            <button
              disabled={pagination.page >= totalPages - 1}
              onClick={() => handlePageChange(pagination.page + 1)}
            >
              Next
            </button>
          </div>
        </div>
      );
    }

    export default PostsList;
    ```

=== "Create Post Form"

    ```javascript
    import React, { useState } from 'react';
    import { gql, useMutation, useQuery } from '@apollo/client';

    const CREATE_POST = gql`
      mutation CreatePost($postData: PostCreateGenericType!) {
        createPost(newPost: $postData) {
          ok
          post {
            id
            title
            slug
            status
          }
          errors {
            field
            messages
          }
        }
      }
    `;

    const GET_CATEGORIES_AND_TAGS = gql`
      query GetCategoriesAndTags {
        categories {
          id
          name
        }
        tags {
          id
          name
          color
        }
      }
    `;

    function CreatePostForm() {
      const [formData, setFormData] = useState({
        title: '',
        slug: '',
        content: '',
        excerpt: '',
        status: 'draft',
        category: '',
        tags: []
      });

      const { data: optionsData } = useQuery(GET_CATEGORIES_AND_TAGS);
      const [createPost, { loading, error }] = useMutation(CREATE_POST);

      const handleSubmit = async (e) => {
        e.preventDefault();

        try {
          const result = await createPost({
            variables: { postData: formData }
          });

          if (result.data.createPost.ok) {
            alert('Post created successfully!');
            // Reset form or redirect
          } else {
            // Handle validation errors
            console.error('Validation errors:', result.data.createPost.errors);
          }
        } catch (err) {
          console.error('Mutation error:', err);
        }
      };

      return (
        <form onSubmit={handleSubmit} className="create-post-form">
          <div className="form-group">
            <label>Title</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData(prev => ({
                ...prev,
                title: e.target.value,
                slug: e.target.value.toLowerCase().replace(/\s+/g, '-')
              }))}
              required
            />
          </div>

          <div className="form-group">
            <label>Slug</label>
            <input
              type="text"
              value={formData.slug}
              onChange={(e) => setFormData(prev => ({
                ...prev,
                slug: e.target.value
              }))}
              required
            />
          </div>

          <div className="form-group">
            <label>Content</label>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData(prev => ({
                ...prev,
                content: e.target.value
              }))}
              rows={10}
              required
            />
          </div>

          <div className="form-group">
            <label>Category</label>
            <select
              value={formData.category}
              onChange={(e) => setFormData(prev => ({
                ...prev,
                category: e.target.value
              }))}
              required
            >
              <option value="">Select Category</option>
              {optionsData?.categories?.map(category => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Status</label>
            <select
              value={formData.status}
              onChange={(e) => setFormData(prev => ({
                ...prev,
                status: e.target.value
              }))}
            >
              <option value="draft">Draft</option>
              <option value="published">Published</option>
            </select>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="submit-button"
          >
            {loading ? 'Creating...' : 'Create Post'}
          </button>

          {error && (
            <div className="error-message">
              Error: {error.message}
            </div>
          )}
        </form>
      );
    }

    export default CreatePostForm;
    ```

