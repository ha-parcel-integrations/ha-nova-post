# Working in this repository

Home Assistant custom integration for **Nova Post** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

Nova Post targets the official `novaposhta.ua` JSON-RPC surface only — a
different, weaker-evidence `novapost.com` REST surface exists and is
deliberately **not** used here (see `carrier-research/nova-post.md#build`).
Full mechanics live in `carrier-research/api/nova-post/` (private); this
section is the HA-side decisions and the pre-1.0 posture.

- **`apiKey` is always the literal empty string `""`.** This looks exactly
  like the shape of a BYO-key carrier (the request body *has* an `apiKey`
  field) but it is a deliberate anonymous path for this one method,
  live-confirmed by probing all four methods either of the two known HA
  client repos call. **There is no credential step and there must never be
  one** — `config_flow.py` never asks for a key.
- **Branch on `data[0]["StatusCode"]`, never on `success` or the HTTP status.**
  A bogus/unknown TTN still answers HTTP 200, `success: true`, with
  `StatusCode: "3"` inside a fully-present `data[0]`. `api.py` treats that as
  the not-found signal (`async_get_parcel` returns `None`); it never reaches
  `parcels.py`'s status map, which deliberately has no "3" entry.
- **This is a genuinely pre-1.0 payload — every field but `StatusCode: "3"`
  is unconfirmed.** The one live probe used a bogus TTN, so every other field
  came back present-but-empty. `parcels.check_payload_shape()` is the
  self-reporting machinery required by CONVENTIONS.md's *Pre-1.0 releases*
  section: it warns once per field the first time a real response populates
  something this build has only ever seen empty, once on any top-level key
  outside the known field inventory (schema drift), and once on the first
  delivered parcel (to settle the `delivered_at` guess). None of these log
  values — keys and status codes only.
- **The known-field inventory (`_EMPTY_ONLY_FIELD_NAMES` /
  `_KNOWN_TOP_LEVEL_FIELDS` in `parcels.py`) covers 128 keys as of a
  2026-08-10 correction**, not the original thirteen. A fresh probe of a
  bogus-TTN response properly enumerated `data[0]`: `ScheduledDeliveryDate`,
  `AdjustedDate`, `ActualDeliveryDate`, `RecipientFullName`,
  `RecipientFullNameEW`, `SenderFullNameEW`, `WarehouseRecipientAddress`,
  `WarehouseRecipientNumber`, `CategoryOfWarehouse`, `ParentBranchName`,
  `FactualWeight`, `VolumeWeight`, `CalculatedWeight`, `CheckWeight`,
  `PaymentStatus`, `UndeliveryReasons*`, `TrackingUpdateDate`, `DateScan`,
  `DateMoving`, `Declarations`, `Services`, `Packaging` are all now known
  field *names* — first-party fact — even though every one of them still
  came back empty on that probe. This is purely additive: it stops those
  fields from tripping the schema-drift warning, nothing else changes.
- **`StatusCode == "2"` ("Видалено" / Deleted) maps to `problem`, no longer
  contested.** Two independent third-party sources used to disagree on where
  it belonged; a 2026-08-10 correction settled it — Nova Post's own published
  57-code table glosses `2` as "Deleted", and the carrier's own independent
  bucketing files `2` under a `Removed` category, not with any
  delivered/received bucket. Both are first-party and both agree with this
  map's existing
  choice; the third-party repo's grouping of `2` with `9`/`10`/`11` is now
  understood to be a filter convenience in that project, not a claim about
  the parcel. **`2` no longer gets the every-occurrence
  `_warn_uncertain_status` warning** (that mechanism is gone entirely) — it
  behaves like every other mapped code, silent, subject only to the general
  "values have never been seen on the wire" caveat that covers the whole map.
