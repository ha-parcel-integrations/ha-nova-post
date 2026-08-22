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

**2026-08-13: moved from the `novaposhta.ua` JSON-RPC surface
(`getStatusDocuments`) to the `/site/v.1.0/shipments/tracking/{ttn}` website
REST surface** (`carrier-research/nova-post.md#build`, addendum 2026-08-13),
on the strength of a real captured payload (maintainer-supplied TTN `12348`,
an in-flight CN→MD parcel) that confirmed `history`, `weight` (kg),
`dimensions` (cm), `pickup_point` and a constructible `url` — everything the
old surface lacked. Full mechanics live in `carrier-research/nova-post/api/`
(private); this section is the HA-side decisions and what changed.

- **`GET`, keyless, tracking code in the URL path — not a POST body.**
  `TRACKING_API_URL` in `const.py` is now a `.format(ttn=...)` template; the
  old surface's `Documents` list body is gone. No headers, no key, nothing to
  register — control-tested against a protected sibling on the same host
  (`/mobileapp/v.1.1/` answers `401` with no credential) and against a
  route-existence oracle that separates "no such route" from "no such
  shipment", both in `novapost-tracking.md`.
- **Not-found is a plain HTTP 404, not an in-body status code.** The old
  surface always answered `200`/`success: true` and branched on
  `StatusCode == "3"`; this one answers `404 {"errorMessage": "not_found"}`
  for an unknown number. `api.py`'s `async_get_parcel` returns `None` on 404,
  raises `NovaPostApiError` on anything else non-2xx.
- **Host is `novaposhta.ua`, not `novapost.com`.** Both are live-confirmed to
  serve byte-identical bodies for the same TTN — one shared NOVA-group
  backend, two brand hostnames — chosen to match this integration's existing
  branding and its tracking-page URL.
- **Tracking-code format widened to `^[A-Za-z0-9]{4,30}$`, and the surface
  itself validates nothing** — "this route takes any string"
  (`novapost-tracking.md` "Surface B"). Three shapes are confirmed live: the
  original 14-digit Ukrainian domestic TTN, short numeric reference codes
  (`12345`/`12348`/`12349`), and cross-border alphanumeric aliases
  (`SHCN8143247690`, 14 chars). `normalize_tracking_code` now upper-cases and
  keeps letters instead of stripping them — the old digits-only regex would
  have rejected the cross-border form outright.
