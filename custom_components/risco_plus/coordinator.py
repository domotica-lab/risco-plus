"""Coordinator for the Risco integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any, override

from pyrisco import CannotConnectError, OperationError, RiscoCloud, UnauthorizedError
from pyrisco.cloud.alarm import Alarm
from pyrisco.cloud.event import Event

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pyrisco.cloud.risco_cloud import EVENTS_URL, STATE_URL

from .const import (
    CONF_CLOUD_CACHE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENTS_INTERVAL,
    EVENTS_INTERVAL_CLOUD_CACHE,
)

LAST_EVENT_STORAGE_VERSION = 1
LAST_EVENT_TIMESTAMP_KEY = "last_event_timestamp"
_LOGGER = logging.getLogger(__name__)


def use_cloud_cache(config_entry: ConfigEntry) -> bool:
    """Return True if data must be read from the Risco Cloud copy."""
    return bool(config_entry.options.get(CONF_CLOUD_CACHE, False))


async def read_cloud_cache(risco: RiscoCloud, url: str, body: dict[str, Any]) -> Any:
    """Read data saved in Risco Cloud without querying the control panel.

    The panel keeps the cloud copy up to date by itself. Older IP modules handle
    one request at a time: reading the copy keeps them free for commands, so the
    iRISCO app is not refused while Home Assistant is running.
    """
    for attempt in range(2):
        try:
            return await risco._authenticated_post(  # noqa: SLF001
                url % risco._site_id,  # noqa: SLF001
                {
                    **body,
                    "fromControlPanel": False,
                    "sessionToken": risco._session_id,  # noqa: SLF001
                },
            )
        except UnauthorizedError:
            if attempt:
                raise
            await risco.close()
            await risco.login()
    return None


class RiscoDataUpdateCoordinator(DataUpdateCoordinator[Alarm]):
    """Class to manage fetching risco data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        risco: RiscoCloud,
    ) -> None:
        """Initialize global risco data updater."""
        self.risco = risco
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
            ),
        )

    @override
    async def _async_update_data(self) -> Alarm:
        """Fetch data from risco."""
        try:
            if use_cloud_cache(self.config_entry):
                resp = await read_cloud_cache(self.risco, STATE_URL, {})
                return Alarm(self.risco, resp["state"]["status"], True)
            return await self.risco.get_state()
        except (CannotConnectError, UnauthorizedError, OperationError) as error:
            raise UpdateFailed(error) from error
        except (KeyError, TypeError) as error:
            raise UpdateFailed(f"Unexpected Risco Cloud response: {error}") from error


class RiscoEventsDataUpdateCoordinator(DataUpdateCoordinator[list[Event]]):
    """Class to manage fetching risco data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        risco: RiscoCloud,
    ) -> None:
        """Initialize global risco data updater."""
        self.risco = risco
        self._store = Store[dict[str, Any]](
            hass,
            LAST_EVENT_STORAGE_VERSION,
            f"risco_{config_entry.entry_id}_last_event_timestamp",
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_events",
            update_interval=timedelta(
                seconds=EVENTS_INTERVAL_CLOUD_CACHE
                if use_cloud_cache(config_entry)
                else EVENTS_INTERVAL
            ),
        )

    @override
    async def _async_update_data(self) -> list[Event]:
        """Fetch data from risco."""
        last_store = await self._store.async_load() or {}
        last_timestamp = last_store.get(
            LAST_EVENT_TIMESTAMP_KEY, "2020-01-01T00:00:00Z"
        )
        try:
            if use_cloud_cache(self.config_entry):
                resp = await read_cloud_cache(
                    self.risco,
                    EVENTS_URL,
                    {"count": 10, "newerThan": last_timestamp, "offset": 0},
                )
                events = [
                    Event(e) for e in (resp or {}).get("controlPanelEventsList") or []
                ]
            else:
                events = await self.risco.get_events(last_timestamp, 10)
        except (CannotConnectError, UnauthorizedError, OperationError) as error:
            raise UpdateFailed(error) from error

        if len(events) > 0:
            await self._store.async_save({LAST_EVENT_TIMESTAMP_KEY: events[0].time})

        return events
