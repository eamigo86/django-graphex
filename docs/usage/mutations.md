# Mutations

GraphQL mutations allow you to modify data on your server. `django-graphex` provides powerful tools to create mutations from Django models, making CRUD operations simple and consistent.

## DjangoModelMutation

The `DjangoModelMutation` is the cornerstone of mutations in `django-graphex`. It automatically generates Create, Read, Update, and Delete (CRUD) operations directly from a Django model.

### Features

- :material-auto-fix: **Automatic CRUD Operations**: Generates create, update, and delete mutations
- :material-check-circle: **Built-in Validation**: Validates all writable model fields, FK existence, uniqueness, and `unique_together` constraints
- :material-file-upload: **File Upload Support**: Handles multipart/form-data requests
- :material-link-variant: **Nested Relationships**: Supports nested field creation and updates
- :material-alert-circle: **Error Handling**: Returns structured error responses

### Basic Usage

=== "Define Your Mutation"

    ```python
    from django.contrib.auth.models import User
    from django_graphex.mutation import DjangoModelMutation

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            description = "User mutations: create, update, delete"
    ```

=== "Add to Schema"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        # Get all mutation fields (create, update, delete)
        user_create, user_delete, user_update = UserMutation.MutationFields()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "Alternative Schema Setup"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        # Individual mutation fields
        create_user = UserMutation.CreateField()
        update_user = UserMutation.UpdateField()
        delete_user = UserMutation.DeleteField()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

!!! tip "Deprecating a mutation field"
    Every mutation-field builder (`CreateField`, `UpdateField`, `DeleteField`,
    and `MutationFields`) accepts `deprecation_reason=`, wired straight into the
    compiled field so the SDL renders `@deprecated(reason: ...)`:

    ```python
    class Mutation(ObjectType):
        create_user = UserMutation.CreateField(
            deprecation_reason="Use `createUserV2` instead; will be removed in 3.0."
        )
    ```

### Configuration Options

The `DjangoModelMutation` supports several configuration options:

#### Meta Configuration

```python
from django.contrib.auth.models import User
from .models import Address, Profile

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        only_fields = ('username', 'email', 'first_name', 'last_name')
        exclude_fields = ('password',)
        input_field_name = 'user_data'  # Default: 'new_{model_name}'
        output_field_name = 'user'      # Default: '{model_name}'
        description = "Custom description for the mutation"
        # map each nested field to its related Django model
        nested_fields = {'profile': Profile, 'addresses': Address}
```

#### Field Filtering

!!! tip "Field Control"
    Use `only_fields` to include specific fields, or `exclude_fields` to exclude certain fields from mutations.

=== "Include Specific Fields"

    ```python
    from django.contrib.auth.models import User

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            only_fields = ('username', 'email', 'first_name', 'last_name')
    ```

=== "Exclude Fields"

    ```python
    from django.contrib.auth.models import User

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('password', 'is_staff', 'is_superuser')
    ```

#### `editable=False` fields are never input

A model field declared `editable=False` is server-managed, so it is left out of
the generated create and update inputs — you do not have to list it in
`exclude_fields`. This covers relations too: a `created_by` / `tenant`
`ForeignKey` or `OneToOneField` set inside `save()` no longer advertises itself
as writable.

```python
class Document(models.Model):
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, editable=False)
```

```graphql
input DocumentCreateGenericType {
  title: String!
  # no "owner" — the server owns it
}
```

!!! warning "Known gap"
    A non-editable `ManyToManyField` still appears in the input, now as a raw
    list of primary keys rather than `[ID!]`. List it in `exclude_fields` if
    you need it gone today.

### Custom Arguments with `Field`

You can add custom arguments to your mutations. Declare them in a nested
`class Arguments` with the unified `Field` descriptor — the same descriptor
used in output position — or one of the typed shortcuts (`BooleanField`,
`CharField`, `IntField`, …) for a bare scalar:

```python
from django.contrib.auth.models import User
from django_graphex.core import BooleanField
from django_graphex.mutation import DjangoModelMutation

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    class Arguments:
        send_email = BooleanField(
            default=False,
            description="Send welcome email after user creation",
        )

    @classmethod
    def create(cls, root, info, **kwargs):
        send_email = kwargs.pop('send_email', False)
        response = super().create(root, info, **kwargs)
        if response.ok and send_email:
            send_welcome_email(getattr(response, cls._meta.output_field_name).email)
        return response
```

!!! info "`class Arguments` may inherit"

    Shared arguments can be factored into a base class; the compiler walks the
    whole MRO, so inherited attributes are compiled alongside the ones declared
    in the class body and the most-derived declaration wins on a name clash.

    ```python
    class TenantArgs:
        tenant = CharField(required=True)

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User

        class Arguments(TenantArgs):
            send_email = BooleanField(default=False)
    # compiles to: userMutation(tenant: String!, sendEmail: Boolean, ...)
    ```

### Nested Fields Support

Handle related models with nested fields:

```python
from django.contrib.auth.models import User
from .models import Address, Profile

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        # each nested field maps to its related Django model
        nested_fields = {'profile': Profile, 'addresses': Address}
```

!!! info "Nested Fields Behavior"
    - For single objects: The created object's ID is assigned to the field
    - For lists: Objects are added to the many-to-many relationship

### Row scoping: `get_queryset` / `filter_queryset`

