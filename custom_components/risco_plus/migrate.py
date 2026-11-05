"""Risco Plus: move from the standard Risco integration without losing anything.

The config flow copies account and options of a "risco" entry; at the first
setup the old entry is disabled (not deleted) and the entities take over the
same entity ids, names, icons and areas, so dashboards and automations keep
working.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_MIGRATED_FROM, CORE_DOMAIN, DOMAIN
from .models import RiscoConfigEntry

_LOGGER = logging.getLogger(__name__)
OLD_SUFFIX = "_risco_old"


async def async_migrate_from_core(hass: HomeAssistant, entry: RiscoConfigEntry) -> None:
    """Take over the entities of the standard Risco entry (only once)."""
    if not (old_id := entry.data.get(CONF_MIGRATED_FROM)):
        return
    old = hass.config_entries.async_get_entry(old_id)
    if old is not None and old.domain == CORE_DOMAIN:
        # one connection at a time: the old integration must stop first
        if old.disabled_by is None:
            await hass.config_entries.async_set_disabled_by(
                old_id, ConfigEntryDisabler.USER
            )
        _move_devices(hass, old_id, entry)
        moved = _move_entities(hass, old_id, entry)
        _LOGGER.info("Moved %s entities from the standard Risco integration", moved)
    data = {k: v for k, v in entry.data.items() if k != CONF_MIGRATED_FROM}
    hass.config_entries.async_update_entry(entry, data=data)


def _move_devices(hass: HomeAssistant, old_id: str, entry: RiscoConfigEntry) -> None:
    """Same device names (if renamed) and areas."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, old_id):
        identifiers = {(DOMAIN, i) for d, i in device.identifiers if d == CORE_DOMAIN}
        if not identifiers:
            continue
        new = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=identifiers,
            manufacturer=device.manufacturer,
            name=device.name,
        )
        registry.async_update_device(
            new.id, area_id=device.area_id, name_by_user=device.name_by_user
        )


def _move_entities(hass: HomeAssistant, old_id: str, entry: RiscoConfigEntry) -> int:
    """New entities with the entity ids and settings of the old ones."""
    registry = er.async_get(hass)
    moved = 0
    for old in er.async_entries_for_config_entry(registry, old_id):
        if registry.async_get_entity_id(old.domain, DOMAIN, old.unique_id):
            continue
        entity_id = old.entity_id
        if not entity_id.endswith(OLD_SUFFIX):
            registry.async_update_entity(
                entity_id, new_entity_id=f"{entity_id}{OLD_SUFFIX}"
            )
        new = registry.async_get_or_create(
            old.domain, DOMAIN, old.unique_id, config_entry=entry
        )
        registry.async_update_entity(
            new.entity_id,
            new_entity_id=entity_id,
            name=old.name,
            icon=old.icon,
            area_id=old.area_id,
            hidden_by=old.hidden_by,
            disabled_by=(
                old.disabled_by
                if old.disabled_by is er.RegistryEntryDisabler.USER
                else None
            ),
        )
        moved += 1
    return moved
