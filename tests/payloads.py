"""Sample Nova Post (``getStatusDocuments``) payloads shared by the test suite.

No real payload has ever been captured — the one live probe used a bogus TTN
and every field came back empty (see
carrier-research/api/nova-post/tracking.md). These fixtures follow the
BUILD_PLAN's instruction: every field present as a key (matching the
shape-confirmed field list), populated with clearly-fake placeholder values
for the "populated" samples. Keep them in one module rather than inline in
each test — when the real shape turns out to differ, there is exactly one
place to fix.

Every ``StatusCode`` used below comes straight from
carrier-research/api/nova-post/tracking.md#status-vocabulary.
"""
from __future__ import annotations

# 14-digit numeric TTNs — the format confirmed in BUILD_PLAN.md ("tracking-code
# format"). Never a real waybill number: made up for these fixtures only.
ACTIVE_CODE = "20450000000001"
DELIVERED_CODE = "20450000000002"
PICKUP_CODE = "20450000000003"


def raw_response(
    code: str, status_code: str, status_text: str, **overrides: object
) -> dict:
    """Build a ``data[0]`` item with every shape-confirmed key present.

    Defaults every field to ``""`` — the value the one live probe actually
    returned for everything except ``Number``/``StatusCode``/``Status``.
    ``overrides`` lets a specific test populate one or more fields to exercise
    the pre-1.0 "first non-empty value" warnings.
    """
    base = {
        "Number": code,
        "StatusCode": status_code,
        "Status": status_text,
        "DateCreated": "",
        "RecipientDateTime": "",
        "CargoType": "",
        "DocumentCost": "",
        "AnnouncedPrice": "",
        "DocumentWeight": "",
        "CitySender": "",
        "CityRecipient": "",
        "WarehouseSender": "",
        "WarehouseRecipient": "",
        "PhoneSender": "",
        # Added 2026-08-10 — the 128-key enumeration (tracking.md "Correction
        # 2026-08-10"). Present as empty keys by default, same as every other
        # field above; individual tests override the ones they exercise.
        "ScheduledDeliveryDate": "",
        "AdjustedDate": "",
        "ActualDeliveryDate": "",
        "RecipientFullName": "",
        "RecipientFullNameEW": "",
        "SenderFullNameEW": "",
        "WarehouseRecipientAddress": "",
        "WarehouseRecipientNumber": "",
        "CategoryOfWarehouse": "",
        "ParentBranchName": "",
        "FactualWeight": "",
        "VolumeWeight": "",
        "CalculatedWeight": "",
        "CheckWeight": "",
        "PaymentStatus": "",
        "UndeliveryReasons": "",
        "UndeliveryReasonsDate": "",
        "UndeliveryReasonsSubtypeDescription": "",
        "TrackingUpdateDate": "",
        "DateScan": "",
        "DateMoving": "",
        "Declarations": "",
        "Services": "",
        "Packaging": "",
    }
    base.update(overrides)
    return base


def not_found_sample(code: str = "20450000000000") -> dict:
    """The not-found envelope — the only shape live-confirmed on the wire."""
    return raw_response(code, "3", "Номер не знайдено")


def registered_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "1", "Нова накладна")


def in_transit_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "5", "В дорозі")


def at_branch_sample(code: str = PICKUP_CODE) -> dict:
    """``StatusCode`` 7 — arrived at a branch (as opposed to a locker, 8)."""
    return raw_response(
        code, "7", "Прибуло у відділення", WarehouseRecipient="Example Branch 1"
    )


def at_locker_sample(code: str = PICKUP_CODE) -> dict:
    """``StatusCode`` 8 — arrived at a parcel locker (as opposed to 7)."""
    return raw_response(
        code, "8", "Прибуло у поштомат", WarehouseRecipient="Example Locker 1"
    )


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    return raw_response(code, "9", "Отримано")


def deleted_sample(code: str = ACTIVE_CODE) -> dict:
    """``StatusCode`` 2 — the genuinely disputed mapping (BUILD_PLAN.md §4)."""
    return raw_response(code, "2", "Видалено")


def problem_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "12", "Проблемне відправлення")


def returning_sample(code: str = ACTIVE_CODE) -> dict:
    return raw_response(code, "11", "Повернення")


def populated_sample(code: str = ACTIVE_CODE) -> dict:
    """A synthetic *fully populated* response, fields never confirmed by a
    real payload — every value here is a made-up placeholder, used only to
    exercise the pre-1.0 "first non-empty value" self-reporting warnings.
    """
    return raw_response(
        code,
        "5",
        "В дорозі",
        DateCreated="2026-04-27 10:00:00",
        RecipientDateTime="2026-04-29 13:12:42",
        CargoType="Parcel",
        DocumentCost="150",
        AnnouncedPrice="150",
        DocumentWeight="1.25",
        CitySender="Example City A",
        CityRecipient="Example City B",
        WarehouseSender="Example Warehouse 1",
        WarehouseRecipient="Example Warehouse 2",
        PhoneSender="380000000000",
    )


def named_parties_sample(code: str = ACTIVE_CODE) -> dict:
    """``SenderFullNameEW``/``RecipientFullName`` both populated — the
    primary sender/receiver source pair (tracking.md "Correction
    2026-08-10")."""
    return raw_response(
        code,
        "5",
        "В дорозі",
        SenderFullNameEW="Example Sender LLC",
        RecipientFullName="Приклад Отримувач",
        RecipientFullNameEW="Example Recipient",
    )


def named_parties_ew_fallback_sample(code: str = ACTIVE_CODE) -> dict:
    """``RecipientFullName`` empty, only the EW variant populated — exercises
    the receiver fallback in ``normalize_parcel``."""
    return raw_response(
        code,
        "5",
        "В дорозі",
        SenderFullNameEW="Example Sender LLC",
        RecipientFullNameEW="Example Recipient",
    )


def schema_drift_sample(code: str = ACTIVE_CODE) -> dict:
    """A response with a top-level key outside the known field inventory."""
    sample = raw_response(code, "5", "В дорозі")
    sample["SomeNewField"] = "unexpected"
    return sample