`update` and `delete` resolve their target row through the same two hooks
`DjangoModelType` uses, with the same names and signatures, so an override
moves between the two hosts unchanged:

```python
from django_graphex.mutation import DjangoModelMutation

class DocumentMutation(DjangoModelMutation):
    class Meta:
        model = Document

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        return qs.filter(tenant=info.context.user.tenant)
```

A row outside the scope answers exactly as a missing one (`ok: false`,
`<Model> with id <pk> does not exist.`), so the response cannot be used to probe
which primary keys exist. `create` has no target row, so nothing is scoped there.

!!! warning "`permission_classes` is `DjangoModelType`-only"
    The two hosts are **not** symmetric on authorization. `permission_classes` /
    `authorize` — the per-action checks described under
    [Permissions](permissions.md) — are honored by `DjangoModelType` only.
    Declaring `permission_classes` on a `DjangoModelMutation` has **no effect**:
    the class never reads it. Reach for `DjangoModelType` when you need
    per-action authorization, or gate the mutation field at the schema root.

### Automatic multipart uploads

The mutation automatically handles file uploads when the request content type is `multipart/form-data`:

```python
from .models import Profile

# The mutation will automatically handle avatar uploads (ImageField on the model)
class ProfileMutation(DjangoModelMutation):
    class Meta:
        model = Profile
```

### Error Handling

All mutations return a consistent response structure:

```python
{
  "ok": Boolean,           # True if successful, False if errors
  "errors": [ErrorType],   # List of validation errors
  "{model_name}": Object   # The created/updated/deleted object (null if errors)
}
```

Example error response:

```json
{
  "data": {
    "createUser": {
      "ok": false,
      "errors": [
        {
          "field": "email",
          "messages": ["This field is required."]
        },
        {
          "field": "username",
          "messages": ["A user with that username already exists."]
        }
      ],
      "user": null
    }
  }
}
```

!!! tip "FK existence check runs only on the failure path"
    A valid mutation issues a single `INSERT`/`UPDATE` — the per-FK `SELECT 1`
    existence pre-check is **not** run on the happy path. If the write raises an
    `IntegrityError` (e.g. a bad FK pk), the same diagnostics that used to run
    eagerly now run **after** the failure to attribute the exact field, so a bad
    FK still returns the identical structured `errors[]` envelope. Nested writes
    (`Meta.nested_fields`) similarly open a `transaction.atomic()` savepoint
    **only when nested child work is actually present** — a plain, parent-only
    create/update pays no savepoint overhead. Both changes are purely
    performance-oriented: the observable response shape is unchanged.

### Custom Mutation Logic

Override methods to add custom logic:

=== "Custom Save Logic"

    Override `create` / `update` and call `super()` to run logic around the save
    (there is no separate `save` hook — validation and persistence happen inside
    `create`/`update`):

    ```python
    from django.contrib.auth.models import User
    from django_graphex.mutation import DjangoModelMutation

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User

        @classmethod
        def create(cls, root, info, **kwargs):
            response = super().create(root, info, **kwargs)
            # Custom logic after a successful save
            if response.ok:
                send_welcome_email(getattr(response, cls._meta.output_field_name).email)
            return response
    ```

### Complete Example

Here's a complete example showing all features:

=== "models.py"

    ```python
    from django.db import models
    from django.contrib.auth.models import User

    class Profile(models.Model):
        user = models.OneToOneField(User, on_delete=models.CASCADE)
        bio = models.TextField(blank=True)
        avatar = models.ImageField(upload_to='avatars/', blank=True)
        birth_date = models.DateField(null=True, blank=True)

    class Address(models.Model):
        user = models.ForeignKey(User, on_delete=models.CASCADE)
        street = models.CharField(max_length=255)
        city = models.CharField(max_length=100)
        country = models.CharField(max_length=100)
    ```

=== "mutations.py"

    ```python
    from django.contrib.auth.models import User
    from django_graphex.core import BooleanField
    from django_graphex.mutation import DjangoModelMutation
    from .models import Address, Profile

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('is_staff', 'is_superuser')
            nested_fields = {'profile': Profile, 'addresses': Address}

        class Arguments:
            send_welcome_email = BooleanField(default=True)
    ```

=== "schema.py"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        create_user, delete_user, update_user = UserMutation.MutationFields()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "GraphQL client"

    ```graphql
    mutation CreateUser($userData: NewUser!, $sendEmail: Boolean) {
      createUser(newUser: $userData, sendWelcomeEmail: $sendEmail) {
        ok
        user {
          id
          username
          email
          profile {
            bio
            avatar
          }
          addresses {
            totalCount
            results { street city country }
          }
        }
        errors { field messages }
      }
    }
    ```

=== "Variables"

    ```json
    {
      "userData": {
        "username": "jane_doe",
        "email": "jane@example.com",
        "firstName": "Jane",
        "lastName": "Doe",
        "profile": {
          "bio": "Django + GraphQL enthusiast",
          "birthDate": "1990-06-15"
        },
        "addresses": [
          { "street": "123 Main St", "city": "Springfield", "country": "US" }
        ]
      },
      "sendEmail": true
    }
    ```

### How nested writes work

`nested_fields = {field_name: RelatedModel}` lets a single create/update write
related objects alongside the parent. The same engine backs both
`DjangoModelMutation` and `DjangoModelType`.

