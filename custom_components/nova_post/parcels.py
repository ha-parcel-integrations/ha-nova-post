"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

**2026-08-13: rewritten for the ``/site/v.1.0/`` REST surface**, replacing the
``getStatusDocuments`` JSON-RPC mapping (carrier-research/nova-post.md "##
Build", addendum 2026-08-13; full field table in carrier-research/api/
nova-post/novapost-tracking.md). The trigger was a real captured payload (TTN
``12348``, an in-flight CN→MD parcel) that confirmed ``history``, ``weight``
(kg), ``dimensions`` (cm), ``pickup_point`` and a constructible ``url`` — all
of which the old surface lacked. The one thing lost in the move:
``sender``/``receiver`` carry geography (country/settlement) here, never a
name — the old surface's ``SenderFullNameEW``/``RecipientFullName`` have no
equivalent on this one. ``sender``/``receiver`` are not part of
``KNOWN_CAPABILITIES`` (const.py), so that loss does not show up as a
capability regression on the docs site, but it is a real one.

The payload is now **confirmed**, not reconstructed, so most of this module's
old "first non-empty field" self-reporting (built for a payload whose values
had only ever been seen empty) is gone. What is still a guess and still
warns once: the delivered-at inference (no field is named anything like
``delivered_at`` — the newest "Received"-bucket ``tracking[]`` hop is the best
candidate, not a confirmed one) and an unrecognised status code.
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
    HISTORY_MAX_EVENTS,
    TRACKING_URL_TEMPLATE,
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

