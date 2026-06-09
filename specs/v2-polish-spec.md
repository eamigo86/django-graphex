# SPEC — v2 polish phase (resolvers, settings, enum naming, review, coverage, docs)

Status: accepted
Branch: `polish` (off `native-filtering`)

Six independent polish tasks, each landed as its own commit.

## 1. Honor `resolve_<field>` on `DjangoModelType` custom fields (bug fix)

Custom graphene fields declared on a `DjangoModelType` are moved to the generated
output type, but their `resolve_<field>` methods are left on the wrapper and never
run (the field resolves to `None`). Fix: when building the output type, forward the
matching `resolve_<name>` methods (collected down the MRO) into the generated
output type's namespace, alongside the fields. `source=` keeps working. ACs:
a custom field with a `resolve_<field>` resolves through it; inheritance/override
honored; existing `source=` behavior unchanged.

## 2. Rename `DEFAULT_FILTER_LOOKUPS` → `COMMON_FILTER_LOOKUPS` + settings page

The setting names the *common base* lookup set added to every field — rename for
clarity (unreleased, clean rename). Add a dedicated `docs/usage/settings.md` listing
every `GRAPHENE_DJANGO_EXTRAS` setting with its default + purpose + a single
copy-paste block, wired into the nav.

## 3. Enum member naming from choices — Option 1 (refined)

Member-name cascade: (1) the choice **value** if it is a valid GraphQL name
(unchanged: `TextChoices` value `"draft"` → `DRAFT`); (2) else the **label** resolved
as its **source msgid** with translations deactivated (`override(None)`), so a lazy
`_("Male")` → `MALE` deterministically regardless of locale; (3) else `A_<value>`
(last resort). Stored values never change; collisions de-duplicated as today. Fixes
the confusing `A_1`/`A_2` output for numeric/opaque-valued choices.

## 4. Code review pass

Sweep the package for real bugs, stale comments/docstrings referencing removed
concepts (DRF, django-filter, graphene-django, old class names), wrong cross-refs,
dead code, and inconsistencies introduced across the v2 work. Fix what is found.

## 5. Coverage to ~100%

Raise line+branch coverage as close to 100% as practical with meaningful tests
(not coverage-padding): target the new `filtering/`, `native/`, validators, the
resolver fix, enum naming, and any low-covered core modules.

## 6. Documentation review/restructure

Ensure every v2 feature lives in its correct section with a clear, detailed
explanation and illustrative example(s). Prefer splitting into more pages/sections
over one endless page. Verify the nav reflects the structure.

## Acceptance (all)
- Full suite green with DRF and django-filter uninstalled; ruff + mypy clean.
- Coverage materially up (target ~100%).