- **Atomic** — the whole operation runs in a `transaction.atomic()` block. If the
  parent *or* any child fails validation, **everything rolls back** (no orphan
  rows) and the response is `ok: false` with the errors.
- **Relation-aware** — the relation is introspected from the model:

    | Relation | Order | Behavior |
    |---|---|---|
    | Forward `ForeignKey` / `OneToOneField` | child saved **first** | its pk is set on the parent |
    | Reverse FK / reverse `OneToOne` | parent **first** | each child is linked to the parent |
    | `ManyToManyField` (either side) | parent **first** | children are saved and `.add()`-ed |

- **Upsert** — a child payload that carries its `id` **updates** that row; without
  an `id` it creates a new one. (The nested input only exposes `id` on the
  parent's *update* input, so nested **creates** stay create-only.) On a
  relation whose rows the parent does not own this is narrowed by the link rule
  below.
- **Link, don't rewrite** — on a **forward** `ForeignKey` / `OneToOneField` or a
  `ManyToManyField`, a payload carrying an `id` the parent is **not already
  attached to** only **links** that row: it is set on the parent (or `.add()`-ed)
  and the payload's other fields are **ignored**. The row the parent is already
  attached to is still updated in place, which is the documented use — *change
  the category attached to this document*, not *edit any row of the category
  table*. Without the rule, `{ id: <mine>, category: { id: <any pk>, name: "x" } }`
  rewrote a shared lookup row that no scope hid and no ownership guard covered.
- **Child validation** — a nested child is validated with the **same** rules as
  its own mutation: when a `DjangoModelType` / `DjangoModelMutation` for the
  child model declares inline `validate_<field>` / `validate` methods or a
  `Meta.pydantic_model`, the nested write runs them too. (When more than one
  host declares validation for the same model, the last one defined wins.)
- **Child projection** — the nested child input is derived from the child's own
  hosts: `only_fields` / `exclude_fields` on a `DjangoModelType` /
  `DjangoModelMutation` for the child model apply to the parent's nested payload
  too. The two axes are merged differently, because they say different things.

    An `exclude_fields` is a **prohibition** — *this column is never
    client-writable* — so every declared host's exclusions are **unioned**,
    whether or not that host serves the operation being built, and they are
    applied **last**. Otherwise a create-only mutation's exclusion would vanish
    from the nested *update* surface, and a client would write, on an existing
    row through the parent, a column the project's own write mutation refuses.

    An `only_fields` is a positive **allowance**, so only the hosts that **serve
    the operation** union theirs: the result is what some declared host would
    permit, and it is meaningful only for that operation (a host declaring
    `model_operations = ("update",)` does not narrow the nested *create*, just
    as it does not narrow the child's own). Splitting the read and write
    surfaces — a display card projecting `("id", "slug")` and a write mutation
    projecting `("name",)` — is an ordinary configuration, not a contradiction,
    and both columns reach the nested input.

    No allowance restriction is applied when that union comes out **empty**, and
    there are exactly two ways to get there. The child may have **no declared
    host at all** — the ordinary `nested_fields` case, where it is a plain
    related model — and then the nested input is the unprojected surface minus
    the prohibitions, which is what the library has always built. Or the child's
    hosts may all have declared, through `Meta.model_operations`, that they do
    not serve this operation; both host classes default that option to **every**
    operation they can generate, so the branch cannot be reached without the
    project saying so.

    The primary key is **not** subject to either axis on the *update* surface.
    It is not a projectable column there — it is how the row is identified — so
    a write host projecting `only_fields = ("headline",)` still leaves `id` on
    the nested update input and the documented upsert-by-id keeps working.

    A projection whose every allowed column is excluded by a sibling would leave
    the nested input with **no field at all**, which graphql-core does not
    consider a legal schema. That is refused at build time with an
    `ImproperlyConfigured` naming the child model, the parent, and every
    contributing host with both of its projection axes — shipping a schema whose
    every request fails validation is worse than a build error. Widen one of the
    two declarations, or mark the read host with
    `model_operations = ("list", "retrieve")` so its allowance leaves the write
    path.

    Declare every host for a model **before** the first schema build:
    graphql-core caches an input object's field map, so a projection (or a
    `required_perms`) declared afterwards can never reach an already-built
    nested surface, and the library refuses it rather than ignore it. A late
    host that merely repeats a declaration already contributing is accepted:
    the merge is idempotent, so refusing a no-op would buy nothing.
- **Child permissions** — a nested create or update runs the child's own
  `permission_classes` / `authorize`, exactly as the child's own mutation does.
  A denial is the same `PERMISSION_DENIED` / HTTP 403 the direct mutation
  returns, and it rolls the **whole** write back — parent included, no orphan
  rows. Every `DjangoModelType` / `DjangoModelMutation` declared for the child
  model is consulted, so two hosts for one model fail **closed**: all of them
  must allow the write. A `DjangoModelMutation` has no `permission_classes` at
  all, so a `DjangoModelMutation`-only child gets the scoping below and nothing
  else.

    The hosts are read from the **parent's registry unioned with the global
    one**. `Meta.registry` is an option on `DjangoModelMutation` only, so a
    child's `permission_classes` can only ever live in the global registry;
    reading the parent's registry alone left a parent declared with
    `Meta.registry` finding no hosts for its children and the gate went silent.
    A host bound to a *non-global* registry still describes that schema's
    surface alone and cannot reach another registry's parents.
- **Child scoping** — a nested upsert naming a pk resolves it through the
  `get_queryset` / `filter_queryset` (and `Meta.queryset`) of the child hosts
  that **serve the write**, so it mirrors what those hosts' own `update` /
  `delete` do. A row they hide is a clean *not found*, never a silent update of
  the hidden row nor a create at that key — and it is the same *not found*
  whether or not the hidden row happens to belong to another parent, so the
  answer never confirms that a row you cannot see exists.

    Which hosts serve a write follows from `Meta.model_operations`, and **both**
    host classes take it: a mutation narrowed to `model_operations =
    ("create",)` has no `update` to mirror, so its scope is never applied to a
    nested update, and a `DjangoModelType` declaring
    `model_operations = ("list", "retrieve")` is a read host whose
    `Meta.queryset` leaves the nested write path entirely. That option is the
    remedy to reach for before narrowing `Meta.queryset` on a display type
    (hiding archived or unpublished rows): without it, that display default also
    stops the parent updating those children inline, because the type's own
    `update` and `delete` apply the same scope.
- **Additive & safe** — M2M/reverse children are only added, never removed; an
  empty `[]` / `{}` payload is a no-op (the relation is left untouched).
- **Errors are prefixed** — a child error is reported as `field.subfield`
  (e.g. `addresses.zip_code`).
- **M2M pk validation** — when M2M pks are passed directly to the top-level
  mutation (not via `nested_fields`), non-existent pks are caught *before* the
  DB write and returned as a structured `ErrorType` (field name + message),
  never as an `IntegrityError` 500.
- **To-one list guard** — supplying a list to a forward `ForeignKey` /
  `OneToOneField` nested field raises a clean error if the list contains more
  than one item. A single-element list is accepted as a convenience.
- **Reverse-O2O list guard** — supplying a list of more than one item to a
  reverse `OneToOneField` nested field raises a clean error instead of hitting
  the DB UNIQUE constraint.
- **Reverse ownership guard** — upsert of a reverse child by pk is rejected if
  that child currently belongs to a *different* parent. This prevents a client
  from silently re-parenting (stealing) rows owned by another object. The error
  message is `"Object <pk> does not belong to this <Model>."`. The guard covers
  **both** reverse kinds — reverse `ForeignKey` **and** reverse
  `OneToOneField` — identically, so the two are indistinguishable to a client.
  It does **not** apply to forward `ForeignKey` / `OneToOneField` or to
  `ManyToManyField` children: those rows are not owned by the parent (many
  parents may legitimately point at the same one), so there is no owner to
  compare against. Those two relations are protected by the **link rule**
  above instead — the row is attached, never rewritten.

!!! warning "Reverse child re-parenting"
    Attempting to assign an existing reverse child (by pk) to a new parent via
    the nested write path will fail with a validation error if the child's FK or
    O2O key already points to a different parent. To genuinely re-parent a row,
    issue a direct update mutation on the child model instead.

!!! warning "Editing a forward FK / M2M row through the parent"
    A nested payload can only edit the forward-FK or M2M row the parent is
    **already** attached to. Naming a different row's `id` attaches it and
    **silently ignores** the rest of the payload — `ok` is still `true` and that
    row is unchanged. To edit a row the parent is not attached to yet, issue a
    mutation on the child model directly, or attach it first and edit it in a
    second call.

!!! info "The link paths are deliberately not gated"
    Attaching an existing row through a **forward** `ForeignKey` /
    `OneToOneField` or a `ManyToManyField` by pk (the **link rule** above) is
    not a write on the child, so it does not run the child's permissions or
    scoping. It is the same reachability the plain `category: ID` surface has
    always offered — a nested payload cannot do anything there that a plain id
    reference could not.

#### The nested child input type

Each nesting parent gets its **own** copy of the child's input, named
`<Child><Op>In<Parent>Type` (e.g. `CommentCreateInPostType`). It is never
registered as the child's canonical input, so declaring a parent that nests a
model can no longer change what that model's own mutation accepts, and the order
in which you declare the two makes no difference to either surface.

The one difference from the child's own input is the **back-reference foreign
key**. Inside a nested payload the parent does not exist yet (or is already
known), and the writer injects the key at save time, so the parent's own column
is optional on this copy:

```graphql
input CommentCreateGenericType {   # the child's own mutation
  post: ID!
  body: String!
}

input CommentCreateInPostType {    # the copy inside postCreate
  post: ID                         # injected by the writer
  body: String!
}
```

A child nested under two parents gets one copy per parent, each relaxing its
*own* foreign key and nothing else. The child's Pydantic validation model still
requires the key, so a standalone create that genuinely omits it fails cleanly.

!!! note "Type names in client documents"
    Only a client document that spells the nested child input type name out (an
    explicit variable declaration, for instance) is affected by this naming.
    Field names and shapes are unchanged.

#### Writable only through its parent

The child's permission checks receive a `nested_parent` keyword argument: the
**parent model class** when the write arrives through a nested payload, and
nothing at all on the child's own mutation. That is enough to express *this
model may only be written inside its parent*:

```python
from django_graphex.permissions import BasePermission


class OnlyViaParent(BasePermission):
    """Allow creates only when they arrive through a nesting parent."""

    def has_create_permission(self, info, model, **kwargs):
        return kwargs.get("nested_parent") is not None
```

```python
class CommentType(DjangoModelType):
    permission_classes = (OnlyViaParent,)

    class Meta:
        model = Comment
```

`commentCreate` now answers `PERMISSION_DENIED`, while
`postCreate(newPost: { title: "...", comments: [{ body: "..." }] })` succeeds.

!!! note "Under a permission-scoped schema, don't mount the child's root"
    A `permission_classes` policy runs at **write** time; the
    [permission-scoped schema](permission-scoped-schema.md) prunes at **build**
    time and cannot evaluate one. It labels the `comments` field with the
    child's write permissions — and that is exactly right: the caller writing
    a comment through its post genuinely holds `add_comment`. What the hatch
    withholds is the child's **own** root, so simply leave `commentCreate`
    off your `Mutation`; a root that is never mounted gives the pruner nothing
    to prune, and the nested field survives for every caller who may write the
    child.

    `required_perms` on a child host can only **add** to the nested field's
    label, never replace it: the field always requires the child's composite
    write permissions, and the override of every host that **serves** one of
    the verbs the nested field enables is unioned on top. A write host's
    stricter label therefore genuinely reaches the nested surface, and a
    delete-only host's label stays off a nested *create*.

    It is an extra requirement, not a free one. A `DjangoModelType` serves every
    operation unless it says otherwise, so a read card labelled
    `required_perms = ["blog.read_comment_card"]` labels the nested field too,
    and a caller without that label loses `comments` from the parent's payload —
    even though another host's `commentCreate` still accepts the same write.
    That is fail-closed and matches what the label does to the card's *own*
    create/update roots, but if you meant the label as a read gate only, declare
    the card with `model_operations = ("list", "retrieve")`, or drop the label
    and gate reads with `permission_classes`.

!!! note "Permission checks with a closed signature"
    `nested_parent` is only passed to a check that can accept it. A policy or
    an `authorize` override that spells its arguments out
    (`def has_create_permission(self, info, model, data=None)`) keeps working —
    it simply never sees the marker, and therefore reads a nested write exactly
    as it reads a direct one. Accept `**kwargs` to see it.

#### Worked examples — UPDATE + nested create and UPDATE + nested update (upsert)

=== "UPDATE + nested create"

    ```graphql
    # Add a brand-new address to an existing user (no `id` on the address payload
    # → creates a new Address row and links it to the user).
    mutation {
      updateUser(newUser: {
        id: "1"
        addresses: [
          { street: "456 Oak Ave", city: "Shelbyville", country: "US" }
        ]
      }) {
        ok
        user {
          addresses {
            results { id street city country }
            totalCount
          }
        }
        errors { field messages }
      }
    }
    ```

    The new address is **added** to the user's existing addresses (`M2M`/reverse-FK
    children use `.add()` semantics — existing links are kept). `totalCount` will
    increase by 1.

