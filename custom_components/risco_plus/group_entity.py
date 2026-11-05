"""Risco Plus: optional entities for every group (armed sensor, arm button)."""

from __future__ import annotations

from collections.abc import Iterator
import re
from typing import Any, override

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_GROUP_ENTITIES, CONF_GROUP_NAMES, DOMAIN, RISCO_GROUPS
from .groups import group_label, parse_group_names
from .models import RiscoConfigEntry

GROUP_UNIQUE_ID = re.compile(r"_group_[A-D](_arm)?$")


def alarm_unique_id(entry: RiscoConfigEntry, partition_id: int) -> str:
    """Unique id of the alarm entity (and device) of a partition."""
    data = entry.runtime_data
    if data.local_data:
        return f"{data.local_data.system.id}_{partition_id}_local"
    assert data.cloud_data
    return f"{data.cloud_data.coordinator.risco.site_uuid}_{partition_id}"


def partition_groups(entry: RiscoConfigEntry) -> Iterator[tuple[int, str]]:
    """(partition id, group) for every partition and group A-D."""
    data = entry.runtime_data
    if data.local_data:
        partitions = data.local_data.system.partitions
    elif data.cloud_data and data.cloud_data.coordinator.data:
        partitions = data.cloud_data.coordinator.data.partitions
    else:
        partitions = {}
    for partition_id in partitions:
        for group in RISCO_GROUPS:
            yield partition_id, group


def setup_group_entities(
    hass: HomeAssistant, entry: RiscoConfigEntry, domain: str
) -> bool:
    """True if group entities are enabled; otherwise remove the old ones."""
    if entry.options.get(CONF_GROUP_ENTITIES):
        return True
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == domain and GROUP_UNIQUE_ID.search(item.unique_id):
            registry.async_remove(item.entity_id)
    return False


class RiscoGroupEntity(Entity):
    """Base class: one group (A-D) of one partition."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: RiscoConfigEntry, partition_id: int, group: str, suffix: str
    ) -> None:
        """Init the group entity."""
        self._entry = entry
        self._partition_id = partition_id
        self._group = group
        self._alarm_unique_id = alarm_unique_id(entry, partition_id)
        self._attr_unique_id = f"{self._alarm_unique_id}_group_{group}{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._alarm_unique_id)}
        )
        names = parse_group_names(entry.options.get(CONF_GROUP_NAMES) or "")
        self._attr_translation_placeholders = {"group": group_label(group, names)}

    def _partition(self) -> Any:
        """Current partition object."""
        data = self._entry.runtime_data
        if data.local_data:
            return data.local_data.system.partitions.get(self._partition_id)
        coordinator = data.cloud_data.coordinator
        return coordinator.data.partitions.get(self._partition_id)

    @property
    @override
    def available(self) -> bool:
        """Cloud: available while Risco Cloud answers."""
        data = self._entry.runtime_data
        if data.cloud_data:
            return data.cloud_data.coordinator.last_update_success
        return True

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the partition updates."""
        data = self._entry.runtime_data
        if data.cloud_data:
            self.async_on_remove(
                data.cloud_data.coordinator.async_add_listener(
                    self.async_write_ha_state
                )
            )
            return
        listeners = data.local_data.group_listeners.setdefault(
            self._partition_id, []
        )
        listeners.append(self.async_write_ha_state)
        self.async_on_remove(lambda: listeners.remove(self.async_write_ha_state))
