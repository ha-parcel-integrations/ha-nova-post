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
    to_iso_timestamp,
)

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    PICKUP_CODE,
    at_branch_sample,
    at_locker_sample,
    deleted_sample,
    delivered_sample,
    in_transit_sample,
    named_parties_ew_fallback_sample,
    named_parties_sample,
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
        ("10", ParcelStatus.RETURNING),
        ("11", ParcelStatus.RETURNING),
        ("12", ParcelStatus.PROBLEM),
    ],
)
def test_map_parcel_status_known(code, expected):
    assert map_parcel_status(code) == expected


def test_map_parcel_status_missing_is_unknown():
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status("") == ParcelStatus.UNKNOWN


def test_map_parcel_status_unmapped_is_unknown():
    assert map_parcel_status("99") == ParcelStatus.UNKNOWN


def test_map_parcel_status_never_reads_status_code_3():
    """StatusCode 3 (not found) is not a parcel state — it is handled in
    api.py before normalize_parcel ever runs, and is deliberately absent from
    the status map, so it would be reported as 'unknown' if it ever leaked
    through."""
    assert map_parcel_status("3") == ParcelStatus.UNKNOWN


def test_unmapped_status_warns_only_once(caplog):
    assert map_parcel_status("77") == ParcelStatus.UNKNOWN
    assert map_parcel_status("77") == ParcelStatus.UNKNOWN
    assert caplog.text.count("StatusCode=77") == 1
    assert "issues/new" in caplog.text


def test_status_2_no_longer_warns_specially(caplog):
    """StatusCode 2's mapping was a genuine, unsettled disagreement between
    two third-party sources; resolved 2026-08-10 by the carrier's own
    published table and its own independent bucketing (both first-party,
    both agree with 'problem'). It now maps silently, like every other
    mapped code — no more every-occurrence self-report."""
    assert map_parcel_status("2") == ParcelStatus.PROBLEM
    assert map_parcel_status("2") == ParcelStatus.PROBLEM
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    # A naive value is assumed UTC so mixed lists still sort.
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_converts_epoch_milliseconds():
    assert to_iso_timestamp(1784203767167) == "2026-07-16T12:09:27.167000+00:00"
    assert to_iso_timestamp("2026-04-29T13:12:42Z") == "2026-04-29T13:12:42Z"
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**20) is None  # out of range -> None, never raises


# ---------------------------------------------------------------------------
# check_payload_shape — pre-1.0 self-reporting (BUILD_PLAN.md §4)
# ---------------------------------------------------------------------------


def test_check_payload_shape_silent_on_fully_empty_response():
    """The shape-confirmed-but-empty response (the only one ever actually
    seen on the wire) triggers no warning at all."""
    check_payload_shape(in_transit_sample())


def test_check_payload_shape_skips_pending_placeholder(caplog):
    """The coordinator's ``{"Number": code}`` placeholder has no StatusCode
    key and must never be treated as a real response."""
    check_payload_shape({"Number": ACTIVE_CODE})
    assert caplog.text == ""


def test_check_payload_shape_warns_once_per_nonempty_field(caplog):
    check_payload_shape(populated_sample())
    for field in ("DateCreated", "RecipientDateTime", "DocumentWeight"):
        assert caplog.text.count(f"'{field}'") == 1
    check_payload_shape(populated_sample())  # second call: no new warnings
    for field in ("DateCreated", "RecipientDateTime", "DocumentWeight"):
        assert caplog.text.count(f"'{field}'") == 1


def test_check_payload_shape_warns_on_city_and_phone_prefix_families(caplog):
    check_payload_shape(populated_sample())
    assert "'CitySender'" in caplog.text
    assert "'CityRecipient'" in caplog.text
    assert "'PhoneSender'" in caplog.text


def test_check_payload_shape_warns_on_schema_drift(caplog):
    check_payload_shape(schema_drift_sample())
    assert "SomeNewField" in caplog.text


def test_check_payload_shape_schema_drift_warns_only_once(caplog):
    check_payload_shape(schema_drift_sample())
    check_payload_shape(schema_drift_sample())
    assert caplog.text.count("SomeNewField") == 1


def test_check_payload_shape_silent_on_2026_08_10_fields(caplog):
    """The 23 field names the 2026-08-10 128-key enumeration newly confirmed
    (ScheduledDeliveryDate, ActualDeliveryDate, RecipientFullName, etc.) are
    now in the known-field inventory, present-but-empty by default in every
    fixture — they must not trip schema drift just for existing."""
    check_payload_shape(in_transit_sample())
    check_payload_shape(named_parties_sample())
    assert "SomeNewField" not in caplog.text
    assert "not in this integration's known" not in caplog.text