# ``tracking[].code`` → canonical ParcelStatus. Nova Post's own published
# 57-code table (carrier-research/api/nova-post/novapost-tracking.md
# "## Status vocabulary"), the authority — the app's independent 18-category
# bucketing corroborates it, in particular the trap that matters most: the
# carrier's own "Delivered" wording (codes 7/8) means *arrived at the branch
# or locker*, not handed over. That is ``at_pickup_point`` here; the carrier's
# word for actually handed over is "Received" (9/10/11/106), mapped to
# ``delivered``. Neither the published table nor the app's bucketing is a
# superset of the other — an unmapped code still falls back to ``unknown``
# with a one-shot warning, same as every other suite carrier.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "1": ParcelStatus.REGISTERED,        # Ready to send
    "2": ParcelStatus.PROBLEM,           # Deleted
    "4": ParcelStatus.IN_TRANSIT,        # Accepted for sending
    "5": ParcelStatus.IN_TRANSIT,        # Sent from the sender's division
    "6": ParcelStatus.IN_TRANSIT,        # Arrived in the recipient's city
    "7": ParcelStatus.AT_PICKUP_POINT,   # Arrived at the division
    "8": ParcelStatus.AT_PICKUP_POINT,   # Arrived at the Postomat
    "9": ParcelStatus.DELIVERED,         # Closed
    "10": ParcelStatus.DELIVERED,        # Closed, money transfer sent to sender
    "11": ParcelStatus.DELIVERED,        # Closed, sender received the money transfer
    "13": ParcelStatus.IN_TRANSIT,       # Arrival at transit sorting centre
    "16": ParcelStatus.IN_TRANSIT,       # Departure from transit sorting centre
    "17": ParcelStatus.IN_TRANSIT,       # Transit-warehouse arrival (carrier: unused)
    "19": ParcelStatus.IN_TRANSIT,       # Transit-warehouse departure (carrier: unused)
    "30": ParcelStatus.IN_TRANSIT,       # Arrived at customs terminal
    "31": ParcelStatus.IN_TRANSIT,       # Departed from customs terminal
    "99": ParcelStatus.PROBLEM,          # Delivery to Postomat impossible
    "101": ParcelStatus.OUT_FOR_DELIVERY,  # Uploaded to the courier
    "102": ParcelStatus.RETURNING,       # Returns (sender ordered a return)
    "103": ParcelStatus.RETURNING,       # Refusal of shipment
    "104": ParcelStatus.IN_TRANSIT,      # Redirecting
    "105": ParcelStatus.PROBLEM,         # Utilization
    "106": ParcelStatus.DELIVERED,       # Received; return-shipment docs created
    "110": ParcelStatus.IN_TRANSIT,      # Transferred to temporary storage
    "111": ParcelStatus.PROBLEM,         # Failed delivery attempt
    "112": ParcelStatus.IN_TRANSIT,      # Delivery date postponed
    "113": ParcelStatus.PROBLEM,         # Storage period expired
    "114": ParcelStatus.IN_TRANSIT,      # Customs: awaiting clearance
    "115": ParcelStatus.IN_TRANSIT,      # Arrived at customs terminal
    "116": ParcelStatus.PROBLEM,         # Broker refusal — under resolution
    "117": ParcelStatus.PROBLEM,         # Cargo not found or lost (customs)
    "118": ParcelStatus.PROBLEM,         # Forbidden content — delivery impossible
    "119": ParcelStatus.IN_TRANSIT,      # Customs: clearance in progress
    "120": ParcelStatus.IN_TRANSIT,      # Customs: clearance completed
    "121": ParcelStatus.IN_TRANSIT,      # Sent to destination city after customs
    "122": ParcelStatus.IN_TRANSIT,      # Customs: preparing documents
    "123": ParcelStatus.PROBLEM,         # Awaiting information from the recipient
    "125": ParcelStatus.IN_TRANSIT,      # Customs: verifying
    "126": ParcelStatus.IN_TRANSIT,      # Customs: document processing
    "127": ParcelStatus.IN_TRANSIT,      # Customs: document processing
    "128": ParcelStatus.IN_TRANSIT,      # Customs: document processing
    "130": ParcelStatus.PROBLEM,         # Import prohibited by customs
    "131": ParcelStatus.RETURNING,       # Return of uncleared cargo
    "132": ParcelStatus.RETURNING,       # Preparing for return
    "133": ParcelStatus.PROBLEM,         # Client communication re: customs comment
    "134": ParcelStatus.IN_TRANSIT,      # Handed to the customs broker
    "135": ParcelStatus.IN_TRANSIT,      # Placed in storage area
    "138": ParcelStatus.PROBLEM,         # Delay: incorrect recipient information
    "141": ParcelStatus.PROBLEM,         # Storage period expired
    "144": ParcelStatus.PROBLEM,         # Storage period expired
    "149": ParcelStatus.IN_TRANSIT,      # In storage
    "155": ParcelStatus.PROBLEM,         # Transferred for disposal
    "197": ParcelStatus.IN_TRANSIT,      # Customs inspection
    "198": ParcelStatus.IN_TRANSIT,      # Customs inspection
    "199": ParcelStatus.IN_TRANSIT,      # Customs: clearance stage
    "999": ParcelStatus.UNKNOWN,         # Undetermined — the carrier's own catch-all
}

# "Received" bucket — the carrier's own word for actually handed over, as
# opposed to merely arrived and waiting. Used both by the status map above and
# by ``_delivered_at`` below to find which hop was the delivery itself.
_RECEIVED_CODES = frozenset({"9", "10", "11", "106"})

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Nova Post tracking code — help us map it. Open an issue "
        "and paste this line: %s\n  code=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a Nova Post ``tracking[].code`` to a canonical :class:`ParcelStatus`.

    ``None`` (no scan yet, or a not-yet-fetched placeholder) reports
    ``unknown`` silently; an unrecognised code reports ``unknown`` with a
    one-shot warning. Map on the numeric ``code`` only — never on
    ``event_name``, the human-readable text paired with it, the same trap as
    SunYou's ``toLanguage``-localised event text.
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


# ---------------------------------------------------------------------------
# Pre-1.0 self-reporting (see .github/CONVENTIONS.md § Pre-1.0 releases)
# ---------------------------------------------------------------------------

# The full top-level key inventory of a real captured response (TTN 12348,
# carrier-research/api/nova-post/novapost-tracking.md "Real captured
# response"). A key outside this set is schema drift worth hearing about —
# the public surface may have grown since this was written.
_KNOWN_TOP_LEVEL_FIELDS = frozenset(
    {
        "number",
        "sender",
        "recipient",
        "scheduled_delivery_date",
        "payer_type",
        "total_weight",
        "tracking",
        "alternative_numbers",
        "parcels",
        "alternativeNumbersGW",
        "alternativeNumbersGWNew",
        "deliveryInfo",
        "parcelActions",
    }
)

