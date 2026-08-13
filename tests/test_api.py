"""Tests for the Nova Post API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.nova_post.api import (
    NovaPostApiClient,
    NovaPostApiError,
)
from custom_components.nova_post.const import TRACKING_API_URL

from .payloads import ACTIVE_CODE, in_transit_sample


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
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_body_on_success():
    session = _session_returning(200, in_transit_sample())
    client = NovaPostApiClient(session)

    parcel = await client.async_get_parcel(ACTIVE_CODE)

    assert parcel["number"] == ACTIVE_CODE
    assert parcel["tracking"][0]["code"] == "5"


async def test_get_parcel_requests_the_documented_url():
    session = _session_returning(200, in_transit_sample())
    client = NovaPostApiClient(session)

    await client.async_get_parcel(ACTIVE_CODE)

    (url,), _ = session.get.call_args
    assert url == TRACKING_API_URL.format(ttn=ACTIVE_CODE)


async def test_get_parcel_returns_none_on_404():
    """A bogus/unknown number answers a plain 404 — a normal state, not an
    error."""
    client = NovaPostApiClient(_session_returning(404, {"errors": {"errorMessage": "not_found"}}))
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


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = NovaPostApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(ACTIVE_CODE)


async def test_get_parcel_accepts_alphanumeric_codes():
    """This surface takes any string — cross-border aliases like
    'SHCN8143247690' are not restricted to the old 14-digit format."""
    code = "SHCN8143247690"
    session = _session_returning(200, in_transit_sample(code))
    client = NovaPostApiClient(session)

    parcel = await client.async_get_parcel(code)

    assert parcel["number"] == code
    (url,), _ = session.get.call_args
    assert url == TRACKING_API_URL.format(ttn=code)
