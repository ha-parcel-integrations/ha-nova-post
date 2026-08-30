"""Config flow for the Nova Post parcel tracker integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# **2026-08-13: widened for the ``/site/v.1.0/`` REST surface**
# (carrier-research/nova-post.md `## Build`, addendum 2026-08-13), which this
# integration now calls instead of the JSON-RPC ``getStatusDocuments`` method.
# That surface "takes any string" (novapost-tracking.md "Surface B") — it has
# no documented format at all, unlike the old surface's strict 14-digit
# ``DocumentNumber``. Two shapes are confirmed live: short numeric reference
# codes (`12345`, `12348`, `12349`, 5 digits) and cross-border alphanumeric
# TTNs (`SHCN8143247690`, 14 chars) alongside the original 14-digit Ukrainian
# domestic TTN. 4-30 alphanumeric characters covers all three with a
# deliberate buffer rather than a proven bound on either end — narrow it once
# a real code shows the actual limits.
_TRACKING_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,30}$")


def normalize_tracking_code(value: str) -> str:
    """Return the tracking code upper-cased with separators stripped.

    So a code pasted with spaces or dashes (as it is often printed on a
    shipping label) still validates, and matches regardless of case.
    """
    return re.sub(r"[^A-Za-z0-9]+", "", (value or "")).upper()


def valid_tracking_code(value: str) -> bool:
    """Whether ``value`` looks like a Nova Post tracking code: 4-30 alphanumeric characters."""
    return bool(_TRACKING_CODE_RE.match(value))


def _current_parcels(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return a mutable copy of the tracked parcels list."""
    return [dict(item) for item in entry.options.get(CONF_PARCELS, [])]


class NovaPostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI-driven configuration flow for the Nova Post integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> NovaPostOptionsFlowHandler:
        """Return the options flow handler."""
        return NovaPostOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the Nova Post hub — single instance, no input needed.

        Tracking is keyed on the tracking code alone (no account, no postal
        code), so there is nothing to ask at setup: the entry is created
        straight away and parcels are added afterwards via the options flow,
        the ``nova_post.track_parcel`` service or a dashboard button.
        ``single_config_entry`` in the manifest enforces one hub.
        """
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Nova Post",
            data={},
            options={
                CONF_PARCELS: [],
                CONF_DELIVERED_FILTER_TYPE: DEFAULT_DELIVERED_FILTER_TYPE,
                CONF_DELIVERED_FILTER_AMOUNT: DEFAULT_DELIVERED_FILTER_AMOUNT,
                CONF_INCLUDE_HISTORY: DEFAULT_INCLUDE_HISTORY,
            },
        )


class NovaPostOptionsFlowHandler(OptionsFlow):
    """Manage tracked parcels and history in one sectioned form.

    Mirrors the other suite carriers' section layout (``parcels`` /
    ``delivered`` / ``history``). The ``/site/v.1.0/`` surface this
    integration calls since 2026-08-13 exposes a real ``tracking[]``
    timeline (see parcels.py), so ``history`` is now a real opt-in, off by
    default like every other suite carrier's. Changes apply live via HA's
    options-update listener (which refreshes the coordinator), so new/removed
    per-parcel sensors appear and disappear immediately. Polling is dynamic
    and status-driven, unconditionally — there is no interval to configure
    here (`carrier-research/dynamic-polling.md`).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer parcel management separately from integration settings."""
        return self.async_show_menu(
            step_id="init", menu_options=["parcels", "settings"]
        )

    async def async_step_parcels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle the complete tracked-code list."""
        errors: dict[str, str] = {}
        if user_input is not None:
            codes = list(
                dict.fromkeys(
                    normalize_tracking_code(code)
                    for code in user_input.get("tracking_codes", [])
                    if normalize_tracking_code(code)
                )
            )
            if any(not valid_tracking_code(code) for code in codes):
                errors["base"] = "invalid_tracking_code"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **self.config_entry.options,
                        CONF_PARCELS: [{CONF_TRACKING_CODE: code} for code in codes],
                    },
                )

        current_codes = [
            parcel[CONF_TRACKING_CODE] for parcel in _current_parcels(self.config_entry)
        ]
        schema = vol.Schema(
            {
                vol.Optional("tracking_codes"): selector.TextSelector(
                    selector.TextSelectorConfig(multiple=True)
                )
            }
        )
        return self.async_show_form(
            step_id="parcels",
            data_schema=self.add_suggested_values_to_schema(
                schema, {"tracking_codes": current_codes}
            ),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle non-parcel integration settings."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    CONF_DELIVERED_FILTER_TYPE: user_input[CONF_DELIVERED_FILTER_TYPE],
                    CONF_DELIVERED_FILTER_AMOUNT: int(
                        user_input[CONF_DELIVERED_FILTER_AMOUNT]
                    ),
                    CONF_INCLUDE_HISTORY: bool(user_input[CONF_INCLUDE_HISTORY]),
                },
            )

        current = self.config_entry.options
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DELIVERED_FILTER_TYPE,
                        default=current.get(
                            CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["days", "parcels"],
                            translation_key=CONF_DELIVERED_FILTER_TYPE,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_DELIVERED_FILTER_AMOUNT,
                        default=current.get(
                            CONF_DELIVERED_FILTER_AMOUNT,
                            DEFAULT_DELIVERED_FILTER_AMOUNT,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_INCLUDE_HISTORY,
                        default=current.get(
                            CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY
                        ),
                    ): selector.BooleanSelector(),
                }
            ),
        )
