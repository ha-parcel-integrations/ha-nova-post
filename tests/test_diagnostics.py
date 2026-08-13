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
                "number": "20450000000001",
                "sender": {"country_code": "CN", "latitude": 22.7, "longitude": 113.5},
                "recipient": {"country_code": "MD", "settlement": "Chișinău"},
                "tracking": [
                    {
                        "number": "20450000000001",
                        "code": "5",
                        "event_name": "In transit",
                        "division_name": "Example Branch 1",
                        "settlement_name": "Example City B",
                        "post_code": "MD-2069",
                        "division_coordinates": {"latitude": 47.0, "longitude": 28.8},
                    }
                ],
                "alternative_numbers": ["20450000000001", "SHCN8143247690"],
                "parcels": [
                    {
                        "number": "20450000000001",
                        "parcel_description": "example contents",
                        "insurance_cost": 98.62,
                        "insurance_cost_currency_code": "MDL",
                    }
                ],
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
    raw = result["incoming"][0]["raw"]
    assert raw["number"] == "**REDACTED**"
    # sender/recipient are redacted as whole blocks — they carry GPS
    # coordinates, which is narrower than any address.
    assert raw["sender"] == "**REDACTED**"
    assert raw["recipient"] == "**REDACTED**"
    assert raw["alternative_numbers"] == "**REDACTED**"
    hop = raw["tracking"][0]
    assert hop["number"] == "**REDACTED**"
    assert hop["division_name"] == "**REDACTED**"
    assert hop["settlement_name"] == "**REDACTED**"
    assert hop["post_code"] == "**REDACTED**"
    assert hop["division_coordinates"] == "**REDACTED**"
    parcel = raw["parcels"][0]
    assert parcel["number"] == "**REDACTED**"
    assert parcel["parcel_description"] == "**REDACTED**"
    assert parcel["insurance_cost"] == "**REDACTED**"
    assert parcel["insurance_cost_currency_code"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"
    assert hop["code"] == "5"
    assert hop["event_name"] == "In transit"