def test_check_payload_shape_warns_once_on_newly_confirmed_field(caplog):
    """A 2026-08-10 field carrying a real value for the first time still
    gets the ordinary first-nonempty-value self-report, same as any other
    known-but-unconfirmed field."""
    check_payload_shape(named_parties_sample())
    assert "'SenderFullNameEW'" in caplog.text
    assert "'RecipientFullName'" in caplog.text


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
    assert parcel["raw_status"] == "Отримано"
    assert parcel["delivered"] is True
    # Never guessed — see the "Do not guess delivered_at" trap.
    assert parcel["delivered_at"] is None
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    # No confirmed name field and no confirmed tracking-page URL.
    assert parcel["sender"] is None
    assert parcel["receiver"] is None
    assert parcel["url"] is None
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["history"] is None
    assert "StatusCode 9" in caplog.text  # first-delivered self-report


def test_normalize_first_delivered_warning_fires_once(caplog):
    normalize_parcel(delivered_sample())
    normalize_parcel(delivered_sample())
    assert caplog.text.count("StatusCode 9") == 1


def test_normalize_in_transit_parcel():
    parcel = normalize_parcel(in_transit_sample())
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False
    assert parcel["pickup"] is False


def test_normalize_registered_parcel():
    parcel = normalize_parcel(registered_sample())
    assert parcel["status"] == ParcelStatus.REGISTERED
    assert parcel["raw_status"] == "Нова накладна"


def test_normalize_branch_pickup_parcel():
    """StatusCode 7 — arrived at a branch."""
    parcel = normalize_parcel(at_branch_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Branch 1"
    assert parcel["barcode"] == PICKUP_CODE


def test_normalize_locker_pickup_parcel():
    """StatusCode 8 — arrived at a locker. Distinct source status from 7
    (branch), same canonical bucket — this is the band-ordering trap the
    BUILD_PLAN calls out explicitly."""
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


def test_normalize_deleted_status_maps_to_problem_without_warning(caplog):
    """StatusCode 2 — resolved 2026-08-10 (see nova-post.md UPDATE
    2026-08-10). Mapped to 'problem', no longer a special every-occurrence
    warning."""
    parcel = normalize_parcel(deleted_sample())
    assert parcel["status"] == ParcelStatus.PROBLEM
    assert caplog.text == ""


def test_normalize_not_found_never_reaches_normalize_parcel():
    """StatusCode 3 is filtered out in api.py (returns None) before
    normalize_parcel is ever called with it — normalize_parcel only ever sees
    the coordinator's pending placeholder for an unknown code."""
    parcel = normalize_parcel({"Number": "20450000000000"})
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None


def test_normalize_pending_placeholder():
    """A tracked-but-not-yet-fetched code still yields a full parcel dict."""
    parcel = normalize_parcel({"Number": "20450000000009"})
    assert parcel["barcode"] == "20450000000009"
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["weight"] is None
    assert parcel["history"] is None


def test_normalize_sender_receiver_from_first_party_fields():
    """Sender/receiver were unfilled ('weakest mapping in the table') until
    the 2026-08-10 correction named SenderFullNameEW/RecipientFullName as
    real field names."""
    parcel = normalize_parcel(named_parties_sample())
    assert parcel["sender"] == "Example Sender LLC"
    assert parcel["receiver"] == "Приклад Отримувач"


def test_normalize_sender_receiver_absent_is_none():
    """No name fields populated (the only shape ever actually observed on
    the wire) — still normalises to None, not an empty string."""
    parcel = normalize_parcel(in_transit_sample())
    assert parcel["sender"] is None
    assert parcel["receiver"] is None


def test_normalize_receiver_falls_back_to_ew_variant():
    """RecipientFullName empty, RecipientFullNameEW populated — the fallback
    the research explicitly calls for."""
    parcel = normalize_parcel(named_parties_ew_fallback_sample())
    assert parcel["sender"] == "Example Sender LLC"
    assert parcel["receiver"] == "Example Recipient"


def test_normalize_weight_parses_document_weight():
    parcel = normalize_parcel(populated_sample())
    assert parcel["weight"] == 1.25


def test_normalize_weight_none_when_unparseable():
    raw = populated_sample()
    raw["DocumentWeight"] = "not-a-number"
    assert normalize_parcel(raw)["weight"] is None


def test_normalize_falls_back_to_status_code_without_text():
    raw = in_transit_sample()
    raw["Status"] = ""
    assert normalize_parcel(raw)["raw_status"] == "5"


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


def test_capabilities_omit_unconfirmed_fields():
    """Dimensions, delivery window, url, and history are all still None."""
    assert CAPABILITIES == {"weight", "pickup_point"}