_schema_drift_logged = False
_delivered_at_inferred_logged = False


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


def _warn_delivered_at_inferred() -> None:
    """Log once, the first time ``delivered_at`` is filled in by inference.

    No field on this surface is named anything like ``delivered_at`` — the
    newest ``tracking[]`` hop whose code falls in the "Received" bucket is the
    best candidate, not a confirmed one (carrier-research/api/nova-post/
    novapost-tracking.md "What the real capture confirms"). This is a one-shot
    heads-up, not a request for a bug report: if a user's own delivery
    timestamp does not match what shows up here, that is useful to know.
    """
    global _delivered_at_inferred_logged
    if _delivered_at_inferred_logged:
        return
    _delivered_at_inferred_logged = True
    _LOGGER.warning(
        "Nova Post marked a parcel delivered — 'delivered_at' is inferred "
        "from the newest tracking event in the carrier's 'Received' bucket, "
        "not a field the carrier names as such. If it does not match the "
        "real delivery time, please open an issue: %s",
        NEW_ISSUE_URL,
    )


def check_payload_shape(raw: dict) -> None:
    """One-shot WARNING for a real response carrying an unknown top-level key.

    Skips the coordinator's pending placeholder (a bare ``{"number": code}``
    dict with no ``tracking`` key) — every real response carries a
    ``tracking`` key (an empty list at worst), so its absence is what marks
    the placeholder rather than a real response to have an opinion about.
    """
    if "tracking" not in raw:
        return

    unknown_fields = sorted(key for key in raw if key not in _KNOWN_TOP_LEVEL_FIELDS)
    if unknown_fields:
        _warn_schema_drift(unknown_fields)


def _tracking_hops(raw: dict) -> list[dict]:
    """Return ``tracking[]`` as a list of dicts, oldest→newest, as returned.

    Confirmed order by the timestamps in the one real capture on file — see
    novapost-tracking.md "What the real capture confirms". Non-dict entries
    are dropped defensively rather than raising.
    """
    hops = raw.get("tracking")
    if not isinstance(hops, list):
        return []
    return [hop for hop in hops if isinstance(hop, dict)]


def _hop_code(hop: dict) -> str | None:
    """Return a tracking hop's ``code`` as a string, or ``None``."""
    code = hop.get("code")
    return str(code) if code not in (None, "") else None


def _format_party(party: Any) -> str | None:
    """Return a ``sender``/``recipient`` block as one display string.

    This surface carries geography only — ``country_code``, ``settlement``,
    ``divisionId``, latitude/longitude — never a name (unlike the old JSON-RPC
    surface's ``SenderFullNameEW``/``RecipientFullName``). ``"Chișinău, MD"``
    when both are present, one alone when only one is, ``None`` when neither
    is (the sender side of an international parcel commonly has no
    ``settlement`` at all — see the real capture).
    """
    if not isinstance(party, dict):
        return None
    settlement = str(party.get("settlement") or "").strip()
    country = str(party.get("country_code") or "").strip()
    if settlement and country:
        return f"{settlement}, {country}"
    return settlement or country or None


def _pickup_point(hops: list[dict]) -> str | None:
    """Return the newest tracking hop's ``division_name``, or ``None``.

    Not gated on status: the old surface's ``WarehouseRecipient`` was shown
    regardless of whether the parcel had actually arrived yet, and this
    mirrors that — the most recent hop's location is informative even while a
    parcel is still in transit.
    """
    if not hops:
        return None
    return str(hops[-1].get("division_name") or "").strip() or None


def _delivered_at(hops: list[dict]) -> str | None:
    """Return the timestamp of the newest "Received"-bucket hop, or ``None``.

    Scans from the newest hop backwards — see :func:`_warn_delivered_at_inferred`
    for why this is a best-candidate inference, not a confirmed field.
    """
    for hop in reversed(hops):
        if _hop_code(hop) in _RECEIVED_CODES:
            _warn_delivered_at_inferred()
            return hop.get("date")
    return None


