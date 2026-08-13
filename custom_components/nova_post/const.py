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

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping this carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# Which optional contract fields this carrier's API actually populates — feeds
# the comparison table on the docs site. Keep in lockstep with
# normalize_parcel() in parcels.py: everything not listed here comes back as a
# literal None there.
#
# **2026-08-13: moved from getStatusDocuments to the /site/v.1.0/ REST
# surface** (carrier-research/nova-post.md "## Build", addendum 2026-08-13) on
# the strength of a real captured payload (TTN 12348). That surface confirms
# ``weight`` (kg), ``dimensions`` (cm), ``pickup_point``, ``url`` (a real
# constructible consumer deep link) and ``history`` (an ordered, geo-tagged
# timeline) — everything the old surface lacked except delivery_window, which
# comes along for free from ``scheduled_delivery_date``. The trade: this
# surface's ``sender``/``recipient`` carry geography (country/settlement) only,
# never a name — the old ``SenderFullNameEW``/``RecipientFullName`` fields have
# no equivalent here. ``sender``/``receiver`` are not part of
# ``KNOWN_CAPABILITIES`` so that loss does not show up on the docs site; see
# CLAUDE.md for the full trade-off writeup.
CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# The website's public tracking API (``/site/v.1.0/``), value-confirmed
# 2026-08-13 against a real in-flight parcel — see
# carrier-research/nova-post.md#surface-keyless-by-number-rest-novapostcom-sitev10
# and carrier-research/api/nova-post/novapost-tracking.md#surface-b--the-website-api-sitev10-keyless.
# GET, keyless, the tracking code travels in the URL path (unlike the old
# JSON-RPC surface's request-body ``Documents`` list).
#
# Host is ``novaposhta.ua``, not ``novapost.com``: both are live-confirmed to
# serve byte-identical bodies for the same TTN (one shared NOVA-group backend,
# two brand hostnames), and ``novaposhta.ua`` matches this integration's
# existing branding and its tracking-page URL below.
#
# No auth of any kind. A bogus/unknown number answers a plain
# ``404 {"errors":{"errorMessage":"not_found"}}`` — unlike the old surface
# there is no second, different not-found shape, and this route accepts any
# string, not just 14-digit TTNs.
#
# No rate-limit evidence either way (25 back-to-back probes, no throttling
# observed) — ``rate_limit: none-observed``, still not enough traffic to call
# it settled.
TRACKING_API_URL = "https://api.novaposhta.ua/site/v.1.0/shipments/tracking/{ttn}"

# The consumer tracking page this same surface backs — confirmed by reading
# the site's own JS bundle: it calls exactly this REST route, client-side,
# unauthenticated (carrier-research/api/nova-post/novapost-tracking.md#the-consumer-tracking-pages-call-this-route).
# ``novaposhta.ua`` takes at most one optional locale segment and defaults
# (Ukrainian) with none, so the no-prefix form is the one guaranteed to
# resolve regardless of the user's language — unlike ``novapost.com``, which
# requires a two-segment ``{lang}-{country}`` tag this integration has no
# per-user locale to fill in.
TRACKING_URL_TEMPLATE = "https://novaposhta.ua/tracking/{ttn}"

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

# Per-parcel status history is opt-in and off by default, identical across the
# suite. The ``/site/v.1.0/`` surface's ``tracking[]`` array is real and rich
# (a geo-tagged, ordered timeline — see parcels.py) and costs no extra
# request, unlike the old ``getStatusDocuments`` surface which had no events
# array at all. Kept off by default anyway: it is a large attribute, and the
# suite's convention does not special-case "free" history.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
