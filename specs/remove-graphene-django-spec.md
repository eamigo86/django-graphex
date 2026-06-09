# SPEC — Remove the graphene-django dependency (depend on graphene directly)

**Status:** IMPLEMENTED on branch `decouple-graphene-django` (off `pre-v2`). All
four phases done; the full suite (394 tests) passes with `graphene-django`
uninstalled. Public API unchanged. (The `register_description(Promise)`
side-effect graphene-django performed on import is now done in our `converter`.)
**Date:** 2026-06-08
**Goal:** drop `graphene-django` (unmaintained) entirely; depend on
`graphene` (core) directly. We already roll our own `DjangoObjectType` +
`converter`, so the coupling is only at the edges.

> **Out of scope (future):** the package **rename** + new repo (this becomes
> v1 of a new package; `graphene-django-extras` stays legacy 1.x). For now we keep
> the name `graphene_django_extras` and work on this branch.

---

## 1. Exact dependency inventory

| graphene-django symbol | Used in | Size | Plan |
|---|---|---|---|
| `types.ErrorType` (`{field, messages}`) | types, mutation, nested, utils | 3 lines | **vendor** → `_compat.py` |
| `utils.is_valid_django_model` | types, fields, utils | 2 lines | **vendor** |
| `utils.maybe_queryset` | fields | 4 lines | **vendor** |
| `utils.DJANGO_FILTER_INSTALLED` | types, fields | flag | **vendor** (try-import) |
| `utils.str_converters.to_const` | converter | 1 line (+`text_unidecode`) | **vendor** (keep `text-unidecode` as a direct dep) |
| `compat.{Array,HStore,JSON,Range}Field` | converter | 65 lines | **vendor** (try-import django.contrib.postgres) |
| `fields.DjangoListField` (DLF) | fields (base of ours) | — | **drop**: our subclass already bypasses it (`super(DLF,...)` → `graphene.Field`); inherit `graphene.Field` directly |
| `filter.utils.get_filtering_args_from_filterset` | fields (×4) | ~95 lines | **vendor** (django-filter bridge) |
| `filter.utils.replace_csv_filters` | filters/filter | ~35 lines | **vendor** |
| `forms.GlobalIDFormField` | filters/fields | — | **drop**: our `GraphqlIDFormField` overrides `clean` fully; only needed for `convert_form_field` MRO dispatch, which the vendored bridge controls |
| `views.GraphQLView` | views, subscriptions | 433 lines | **fork** → internal base view |
| `settings.graphene_settings` | subscriptions/views | — | read Django `GRAPHENE` setting via a tiny shim |

Everything depends on **graphene-core** (`ObjectType/Field/Schema/...`), which we
**keep** and add as a direct dependency.

---

## 2. Phased plan (each phase: tests green, committed)

### Phase 1 — trivial edges (low risk)
- New `graphene_django_extras/_compat.py` holding vendored: `ErrorType`,
  `is_valid_django_model`, `maybe_queryset`, `DJANGO_FILTER_INSTALLED`,
  `to_const`, and the postgres field shims.
- Repoint all imports of those from `graphene_django.*` to `._compat`.
- Drop the `DLF` base: `class DjangoListField(graphene.Field)` (our `__init__`
  already calls the `graphene.Field` initializer; remove the `super(DLF,...)`
  indirection and the `type`-property workaround becomes a no-op we can simplify).

### Phase 2 — django-filter bridge (moderate)
- Vendor `get_filtering_args_from_filterset` + `replace_csv_filters` into a new
  `graphene_django_extras/filters/bridge.py` (adapt to our `convert_form_field`
  handling so `GraphqlIDFormField` maps to a GraphQL `ID`).
- Make `GraphqlIDFormField` a plain `django.forms.Field` (drop
  `GlobalIDFormField`); ensure the bridge maps it to `ID`.

### Phase 3 — fork the view (moderate)
- Vendor graphene-django's `GraphQLView` as `graphene_django_extras/_view.py`
  (GET/POST, GraphiQL, batch, query/variable parsing, execution). `ExtraGraphQLView`
  (which already overrides 13 methods) subclasses the fork instead.
- Subscriptions view: subclass the fork; replace `graphene_settings` with a small
  `_django_setting("GRAPHENE", ...)` reader.

### Phase 4 — dependency swap & docs
- `pyproject.toml`: remove `graphene-django>=3.2,<4`; add `graphene>=3.4,<4`
  (+ `text-unidecode` if used). Keep `django-filter` optional as today.
- Grep-assert **zero** `graphene_django` imports remain.
- Docs/changelog: note the dependency change (no API change).

---

## 3. Acceptance Criteria
- **AC1** — `grep -r "graphene_django\b" graphene_django_extras/` returns nothing
  (no runtime import of the package).
- **AC2** — Full suite passes unchanged at every phase; public API (imports from
  `graphene_django_extras`, `Meta` options, view classes) is byte-for-byte stable.
- **AC3** — `pyproject` no longer lists `graphene-django`; lists `graphene`
  directly; the package imports and a schema builds with graphene-django
  uninstalled.
- **AC4** — Filtering (django-filter), the views, ErrorType-based mutation errors,
  enums, and postgres-field conversion still work (covered by existing tests).

## 4. Risks & mitigations
- **The view fork** is the largest copy; mitigate by keeping our overrides intact
  and diffing behavior against the current view via the existing `test_views`.
- **The filter bridge** couples to django-filter internals; pin behavior with the
  existing filtering tests; keep django-filter optional.
- **`to_const`/unidecode**: keep `text-unidecode` (tiny, maintained) to preserve
  enum-name behavior for non-ASCII choices.

## 5. Follow-up (not now)
Package rename + new repository; legacy `graphene-django-extras` frozen at 1.x.
