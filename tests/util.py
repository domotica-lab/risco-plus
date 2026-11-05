"""Utilities for Risco tests."""

from unittest.mock import AsyncMock, MagicMock

TEST_SITE_UUID = "test-site-uuid"
TEST_SITE_NAME = "test-site-name"


def zone_mock():
    """Return a mocked zone."""
    return MagicMock(
        triggered=False, bypassed=False, bypass=AsyncMock(return_value=True)
    )


def system_mock():
    """Return a mocked system."""
    return MagicMock(
        low_battery_trouble=False,
        ac_trouble=False,
        monitoring_station_1_trouble=False,
        monitoring_station_2_trouble=False,
        monitoring_station_3_trouble=False,
        phone_line_trouble=False,
        clock_trouble=False,
        box_tamper=False,
        programming_mode=False,
    )


def device_by_identifier(registry, identifier):
    """Find a device by identifier on old and new Home Assistant versions."""
    for item in registry.devices:
        # new versions yield device entries, old ones yield device ids
        device = item if hasattr(item, "identifiers") else registry.devices[item]
        if identifier in device.identifiers:
            return device
    return None
