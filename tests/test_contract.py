"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime

import pytest

from custom_components.nova_post.const import ParcelStatus
from custom_components.nova_post.parcels import normalize_parcel, parse_iso

from .payloads import (
    ACTIVE_CODE,
    PICKUP_CODE,
    _hop,
    at_branch_sample,
    in_transit_sample,
    populated_sample,
    problem_sample,
    raw_response,
    returning_sample,
)

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
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


def _collected() -> dict:
    return raw_response(
        PICKUP_CODE,
        "9",
        "Closed",
        tracking=[
            _hop(
                "7",
                "Arrived at the division",
                date="2026-04-29T09:00:00Z",
                division_name="Example Branch 1",
            ),
            _hop(
                "9",
                "Closed",
                date="2026-04-29T16:00:00Z",
                division_name="Example Branch 1",
            ),
        ],
    )


def _moment_only() -> dict:
    sample = in_transit_sample()
    sample["scheduled_delivery_date"] = "2099-04-29T13:00:00Z"
    return sample


def _date_only() -> dict:
    sample = in_transit_sample()
    sample["scheduled_delivery_date"] = "2099-04-29"
    return sample


def _scheduled_while_waiting() -> dict:
    sample = at_branch_sample()
    sample["scheduled_delivery_date"] = "2099-04-29T13:00:00Z"
    return sample


def _transit_scan_location() -> dict:
    return raw_response(
        ACTIVE_CODE,
        "5",
        "Sent",
        tracking=[_hop("5", "Sent", division_name="Example Sorting Centre")],
    )


SAMPLES = {
    "delivered": populated_sample,
    "active": in_transit_sample,
    "at_pickup_point": at_branch_sample,
    "collected": _collected,
    "returning": returning_sample,
    "problem": problem_sample,
    "moment_only": _moment_only,
    "date_only": _date_only,
    "scheduled_while_waiting": _scheduled_while_waiting,
    "transit_scan_location": _transit_scan_location,
    "bare": lambda: {"number": "20450000000009"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_waiting_parcel_loses_its_scheduled_window():
    parcel = normalize_parcel(_scheduled_while_waiting())
    assert parcel["status"] is ParcelStatus.AT_PICKUP_POINT
    assert parcel["planned_from"] is None


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_collected())
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-04-29T16:00:00Z"
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Branch 1"


def test_a_transit_scan_location_is_not_a_pickup_point():
    parcel = normalize_parcel(_transit_scan_location())
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_a_moment_ends_at_the_end_of_that_day():
    parcel = normalize_parcel(_moment_only())
    start = parse_iso(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert end.date() == start.astimezone(end.tzinfo).date()


def test_a_date_covers_the_whole_day():
    parcel = normalize_parcel(_date_only())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert start.date() == end.date()
