# SPEC — `pageInfo` for cursor pagination (`CursorGraphqlPagination`)

**Status:** APPROVED — implemented in `graphene-django-extras 1.2.0`.
**Scope:** `graphene_django_extras.paginations` + `DjangoListObjectType`.
**Target release:** `graphene-django-extras 1.2.0` (same line as the cursor work).
**Date:** 2026-06-06

---

## 1. Motivation

`CursorGraphqlPagination` (forward keyset) currently returns only `results` +
`totalCount`. To page forward the client must read the ordering field of the last
row and build the next cursor itself (`encode_cursor`). That is awkward and leaks
the cursor-construction detail to the client.

This SPEC adds an **opt-in** `pageInfo` field to a cursor-paginated
`DjangoListObjectType`, so the client reads `endCursor`/`hasNextPage` straight
from the response and never constructs a cursor by hand.

### Goals

- **G1** — Expose `pageInfo { hasNextPage, hasPreviousPage, startCursor, endCursor }`
  on cursor-paginated list types.
- **G2** — **Opt-in and non-breaking**: `pageInfo` appears **only** when the
  configured paginator is `CursorGraphqlPagination`. `LimitOffsetGraphqlPagination`
  and `PageGraphqlPagination` types are byte-for-byte unchanged.
- **G3** — The cursor stays opaque (`base64`), but the client gets it from
  `endCursor` rather than computing it.
- **G4** — Documented with runnable examples.

### Non-Goals

- **NG1** — Backward pagination (`last` / `before`); this stays forward-only keyset.
- **NG2** — Relay `edges { node cursor }` connections.
- **NG3** — Adding `pageInfo` to LimitOffset / Page paginators.

---

## 2. Schema shape (public API)

For a cursor-paginated list type the generated schema becomes:

```graphql
type CursorPageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

type ItemListType {
  results(first: Int, cursor: String): [ItemType]
  totalCount: Int
  pageInfo(first: Int, cursor: String): CursorPageInfo
}
```

`pageInfo` carries **the same arguments** as `results` (`first`, `cursor`). They
must be given the same values so both describe the same page; with GraphQL
variables they are written once:

```graphql
query Items($first: Int!, $cursor: String) {
  items {
    results(first: $first, cursor: $cursor) { id text }
    totalCount
    pageInfo(first: $first, cursor: $cursor) {
      endCursor
      hasNextPage
    }
  }
}
```

To fetch the next page the client sends the previous `pageInfo.endCursor` as
`$cursor`. (Passing the args to both fields is the cost of the existing
"arguments live on `results`" design; the Relay-style alternative — arguments at
the field level — was rejected for this iteration to keep the change non-breaking.)

---

## 3. Semantics (`CursorPageInfo`, forward keyset)

Let the page be the queryset ordered by `ordering`, filtered by the incoming
`cursor`, limited to `first` rows. With `field` = the ordering field and
`descending` derived from a leading `-`:

| Field | Value |
|-------|-------|
| `startCursor` | `encode_cursor(<ordering value of the FIRST row>)`, or `null` if the page is empty |
| `endCursor` | `encode_cursor(<ordering value of the LAST row>)`, or `null` if the page is empty |
| `hasNextPage` | `true` if at least one row exists **after** the last row of the page |
| `hasPreviousPage` | `true` if at least one row exists **before** the first row of the page |

`hasNextPage` is computed by fetching `first + 1` rows and checking whether the
extra row is present (one query, no extra `COUNT`).

`hasPreviousPage` is **exact**: it checks whether a row exists strictly before the
page's first row in the configured ordering — `qs.filter(<field> <lt|gt>
start_value).exists()` (the opposite direction of the cursor filter). This makes
the first page report `false` even if a spurious cursor is supplied, and is
correct at every boundary. It is one extra `EXISTS` query (no `COUNT`).

---

## 4. Design

### 4.1 `BaseDjangoGraphqlPagination`

Add a default hook returning "no page info field":

```python
def get_page_info_field(self, _type):
    """Return a `pageInfo` Field for this paginator, or None if unsupported."""
    return None
