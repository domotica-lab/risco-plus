"""Fixtures for Risco tests (adapted from Home Assistant core)."""

import os
import sys

# HA >= 2026.10 ships "probatio"; older test environments get a small shim.
try:
    import probatio  # noqa: F401
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shim"))


from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from pyrisco.cloud.event import Event
import pytest

from custom_components.risco_plus.const import DOMAIN, TYPE_LOCAL
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_PORT,
    CONF_TYPE,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

from .util import TEST_SITE_NAME, TEST_SITE_UUID, system_mock, zone_mock

from pytest_homeassistant_custom_component.common import MockConfigEntry

TEST_CLOUD_CONFIG = {
    CONF_USERNAME: "test-username",
    CONF_PASSWORD: "test-password",
    CONF_PIN: "1234",
}
TEST_LOCAL_CONFIG = {
    CONF_TYPE: TYPE_LOCAL,
    CONF_HOST: "test-host",
    CONF_PORT: 5004,
    CONF_PIN: "1234",
}


@pytest.fixture
def two_zone_cloud():
    """Fixture to mock alarm with two zones."""
    zone_mocks = {0: zone_mock(), 1: zone_mock()}
    alarm_mock = MagicMock()
    with (
        patch.object(zone_mocks[0], "id", new_callable=PropertyMock(return_value=0)),
        patch.object(
            zone_mocks[0], "name", new_callable=PropertyMock(return_value="Zone 0")
        ),
        patch.object(
            zone_mocks[0], "bypassed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(zone_mocks[1], "id", new_callable=PropertyMock(return_value=1)),
        patch.object(
            zone_mocks[1], "name", new_callable=PropertyMock(return_value="Zone 1")
        ),
        patch.object(
            zone_mocks[1], "bypassed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            alarm_mock,
            "zones",
            new_callable=PropertyMock(return_value=zone_mocks),
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.get_state",
            return_value=alarm_mock,
        ),
    ):
        yield zone_mocks


@pytest.fixture
def two_zone_local():
    """Fixture to mock alarm with two zones."""
    zone_mocks = {0: zone_mock(), 1: zone_mock()}
    system = system_mock()
    with (
        patch.object(zone_mocks[0], "id", new_callable=PropertyMock(return_value=0)),
        patch.object(
            zone_mocks[0], "name", new_callable=PropertyMock(return_value="Zone 0")
        ),
        patch.object(
            zone_mocks[0], "alarmed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            zone_mocks[0], "bypassed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            zone_mocks[0], "armed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(zone_mocks[1], "id", new_callable=PropertyMock(return_value=1)),
        patch.object(
            zone_mocks[1], "name", new_callable=PropertyMock(return_value="Zone 1")
        ),
        patch.object(
            zone_mocks[1], "alarmed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            zone_mocks[1], "bypassed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            zone_mocks[1], "armed", new_callable=PropertyMock(return_value=False)
        ),
        patch.object(
            system, "name", new_callable=PropertyMock(return_value=TEST_SITE_NAME)
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.partitions",
            new_callable=PropertyMock(return_value={}),
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.zones",
            new_callable=PropertyMock(return_value=zone_mocks),
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.system",
            new_callable=PropertyMock(return_value=system),
        ),
    ):
        yield zone_mocks


@pytest.fixture
def options() -> dict[str, Any]:
    """Fixture for default (empty) options."""
    return {}


@pytest.fixture
def events() -> list[Event]:
    """Fixture for default (empty) events."""
    return []


@pytest.fixture
def cloud_config_entry(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Fixture for a cloud config entry."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=TEST_CLOUD_CONFIG,
        options=options,
        unique_id=TEST_CLOUD_CONFIG[CONF_USERNAME],
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def login_with_error(exception):
    """Fixture to simulate error on login."""
    with patch(
        "custom_components.risco_plus.RiscoCloud.login",
        side_effect=exception,
    ):
        yield


@pytest.fixture
async def setup_risco_cloud(
    hass: HomeAssistant, cloud_config_entry: MockConfigEntry, events: list[Event]
) -> AsyncGenerator[MockConfigEntry]:
    """Set up a Risco integration for testing."""
    with (
        patch(
            "custom_components.risco_plus.RiscoCloud.login",
            return_value=True,
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.site_uuid",
            new_callable=PropertyMock(return_value=TEST_SITE_UUID),
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.site_name",
            new_callable=PropertyMock(return_value=TEST_SITE_NAME),
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.close",
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.get_events",
            return_value=events,
        ),
    ):
        await hass.config_entries.async_setup(cloud_config_entry.entry_id)
        await hass.async_block_till_done()

        yield cloud_config_entry


@pytest.fixture
def local_config_entry(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Fixture for a local config entry."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=TEST_LOCAL_CONFIG, options=options
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def connect_with_error(exception):
    """Fixture to simulate error on connect."""
    with patch(
        "custom_components.risco_plus.RiscoLocal.connect",
        side_effect=exception,
    ):
        yield


@pytest.fixture
async def setup_risco_local(
    hass: HomeAssistant, local_config_entry: MockConfigEntry
) -> AsyncGenerator[MockConfigEntry]:
    """Set up a local Risco integration for testing."""
    with (
        patch(
            "custom_components.risco_plus.RiscoLocal.connect",
            return_value=True,
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.id",
            new_callable=PropertyMock(return_value=TEST_SITE_UUID),
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.disconnect",
        ),
    ):
        await hass.config_entries.async_setup(local_config_entry.entry_id)
        await hass.async_block_till_done()

        yield local_config_entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield
