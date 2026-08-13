"""Diagnostics support for the Nova Post parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NovaPostConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
# **2026-08-13: rewritten for the ``/site/v.1.0/`` REST payload** (see
# parcels.py and carrier-research/api/nova-post/novapost-tracking.md "Real
# captured response") — the old JSON-RPC field names (``Number``,
# ``WarehouseRecipient``, ``CitySender``, …) no longer appear on the wire.
#
# The real capture on file carries no person name, phone or street address at
# all (confirmed: "Every string field above is either a code, a country/
# settlement/branch name or a shipment identifier"), which is a lower bar than
# the old surface — but *location* is still identifying, and this surface adds
# something the old one never had: **GPS coordinates**, per tracking hop
# (``division_coordinates``) and per party (``latitude``/``longitude`` inside
# ``sender``/``recipient``). That is narrower than any address the old surface
# ever redacted, so ``sender``/``recipient`` are redacted as **whole blocks**
# (mirrors ha-dynalogic's ``Addressee``/``ContactInformation`` convention —
# the leaves we do not know the names of are exactly the ones a per-leaf list
# would miss), and every location-shaped leaf inside ``tracking[]`` is
# redacted individually: ``settlement_name``, ``division_name``,
# ``settlement_external_id``, ``post_code`` and ``division_coordinates``.
#
# ``number``/``parcel_number`` echo the tracking code (barcode) at every
# level — top-level, each ``tracking[]`` hop, each ``parcels[]`` entry and
# each ``alternativeNumbersGW``/``alternativeNumbersGWNew`` entry — redacted
# everywhere the key appears, same as the canonical ``barcode``.
# ``alternative_numbers`` is the same identifier in other formats, redacted
# whole. ``parcel_description`` is free text about the shipment's contents;
# ``insurance_cost``/``insurance_cost_currency_code`` are the declared value —
# financial, like every other carrier's declared-value field.
#
# ``country_code`` is deliberately **not** redacted: alone, on a tracking hop
# ("customs terminal in this country"), it is not specific enough to locate a
# person and is genuinely useful for debugging the status mapping.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "pickup_point",
    "url",
    # Nova Post /site/v.1.0/ payload fields (see parcels.py)
    "number",
    "parcel_number",
    "recipient",
    "alternative_numbers",
    "settlement_name",
    "settlement_external_id",
    "division_name",
    "division_coordinates",
    "post_code",
    "parcel_description",
    "insurance_cost",
    "insurance_cost_currency_code",
}


def _redact(data: Any) -> Any:
    """Apply the exact-key redaction pass."""
    return async_redact_data(data, TO_REDACT)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NovaPostConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Nova Post config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": _redact(dict(entry.options)),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": _redact(coordinator.data or []),
        "delivered": _redact(coordinator.delivered or []),
    }
