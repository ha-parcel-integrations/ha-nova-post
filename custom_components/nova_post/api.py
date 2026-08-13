"""Nova Post public tracking API client.

Targets ``novaposhta.ua``'s website tracking surface, ``/site/v.1.0/
shipments/tracking/{ttn}`` — see carrier-research/api/nova-post/
novapost-tracking.md for the full write-up. Contract the coordinator relies
on:

* ``async_get_parcel`` returns the raw response body (a bare object, not a
  ``{data: [...]}`` envelope) on success,
* returns ``None`` when the carrier reports the number as unknown (HTTP 404
  with ``errorMessage: "not_found"``) — a normal, expected state, never an
  error,
* raises :class:`NovaPostApiError` for anything else,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.

**2026-08-13: this replaces the ``novaposhta.ua`` JSON-RPC ``getStatusDocuments``
client** (carrier-research/nova-post.md "## Build", addendum 2026-08-13) —
moved for the richer confirmed payload (history/weight/dimensions/pickup_point/
url), at the cost of losing named ``sender``/``receiver`` (this surface only
carries geography). See parcels.py and CLAUDE.md for the full trade-off.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class NovaPostApiError(Exception):
    """Raised when a Nova Post API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        """Store the detail that triggered the error."""
        super().__init__(f"Nova Post API request failed: {detail}")
        self.detail = detail


class NovaPostApiClient:
    """Client for Nova Post's public website tracking route.

    No authentication of any kind — no headers, no key, nothing to register.
    Live-confirmed 2026-08-13 against a real in-flight parcel (TTN ``12348``):
    control-tested against a protected sibling on the same host (every route
    under ``/mobileapp/v.1.1/`` answers ``401`` with no credential), and
    against a route-existence oracle that separates "no such route" from "no
    such shipment" (see novapost-tracking.md). ``api.novapost.com`` and
    ``api.novaposhta.ua`` are live-confirmed to serve byte-identical bodies for
    the same TTN — one shared backend, two brand hostnames — and this client
    targets the ``novaposhta.ua`` host to match the integration's existing
    branding.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the response body for a known tracking number, or ``None``
        when Nova Post reports it as not found (HTTP 404,
        ``errorMessage: "not_found"``). Any other non-2xx status or
        unparseable/malshaped body raises :class:`NovaPostApiError`; network
        errors propagate as ``aiohttp.ClientError``.

        Unlike the old JSON-RPC surface there is no batching — the tracking
        code is a single path segment, one request per parcel, same as
        before.
        """
        url = TRACKING_API_URL.format(ttn=tracking_code)
        async with self._session.get(url) as response:
            if response.status == 404:
                return None
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

        return payload