def build_history(hops: list[dict], *, max_events: int = HISTORY_MAX_EVENTS) -> list[dict]:
    """Build the canonical ``history`` list from ``tracking[]``.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``tracking[]`` is already oldest→newest (see
    :func:`_tracking_hops`), so this only drops hops without a usable
    timestamp and caps to the most recent ``max_events``.
    """
    entries = [
        {
            "timestamp": hop["date"],
            "status": map_parcel_status(_hop_code(hop)),
            "raw_status": hop.get("event_name") or _hop_code(hop),
        }
        for hop in hops
        if hop.get("date")
    ]
    return entries[-max_events:]


def _parse_weight_kg(value: Any) -> float | None:
    """Parse ``total_weight`` as a float, ``None`` on anything else.

    Confirmed kilograms on a real capture (``total_weight: 0.36`` against a
    24×17×2 cm parcel) — see novapost-tracking.md "What the real capture
    confirms".
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dimensions(parcels: Any) -> dict | None:
    """Return the canonical ``dimensions`` dict from ``parcels[0]``, or ``None``.

    Confirmed centimetres on the same real capture as the weight above
    (``length: 24, width: 17, height: 2`` against ``total_weight: 0.36``).
    Only the first ``parcels[]`` entry is read — a multi-parcel shipment's
    later entries are not aggregated, a deliberate scope decision (see
    CLAUDE.md) rather than a research finding.
    """
    if not isinstance(parcels, list) or not parcels or not isinstance(parcels[0], dict):
        return None
    parcel = parcels[0]
    try:
        length = int(parcel["length"])
        width = int(parcel["width"])
        height = int(parcel["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{length} x {width} x {height} cm",
    }


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key Nova Post does not expose is
    ``None``, never omitted.

    Build decisions worth knowing (see CLAUDE.md for the full writeup):

    * **``sender``/``receiver`` are geography, not identity** — this surface
      names no party. A real regression from the old surface's
      ``SenderFullNameEW``/``RecipientFullName``, accepted for the fields this
      move gains.
    * **``planned_from`` and ``planned_to`` are both ``scheduled_delivery_date``.**
      The field is a single point estimate, not a ``from``/``to`` window (on
      the one capture on file it lands 26 minutes before the final tracking
      hop) — represented as a zero-width window rather than leaving one end
      ``None``, so sorting on ``planned_from`` still works.
    * **``delivered_at`` is inferred**, not read from a named field — see
      :func:`_delivered_at`.
    * **``pickup_point`` and ``raw_status`` come from the newest tracking hop**,
      regardless of whether that hop's own code maps to ``at_pickup_point``.
    * **``url`` is always constructible** once a tracking code exists, even for
      a code the carrier does not (yet) recognise — the tracking *page* takes
      any string, same as this API route.
    """
    check_payload_shape(raw)

    tracking_code = raw.get("number")
    hops = _tracking_hops(raw)
    latest = hops[-1] if hops else None
    code = _hop_code(latest) if latest else None
    status = map_parcel_status(code)
    delivered = status is ParcelStatus.DELIVERED
    scheduled = raw.get("scheduled_delivery_date") or None

    return {
        "carrier": "Nova Post",
        "barcode": tracking_code,
        "sender": _format_party(raw.get("sender")),
        "receiver": _format_party(raw.get("recipient")),
        "status": status,
        "raw_status": (latest.get("event_name") or code) if latest else None,
        "delivered": delivered,
        "delivered_at": _delivered_at(hops) if delivered else None,
        "planned_from": scheduled,
        "planned_to": scheduled,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": _pickup_point(hops),
        "url": (
            TRACKING_URL_TEMPLATE.format(ttn=tracking_code) if tracking_code else None
        ),
        "weight": _parse_weight_kg(raw.get("total_weight")),
        "dimensions": _dimensions(raw.get("parcels")),
        "history": build_history(hops) if include_history else None,
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
