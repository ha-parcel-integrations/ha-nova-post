"""Tests for the Nova Post config and options flow."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nova_post.config_flow import (
    normalize_tracking_code,
    valid_tracking_code,
)
from custom_components.nova_post.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_REFRESH_INTERVAL,
    CONF_TRACKING_CODE,
    DOMAIN,
)

CODE_A = "20450000000001"
CODE_B = "20450000000002"
CROSS_BORDER_CODE = "SHCN8143247690"


def test_normalize_tracking_code_strips_separators_and_upcases():
    assert normalize_tracking_code("2045 0000-000001") == CODE_A
    assert normalize_tracking_code("shcn8143247690") == CROSS_BORDER_CODE
    assert normalize_tracking_code("") == ""
    assert normalize_tracking_code(None) == ""


def test_valid_tracking_code_accepts_numeric_and_alphanumeric():
    assert valid_tracking_code(CODE_A)  # 14-digit Ukrainian domestic TTN
    assert valid_tracking_code("12349")  # short consumer reference code
    assert valid_tracking_code(CROSS_BORDER_CODE)  # cross-border alias
    assert valid_tracking_code("1234")  # 4 characters — the loosened floor
    assert not valid_tracking_code("123")  # 3 characters — below the floor
    assert not valid_tracking_code("A" * 31)  # too long
    assert not valid_tracking_code("2045-000000")  # separator not stripped


async def test_user_flow_creates_hub_without_input(hass):
    """No account, no postcode — the entry is created straight away."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Nova Post"
    assert result["options"][CONF_PARCELS] == []
    assert result["options"][CONF_INCLUDE_HISTORY] is False


async def test_second_hub_rejected(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    # single_config_entry in the manifest aborts before the flow runs.
    assert result["reason"] == "single_instance_allowed"


def _hub(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: parcels},
    )


def _init_input(
    *, add="", remove=None,
    interval="30",
    filter_type="days", amount=7,
    include_history=False,
) -> dict:
    """Build the sectioned options-form submission."""
    parcels: dict = {"add": add}
    if remove is not None:
        parcels["remove"] = remove
    return {
        "parcels": parcels,
        "delivered": {
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        "history": {CONF_INCLUDE_HISTORY: include_history},
        "polling": {CONF_REFRESH_INTERVAL: interval},
    }


async def test_options_add_parcel(hass):
    entry = _hub([])
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add=CODE_A)
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: CODE_A}]


async def test_options_add_cross_border_code(hass):
    entry = _hub([])
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add="shcn8143247690")
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: CROSS_BORDER_CODE}]


async def test_options_add_code_with_separators(hass):
    """Pasted codes with spaces/dashes are sanitised like the consumer site."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add="2045 0000-000001")
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: CODE_A}]


async def test_options_add_invalid_tracking_code(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add="123")
    )
    assert result["errors"]["base"] == "invalid_tracking_code"


async def test_options_add_duplicate_rejected(hass):
    entry = _hub([{CONF_TRACKING_CODE: CODE_A}])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add=CODE_A, remove=[])
    )
    assert result["errors"]["base"] == "already_tracked"


async def test_options_remove_parcel(hass):
    entry = _hub([
        {CONF_TRACKING_CODE: CODE_A},
        {CONF_TRACKING_CODE: CODE_B},
    ])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(remove=[CODE_A])
    )
    assert result["type"] == "create_entry"
    codes = {p[CONF_TRACKING_CODE] for p in result["data"][CONF_PARCELS]}
    assert codes == {CODE_B}


async def test_options_remove_then_readd_same_code(hass):
    """Remove-then-add order: re-adding a just-removed code works."""
    entry = _hub([{CONF_TRACKING_CODE: CODE_A}])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(add=CODE_A, remove=[CODE_A])
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: CODE_A}]


async def test_options_changes_interval_and_delivered(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _init_input(interval="120", filter_type="parcels", amount=5),
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_REFRESH_INTERVAL] == 120
    assert result["data"][CONF_DELIVERED_FILTER_TYPE] == "parcels"
    assert result["data"][CONF_DELIVERED_FILTER_AMOUNT] == 5


async def test_options_toggles_include_history(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(include_history=True)
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_INCLUDE_HISTORY] is True