- **`sender`/`receiver` are populated from the 2026-08-10 named fields**:
  `sender` ← `SenderFullNameEW`, `receiver` ← `RecipientFullName` (fallback
  `RecipientFullNameEW` when the first is empty), both `.get()`-guarded with
  an `or None` empty-string normalisation (the same pattern `pickup_point`
  already used for this payload's "present but empty" convention) — no
  further validation, since the *values* behind those names are still
  unconfirmed. This mirrors `ha-delhivery`'s `clientName`/`consignee`
  population.
- **`delivered_at`, `planned_from`/`planned_to` and `url` are still
  hard-coded `None`, deliberately, even though ETA- and delivered-at-shaped
  fields now exist.** `ScheduledDeliveryDate`/`AdjustedDate` (candidates for
  `planned_from`/`planned_to`) and `ActualDeliveryDate` (alongside
  `RecipientDateTime`, both candidates for `delivered_at`) were all newly
  named by the 2026-08-10 correction, but their semantics — point estimate
  vs. window, which field actually populates — are explicitly unconfirmed in
  the research, and shipping a guess between two named-but-unconfirmed
  candidates is worse than `None` + the one-shot `_warn_first_delivered`
  warning. Do not wire these up without a real capture in
  `carrier-research/api/nova-post/`. No public consumer tracking-page URL has
  ever been captured for `url`, so that one stays `None` on its own,
  unrelated basis. Reflected in `const.py`'s `CAPABILITIES` (feeds the docs
  site's comparison table) — keep the two in agreement if that ever changes.
- **`weight` and `dimensions` are untouched.** Four more weight fields
  (`FactualWeight`/`VolumeWeight`/`CalculatedWeight`/`CheckWeight`) are now
  known field names alongside `DocumentWeight`, but which one populates and
  in which unit is unresolved and, per the 2026-08-10 research, *more*
  ambiguous than before (the sibling `novapost.com` API documents grams
  against other confirmed samples reading as kilograms). `weight` still
  parses only `DocumentWeight`, unit still assumed kilograms.
- **No `include_history` option, no `build_history`/`map_event_status`
  helpers.** `getStatusDocuments` looks like a single current-state snapshot
  — no events/timeline array has been observed or is implied by either HA
  client repo that calls this method, and the 2026-08-10 128-key enumeration
  confirms it — no events array anywhere in the 128 keys. `history` is always
  `None`, the same call Budbee makes for the same reason (see its CLAUDE.md).
  The generic delivery-window sensor, the calendar entity and the
  `delivery_time_changed` event stay in place (suite parity) even though
  `planned_from`/`planned_to` never populate for this carrier — same
  situation as Cainiao.
- **Diagnostics redaction (`diagnostics.py`'s `TO_REDACT`) grew ten exact
  keys on 2026-08-10** to match the newly-named fields: `RecipientFullName`,
  `RecipientFullNameEW`, `SenderFullNameEW`, `WarehouseRecipientAddress`,
  `WarehouseRecipientNumber`, `ParentBranchName`, `UndeliveryReasons`,
  `UndeliveryReasonsDate`, `UndeliveryReasonsSubtypeDescription`,
  `PaymentStatus` — alongside, not instead of, the existing
  City*/Warehouse*/Phone* prefix-based defensive pass.
- **Tracking-code format is `^\d{14}$`, tighter than the template default.**
  Every TTN referenced anywhere in the research — including the bogus probe
  number `20450000000000` — is exactly 14 digits, so this is safe to ship as
  a hard requirement rather than the usual permissive regex.

## Options and reloads

The options flow is one sectioned form (`data_entry_flow.section`); changes apply
without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default) apply changes live: an update listener
  retunes `coordinator.update_interval` and calls `async_request_refresh()`, so
  added/removed parcel sensors appear immediately.
- **Account-based carriers** call `async_schedule_reload` on submit and register
  **no** update listener. Combining a listener with a reload-on-update flow is
  deprecated, an error in HA 2026.12+.

The user-tunable poll interval is a deliberate HACS divergence (see
CONVENTIONS.md); a carrier that throttles is generated with a fixed cadence and no
polling option at all.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (no-ops elsewhere):
`disable_socket` is neutralised (Windows event loops need AF_INET socketpairs;
the 127.0.0.1 allowlist stays) and HA's `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development is Windows.

## Running tests

```
python -m pytest tests/ --cov=custom_components.nova_post
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in this carrier's directory under the private
`carrier-research/api/`, never in this repo.
