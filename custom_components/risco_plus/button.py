"""Risco Plus: a button to arm every group (optional)."""

from __future__ import annotations

from typing import override

from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_GROUPS, DOMAIN, SERVICE_ARM_GROUPS
from .group_entity import RiscoGroupEntity, partition_groups, setup_group_entities
from .models import RiscoConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RiscoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the "arm group" buttons."""
    if setup_group_entities(hass, config_entry, "button"):
        async_add_entities(
            RiscoArmGroupButton(config_entry, partition_id, group)
            for partition_id, group in partition_groups(config_entry)
        )


class RiscoArmGroupButton(RiscoGroupEntity, ButtonEntity):
    """Arm one group (same checks as the risco_plus.arm_groups action)."""

    _attr_translation_key = "arm_group"

    def __init__(self, entry: RiscoConfigEntry, partition_id: int, group: str) -> None:
        """Init the button."""
        super().__init__(entry, partition_id, group, "_arm")

    @override
    async def async_press(self) -> None:
        """Arm the group."""
        entity_id = er.async_get(self.hass).async_get_entity_id(
            ALARM_DOMAIN, DOMAIN, self._alarm_unique_id
        )
        if entity_id is None:
            raise HomeAssistantError(f"Alarm entity not found for {self.entity_id}")
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_ARM_GROUPS,
            {"entity_id": entity_id, ATTR_GROUPS: [self._group]},
            blocking=True,
        )
