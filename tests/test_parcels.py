"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the carrier-specific mapping (the part you
rewrite per carrier) can be tested as plain functions.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nova_post.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    ParcelStatus,
)
from custom_components.nova_post.parcels import (
    apply_delivered_filter,
    check_payload_shape,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    sort_parcels_by_ts,
)

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    PICKUP_CODE,
    at_branch_sample,
    at_locker_sample,
    deleted_sample,
    delivered_sample,
    geo_parties_sample,
    in_transit_sample,
    populated_sample,
    problem_sample,
    registered_sample,
    returning_sample,
    schema_drift_sample,
)

# ---------------------------------------------------------------------------
# map_parcel_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("1", ParcelStatus.REGISTERED),
        ("2", ParcelStatus.PROBLEM),
        ("4", ParcelStatus.IN_TRANSIT),
        ("5", ParcelStatus.IN_TRANSIT),
        ("6", ParcelStatus.IN_TRANSIT),
        ("7", ParcelStatus.AT_PICKUP_POINT),
        ("8", ParcelStatus.AT_PICKUP_POINT),
        ("9", ParcelStatus.DELIVERED),
        ("10", ParcelStatus.DELIVERED),
        ("11", ParcelStatus.DELIVERED),
        ("101", ParcelStatus.OUT_FOR_DELIVERY),
        ("102", ParcelStatus.RETURNING),
        ("106", ParcelStatus.DELIVERED),
        ("111", ParcelStatus.PROBLEM),
        ("999", ParcelStatus.UNKNOWN),
    ],
)
def test_map_parcel_status_known(code, expected):
    assert map_parcel_status(code) == expected


def test_map_parcel_status_missing_is_unknown():
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status("") == ParcelStatus.UNKNOWN


def test_map_parcel_status_unmapped_is_unknown():
    assert map_parcel_status("77777") == ParcelStatus.UNKNOWN


def test_unmapped_status_warns_only_once(caplog):
    assert map_parcel_status("77777") == ParcelStatus.UNKNOWN
    assert map_parcel_status("77777") == ParcelStatus.UNKNOWN
    assert caplog.text.count("code=77777") == 1
    assert "issues/new" in caplog.text


def test_status_2_maps_to_problem_at_pickup_bucket_edge():
    """Codes 7/8 are 'arrived, waiting' — at_pickup_point, not delivered; the
    carrier's own 'Received' bucket (9/10/11/106) is delivered."""
    assert map_parcel_status("7") != ParcelStatus.DELIVERED
    assert map_parcel_status("9") == ParcelStatus.DELIVERED


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    # A naive value is assumed UTC so mixed lists still sort.
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


# ---------------------------------------------------------------------------
# check_payload_shape — pre-1.0 self-reporting
# ---------------------------------------------------------------------------


def test_check_payload_shape_silent_on_known_shape():
    check_payload_shape(in_transit_sample())
    check_payload_shape(populated_sample())


def test_check_payload_shape_skips_pending_placeholder(caplog):
    """The coordinator's ``{"number": code}`` placeholder has no ``tracking``
    key and must never be treated as a real response."""
    check_payload_shape({"number": ACTIVE_CODE})
    assert caplog.text == ""


def test_check_payload_shape_warns_on_schema_drift(caplog):
    check_payload_shape(schema_drift_sample())
    assert "someNewField" in caplog.text


def test_check_payload_shape_schema_drift_warns_only_once(caplog):
    check_payload_shape(schema_drift_sample())
    check_payload_shape(schema_drift_sample())
    assert caplog.text.count("someNewField") == 1


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_normalize_delivered_parcel(caplog):
    parcel = normalize_parcel(delivered_sample())
    assert parcel["carrier"] == "Nova Post"
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "Received at branch 5"
    assert parcel["delivered"] is True
    # Inferred from the newest "Received"-bucket hop — see _delivered_at.
    assert parcel["delivered_at"] == "2026-04-24T07:50:52.243000Z"
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    # No name field on this surface at all.
    assert parcel["sender"] is None
    assert parcel["receiver"] is None
    # Always constructible once a barcode exists.
    assert parcel["url"] == f"https://novaposhta.ua/tracking/{DELIVERED_CODE}"
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["history"] is None  # include_history=False by default
    assert "delivered" in caplog.text.lower()  # delivered_at-inferred self-report


def test_normalize_delivered_at_inferred_warning_fires_once(caplog):
    normalize_parcel(delivered_sample())
    normalize_parcel(delivered_sample())
    assert caplog.text.count("inferred") == 1


def test_normalize_in_transit_parcel():
    parcel = normalize_parcel(in_transit_sample())
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False
    assert parcel["pickup"] is False
    assert parcel["delivered_at"] is None


def test_normalize_registered_parcel():
    parcel = normalize_parcel(registered_sample())
    assert parcel["status"] == ParcelStatus.REGISTERED
    assert parcel["raw_status"] == "Ready to send"


