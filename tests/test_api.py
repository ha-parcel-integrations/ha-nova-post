"""Tests for the Nova Post API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.nova_post.api import (
    NovaPostApiClient,
    NovaPostApiError,
)

from .payloads import ACTIVE_CODE, in_transit_sample, not_found_sample


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_data_item_on_success():
    session = _session_returning(200, {"success": True, "data": [in_transit_sample()]})
    client = NovaPostApiClient(session)

    parcel = await client.async_get_parcel(ACTIVE_CODE)

    assert parcel["Number"] == ACTIVE_CODE
    assert parcel["StatusCode"] == "5"


async def test_get_parcel_sends_the_documented_request_body():
    session = _session_returning(200, {"success": True, "data": [in_transit_sample()]})
    client = NovaPostApiClient(session)

    await client.async_get_parcel(ACTIVE_CODE)

    _, kwargs = session.post.call_args
    body = kwargs["json"]
    assert body["apiKey"] == ""  # deliberate: always the literal empty string
    assert body["modelName"] == "TrackingDocument"
    assert body["calledMethod"] == "getStatusDocuments"
    assert body["methodProperties"]["Documents"] == [
        {"DocumentNumber": ACTIVE_CODE}
    ]


async def test_get_parcel_returns_none_when_not_found():
    """StatusCode 3 ('Номер не знайдено') is a normal state, not an error —
    the not-found signal itself, confirmed live against a bogus TTN."""
    client = NovaPostApiClient(
        _session_returning(200, {"success": True, "data": [not_found_sample()]})
    )
    assert await client.async_get_parcel("20450000000000") is None


async def test_get_parcel_raises_on_error_status():
    client = NovaPostApiClient(_session_returning(500, {}))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = NovaPostApiClient(_session_returning(200, "not json"))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = NovaPostApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_success_false():
    """success: false never comes from the not-found case (that is still
    success: true) — treated as an unexpected envelope, never branched on as
    if it meant "not found"."""
    client = NovaPostApiClient(
        _session_returning(200, {"success": False, "errors": ["API key incorrect"]})
    )
    with pytest.raises(NovaPostApiError) as err:
        await client.async_get_parcel(ACTIVE_CODE)
    assert "API key incorrect" in str(err.value)


async def test_get_parcel_raises_on_success_false_without_errors():
    client = NovaPostApiClient(_session_returning(200, {"success": False}))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_empty_data_list():
    client = NovaPostApiClient(_session_returning(200, {"success": True, "data": []}))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_missing_data_key():
    client = NovaPostApiClient(_session_returning(200, {"success": True}))
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_raises_on_non_object_data_item():
    client = NovaPostApiClient(
        _session_returning(200, {"success": True, "data": ["not-a-dict"]})
    )
    with pytest.raises(NovaPostApiError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = NovaPostApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(ACTIVE_CODE)
