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
# Per carrier-research/api/nova-post/tracking.md ("Payload → canonical
# mapping" / diagnostics redaction):
# * ``Number`` is the barcode (it echoes the request) — redacted both under
#   its own payload key and under the canonical ``barcode``.
# * ``CitySender``/``CityRecipient``-class fields and ``WarehouseSender``/
#   ``WarehouseRecipient`` (the pickup-point branch/locker) are redacted even
#   though a branch identity is arguably not personal data — every other
#   suite carrier redacts pickup-point identity the same way (SunYou's
#   ``office``, An Post's ``deliveryPin``/``parcelLockerPin``), and a specific
#   Nova Poshta branch a named parcel sits in narrows down a person's
#   location just as much as an address would.
# * ``PhoneSender`` is the only phone field actually enumerated on the live
#   probe, but the Sender/Recipient field-family pairing makes a
#   recipient-side phone plausible too — redact defensively on any ``Phone*``
#   key via the key-matching pass below, not just the one confirmed name.
# * ``DocumentCost``/``AnnouncedPrice`` are the declared shipment value —
#   financial, redacted like every other carrier's declared-value field.
# * **Added 2026-08-10**, from the 128-key enumeration
#   (tracking.md#correction-2026-08-10--the-item-carries-128-keys-not-thirteen):
#   ``RecipientFullName``/``RecipientFullNameEW``/``SenderFullNameEW`` (party
#   names — ``sender``/``receiver`` now read these, see parcels.py),
#   ``WarehouseRecipientAddress``/``WarehouseRecipientNumber``/
#   ``ParentBranchName`` (fuller pickup-point identity alongside
#   ``WarehouseRecipient``), ``UndeliveryReasons``/``UndeliveryReasonsDate``/
#   ``UndeliveryReasonsSubtypeDescription`` (free-text about why a delivery
#   failed — can easily carry an address or a name) and ``PaymentStatus``
#   (financial, like ``DocumentCost``/``AnnouncedPrice`` above). These sit
#   alongside the existing exact-name list and the City*/Warehouse*/Phone*
#   prefix pass below, not in place of either.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "pickup_point",
    "url",
    # Nova Poshta payload fields (see tracking.md#payload)
    "Number",
    "CitySender",
    "CityRecipient",
    "CitySenderDescription",
    "CityRecipientDescription",
    "WarehouseSender",
    "WarehouseRecipient",
    "PhoneSender",
    "PhoneRecipient",
    "DocumentCost",
    "AnnouncedPrice",
    # Added 2026-08-10 — see the comment block above
    "RecipientFullName",
    "RecipientFullNameEW",
    "SenderFullNameEW",
    "WarehouseRecipientAddress",
    "WarehouseRecipientNumber",
    "ParentBranchName",
    "UndeliveryReasons",
    "UndeliveryReasonsDate",
    "UndeliveryReasonsSubtypeDescription",
    "PaymentStatus",
}

# Nova Poshta's exact field-family names beyond the ones enumerated above are
# unconfirmed (the one live probe returned every field empty — see
# tracking.md). Redact defensively on any key matching one of these families
# rather than trusting the fixed set above to be complete.
_REDACT_KEY_PATTERNS = ("City", "Warehouse", "Phone")


def _redact_unconfirmed_field_families(data: Any) -> Any:
    """Recursively blank any dict key matching an unconfirmed field family.

    Runs in addition to :func:`async_redact_data` (which only matches exact
    keys in ``TO_REDACT``), so a City*/Warehouse*/Phone* sibling that has not
    been enumerated by name is still caught.
    """
    if isinstance(data, dict):
        return {
            key: (
                "**REDACTED**"
                if isinstance(key, str)
                and any(key.startswith(prefix) for prefix in _REDACT_KEY_PATTERNS)
                else _redact_unconfirmed_field_families(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact_unconfirmed_field_families(item) for item in data]
    return data


def _redact(data: Any) -> Any:
    """Apply both the exact-key and the field-family redaction passes."""
    return async_redact_data(_redact_unconfirmed_field_families(data), TO_REDACT)


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
