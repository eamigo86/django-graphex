# SPEC — Subscriptions: configurable notification payload (`id-only` vs full)

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/subscriptions/{bindings,subscription}.py`,
`settings.py`, subscription tests, docs.
**Date:** 2026-06-07
**Origin:** ported idea from a downstream custom `ResourceBinding.serialize()`
override (serialize only `{"id": ...}` for performance). The companion
`post_change_receiver` fix from that same class is **not** ported: that bug
belongs to the old `channels-api` engine, which v2 replaced with a signal
binding (`bindings.py`) where the crash cannot occur.

---

## 1. Problem / Goals

Today `SubscriptionBinding.broadcast()` (`bindings.py:99`) **always** calls
`serialize_instance(serializer_class, instance)` on every `post_save` /
`post_delete`, regardless of whether subscribers need the full object. For hot
models this is pure overhead when clients only need to know *which* object
changed (and will refetch).

**Goals**

- **G1** — Allow the notification `data` to be reduced to `{"id": <pk>}`,
  skipping serialization entirely.
- **G2** — Make it configurable **globally** via settings, with a **per-subscription
  override** in `Meta` (a hot model can be `id-only` while another stays full).
- **G3** — When a subscription is effectively `id-only`, **drop the `data`
  argument** from its generated GraphQL arguments (there are no fields to pick),
  and skip building the `<Model>Fields` enum.
- **G4** — Tests + docs.

### Non-Goals
- Skipping the broadcast when a group has zero listeners (separate optimization).
- Per-instance / filtered dynamic groups (a different feature; see §6 note).

## 2. Design

### 2.1 Setting (global default)
Add to `settings.py` `DEFAULTS`:

```python
# Subscriptions: when False (default), change notifications carry only
# {"id": <pk>} and skip serializing the instance; set True to serialize the
# full instance with the subscription's serializer_class.
"SUBSCRIPTION_SERIALIZE_DATA": False,
```

**Default is `False` (id-only).** This is a **breaking change** vs the current
always-full behavior — accepted for v2 (perf by default).

### 2.2 Per-subscription override (`Meta`)
New `Subscription` `Meta` option `serialize_data` (tri-state):

| Value | Meaning |
|-------|---------|
| `None` *(default)* | Inherit the global `SUBSCRIPTION_SERIALIZE_DATA` setting. |
| `True` | Force full serialization for this subscription. |
| `False` | Force `id-only` for this subscription. |

Stored on `SubscriptionOptions.serialize_data` (default `None`). Resolution
helper on `Subscription`:

```python
@classmethod
def _should_serialize_data(cls):
    value = cls._meta.serialize_data
    if value is None:
        value = graphql_api_settings.SUBSCRIPTION_SERIALIZE_DATA
    return bool(value)
```

### 2.3 Broadcast (`bindings.py`)
`broadcast()` chooses the payload `data` per event (read at broadcast time so
runtime/`override_settings` changes are honored in tests):

```python
if self.subscription_cls._should_serialize_data():
    data = serialize_instance(self.serializer_class, instance)
else:
    data = {"id": instance.pk}
