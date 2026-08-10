"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

Nova Post-specific here: :data:`_STATUS_MAP`, :func:`normalize_parcel` and the
pre-1.0 self-reporting warnings (see :func:`check_payload_shape`). Everything
else — the timestamp parsing, the sort contract, the delivered filter, the
one-shot warning for unmapped statuses — is suite-wide machinery and should be
left alone.

No ``history``/``build_history`` here: ``getStatusDocuments`` looks like a
single current-state snapshot, not a timeline — see const.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-nova-post/issues/new"
    "?template=unrecognised_status.yml"
)

# Nova Poshta's ``StatusCode`` → canonical ParcelStatus. Reproduced from
# carrier-research/api/nova-post/tracking.md#status-vocabulary, itself seeded
# from a single third-party repo's ``const.py`` ("real data from
# getStatusDocuments API" is that repo's own claim, not a capture of ours).
# **Only code "3" (not found) has ever actually been observed on the wire** —
# everything else is this doc's best reading of that seed, corroborated only
# partially by a second, independent source. Treat the whole map as the seed
# it is until real parcels exercise it.
#
# Code "3" ("Номер не знайдено" / number not found) is deliberately absent —
# it is not a parcel state, it is the not-found signal itself, handled in
# api.py by returning ``None`` before this map is ever consulted.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "1": ParcelStatus.REGISTERED,   # Нова накладна — new waybill, not yet handed over
    "2": ParcelStatus.PROBLEM,      # Видалено — deleted; resolved 2026-08-10, see below
    "4": ParcelStatus.IN_TRANSIT,   # Відправлено — dispatched
    "5": ParcelStatus.IN_TRANSIT,   # В дорозі — in transit
    "6": ParcelStatus.IN_TRANSIT,   # У місті призначення — in the destination city
    "7": ParcelStatus.AT_PICKUP_POINT,  # Прибуло у відділення — arrived at a branch
    "8": ParcelStatus.AT_PICKUP_POINT,  # Прибуло у поштомат — arrived at a locker
    "9": ParcelStatus.DELIVERED,    # Отримано — received (picked up)
    "10": ParcelStatus.RETURNING,   # Відмова від отримання — refused to receive
    "11": ParcelStatus.RETURNING,   # Повернення — return in progress
    "12": ParcelStatus.PROBLEM,     # Проблемне відправлення — problem shipment
}

