# Nova Post Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-nova-post.svg)](https://github.com/ha-parcel-integrations/ha-nova-post/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Nova Post](https://novaposhta.ua) (Nova Poshta) parcels within Ukraine. No account and no API key are needed — you enter the 14-digit tracking number (TTN) yourself, just like on the Nova Poshta website.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

> ### ⚠️ Early release — no real Nova Poshta parcel has been tracked yet
>
> The endpoint, the keyless `apiKey: ""` path and the not-found signal are all
> live-confirmed against a real probe — but that probe used a bogus tracking
> number, so every field in the response came back empty. What has **not**
> been seen from a real parcel is a *populated* response, so several things
> are still open:
>
> - the 12-code status vocabulary is seeded from a third-party repo, not a
>   capture — only "not found" (code 3) has ever actually been observed on the
>   wire;
> - `sender`/`receiver` are now populated from named fields the carrier
>   confirmed exist (`SenderFullNameEW`/`RecipientFullName`), but no *value*
>   behind those names has ever been seen on the wire;
> - whether `DocumentWeight` is in kilograms (assumed) is unconfirmed;
> - `delivered_at` and `planned_from`/`planned_to` are left `None` rather than
>   guessed — ETA and delivered-at candidate fields exist
>   (`ScheduledDeliveryDate`/`AdjustedDate`, `ActualDeliveryDate`/
>   `RecipientDateTime`) but which one actually populates, and in what shape,
>   has never been confirmed against a real parcel;
> - a tracking-page `url` is left `None` — no public consumer tracking-page
>   URL has ever been captured for Nova Poshta.
>
> Each of those logs a one-shot warning with a ready-made issue link the first
> time a real parcel hits it, and an unmapped status reports **`unknown`**
> rather than a wrong one. If you see one,
> [please report it](https://github.com/ha-parcel-integrations/ha-nova-post/issues/new?template=unrecognised_status.yml)
> — that is what finishes this integration.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Nova Post parcels by their 14-digit tracking number (TTN) — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `at_pickup_point` / `delivered` / …) and the carrier's own status text
- Summary sensors: incoming parcels, recently delivered parcels
- `nova_post.track_parcel` / `nova_post.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered)
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.7 or newer
- A Nova Post (Nova Poshta) parcel within Ukraine and its 14-digit tracking
  number (TTN), from the shipping confirmation or the missed-delivery card —
  no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-nova-post` as an **Integration**.
3. Install **Nova Post** and restart Home Assistant.

### Manual

Copy `custom_components/nova_post` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Nova Post**. There is nothing to fill in: the hub is created immediately (Nova Post tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`nova_post.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking number (TTN) is on your shipping confirmation or the missed-delivery card.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked TTNs. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Polling | Refresh every | 30 min | How often Nova Post is checked. Slower is gentler on their API. |

There is no *parcel history* option here, unlike some other integrations in
the family: Nova Post's tracking method returns a single current-state
snapshot, not an event timeline, so every parcel's `history` attribute is
always `null`.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Nova Post → ⋮ → Delete**. Nothing is stored on Nova Post's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.nova_post_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.nova_post_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.nova_post_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.nova_post_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.nova_post_last_successful_update` | Diagnostic: when Nova Post was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family. Nova Post's own `StatusCode` vocabulary has no "out for delivery today" state, so that value is never produced by this integration:

| Status | Meaning |
|---|---|
| `registered` | New waybill created, not yet handed over |
| `in_transit` | Dispatched, on the way, or in the destination city |
| `at_pickup_point` | Arrived at a branch or parcel locker, ready to collect |
| `delivered` | Received (picked up) |
| `returning` | Refused, or a return in progress |
| `problem` | An exception, or a deleted waybill |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

The carrier's own human-readable text (in Ukrainian) is always available as `raw_status`.

⚠️ This mapping is seeded from a third-party source, not a live capture — see
the early-release note above. Only "not found" (`StatusCode` 3, which never
reaches `status` at all) has ever actually been observed on the wire.
`StatusCode` 2 ("Видалено" / Deleted, mapped here to `problem`) used to be a
disputed mapping between two third-party sources; the carrier's own published
status table and its own independent status bucketing (both first-party) now
agree with `problem`, so that disagreement is resolved.

## Events

The integration fires these on the event bus (also available as device triggers on the Nova Post device):

| Event | When |
|---|---|
| `nova_post_parcel_registered` | A new parcel appears in the active list |
| `nova_post_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `nova_post_parcel_delivered` | A parcel is delivered |
| `nova_post_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `nova_post.track_parcel` | `tracking_code` | Start tracking a parcel |
| `nova_post.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.nova_post: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Nova Post has not scanned it yet (their API answers "number not found" until the first scan), or the TTN is wrong. It will pick up automatically once scanned.
- **A status logs "Unrecognised Nova Post StatusCode"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-nova-post/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.
- **A warning about a status, a field or a unit** — that is this integration asking for the confirmation it still needs (see the early-release note above). Please [open an issue](https://github.com/ha-parcel-integrations/ha-nova-post/issues/new?template=unrecognised_status.yml) with the logged line.
- **`sender`/`receiver` are sometimes empty** — they read named fields the carrier confirmed exist, but not every parcel is expected to populate them, and no real value has ever been observed; see the early-release note above.
- **`delivered_at` or `url` are always empty** — neither has a confirmed source field yet; see the early-release note above.
- **No delivery-window sensors, calendar or `delivery_time_changed` event ever fire** — Nova Post's tracking method exposes no ETA-shaped field at all.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public, keyless tracking endpoint as the Nova Poshta consumer website. It is not affiliated with, endorsed by, or supported by Nova Poshta. Be gentle with the polling interval.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