payload = {"action": action, "model": self.model_label, "data": data}
```

The id-only payload key is always `"id"` (value `instance.pk`), independent of
the model's pk attribute name.

### 2.4 Dropping the `data` argument (`subscription.py`)
`__init_subclass_with_meta__` gains a `serialize_data=None` kwarg, stores it on
`_meta`, and computes the **effective** mode at class-definition time:

```python
effective_full = (
    serialize_data if serialize_data is not None
    else bool(graphql_api_settings.SUBSCRIPTION_SERIALIZE_DATA)
)
```

- If `effective_full`: build the `<Model>Fields` enum and include
  `"data": List(model_fields_enum, required=False)` in `arguments` (current
  behavior).
- Else (`id-only`): **omit** the enum and the `data` argument entirely.

`_subscribe` already tolerates `data=None`, and the consumer's
`project_fields({"id": ...}, None)` returns `{"id": ...}` unchanged — no change
needed there.

> **Schema is static.** The presence of the `data` argument is fixed when the
> subscription subclass is defined (from its `Meta` override, else the global
> setting at import time). Changing the global setting at runtime affects only
> the serialization cost in `broadcast()`, never the already-built schema. The
> two possible divergences are both harmless:
> - arg present but runtime id-only → client may request fields but receives
>   `{"id": ...}`; `project_fields` simply returns it.
> - arg absent but runtime full → client cannot request fields and receives the
>   full payload.

## 3. Acceptance Criteria
- **AC1** Default (no settings, no `Meta`): a change broadcasts
  `payload["data"] == {"id": instance.pk}` and `serialize_instance` is **not**
  called. [G1]
- **AC2** With `GRAPHENE_DJANGO_EXTRAS = {"SUBSCRIPTION_SERIALIZE_DATA": True}`:
  payload carries the full serialized instance. [G2]
- **AC3** `Meta.serialize_data = True` forces full even when the global is
  id-only; `Meta.serialize_data = False` forces id-only even when the global is
  full. [G2]
- **AC4** An effectively id-only subscription has **no** `data` argument and no
  `<Model>Fields` enum; an effectively full one keeps both. [G3]
- **AC5** Existing two-channel wire protocol, group names and projection in full
  mode are unchanged. Full suite green; base channels-free import green; lint +
  `mkdocs --strict` green. [G4]

## 4. Test Plan (`tests/subscriptions/`)
Extend `test_binding.py` and add a small schema fixture with two extra
subscriptions (`Meta.serialize_data = True/False`):

- AC1: default id-only payload `== {"id": pk}`; `serialize_instance` spy
  `call_count == 0`.
- AC2: under `override_settings(GRAPHENE_DJANGO_EXTRAS={"SUBSCRIPTION_SERIALIZE_DATA": True})`,
  payload `data` is the full dict and the spy is called once.
- AC3: Meta-forced full / id-only beat the opposite global.
- AC4: inspect `Sub._meta.arguments` — `data` present iff effective full.
- Update `test_save_broadcasts_to_action_and_pk_groups` (currently asserts
  `data["username"]`) and `test_signal_registration_is_idempotent` (asserts
  serialize called once) to run in **full** mode explicitly, so they keep
  testing what they intend under the new id-only default.

## 5. Documentation
`docs/usage/subscriptions.md`:
- New "Notification payload" section: the `SUBSCRIPTION_SERIALIZE_DATA` setting,
  the `Meta.serialize_data` override, the **id-only default**, and that the
  `data` argument disappears unless full mode is active.
- Update the client example / arguments list (`data: [...]`, the full-payload
  example) to state they apply in **full** mode.
- Add the setting to any settings reference page if present.

## 6. Definition of Done
1. SPEC approved.
2. Setting + `Meta` override + broadcast/argument changes per §2.
3. §3 ACs green via §4 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs updated.
5. Committed and pushed to `pre-v2`.

> **Note (not in scope) — what "group" means and the `DELETE → UPDATE → CREATE`
> ordering.** Throughout the subscription code (old and v2), a *group* is a
> **Channels group** keyed by `model_label-action[-id]` (`_group_name`), which
> each websocket connection joins in the resolver. It is **not** a Django
> `auth.Group`, and **not** a field-value-derived filter. In the legacy package
> `group_names` was *never* overridden — it was the generic `channels-api`
> `ResourceBindingBase` default, which did not even match the action-keyed
> `_group_name` groups the resolver actually used. The `old/new` diffing and the
> `DELETE → UPDATE → CREATE` order are boilerplate `channels-api` machinery
> designed for a *different* pattern: bindings whose `group_names` derive from
> **instance field values**, where an object moving between value-based groups on
> update yields leave/stay/join (= delete/update/create) and DDP/minimongo-style
> ordered clients need removals before insertions. graphene-django-subscriptions
> never used field-derived groups, so that diffing was inert/mismatched here —
> which is also why a custom binding override was needed to stop it crashing.
> Because the groups are action-keyed, **one DB event maps to exactly one action**
> and v2 broadcasts straight to that action's group(s) (`bindings.py:85-115`):
> the correct, direct expression of the original intent. Nothing functional is
> lost and the multi-action ordering is moot. (A *field-value-filtered* groups
> feature — which neither package has — would be a separate SPEC and would bring
> the ordering back with it.)


