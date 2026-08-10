"""Tests for Nova Post diagnostics."""
from unittest.mock import MagicMock

from custom_components.nova_post.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": "20450000000001"}]}
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "20450000000001",
            "sender": None,
            "receiver": None,
            "status": "out_for_delivery",
            "pickup_point": "Example Branch 1",
            "raw": {
                "Number": "20450000000001",
                "StatusCode": "5",
                "Status": "В дорозі",
                "WarehouseRecipient": "Example Branch 1",
                "CitySender": "Example City A",
                "PhoneSender": "380000000000",
                "DocumentCost": "150",
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    # tracking codes and payload PII are redacted, at every nesting level
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["pickup_point"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["Number"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["WarehouseRecipient"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["CitySender"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["PhoneSender"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["DocumentCost"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"
    assert result["incoming"][0]["raw"]["StatusCode"] == "5"
    assert result["incoming"][0]["raw"]["Status"] == "В дорозі"


async def test_diagnostics_redacts_unnamed_city_and_phone_siblings():
    """City*/Phone* families are redacted by prefix, not just by the one
    exactly-enumerated name — their full set of sibling keys is unconfirmed
    (see carrier-research/api/nova-post/tracking.md#payload)."""
    from custom_components.nova_post.diagnostics import _redact

    redacted = _redact(
        {
            "CityRecipientDescription": "Example City B",
            "PhoneRecipient": "380000000001",
            "StatusCode": "5",
        }
    )
    assert redacted["CityRecipientDescription"] == "**REDACTED**"
    assert redacted["PhoneRecipient"] == "**REDACTED**"
    assert redacted["StatusCode"] == "5"


async def test_diagnostics_redacts_2026_08_10_named_fields():
    """The fields the 2026-08-10 128-key enumeration newly named — party
    names, fuller pickup-point identity, undelivery reasons, payment
    status — are all exact-key redacted, not just caught defensively by a
    prefix."""
    from custom_components.nova_post.diagnostics import _redact

    redacted = _redact(
        {
            "RecipientFullName": "Приклад Отримувач",
            "RecipientFullNameEW": "Example Recipient",
            "SenderFullNameEW": "Example Sender LLC",
            "WarehouseRecipientAddress": "Example Street 1",
            "WarehouseRecipientNumber": "42",
            "ParentBranchName": "Example Regional Branch",
            "UndeliveryReasons": "Recipient unavailable",
            "UndeliveryReasonsDate": "2026-08-10",
            "UndeliveryReasonsSubtypeDescription": "No answer at the door",
            "PaymentStatus": "Paid",
            "StatusCode": "5",
        }
    )
    for key in (
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
    ):
        assert redacted[key] == "**REDACTED**"
    assert redacted["StatusCode"] == "5"
