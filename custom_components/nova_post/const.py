"""Constants for the Nova Post parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "nova_post"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Nova Poshta's official JSON-RPC tracking endpoint (``novaposhta.ua``, *not*
# the weaker-evidence ``novapost.com`` REST surface — see
# carrier-research/nova-post.md#build). One POST, one
# fixed URL — the tracking code travels in the request body, not the URL, so
# unlike most sibling carriers this is not a ``.format()`` template.
#
# No auth: every call sends ``apiKey: ""`` (see api.py) — that is a deliberate
# anonymous path for this one method, live-confirmed by probing all four
# methods either of the two known HA client repos call, not a validation gap.
# Envelope is always HTTP 200 / ``success: true``; branch on
# ``data[0]["StatusCode"]``, never on ``success`` or the HTTP status — see
# carrier-research/api/nova-post/tracking.md#envelope-and-the-not-found-signal.
#
# No rate-limit evidence either way (``rate_limit: unknown``) — only a handful
# of probe requests have ever been sent against this endpoint.
TRACKING_API_URL = "https://api.novaposhta.ua/v2.0/json/"

# No public consumer tracking-page URL has ever been captured for Nova Poshta
# (see carrier-research/api/nova-post/tracking.md#payload--canonical-mapping).
# Guessing a
# query-parameter name risks shipping a link that silently 404s for every
# user, so the canonical ``url`` field is hard-coded ``None`` in parcels.py
# instead of being built from a template here.

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code}`` dicts — this carrier has no account or parcel feed, so the
# user enters the codes themselves. Kept as dicts so future per-parcel fields
# slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Refresh interval (minutes) controls how often the coordinator polls the
# carrier. Default 30 min keeps the load on a consumer endpoint gentle; the
# minimum is 15 min for the same reason.
#
# Deliberate divergence from the HA Core rule that polling intervals are not
# user-configurable: that rule targets core integrations, and in a HACS parcel
# tracker a tunable cadence is a wanted feature. Generate with
# ``--interval fixed`` instead when the carrier throttles or soft-bans unusual
# traffic — that drops the option entirely and hard-codes the cadence, so users
# cannot dial it down to something that gets them blocked.
CONF_REFRESH_INTERVAL = "refresh_interval"
REFRESH_INTERVAL_OPTIONS = (15, 30, 60, 120, 240)
DEFAULT_REFRESH_INTERVAL = 30

# No ``include_history`` option. ``getStatusDocuments`` looks like a single
# current-state snapshot — no history/events array has been observed or is
# implied by either HA client repo that calls this method (see
# carrier-research/api/nova-post/tracking.md#payload). Faking a timeline by
# accumulating polls locally would differ per user depending on when they
# installed the integration, so ``history`` is always ``None`` instead — same
# call as Budbee's, for the same reason.