# Code "2" ("Видалено" / Deleted) **was** a genuine open disagreement between
# two third-party sources — one bucketed it as an exception (this map's
# choice, ``problem``), a second, independent repo bucketed it with 9/10/11 as
# "terminal/delivered-class" and flagged its own choice as odd. **Resolved
# 2026-08-10:** Nova Post's own published 57-code table glosses "2" as
# "Deleted", and the carrier's own independent bucketing files "2" under a `Removed`
# category, not with any delivered/received bucket — two first-party sources
# that both agree with this map's existing choice. The other repo's grouping
# of "2" with 9/10/11 is now understood to be a filter convenience in that
# project, not a claim about the parcel. "2" therefore gets no special
# every-occurrence warning any more — it behaves like every other mapped
# code, still subject only to the general "values have never been seen on the
# wire" caveat that covers the whole map (carrier-research/nova-post.md, "##
# Log", UPDATE 2026-08-10).

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Nova Post StatusCode — help us map it. Open an issue "
        "and paste this line: %s\n  StatusCode=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a Nova Post ``StatusCode`` to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned/pending placeholder) reports ``unknown``
    silently; an unrecognised code reports ``unknown`` with a one-shot
    warning. Map on the numeric code only — never on ``Status``, the
    Ukrainian free-text label paired with it, the same trap as SunYou's
    ``toLanguage``-localised event text (see
    carrier-research/api/nova-post/tracking.md#payload--canonical-mapping).

    Every mapped code, including "2" (see the comment above ``_STATUS_MAP``),
    is returned silently — the per-code "genuine disagreement" warning that
    used to single "2" out is gone as of the 2026-08-10 correction; only a
    wholly unmapped code still self-reports.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. No Nova Poshta timestamp has
    ever been seen with a real value (see :func:`check_payload_shape`), so
    this is currently unexercised by ``normalize_parcel`` itself — kept for
    the moment a field like ``RecipientDateTime`` is confirmed.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


# ---------------------------------------------------------------------------
# Pre-1.0 self-reporting (see .github/CONVENTIONS.md § Pre-1.0 releases)
#
# Every field below was seen on the live probe only as an *empty* key — the
# probe used a bogus TTN, so no real shipment has ever populated them. Each
# check below fires once, the first time reality gives us more than the
# schema did, so the guesses in this file get confirmed or corrected by real
# users instead of by waiting. Keys and codes only, never PII values.
# ---------------------------------------------------------------------------

# Fields only ever observed as an empty key. The exact ``City*``/``Phone*``
# sibling names are unconfirmed (tracking.md notes "more than one City* key
# per side" without enumerating them), so those two families are matched by
# prefix instead of by exact name.
#
# Expanded 2026-08-10: a fresh probe enumerated the response item properly
# and found 128 keys, not thirteen (tracking.md "Correction 2026-08-10 — the
# item carries 128 keys, not thirteen"). These are now known field *names* —
# first-party fact — even though their *values* remain unconfirmed (every one
# came back empty on the only probe ever run, a bogus TTN). Adding them here
# is purely additive: it stops a real response from tripping the schema-drift
# warning below over a field the carrier has always sent, and lets
# ``_warn_first_nonempty_field`` do its job the day one of them is finally
# populated. ``RecipientFullName``/``RecipientFullNameEW``/
# ``SenderFullNameEW`` are also read directly by ``normalize_parcel`` now
# (see ``sender``/``receiver`` below) — being in this set does not change
# that, it only governs the schema-drift/first-nonempty-value warnings.
_EMPTY_ONLY_FIELD_NAMES = frozenset(
    {
        "DateCreated",
        "RecipientDateTime",
        "WarehouseSender",
        "WarehouseRecipient",
        "CargoType",
        "DocumentCost",
        "AnnouncedPrice",
        "DocumentWeight",
        "ScheduledDeliveryDate",
        "AdjustedDate",
        "ActualDeliveryDate",
        "RecipientFullName",
        "RecipientFullNameEW",
        "SenderFullNameEW",
        "WarehouseRecipientAddress",
        "WarehouseRecipientNumber",
        "CategoryOfWarehouse",
        "ParentBranchName",
        "FactualWeight",
        "VolumeWeight",
        "CalculatedWeight",
        "CheckWeight",
        "PaymentStatus",
        "UndeliveryReasons",
        "UndeliveryReasonsDate",
        "UndeliveryReasonsSubtypeDescription",
        "TrackingUpdateDate",
        "DateScan",
        "DateMoving",
        "Declarations",
        "Services",
        "Packaging",
    }
)
_EMPTY_ONLY_FIELD_PREFIXES = ("City", "Phone")

# The full field inventory tracking.md's live probe actually returned a key
# for. A top-level key in a real ``data[0]`` item outside this set (and
# outside the two anticipated-but-unnamed prefixes above) is schema drift —
# the public surface grew a field this build never saw.
_KNOWN_TOP_LEVEL_FIELDS = frozenset({"Number", "StatusCode", "Status"}) | (
    _EMPTY_ONLY_FIELD_NAMES
)

_nonempty_field_logged: set[str] = set()
_schema_drift_logged = False
_first_delivered_logged = False


def _warn_first_nonempty_field(field: str) -> None:
    """Log the first time a field only ever seen empty carries a real value."""
    if field in _nonempty_field_logged:
        return
    _nonempty_field_logged.add(field)
    _LOGGER.warning(
        "Nova Post populated the %r field for the first time — this build has "
        "only ever seen it empty, so its shape and unit are unconfirmed. "
        "Please help us settle it by opening an issue and pasting this line, "
        "redacted diagnostics ideal (never the raw value): %s",
        field,
        NEW_ISSUE_URL,
    )


def _warn_schema_drift(fields: list[str]) -> None:
    """Log once when a real response carries a top-level key we never saw."""
    global _schema_drift_logged
    if _schema_drift_logged:
        return
    _schema_drift_logged = True
    _LOGGER.warning(
        "Nova Post response carries field(s) not in this integration's known "
        "shape (%s) — the public surface may have grown since this was "
        "written. Please help us map it by opening an issue and pasting this "
        "line: %s",
        ", ".join(fields),
        NEW_ISSUE_URL,
    )


def _warn_first_delivered() -> None:
    """Log the first ``StatusCode == "9"`` parcel, to settle ``delivered_at``.

    ``delivered_at`` is deliberately left ``None`` rather than guessed from
    ``RecipientDateTime`` or ``ActualDeliveryDate`` — two unconfirmed
    candidates now exist (the 2026-08-10 correction added the second), and a
    real delivered parcel has to decide between them, not this file. This is
    what turns the guess into a settled fact.
    """
    global _first_delivered_logged
    if _first_delivered_logged:
        return
    _first_delivered_logged = True
    _LOGGER.warning(
        "Nova Post reported a delivered parcel (StatusCode 9) for the first "
        "time. This integration does not fill in 'delivered_at' yet — "
        "RecipientDateTime and ActualDeliveryDate are both plausible sources "
        "but neither has ever been confirmed. Please help us settle it by "
        "opening an issue and pasting this line, redacted diagnostics "
        "ideal: %s",
        NEW_ISSUE_URL,
    )


def check_payload_shape(raw: dict) -> None:
    """One-shot WARNINGs for the parts of the payload still unconfirmed.

    Skips the coordinator's pending placeholder (a bare ``{"Number": code}``
    dict with no ``StatusCode``) — that is a normal not-yet-fetched state, not
    a real response to have an opinion about.
    """
    if "StatusCode" not in raw:
        return

    unknown_fields = sorted(
        key
        for key in raw
        if key not in _KNOWN_TOP_LEVEL_FIELDS
        and not any(key.startswith(prefix) for prefix in _EMPTY_ONLY_FIELD_PREFIXES)
    )
    if unknown_fields:
        _warn_schema_drift(unknown_fields)

    for key, value in raw.items():
        if value in (None, ""):
            continue
        if key in _EMPTY_ONLY_FIELD_NAMES or any(
            key.startswith(prefix) for prefix in _EMPTY_ONLY_FIELD_PREFIXES
        ):
            _warn_first_nonempty_field(key)


def _parse_weight_kg(value: Any) -> float | None:
    """Parse ``DocumentWeight`` as a float, ``None`` on anything else.

    Unit is **assumed kilograms** pending a real value — see
    :func:`check_payload_shape`, which warns the first time this field is
    ever seen non-empty.
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_parcel(raw: dict) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key Nova Post does not expose is
    ``None``, never omitted.

    What Nova Post does not give us (or gives us too unconfirmed to trust),
    and why the ``None``s are intentional — see
    carrier-research/api/nova-post/tracking.md#payload--canonical-mapping:

    * **``sender`` / ``receiver``** — populated since the 2026-08-10
      correction. The earlier "no explicit name-bearing field has ever been
      enumerated" claim was an artefact of a partial reading of the probe: a
      full 128-key enumeration named ``SenderFullNameEW``,
      ``RecipientFullName`` and ``RecipientFullNameEW``. Those are now
      first-party field *names*, so ``sender`` reads ``SenderFullNameEW`` and
      ``receiver`` reads ``RecipientFullName`` (falling back to
      ``RecipientFullNameEW`` when the first is empty) — ``.get()``-guarded,
      with the same ``or None`` empty-string normalisation ``pickup_point``
      already uses for this payload's "present but empty" convention, and no
      further validation, since the *values* behind those names are still
      unconfirmed.
    * **``delivered_at``** — still ``None``. ``RecipientDateTime`` used to be
      the only plausible candidate by name; the 2026-08-10 correction added a
      second, ``ActualDeliveryDate``, which reads as the better-named
      candidate but does not settle which one actually populates. Two
      unconfirmed candidates is not a reason to guess between them — a real
      delivered parcel has to decide, so this stays ``None`` with the
      one-shot warning in :func:`_warn_first_delivered`.
    * **``planned_from`` / ``planned_to``** — still ``None``. The earlier "no
      ETA-shaped field was observed in the key list" is no longer true: the
      2026-08-10 correction found ``ScheduledDeliveryDate`` and
      ``AdjustedDate``. Their semantics (point estimate vs. window, which one
      is "planned" vs. "adjusted") are unconfirmed, so this is deliberately
      still not wired up — a decision for a real capture, not a guess.
    * **``url``** — no public consumer tracking-page URL has ever been
      captured for Nova Poshta anywhere in the research. Guessing a
      query-parameter name risks a link that silently 404s for every user.
    * **``history``** — always ``None``; see const.py and the module
      docstring above.

    ``pickup_point`` is ``WarehouseRecipient`` (the destination locker/branch)
    — ``WarehouseSender`` is the origin side and stays raw-only. ``weight`` is
    ``DocumentWeight`` with the unit assumed kilograms (unconfirmed).
    """
    check_payload_shape(raw)

    tracking_code = raw.get("Number")
    status_code = raw.get("StatusCode")
    status = map_parcel_status(status_code)
    delivered = status is ParcelStatus.DELIVERED
    if delivered:
        _warn_first_delivered()

    return {
        "carrier": "Nova Post",
        "barcode": tracking_code,
        "sender": raw.get("SenderFullNameEW") or None,
        "receiver": raw.get("RecipientFullName") or raw.get("RecipientFullNameEW") or None,
        "status": status,
        "raw_status": raw.get("Status") or status_code,
        "delivered": delivered,
        "delivered_at": None,
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": raw.get("WarehouseRecipient") or None,
        "url": None,
        "weight": _parse_weight_kg(raw.get("DocumentWeight")),
        "dimensions": None,
        "history": None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