def test_normalize_branch_pickup_parcel():
    """code 7 — arrived at a branch."""
    parcel = normalize_parcel(at_branch_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Branch 1"
    assert parcel["barcode"] == PICKUP_CODE


def test_normalize_locker_pickup_parcel():
    """code 8 — arrived at a locker. Distinct source code from 7 (branch),
    same canonical bucket."""
    parcel = normalize_parcel(at_locker_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Locker 1"


def test_normalize_problem_parcel():
    parcel = normalize_parcel(problem_sample())
    assert parcel["status"] == ParcelStatus.PROBLEM


def test_normalize_returning_parcel():
    parcel = normalize_parcel(returning_sample())
    assert parcel["status"] == ParcelStatus.RETURNING


def test_normalize_deleted_status_maps_to_problem():
    """code 2 — resolved 2026-08-10 (see nova-post.md UPDATE 2026-08-10)."""
    parcel = normalize_parcel(deleted_sample())
    assert parcel["status"] == ParcelStatus.PROBLEM


def test_normalize_pending_placeholder():
    """A tracked-but-not-yet-fetched code still yields a full parcel dict,
    including a constructible url — the tracking page takes any string."""
    parcel = normalize_parcel({"number": "20450000000009"})
    assert parcel["barcode"] == "20450000000009"
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None
    assert parcel["weight"] is None
    assert parcel["history"] is None
    assert parcel["url"] == "https://novaposhta.ua/tracking/20450000000009"


def test_normalize_sender_receiver_are_geography_not_identity():
    """This surface names no party — only country/settlement, unlike the old
    JSON-RPC surface's SenderFullNameEW/RecipientFullName."""
    parcel = normalize_parcel(geo_parties_sample())
    assert parcel["sender"] == "CN"  # no settlement on the sender side
    assert parcel["receiver"] == "Chișinău, MD"


def test_normalize_sender_receiver_absent_is_none():
    parcel = normalize_parcel(in_transit_sample())
    assert parcel["sender"] is None
    assert parcel["receiver"] is None


def test_normalize_weight_parses_total_weight():
    parcel = normalize_parcel(populated_sample())
    assert parcel["weight"] == 0.36


def test_normalize_weight_none_when_unparseable():
    raw = populated_sample()
    raw["total_weight"] = "not-a-number"
    assert normalize_parcel(raw)["weight"] is None


def test_normalize_dimensions_from_first_parcel():
    parcel = normalize_parcel(populated_sample())
    assert parcel["dimensions"] == {
        "length": 24,
        "width": 17,
        "height": 2,
        "text": "24 x 17 x 2 cm",
    }


def test_normalize_dimensions_none_when_parcels_empty():
    assert normalize_parcel(in_transit_sample())["dimensions"] is None


def test_normalize_planned_from_and_to_both_read_scheduled_delivery_date():
    """A single point estimate, not a window — represented as a zero-width
    window rather than leaving one end None."""
    parcel = normalize_parcel(populated_sample())
    assert parcel["planned_from"] == "2026-04-24T07:24:00.000000Z"
    assert parcel["planned_from"] == parcel["planned_to"]


def test_normalize_history_disabled_by_default():
    assert normalize_parcel(populated_sample())["history"] is None


def test_normalize_history_when_included():
    parcel = normalize_parcel(populated_sample(), include_history=True)
    history = parcel["history"]
    assert len(history) == 2
    assert history[0]["timestamp"] == "2026-04-18T02:17:54.178824Z"
    assert history[0]["status"] == ParcelStatus.IN_TRANSIT  # code 6
    assert history[1]["status"] == ParcelStatus.DELIVERED  # code 9
    assert history[1]["raw_status"] == "Received at branch 5"


def test_normalize_history_caps_at_max_events():
    raw = populated_sample()
    raw["tracking"] = [
        {
            "number": ACTIVE_CODE,
            "date": f"2026-04-{i:02d}T00:00:00Z",
            "event": "GenericEvent",
            "event_status": "passed",
            "country_code": "UA",
            "code": "5",
            "parcel_number": ACTIVE_CODE,
            "post_code": "",
            "division_name": "",
            "settlement_name": "",
            "settlement_external_id": "",
            "event_name": "In transit",
            "division_coordinates": {"latitude": 0.0, "longitude": 0.0},
        }
        for i in range(1, 26)
    ]
    parcel = normalize_parcel(raw, include_history=True)
    assert len(parcel["history"]) == 20
    assert parcel["history"][-1]["timestamp"] == "2026-04-25T00:00:00Z"


def test_normalize_keeps_raw_payload():
    raw = in_transit_sample()
    assert normalize_parcel(raw)["raw"] is raw


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels


def test_capabilities_are_known_values():
    """A typo here would silently misreport this carrier on the docs site."""
    assert CAPABILITIES <= KNOWN_CAPABILITIES


def test_capabilities_reflect_the_rest_surface():
    assert CAPABILITIES == {
        "weight",
        "dimensions",
        "delivery_window",
        "pickup_point",
        "url",
        "history",
    }
