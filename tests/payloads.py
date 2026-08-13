"""Sample Nova Post (``/site/v.1.0/shipments/tracking/{ttn}``) payloads shared
by the test suite.

**2026-08-13: rewritten for the REST surface** (carrier-research/nova-post.md
`## Build`, addendum 2026-08-13). Unlike the old JSON-RPC fixtures these are
no longer "every field present but empty" placeholders — the payload is now
*confirmed*, not reconstructed (a real TTN, `12348`, returned a fully
populated body; see carrier-research/api/nova-post/novapost-tracking.md
"Real captured response"). These fixtures follow that real shape; field names
and nesting match the capture, values are made-up placeholders.

Every ``code`` used below comes straight from
carrier-research/api/nova-post/novapost-tracking.md#status-vocabulary.
"""
from __future__ import annotations

# Numeric TTNs — never a real waybill number, made up for these fixtures only.
ACTIVE_CODE = "20450000000001"
DELIVERED_CODE = "20450000000002"
PICKUP_CODE = "20450000000003"


def _hop(code: str, event_name: str, *, date: str = "2026-04-18T02:17:54.178824Z", **overrides: object) -> dict:
    """Build one ``tracking[]`` entry, matching the real capture's shape."""
    hop = {
        "number": overrides.pop("number", "") or "",
        "date": date,
        "event": overrides.pop("event", "GenericEvent"),
        "event_status": overrides.pop("event_status", "passed"),
        "country_code": overrides.pop("country_code", "UA"),
        "code": code,
        "parcel_number": overrides.pop("parcel_number", None),
        "post_code": overrides.pop("post_code", ""),
        "division_name": overrides.pop("division_name", ""),
        "settlement_name": overrides.pop("settlement_name", ""),
        "settlement_external_id": overrides.pop("settlement_external_id", ""),
        "event_name": event_name,
        "division_coordinates": overrides.pop(
            "division_coordinates", {"latitude": 0.0, "longitude": 0.0}
        ),
    }
    hop.update(overrides)
    return hop


def raw_response(code: str, hop_code: str, event_name: str, **overrides: object) -> dict:
    """Build a full response body with every shape-confirmed key present.

    One default tracking hop reflecting the requested status; ``overrides``
    replaces or adds top-level keys (pass ``tracking=[...]`` to control the
    hop list directly, e.g. for a multi-hop or a pickup-point sample).
    """
    base = {
        "number": code,
        "sender": {
            "country_code": "",
            "settlement": "",
            "divisionId": "",
            "latitude": None,
            "longitude": None,
        },
        "recipient": {
            "country_code": "",
            "settlement": "",
            "divisionId": "",
            "latitude": None,
            "longitude": None,
        },
        "scheduled_delivery_date": "",
        "payer_type": "",
        "total_weight": "",
        "tracking": [_hop(hop_code, event_name, number=code)],
        "alternative_numbers": [code],
        "parcels": [],
        "alternativeNumbersGW": [],
        "alternativeNumbersGWNew": [],
        "deliveryInfo": None,
        "parcelActions": {
            "canSafePlace": False,
            "isSafePlaceOrdered": False,
            "serviceId": None,
        },
    }
    base.update(overrides)
    return base


def registered_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "1", "Ready to send")


def in_transit_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "5", "Sent from the sender's division")


def at_branch_sample(code: str = PICKUP_CODE) -> dict:
    """``code`` 7 — arrived at a branch (as opposed to a locker, 8)."""
    return raw_response(
        code,
        "7",
        "Arrived at the division",
        tracking=[
            _hop(
                "7",
                "Arrived at the division",
                number=code,
                division_name="Example Branch 1",
            )
        ],
    )


def at_locker_sample(code: str = PICKUP_CODE) -> dict:
    """``code`` 8 — arrived at a parcel locker (as opposed to 7)."""
    return raw_response(
        code,
        "8",
        "Arrived at the Postomat",
        tracking=[
            _hop(
                "8",
                "Arrived at the Postomat",
                number=code,
                division_name="Example Locker 1",
            )
        ],
    )


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """``code`` 9 — the "Received" bucket, what ``delivered_at`` infers from."""
    return raw_response(
        code,
        "9",
        "Received at branch 5",
        tracking=[
            _hop(
                "9",
                "Received at branch 5",
                number=code,
                date="2026-04-24T07:50:52.243000Z",
                division_name="branch 5",
            )
        ],
    )


def deleted_sample(code: str = ACTIVE_CODE) -> dict:
    """``code`` 2 — the resolved "Deleted" mapping (nova-post.md UPDATE 2026-08-10)."""
    return raw_response(code, "2", "Deleted")


def problem_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "111", "Failed delivery attempt")


def returning_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "102", "Returns")


def geo_parties_sample(code: str = ACTIVE_CODE) -> dict:
    """``sender``/``recipient`` populated with geography — this surface's
    only party data; no name field exists anywhere on the wire."""
    return raw_response(
        code,
        "5",
        "Sent from the sender's division",
        sender={
            "country_code": "CN",
            "settlement": "",
            "divisionId": "",
            "latitude": 22.7312799,
            "longitude": 113.4868,
        },
        recipient={
            "country_code": "MD",
            "settlement": "Chișinău",
            "divisionId": "1835788",
            "latitude": 47.056743,
            "longitude": 28.889328,
        },
    )


def populated_sample(code: str = ACTIVE_CODE) -> dict:
    """A fully populated response — weight, dimensions, ETA and a two-hop
    history — mirroring the real capture's richness (values made up)."""
    return raw_response(
        code,
        "6",
        "Arrived at the address depot",
        scheduled_delivery_date="2026-04-24T07:24:00.000000Z",
        payer_type="ThirdPerson",
        total_weight=0.36,
        tracking=[
            _hop(
                "6",
                "Arrived at the address depot",
                number=code,
                date="2026-04-18T02:17:54.178824Z",
                division_name="customs terminal Chișinău",
                settlement_name="Chișinău",
                post_code="MD-2069",
            ),
            _hop(
                "9",
                "Received at branch 5",
                number=code,
                date="2026-04-24T07:50:52.243000Z",
                division_name="branch 5",
                settlement_name="Chișinău",
                post_code="MD-2075",
            ),
        ],
        parcels=[
            {
                "number": code,
                "row_number": 1,
                "untied": False,
                "cargo_category_group": "parcel",
                "cargoCategoryId": "97",
                "category_cargo_name": "Parcel",
                "parcel_description": "",
                "insurance_cost": 98.62,
                "insurance_cost_currency_code": "MDL",
                "length": 24,
                "width": 17,
                "height": 2,
                "actual_weight": 0.36,
                "volumetric_weight": 0.163,
                "length_check": None,
                "width_check": None,
                "height_check": None,
                "actual_weight_check": None,
                "volumetric_weight_check": None,
            }
        ],
    )


def schema_drift_sample(code: str = ACTIVE_CODE) -> dict:
    """A response with a top-level key outside the known field inventory."""
    sample = raw_response(code, "5", "Sent from the sender's division")
    sample["someNewField"] = "unexpected"
    return sample
