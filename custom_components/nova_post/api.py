"""Nova Poshta public tracking API client.

Targets ``novaposhta.ua``'s official JSON-RPC surface, method
``TrackingDocument.getStatusDocuments`` — see
carrier-research/api/nova-post/tracking.md for the full write-up. Contract the
coordinator relies on:

* ``async_get_parcel`` returns the raw ``data[0]`` dict on success,
* returns ``None`` when the carrier reports the tracking code as unknown
  (``StatusCode == "3"``) — a normal, expected state, never an error,
* raises :class:`NovaPostApiError` for anything else (including a
  ``success: false`` envelope, which never comes from the not-found case —
  the not-found case is still ``success: true``),
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)

# Nova Poshta's own signal for "no such tracking number" (Ukrainian:
# "Номер не знайдено"). Confirmed live against a bogus TTN — see
# carrier-research/api/nova-post/tracking.md#envelope-and-the-not-found-signal.
# This is not a parcel state and must never reach the status map.
_STATUS_NOT_FOUND = "3"


class NovaPostApiError(Exception):
    """Raised when a Nova Poshta API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        """Store the detail that triggered the error."""
        super().__init__(f"Nova Poshta API request failed: {detail}")
        self.detail = detail


class NovaPostApiClient:
    """Client for Nova Poshta's public ``getStatusDocuments`` method.

    No authentication in the ordinary sense: **``apiKey`` is always the
    literal empty string.** This is Nova Poshta's official, key-gated JSON-RPC
    API — every other method needs a registered key — but this one method
    (and the unrelated ``Common.getCargoTypes`` reference-data call) are
    deliberately anonymous. Do not add a credential step; see
    carrier-research/api/nova-post/tracking.md#endpoint--request.

    The envelope is always HTTP 200 with ``success: true`` — even for a
    tracking number that does not exist. The only reliable signal is
    ``data[0]["StatusCode"]``, so this client never branches on ``success`` or
    the HTTP status for the not-found case.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the ``data[0]`` dict for a known tracking number, or ``None``
        when Nova Poshta reports it as not found (``StatusCode == "3"``). Any
        other failure envelope or non-2xx status raises
        :class:`NovaPostApiError`; network errors propagate as
        ``aiohttp.ClientError``.

        ``Documents`` is sent as a one-item list — batching multiple
        ``DocumentNumber`` entries per call is unconfirmed (no source ever
        exercised it), so one document per request until proven otherwise.
        """
        body = {
            "apiKey": "",
            "modelName": "TrackingDocument",
            "calledMethod": "getStatusDocuments",
            "methodProperties": {"Documents": [{"DocumentNumber": tracking_code}]},
        }
        async with self._session.post(TRACKING_API_URL, json=body) as response:
            if response.status != 200:
                raise NovaPostApiError(f"HTTP {response.status}")
            try:
                # content_type=None: some consumer endpoints serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise NovaPostApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise NovaPostApiError("unexpected body (not a JSON object)")

        if payload.get("success") is not True:
            raise NovaPostApiError(str(payload.get("errors") or "success: false"))

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            # A bare success with an empty data list is not the documented
            # not-found shape (that is StatusCode "3" on a populated item) —
            # treat it as an unexpected envelope rather than guessing "not
            # found".
            raise NovaPostApiError("success envelope carried no data item")

        item = data[0]
        if not isinstance(item, dict):
            raise NovaPostApiError("unexpected data[0] (not a JSON object)")

        if item.get("StatusCode") == _STATUS_NOT_FOUND:
            return None
        return item