=== "UPDATE + nested update (upsert)"

    ```graphql
    # Update an existing address: include its `id` in the payload.
    # Without an id → creates; with an id → updates that row in place.
    mutation {
      updateUser(newUser: {
        id: "1"
        addresses: [
          { id: "3", street: "789 Elm St", city: "Springfield", country: "US" }
        ]
      }) {
        ok
        user {
          addresses {
            results { id street city country }
          }
        }
        errors { field messages }
      }
    }
    ```

    A child payload **with `id`** updates that existing row. A child payload
    **without `id`** creates a new one. Both can appear in the same `addresses`
    list in a single mutation call.

!!! tip "Removing M2M/reverse-FK children"
    Nested writes are **additive only** (`.add()` — existing links are kept).
    To remove links, issue a separate mutation that targets the child directly or
    override the top-level mutation. See
    [M2M write semantics](#m2m-write-semantics-nested-path-vs-top-level-path) below.

!!! warning "Reverse-FK nested fields"

    For a **reverse** relation (the child holds the FK to the parent), the child's
    FK back to the parent is injected automatically at save time — you do not need
    to supply it in the mutation input. Use `exclude_fields` on the child's
    `DjangoModelMutation` (or `only_fields`) to keep it out of the input:

    ```python
    class PostMutation(DjangoModelMutation):
        class Meta:
            model = Post
            only_fields = ["id", "title", "body"]   # no "author": injected from parent
    ```

### M2M write semantics: nested path vs. top-level path

The two write paths use **different M2M semantics** — this is intentional and the two paths
are not yet unified:

| Write path | M2M operation | Effect |
|---|---|---|
| **Nested** (`nested_fields`) | `.add(*children)` | **Additive** — existing links are kept; the submitted items are appended. Submitting an empty list (or `null`) is a **no-op**. |
| **Top-level native backend** | `.set(pks)` | **Replace** — existing links are removed and replaced with exactly the submitted list. Submitting an empty list `[]` **or an explicit `null`** clears all links. Omitting the field entirely leaves the relation untouched. |

**Practical implication:** to *remove* M2M links via the nested path you currently cannot — use the
top-level mutation instead (send `tags: []` or `tags: null` to clear), or issue a separate mutation
that clears and re-adds.

!!! note "Not yet implemented as of v2.0"
    A per-field `m2m_behavior = "set" | "add"` option will let you choose the semantics on the
    nested path and align the default to `.set` (matching top-level behavior).

### Explicit-null semantics in update mutations

`update()` follows the GraphQL specification: **an omitted field is not the same as an explicit
`null`**. On a partial update:

| Input | Effect |
|---|---|
| Field **omitted** from the input | Value is **left unchanged** (partial-update semantics). |
| Field sent as **explicit `null`** (nullable field / FK) | Column is set to **`NULL`**. |
| Field sent as **explicit `null`** (required field) | A clean **validation error** (`ok: false`, `errors[]`) — never a 500. |
| M2M sent as `null` **or** `[]` (top-level path) | Relation is **cleared**. |
| M2M **omitted** (top-level path) | Relation is **left unchanged**. |

```graphql
# Clear the nullable ``bio`` field:
mutation {
  updateUser(newUser: { id: 1, bio: null }) {
    ok
    user { id bio }        # -> bio is now null
  }
}

# Leave ``bio`` untouched (it is simply omitted):
mutation {
  updateUser(newUser: { id: 1, firstName: "Ada" }) {
    ok
    user { id bio }        # -> bio unchanged
  }
}

# Clear an M2M (``tags: null`` is equivalent to ``tags: []``):
mutation {
  updatePost(newPost: { id: 1, tags: null }) {
    ok
    post { id }
  }
}
```

!!! warning "Nested inputs treat `null` as a no-op"
    Explicit-null semantics apply to **scalar fields, foreign keys, and the top-level
    (`ID`-list) M2M surface**. For **nested inputs** (`Meta.nested_fields`) a `null` / `[]` /
    `{}` payload is a deliberate **no-op** — the related children are left untouched, never
    deleted. Interpreting `null` as "delete every related child" would be dangerous and
    irreversible, so nested writes never clear on `null`. To remove nested children, target the
    child model directly.

### perform_mutate response shape

`DjangoModelMutation.perform_mutate` and `DjangoModelType.perform_mutate` intentionally differ in
how they produce the response object after a successful write:

| Class | Response object | Optimizer applied? | Extra DB query? |
|---|---|---|---|
| `DjangoModelType` | Re-reads via `get_queryset()` — picks up DB defaults, signals, annotations | Yes — the re-read passes through `queryset_factory` so `select_related` / `prefetch_related` / `.only()` are derived from the mutation's response selection | Yes (one re-read) |
| `DjangoModelMutation` | Returns the **in-memory** object that was just saved | No re-read, so no optimizer pass | No |

**Practical implication:** if your mutation response selects nested relations
(e.g. `user { profile { bio } }`), `DjangoModelType` will resolve them via the
re-read queryset — which the optimizer makes efficient. `DjangoModelMutation`
returns the in-memory object, so relations are resolved lazily (one per field),
unless you `refresh_from_db()` in a custom `perform_mutate`.

To avoid N+1 on `DjangoModelMutation` responses with nested relations, or when you
need DB defaults or signals to be reflected, override `perform_mutate`:

```python
class MyMutation(DjangoModelMutation):
    class Meta:
        model = MyModel

    @classmethod
    def perform_mutate(cls, obj, info):
        obj.refresh_from_db()
        return super().perform_mutate(obj, info)
```

## Mutation response: depth limits and optimizer

### `MAX_QUERY_DEPTH` and `Meta.max_depth` apply to mutations

Query depth limiting (`MAX_QUERY_DEPTH` global setting and `Meta.max_depth` per-type)
is enforced on **all** operation types — including mutation response selection sets.
The selection set validation runs before execution, so a mutation that requests
deeper nesting than the limit permits is rejected with a validation error before
any database writes occur.

```python
DJANGO_GRAPHEX = {
    "MAX_QUERY_DEPTH": 5,   # enforced on query, mutation, and subscription selection sets
}
```

The per-type attribute is `Meta.max_depth`; the global setting key is
`MAX_QUERY_DEPTH`:

```python
class UserModelType(DjangoModelType):
    class Meta:
        model = User
        max_depth = 3   # overrides the global MAX_QUERY_DEPTH for this type
```

See [Query depth & cost limits](query-limits.md) for the full reference.

## Traditional GraphQL Mutations

While `DjangoModelMutation` covers most use cases, you can still create traditional GraphQL mutations for custom logic:

=== "Traditional Mutation"

    ```python
    from django_graphex.core import BooleanField, CharField, Field, Mutation
    from django_graphex.types import DjangoObjectType
    from django.contrib.auth.models import User

    class UserType(DjangoObjectType):
        class Meta:
            model = User

    class CreateUser(Mutation):
        class Arguments:
            username = CharField(required=True)
            email = CharField(required=True)
            password = CharField(required=True)

        ok = BooleanField()
        user = Field(UserType)

        @staticmethod
        def mutate(root, info, username, email, password):
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            return CreateUser(ok=True, user=user)
    ```

=== "With Error Handling"

    ```python
    from django_graphex.core import BooleanField, CharField, Field, Mutation
    from django_graphex.errors import ErrorType
    # ErrorType is a native ObjectType (a Python class), so wrap it in the
    # lazy NativeList rather than graphql-core's GraphQLList.
    from django_graphex.core.descriptors import NativeList

    class CreateUser(Mutation):
        class Arguments:
            username = CharField(required=True)
            email = CharField(required=True)
            password = CharField(required=True)

        ok = BooleanField()
        user = Field(UserType)
        errors = Field(NativeList(ErrorType))

        @staticmethod
        def mutate(root, info, username, email, password):
            # Validation
            errors = []

            if User.objects.filter(username=username).exists():
                errors.append(ErrorType(
                    field="username",
                    messages=["Username already exists"]
                ))

            if User.objects.filter(email=email).exists():
                errors.append(ErrorType(
                    field="email",
                    messages=["Email already registered"]
                ))

            if errors:
                return CreateUser(ok=False, errors=errors, user=None)

            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            return CreateUser(ok=True, user=user, errors=None)
    ```

## Best Practices

!!! tip "Mutation Best Practices"

    1. **Use DjangoModelMutation**: Drive mutations from `Meta.model` for consistency
    2. **Validate Input**: Always validate input data before processing
    3. **Handle Errors Gracefully**: Provide clear, actionable error messages
    4. **Test Thoroughly**: Write tests for all mutation scenarios
    5. **Document Fields**: Use descriptions for all mutation fields and arguments
    6. **Security First**: Implement proper authentication and authorization

### Authentication & Permissions

```python
from graphql import GraphQLError
from django.contrib.auth.models import User
from django_graphex.mutation import DjangoModelMutation

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    @classmethod
    def create(cls, root, info, **kwargs):
        if not info.context.user.is_authenticated:
            raise GraphQLError("Authentication required")

        if not info.context.user.has_perm('auth.add_user'):
            raise GraphQLError("Permission denied")

        return super().create(root, info, **kwargs)
```

### Custom Validation

For field-level validation beyond automatic DB checks (inline `validate_<field>`
methods, object-level `validate()`, and `Meta.pydantic_model`), see the
authoritative reference:
[Model backend (Pydantic) — Custom validation](backends.md#custom-validation-inline-validate_field).

## Testing Mutations

=== "Basic Test"

    ```python
    import pytest
    from graphql import graphql_sync
    from .schema import schema   # a DjangoGraphQLSchema

    @pytest.mark.django_db
    def test_create_user_mutation():
        mutation = """
            mutation CreateUser($userData: UserInput!) {
                createUser(newUser: $userData) {
                    ok
                    user {
                        id
                        username
                        email
                    }
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        variables = {
            "userData": {
                "username": "testuser",
                "email": "test@example.com",
                "password": "secretpass123"
            }
        }

        result = graphql_sync(schema.graphql_schema, mutation, variable_values=variables)
        assert result.errors is None
        assert result.data['createUser']['ok'] is True
        assert result.data['createUser']['user']['username'] == 'testuser'
    ```

=== "Error Handling Test"

    ```python
    from graphql import graphql_sync

    @pytest.mark.django_db
    def test_create_user_validation_error():
        mutation = """
            mutation CreateUser($userData: UserInput!) {
                createUser(newUser: $userData) {
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        # Missing required email
        variables = {
            "userData": {
                "username": "testuser",
                "password": "secretpass123"
            }
        }

        result = graphql_sync(schema.graphql_schema, mutation, variable_values=variables)
        assert result.data['createUser']['ok'] is False
        assert len(result.data['createUser']['errors']) > 0
    ```

The mutation system in `django-graphex` provides a robust foundation for handling data modifications in your GraphQL API, with built-in validation, error handling, and support for complex operations.

---

## File Upload Support

### Base64FileInput

`django-graphex` ships an **opt-in** `Base64FileInput` for sending files through the GraphQL body as base64-encoded strings. Import it explicitly — it is not wired into `DjangoModelMutation` automatically.

```python
from django_graphex.uploads import Base64FileInput
from django_graphex.uploads import Base64FileInput, decode_base64_file
```

#### Shape

```graphql
input Base64FileInput {
  filename: String!           # Original filename (stored / used as the key by FileField)
  data: String!               # Base64-encoded file content
  contentType: String         # MIME type — defaults to "application/octet-stream"
}
```

#### Resolver usage

```python
from django_graphex.core import BooleanField, Field, Mutation
from django_graphex.core.base import compile_all_inputs
from django_graphex.uploads import Base64FileInput

# Compile the imported InputType subclasses before any Field(...) reads them.
# See the note below for why importing the module is not enough on its own.
compile_all_inputs()

class UploadAvatarMutation(Mutation):
    class Arguments:
        # Pass the input-object CLASS directly — no thunk boilerplate.
        avatar = Field(Base64FileInput, required=True)

    ok = BooleanField()

    @classmethod
    def mutate(cls, root, info, **kwargs):
        # The input object arrives as a dict (snake-cased keys); rehydrate it into a
        # Base64FileInput so .to_uploaded_file() is available.
        avatar = Base64FileInput(**kwargs["avatar"])
        # Pass max_size to override the global MAX_UPLOAD_SIZE for this field:
        uploaded = avatar.to_uploaded_file(max_size=512 * 1024)  # 512 KB cap
        profile = info.context.user.profile
        profile.avatar.save(uploaded.name, uploaded, save=True)
        return cls(ok=True)
```

The `avatar` argument arrives in the resolver as a plain `dict` of the input
fields; rehydrate it with `Base64FileInput(**kwargs["avatar"])` to get a validated
instance with `.filename`, `.data`, `.content_type` attributes **and** a
`.to_uploaded_file(*, max_size=None)` method that returns a `SimpleUploadedFile`.

!!! warning "Compile the input type before you declare the mutation"
    `Field(Base64FileInput, ...)` needs `Base64FileInput._meta.graphql_input_type`
    to be compiled **already** — it is read when `YourMutation.Field()` is
    evaluated in the surrounding `ObjectType` body, not lazily at schema-build
    time. If it is still `None`, that line raises:

    ```
    TypeError: Can only create a wrapper for a GraphQLType, but got:
    <class 'django_graphex.uploads.Base64FileInput'>
    ```

    `AppConfig.ready()` does call `compile_all_inputs()`, but it can only compile
    the `InputType` subclasses that have been **imported** by then — and the
    package never imports `django_graphex.uploads` itself. Listing
    `django_graphex` in `INSTALLED_APPS` is therefore *not* sufficient on its own.

    Do one of these:

    ```python
    # Option A — compile explicitly, right after the import. Works anywhere.
    from django_graphex.core.base import compile_all_inputs
    from django_graphex.uploads import Base64FileInput

    compile_all_inputs()
    ```

    ```python
    # Option B — import it from a module Django loads during app population
    # (e.g. your app's models.py), so AppConfig.ready() picks it up.
    from django_graphex.uploads import Base64FileInput  # noqa: F401
    ```

    The older `lambda: GraphQLArgument(GraphQLNonNull(...))` thunk still works as
    the low-level substrate, and defers the lookup to schema-build time.

You can also call the module-level helper directly if you hold the raw dict:

```python
from django_graphex.uploads import decode_base64_file

uploaded = decode_base64_file(
    {"filename": "report.pdf", "data": b64_string, "content_type": "application/pdf"},
    max_size=10 * 1024 * 1024,  # 10 MB override
)
```

#### GraphQL client example

```graphql
mutation UploadAvatar($file: Base64FileInput!) {
  uploadAvatar(avatar: $file) { ok }
}
```

Variables:
```json
{
  "file": {
    "filename": "photo.png",
    "contentType": "image/png",
    "data": "<base64 string>"
  }
}
```

### Settings

Add both settings to your `DJANGO_GRAPHEX` dict in `settings.py`:

```python
DJANGO_GRAPHEX = {
    # Required when Base64FileInput is used — raises ImproperlyConfigured if
    # absent and no per-field override is given.
    "MAX_UPLOAD_SIZE": 5 * 1024 * 1024,    # 5 MB per decoded file

    # Primary memory cap: the full JSON body is rejected BEFORE parsing when
    # this limit is exceeded. None = disabled (not recommended for public APIs).
    # Rule of thumb: ≥ base64_overhead × MAX_UPLOAD_SIZE × expected_files_per_request
    # (base64 encodes 3 bytes as 4 ASCII chars → overhead ≈ 4/3)
    "MAX_REQUEST_BODY_SIZE": 20 * 1024 * 1024,  # 20 MB total body
}
```

#### Per-field override

Pass `max_size` to `.to_uploaded_file()` or `decode_base64_file()` to use a tighter (or looser) cap for a specific field:

```python
avatar.to_uploaded_file(max_size=512 * 1024)         # 512 KB — tight avatar cap
document.to_uploaded_file(max_size=50 * 1024 * 1024) # 50 MB — loose document cap
```

Per-field `max_size` overrides the global `MAX_UPLOAD_SIZE` for that call only.

### Memory-safety architecture

> **Why two settings?**

The base64 payload lives inside the JSON body. By the time any field resolver sees it, the entire body is already in RAM. The guards compose as follows:

| Guard | Where it fires | What it saves |
|---|---|---|
| `MAX_REQUEST_BODY_SIZE` | `dispatch()` — BEFORE JSON parse | The entire body allocation |
| Per-field decoded-size pre-check | Inside `decode_base64_file` — BEFORE `base64.decode` | The decoded-bytes allocation |

**Peak memory** ≈ `body_size + MAX_UPLOAD_SIZE`.

For batch requests, `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE` (bytes) compose naturally: operations execute sequentially so peak decoded memory is bounded by one file's size, not the whole batch.

### Error handling

| Condition | Result |
|---|---|
| Body exceeds `MAX_REQUEST_BODY_SIZE` | HTTP 413 (before parsing) |
| Estimated decoded size > effective cap | `GraphQLError` (before decode) |
| Invalid / malformed base64 | `GraphQLError` (never HTTP 500) |
| `MAX_UPLOAD_SIZE` unset + no per-field override | `ImproperlyConfigured` at call time |

### Content validation

Magic-byte / MIME-type sniffing is **out of scope**. Use Django's `FileField` validators (e.g. `FileExtensionValidator`) or a custom model validator for content-type enforcement — that is the correct layer.

### Query cost

Input payload size is **not** accounted for in query-cost analysis (the `MAX_QUERY_COST` setting). The body-size guard (`MAX_REQUEST_BODY_SIZE`) is the canonical byte-level cap.

### Response caching

Upload mutations are not cached. The response-cache layer already skips `mutation` operations — no special configuration needed.

### Batch uploads

For batch requests:

- `MAX_REQUEST_BODY_SIZE` caps the total body of all operations combined.
- Per-field decoded-size pre-checks fire inside each operation's resolver.
- No special upload-batch rejection: rely on `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE` (bytes).

### REST side-channel alternative

For gateway-constrained environments (e.g. an API gateway with a 10 MB payload limit), the recommended alternative is a **REST side-channel**:

1. Upload the file directly to a presigned URL (S3, GCS, Azure Blob) or a separate `POST /upload/` endpoint.
2. Receive a file key or public URL in response.
3. Pass that reference as a plain `String` field in the GraphQL mutation.

This avoids base64 overhead (≈33% size increase) entirely and scales naturally with file size.