- **The 57-code status map (`_STATUS_MAP` in `parcels.py`) replaced the old
  12-code seed wholesale**, sourced from Nova Post's own published table
  (`carrier-research/nova-post/api/novapost-tracking.md#status-vocabulary`) —
  the same numeric `code` space `tracking[].code` uses. Map on `code` only,
  never `event_name` (server-rendered, localised text — the same trap as
  SunYou's `toLanguage`). The trap that matters most survives from the old
  map: codes `7`/`8` ("arrived at branch/locker") are `at_pickup_point`, not
  `delivered` — the carrier's own word for handed-over is "Received"
  (`9`/`10`/`11`/`106`).
- **`sender`/`receiver` are now geography, not identity — a real regression.**
  This surface's `sender`/`recipient` blocks carry only `country_code`,
  `settlement`, `divisionId` and coordinates; no name field exists anywhere on
  the wire. The old surface's `SenderFullNameEW`/`RecipientFullName` have no
  equivalent here. `_format_party()` renders `"Chișinău, MD"` (settlement +
  country) or whichever half is present. Accepted deliberately for the fields
  this move gains — `sender`/`receiver` are not part of `KNOWN_CAPABILITIES`,
  so this loss does not show up on the docs site's capability table; it only
  shows up here and in `## Log`-style commit messages.
- **`delivered_at` is inferred, not read from a named field.** No field on
  this surface is named anything like `delivered_at` — `_delivered_at()`
  scans `tracking[]` backwards for the newest hop whose `code` is in the
  "Received" bucket (`9`/`10`/`11`/`106`) and takes its `date`. Warns once via
  `_warn_delivered_at_inferred` the first time this fires — a heads-up, not a
  bug report request, since it *is* now populated (unlike the old surface,
  where it stayed `None` forever).
- **`planned_from` and `planned_to` are both `scheduled_delivery_date`.** The
  field is a single point estimate, not a `from`/`to` window (on the one
  capture on file it lands 26 minutes before the final tracking hop) —
  represented as a zero-width window rather than leaving one end `None`, so
  `sort_parcels_by_ts` on `planned_from` still works and the delivery-window
  sensor still shows something.
- **`pickup_point` and `raw_status` come from the newest `tracking[]` hop**,
  not gated on the current status — mirrors the old surface's
  `WarehouseRecipient`, which was shown regardless of whether the parcel had
  actually arrived.
- **`url` is always constructible once a tracking code exists**, even for a
  code the carrier does not (yet) recognise — `TRACKING_URL_TEMPLATE` in
  `const.py` is `https://novaposhta.ua/tracking/{ttn}` (no locale prefix: the
  no-prefix form is confirmed to resolve regardless of the user's language,
  unlike `novapost.com`'s required two-segment `{lang}-{country}` tag).
- **`weight` is `total_weight` (kg), `dimensions` is `parcels[0]`'s
  `length`/`width`/`height` (cm)** — both confirmed on the real capture
  (`total_weight: 0.36` against `24×17×2`, only sane as kg/cm), resolving the
  old surface's g/mm-vs-kg/cm ambiguity for this one. Only the first
  `parcels[]` entry is read; a multi-parcel shipment's later entries are not
  aggregated — a scope decision, not a research finding, revisit if a
  multi-parcel capture ever surfaces.
- **`history` is real now, and `include_history` is a real option.**
  `tracking[]` is an ordered, geo-tagged timeline (confirmed oldest→newest by
  the real capture's timestamps) — `build_history()` maps each hop through the
  same status map used for the current status, capped at
  `HISTORY_MAX_EVENTS` (20). The options flow gained a `history` section
  (`CONF_INCLUDE_HISTORY`, off by default), mirroring every other suite
  carrier's convention — including this one costing no extra request, unlike
  carriers where history needs a second call.
- **The pre-1.0 self-reporting machinery was replaced, not extended.** The old
  "first non-empty field" mechanism (`_EMPTY_ONLY_FIELD_NAMES`,
  `_warn_first_nonempty_field`) existed for a payload whose values had only
  ever been seen empty — that is no longer true; the payload is confirmed.
  What is still a guess and still warns once: an unrecognised status `code`
  (`_warn_unmapped_status`), an unknown top-level key
  (`_warn_schema_drift`/`check_payload_shape`, keyed off the presence of a
  `tracking` key rather than the old `StatusCode` key to tell a real response
  from the coordinator's `{"number": code}` placeholder), and the
  `delivered_at` inference above.
- **Diagnostics redaction (`diagnostics.py`'s `TO_REDACT`) was rewritten, not
  extended** — none of the old field names (`Number`, `WarehouseRecipient`,
  `CitySender`, …) exist on this surface. `sender`/`recipient` are redacted as
  **whole blocks** (mirrors `ha-dynalogic`'s `Addressee`/`ContactInformation`
  convention) because this surface carries something the old one never did:
  GPS coordinates per party and per tracking hop. Location-shaped leaves
  inside `tracking[]` (`settlement_name`, `division_name`,
  `settlement_external_id`, `post_code`, `division_coordinates`) are redacted
  individually, alongside `number`/`parcel_number` (echo the barcode at every
  level), `alternative_numbers`, and the financial/free-text
  `parcel_description`/`insurance_cost`/`insurance_cost_currency_code`.
  `country_code` is deliberately **not** redacted — alone it is not specific
  enough to locate a person and is useful for debugging the status mapping.

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

## Running tests

```
python -m pytest tests/ --cov=custom_components.nova_post
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in `carrier-research/nova-post/api/` (this
carrier's own directory, private), never in this repo.
