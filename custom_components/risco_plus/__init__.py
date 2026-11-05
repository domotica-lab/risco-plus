"""The Risco integration."""

from __future__ import annotations

from asyncio import CancelledError
import logging
from pathlib import Path

from pyrisco import (
    CannotConnectError,
    OperationError,
    RiscoCloud,
    RiscoLocal,
    UnauthorizedError,
)
from pyrisco.common import Partition, System, Zone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_PORT,
    CONF_TYPE,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    CONF_COMMUNICATION_DELAY,
    CONF_CONCURRENCY,
    DEFAULT_CONCURRENCY,
    DOMAIN,
    SYSTEM_UPDATE_SIGNAL,
    TYPE_LOCAL,
)
from .coordinator import RiscoDataUpdateCoordinator, RiscoEventsDataUpdateCoordinator
from .migrate import async_migrate_from_core
from .models import CloudData, LocalData, RiscoConfigEntry, RiscoData
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)
# pyrisco exposes timeout context as message text for this case.
CLOCK_TIMEOUT_ERROR_FRAGMENT = "Timeout in command: CLOCK"
# Risco Plus: the dashboard card is served by the integration itself
CARD_URL = f"/{DOMAIN}/risco-plus-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "risco-plus-card.js"


def is_local(entry: ConfigEntry) -> bool:
    """Return whether the entry represents an instance with local communication."""
    return entry.data.get(CONF_TYPE) == TYPE_LOCAL


def zone_update_signal(zone_id: int) -> str:
    """Return a signal for the dispatch of a zone update."""
    return f"risco_plus_zone_update_{zone_id}"


async def async_setup_entry(hass: HomeAssistant, entry: RiscoConfigEntry) -> bool:
    """Set up Risco from a config entry."""
    await async_migrate_from_core(hass, entry)
    if is_local(entry):
        return await _async_setup_local_entry(hass, entry)

    return await _async_setup_cloud_entry(hass, entry)


async def _async_setup_local_entry(
    hass: HomeAssistant, entry: RiscoConfigEntry
) -> bool:
    data = entry.data
    concurrency = entry.options.get(CONF_CONCURRENCY, DEFAULT_CONCURRENCY)
    risco = RiscoLocal(
        data[CONF_HOST],
        data[CONF_PORT],
        data[CONF_PIN],
        communication_delay=data.get(CONF_COMMUNICATION_DELAY, 0),
        concurrency=concurrency,
    )

    try:
        await risco.connect()
    except CannotConnectError as error:
        raise ConfigEntryNotReady from error
    except UnauthorizedError:
        _LOGGER.exception("Failed to authenticate with local Risco panel")
        return False

    async def _error(error: Exception) -> None:
        if isinstance(error, OperationError) and CLOCK_TIMEOUT_ERROR_FRAGMENT in str(
            error
        ):
            _LOGGER.warning(
                "Risco keep-alive timeout for entry %s (host: %s)",
                entry.title,
                data.get(CONF_HOST, "unknown"),
            )
        else:
            _LOGGER.error(
                "Error in Risco library",
                exc_info=error,
            )
            if isinstance(error, ConnectionResetError) and not hass.is_stopping:
                _LOGGER.debug("Disconnected from panel. Reloading integration")
                hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    entry.async_on_unload(risco.add_error_handler(_error))

    async def _default(command: str, result: str, *params: list[str]) -> None:
        _LOGGER.debug(
            "Unhandled update from Risco library: %s, %s, %s", command, result, params
        )

    entry.async_on_unload(risco.add_default_handler(_default))

    local_data = LocalData(risco)

    async def _zone(zone_id: int, zone: Zone) -> None:
        _LOGGER.debug("Risco zone update for %d", zone_id)
        async_dispatcher_send(hass, zone_update_signal(zone_id))

    entry.async_on_unload(risco.add_zone_handler(_zone))

    async def _partition(partition_id: int, partition: Partition) -> None:
        _LOGGER.debug("Risco partition update for %d", partition_id)
        callback = local_data.partition_updates.get(partition_id)
        if callback:
            callback()
        for listener in list(local_data.group_listeners.get(partition_id, [])):
            listener()

    entry.async_on_unload(risco.add_partition_handler(_partition))

    async def _system(system: System) -> None:
        _LOGGER.debug("Risco system update")
        async_dispatcher_send(hass, SYSTEM_UPDATE_SIGNAL)

    entry.async_on_unload(risco.add_system_handler(_system))

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    entry.runtime_data = RiscoData(local_data=local_data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_setup_cloud_entry(
    hass: HomeAssistant, entry: RiscoConfigEntry
) -> bool:
    data = entry.data
    risco = RiscoCloud(data[CONF_USERNAME], data[CONF_PASSWORD], data[CONF_PIN])
    try:
        await risco.login(async_get_clientsession(hass))
    except CannotConnectError as error:
        raise ConfigEntryNotReady from error
    except UnauthorizedError as error:
        raise ConfigEntryAuthFailed from error

    coordinator = RiscoDataUpdateCoordinator(hass, entry, risco)
    await coordinator.async_config_entry_first_refresh()
    events_coordinator = RiscoEventsDataUpdateCoordinator(hass, entry, risco)

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    entry.runtime_data = RiscoData(
        cloud_data=CloudData(
            coordinator=coordinator,
            events_coordinator=events_coordinator,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await events_coordinator.async_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: RiscoConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and (local_data := entry.runtime_data.local_data):
        try:
            await local_data.system.disconnect()
        except CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Failed to disconnect from local Risco panel for entry %s (host: %s)",
                entry.title,
                entry.data.get(CONF_HOST, "unknown"),
            )

    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: RiscoConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Risco integration services."""

    async_setup_services(hass)
    await _async_register_card(hass)

    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and load it in every dashboard (no manual resource)."""
    if getattr(hass, "http", None) is None:
        return
    try:
        from homeassistant.components.frontend import (  # noqa: PLC0415
            DATA_EXTRA_MODULE_URL,
            add_extra_js_url,
        )
        from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

        version = (await async_get_integration(hass, DOMAIN)).version
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(CARD_PATH), True)]
        )
        url = f"{CARD_URL}?v={version}"

        @callback
        def _add_card(_hass: HomeAssistant | None = None) -> bool:
            """Add the card to the dashboards once the frontend is ready."""
            if DATA_EXTRA_MODULE_URL not in hass.data:
                return False
            if url not in getattr(hass.data[DATA_EXTRA_MODULE_URL], "urls", []):
                add_extra_js_url(hass, url)
            return True

        @callback
        def _add_card_when_started(_hass: HomeAssistant) -> None:
            if not _add_card():
                _LOGGER.warning(
                    "Risco Plus card not added automatically: add %s as a "
                    "dashboard resource (JavaScript module)",
                    CARD_URL,
                )

        # the frontend may start after Risco Plus: try again when Home Assistant is up
        if not _add_card():
            async_at_started(hass, _add_card_when_started)
    except Exception:  # never block the alarm because of the card
        _LOGGER.exception("Could not load the Risco Plus card")
