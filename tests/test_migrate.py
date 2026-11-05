"""Tests for moving from the standard Risco integration to Risco Plus."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.risco_plus.const import CONF_MIGRATED_FROM, DOMAIN
from custom_components.risco_plus.migrate import async_migrate_from_core

from .conftest import TEST_CLOUD_CONFIG
from .util import device_by_identifier

OLD_OPTIONS = {"code_disarm_required": True, "custom_code": "2468"}


def _core_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain="risco",
        title="Casa",
        data=TEST_CLOUD_CONFIG,
        options=OLD_OPTIONS,
        unique_id=TEST_CLOUD_CONFIG["username"],
    )
    entry.add_to_hass(hass)
    return entry


async def test_flow_copies_core_entry(hass: HomeAssistant) -> None:
    """The menu offers the copy; account and options are copied."""
    old = _core_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"][0] == "migrate"
    with patch("custom_components.risco_plus.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "migrate"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Casa"
    assert result["data"] == {**TEST_CLOUD_CONFIG, CONF_MIGRATED_FROM: old.entry_id}
    assert result["options"] == OLD_OPTIONS

    # already taken over: no more copy in the menu
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert "migrate" not in result["menu_options"]


async def test_no_core_entry_no_copy(hass: HomeAssistant) -> None:
    """Without the standard integration the menu is the usual one."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["menu_options"] == ["cloud", "local"]


async def test_entities_keep_their_ids(hass: HomeAssistant) -> None:
    """Old entry disabled, entity ids / names / areas taken over, flag removed."""
    old = _core_entry(hass)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=old.entry_id,
        identifiers={("risco", "uuid_0")},
        name="Risco Casa Partition 0",
    )
    devices.async_update_device(device.id, area_id="soggiorno", name_by_user="Allarme")
    alarm = entities.async_get_or_create(
        "alarm_control_panel", "risco", "uuid_0", config_entry=old, device_id=device.id
    )
    entities.async_update_entity(
        alarm.entity_id, new_entity_id="alarm_control_panel.allarme", name="Allarme"
    )
    zone = entities.async_get_or_create(
        "binary_sensor", "risco", "uuid_zone_1", config_entry=old
    )
    entities.async_update_entity(
        zone.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    new = MockConfigEntry(
        domain=DOMAIN,
        data={**TEST_CLOUD_CONFIG, CONF_MIGRATED_FROM: old.entry_id},
        unique_id=TEST_CLOUD_CONFIG["username"],
    )
    new.add_to_hass(hass)
    await async_migrate_from_core(hass, new)

    assert old.disabled_by is ConfigEntryDisabler.USER
    assert CONF_MIGRATED_FROM not in new.data
    moved = entities.async_get("alarm_control_panel.allarme")
    assert moved.platform == DOMAIN
    assert moved.config_entry_id == new.entry_id
    assert moved.name == "Allarme"
    assert entities.async_get("alarm_control_panel.allarme_risco_old").platform == "risco"
    zone_new = entities.async_get(
        entities.async_get_entity_id("binary_sensor", DOMAIN, "uuid_zone_1")
    )
    assert zone_new.disabled_by is er.RegistryEntryDisabler.USER
    new_device = device_by_identifier(devices, (DOMAIN, "uuid_0"))
    assert new_device.area_id == "soggiorno"
    assert new_device.name_by_user == "Allarme"

    # second start: nothing happens
    await async_migrate_from_core(hass, new)
    assert entities.async_get("alarm_control_panel.allarme").platform == DOMAIN


async def test_card_is_served(hass: HomeAssistant, hass_client) -> None:
    """The integration serves its card and adds it to every dashboard."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
    from homeassistant.setup import async_setup_component

    # what the frontend sets up in a real Home Assistant
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *args: None, [])
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_client()
    response = await client.get("/risco_plus/risco-plus-card.js")
    assert response.status == 200
    assert "risco-plus-card" in await response.text()
    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(url.startswith("/risco_plus/risco-plus-card.js?v=") for url in urls)


async def test_card_added_when_frontend_starts_later(hass: HomeAssistant) -> None:
    """If the frontend is not ready yet, the card is added once Home Assistant has started."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState
    from homeassistant.setup import async_setup_component

    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    assert DATA_EXTRA_MODULE_URL not in hass.data

    # the frontend comes up, then Home Assistant finishes starting
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *args: None, [])
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert [u for u in urls if u.startswith("/risco_plus/risco-plus-card.js?v=")]