```

`LimitOffsetGraphqlPagination` / `PageGraphqlPagination` inherit the `None`
default → their list types gain no `pageInfo` field (G2).

### 4.2 `CursorGraphqlPagination`

- New `CursorPageInfo(graphene.ObjectType)` with the four fields in §3.
- `get_page_info_field(self, _type)` → a `graphene.Field(CursorPageInfo, args={first, cursor}, resolver=...)`
  whose resolver calls `self.get_page_info(root.results, **kwargs)` when `root`
  is a `DjangoListObjectBase`.
- `get_page_info(self, qs, **kwargs)` → computes the dict described in §3,
  reusing `_ordering_field`, the same page-size resolution as
  `paginate_queryset`, `decode_cursor` and `encode_cursor`.

No change to `paginate_queryset` (kept independent so `results` and `pageInfo`
do not depend on resolution order).

### 4.3 `DjangoListObjectType.__init_subclass_with_meta__`

After building the `results` and `count` fields, when a paginator is configured:

```python
page_info_field = pagination.get_page_info_field(baseType)
if page_info_field is not None:
    _meta.fields["page_info"] = page_info_field   # exposed as `pageInfo`
```

(Applied for both the explicit `Meta.pagination` and the global
`DEFAULT_PAGINATION_CLASS` paths.) Field name `page_info` → camelCase `pageInfo`.

---

## 5. Acceptance Criteria

- **AC1** — A cursor-paginated `DjangoListObjectType` exposes `pageInfo`
  (`CursorPageInfo`); a LimitOffset/Page one does **not** (schema introspection).
- **AC2** — `pageInfo.endCursor` of page *N*, sent as `cursor` to page *N+1*,
  returns the contiguous next page with **no overlap**.
- **AC3** — `hasNextPage` is `true` on a non-final page and `false` on the last.
- **AC4** — `hasPreviousPage` is `false` on the first page (even if a spurious
  cursor is supplied) and `true` on any later page (a row exists before the
  page's first row).
- **AC5** — An empty page yields `startCursor=null`, `endCursor=null`,
  `hasNextPage=false`.
- **AC6** — Existing LimitOffset/Page tests still pass unchanged (regression).

---

## 6. Test Plan (`tests/test_paginations.py`)

| Test | Asserts |
|------|---------|
| `test_cursor_exposes_pageinfo` | cursor list type has `pageInfo`; introspection. |
| `test_limitoffset_page_have_no_pageinfo` | LimitOffset/Page list types have no `pageInfo`. [AC1] |
| `test_pageinfo_endcursor_drives_next_page` | endCursor → next page, no overlap. [AC2] |
| `test_hasnextpage_true_then_false` | true mid-list, false on last page. [AC3] |
| `test_haspreviouspage` | false on first page (even with a spurious cursor), true on later pages. [AC4] |
| `test_pageinfo_empty_page` | nulls + hasNextPage false. [AC5] |

Existing cursor/LimitOffset/Page tests remain (regression, AC6).

---

## 7. Documentation

- `docs/api/paginations.md` — extend the `CursorGraphqlPagination` section with
  `CursorPageInfo`, the `pageInfo` argument set and a forward-paging example
  driven by `endCursor`.
- `docs/usage/pagination.md` — add a "Cursor pagination with `pageInfo`" example
  (query with variables + how to advance using `endCursor`).
- This SPEC lives in `specs/` (a repo-internal design doc, excluded from the
  published documentation site).

---

## 8. Definition of Done

1. SPEC approved.
2. `pageInfo` implemented per §4; opt-in and non-breaking.
3. All §5 ACs green via §6 tests; full suite + base-install isolation green;
   `ruff`/`black`/`isort`/`flake8` clean; `mkdocs build --strict` green.
4. Docs (§7) updated with examples.
5. Committed and pushed to `pre-v2`.
