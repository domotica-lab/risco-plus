"""Support for Risco alarms.

Risco Plus: based on the Home Assistant 2026.10.2 Risco integration, with:
  - action risco_plus.arm_groups to arm several groups at once (e.g. ["B", "C"]);
  - attribute "armed_groups" with the groups currently armed;
  - optional custom code for arming/disarming from Home Assistant;
  - optional refusal to arm when perimeter zones (doors/windows) are open;
  - automatic retries when Risco Cloud reports the panel as busy (result 52);
  - Home Assistant modes mapped to several groups (e.g. armed_night = B + C);
  - group names and optional bypass of open zones before arming.
Everything else behaves exactly like the original integration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import logging
from typing import Any, override

from pyrisco import OperationError
from pyrisco.common import Partition, Zone
from pyrisco.local.partition import Partition as LocalPartition
import voluptuous as vol

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.const import ATTR_CODE, CONF_PIN
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ARMED_GROUPS,
    ATTR_GROUP_NAMES,
    ATTR_GROUPS,
    CLOUD_BUSY_RESULT,
    COMMAND_RETRIES,
    COMMAND_RETRY_DELAY,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_CUSTOM_CODE,
    CONF_GROUP_NAMES,
    CONF_NOTIFY,
    CONF_HA_STATES_TO_RISCO,
    CONF_PERIMETER_ZONES,
    CONF_RISCO_STATES_TO_HA,
    CONF_ZONE_GROUPS,
    DEFAULT_EXTRA_OPTIONS,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_ARMING_REFUSED,
    EVENT_ZONES_BYPASSED,
    GROUP_ARM_PAUSE,
    OPEN_ZONES_BLOCK,
    OPEN_ZONES_BYPASS,
    OPEN_ZONES_OFF,
    RISCO_ARM,
    RISCO_GROUPS,
    RISCO_NOT_USED,
    RISCO_PARTIAL_ARM,
    SERVICE_ARM_GROUPS,
    open_zones_mode,
    zone_ids_groups,
)
from .coordinator import RiscoDataUpdateCoordinator, use_cloud_cache
from .entity import RiscoCloudEntity
from .groups import groups_of, parse_group_names
from .models import RiscoConfigEntry

_LOGGER = logging.getLogger(__name__)

STATES_TO_SUPPORTED_FEATURES = {
    AlarmControlPanelState.ARMED_AWAY: AlarmControlPanelEntityFeature.ARM_AWAY,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: (
        AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
    ),
    AlarmControlPanelState.ARMED_HOME: AlarmControlPanelEntityFeature.ARM_HOME,
    AlarmControlPanelState.ARMED_NIGHT: AlarmControlPanelEntityFeature.ARM_NIGHT,
}


def _normalize(name: Any) -> str:
    """Normalize a zone name for comparisons (case and spaces)."""
    return " ".join(str(name).lower().split())


def parse_zone_groups(text: str) -> dict[str, str]:
    """Parse "Zone name: BC" lines into {normalized name: "BC"}."""
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        name, groups = line.rsplit(":", 1)
        letters = "".join(g for g in groups.upper() if g in RISCO_GROUPS)
        if name.strip() and letters:
            result[_normalize(name)] = letters
    return result


def zone_groups(zone: Zone, mapping: dict[str, str]) -> str | None:
    """Return the groups of a zone ("BC"), or None if unknown (= all groups).

    `mapping` has normalized names and "#<zone id>" keys (zones chosen per group).
    """
    if (letters := mapping.get(f"#{getattr(zone, 'id', '')}")) is not None:
        return letters
    if (letters := mapping.get(_normalize(getattr(zone, "name", "")))) is not None:
        return letters
    # Local connection: pyrisco knows the zone groups.
    groups = getattr(zone, "groups", None)
    if isinstance(groups, (list, tuple)) and groups:
        return "".join(g for g in groups if g in RISCO_GROUPS) or None
    # Cloud connection: use the groups only if the cloud sends them.
    raw = getattr(zone, "_raw", None)
    if isinstance(raw, dict):
        value = raw.get("groups", raw.get("zoneGroups"))
        if isinstance(value, int) and value > 0:
            return "".join(
                RISCO_GROUPS[i] for i in range(len(RISCO_GROUPS)) if value & (1 << i)
            )
        if isinstance(value, (list, tuple)) and value:
            letters = "".join(
                RISCO_GROUPS[g] if isinstance(g, int) and g < len(RISCO_GROUPS) else str(g)
                for g in value
            )
            return "".join(g for g in letters if g in RISCO_GROUPS) or None
    return None


def open_perimeter_zones(
    zones: Iterable[Zone],
    perimeter_ids: Iterable[Any] | None,
    mapping: dict[str, str],
    groups: list[str] | None,
) -> list[str]:
    """Return the names of open zones that block arming `groups`.

    perimeter_ids=None means every zone; groups=None means a full or partial arm.
    """
    wanted = None if perimeter_ids is None else {str(z) for z in perimeter_ids}
    found = []
    for zone in zones:
        if wanted is not None and str(getattr(zone, "id", "")) not in wanted:
            continue
        if not getattr(zone, "triggered", False):
            continue
        if getattr(zone, "bypassed", False) is True:
            continue
        letters = zone_groups(zone, mapping)
        if groups is None or letters is None or any(g in letters for g in groups):
            found.append(str(getattr(zone, "name", zone.id)).strip())
    return sorted(found)


def zones_to_bypass(
    zones: Iterable[Zone],
    keep_ids: Iterable[Any],
    mapping: dict[str, str],
    groups: list[str] | None,
) -> list[Zone]:
    """Return the open zones to bypass before arming `groups` (None = all).

    Zones in `keep_ids` (the perimeter zones that block arming) are never bypassed.
    """
    keep = {str(zone_id) for zone_id in keep_ids}
    result = []
    for zone in zones:
        if str(getattr(zone, "id", "")) in keep:
            continue
        if getattr(zone, "triggered", False) is not True:
            continue
        if getattr(zone, "bypassed", False) is True:
            continue
        letters = zone_groups(zone, mapping)
        if groups is None or letters is None or any(g in letters for g in groups):
            result.append(zone)
    return result


async def retry_when_busy(func: Callable[..., Any], *args: Any) -> Any:
    """Call a Risco Cloud command, retrying while the panel is busy (result 52)."""
    for attempt in range(1, COMMAND_RETRIES + 1):
        try:
            return await func(*args)
        except OperationError as err:
            if f"'result': {CLOUD_BUSY_RESULT}" not in str(err):
                raise
            if attempt == COMMAND_RETRIES:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="panel_busy",
                ) from err
            _LOGGER.info(
                "Panel busy (%s), retry %s of %s",
                CLOUD_BUSY_RESULT,
                attempt + 1,
                COMMAND_RETRIES,
            )
            await asyncio.sleep(COMMAND_RETRY_DELAY)
    return None


BYPASS_TEXTS = {
    "it": ("Allarme inserito escludendo", "Zone escluse perche' aperte: {zones}"),
    "en": ("Alarm armed with bypassed zones", "Zones bypassed because open: {zones}"),
}
REFUSED_TEXTS = {
    "it": ("Allarme non inserito", "Ci sono zone aperte: {zones}. Chiudile e riprova."),
    "en": ("Alarm not armed", "Open zones: {zones}. Close them and try again."),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RiscoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Risco alarm control panel."""
    options = {**DEFAULT_OPTIONS, **DEFAULT_EXTRA_OPTIONS, **config_entry.options}
    risco_data = config_entry.runtime_data
    if local_data := risco_data.local_data:
        async_add_entities(
            RiscoLocalAlarm(
                local_data.system.id,
                partition_id,
                partition,
                local_data.partition_updates,
                config_entry.data[CONF_PIN],
                options,
                local_data.system.zones,
            )
            for partition_id, partition in local_data.system.partitions.items()
        )
    elif cloud_data := risco_data.cloud_data:
        coordinator = cloud_data.coordinator
        async_add_entities(
            RiscoCloudAlarm(
                coordinator, partition_id, config_entry.data[CONF_PIN], options
            )
            for partition_id in coordinator.data.partitions
        )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ARM_GROUPS,
        {
            # voluptuous: same as the version tested on HA 2026.10.2
            vol.Required(ATTR_GROUPS): vol.All(
                cv.ensure_list,
                [vol.All(cv.string, vol.Upper, vol.In(RISCO_GROUPS))],
            ),
            # needed only when "Require code to arm" is enabled
            vol.Optional(ATTR_CODE): cv.string,
        },
        "async_arm_groups",
    )


class RiscoAlarm(AlarmControlPanelEntity):
    """Representation of a Risco cloud partition."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        *,
        partition_id: int,
        partition: Partition,
        code: str,
        options: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Init the partition."""
        super().__init__(**kwargs)
        self._partition_id = partition_id
        self._partition = partition
        self._code = code
        self._custom_code = str(options.get(CONF_CUSTOM_CODE) or "")
        self._perimeter_zones = list(options.get(CONF_PERIMETER_ZONES) or [])
        self._zone_groups = {
            **parse_zone_groups(options.get(CONF_ZONE_GROUPS) or ""),
            **{f"#{zone_id}": g for zone_id, g in zone_ids_groups(options).items()},
        }
        self._group_names = parse_group_names(options.get(CONF_GROUP_NAMES) or "")
        self._open_zones_mode = open_zones_mode(options)
        self._notifications = bool(options.get(CONF_NOTIFY))
        arm_required = options[CONF_CODE_ARM_REQUIRED]
        # a custom code always protects disarming
        disarm_required = options[CONF_CODE_DISARM_REQUIRED] or bool(self._custom_code)
        self._attr_code_arm_required = arm_required
        self._code_disarm_required = disarm_required
        # numeric keypad for numeric codes, normal keyboard otherwise
        active_code = self._custom_code or str(code)
        self._attr_code_format = (
            (CodeFormat.NUMBER if active_code.isdigit() else CodeFormat.TEXT)
            if arm_required or disarm_required
            else None
        )
        self._risco_to_ha = options[CONF_RISCO_STATES_TO_HA]
        self._ha_to_risco = options[CONF_HA_STATES_TO_RISCO]
        for state, risco_state in self._ha_to_risco.items():
            if risco_state and risco_state != RISCO_NOT_USED:
                self._attr_supported_features |= STATES_TO_SUPPORTED_FEATURES[state]

    def _armed_groups(self) -> list[str]:
        """Return the armed groups, e.g. ["B", "C"]."""
        groups = getattr(self._partition, "groups", None) or {}
        return sorted(group for group, armed in groups.items() if armed)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the armed groups (and their names, if set)."""
        if self._partition.armed:
            attributes = {ATTR_ARMED_GROUPS: list(RISCO_GROUPS)}
        else:
            attributes = {ATTR_ARMED_GROUPS: self._armed_groups()}
        if self._group_names:
            attributes[ATTR_GROUP_NAMES] = dict(self._group_names)
        return attributes

    @property
    @override
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the device."""
        if self._partition.triggered:
            return AlarmControlPanelState.TRIGGERED
        if self._partition.arming:
            return AlarmControlPanelState.ARMING
        if self._partition.disarmed:
            return AlarmControlPanelState.DISARMED
        if self._partition.armed:
            return self._risco_to_ha[RISCO_ARM]
        if self._partition.partially_armed:
            armed = self._armed_groups()
            # every group armed one by one = full arm
            if set(armed) >= set(RISCO_GROUPS):
                return self._risco_to_ha[RISCO_ARM]
            # a Home Assistant mode mapped to exactly these groups (e.g. night = BC)
            if len(armed) > 1:
                for ha_state, risco_state in self._ha_to_risco.items():
                    combo = groups_of(risco_state)
                    if combo and sorted(combo) == armed:
                        return AlarmControlPanelState(ha_state)
            if armed:
                return self._risco_to_ha[armed[0]]
            return self._risco_to_ha[RISCO_PARTIAL_ARM]

        return None

    def _refuse_code(self, action: str) -> None:
        """Wrong or missing code: stop with a clear message."""
        _LOGGER.warning("Wrong code entered for %s", action)
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_code"
        )

    def _validate_code(self, code: str | None) -> bool:
        """Validate given code (custom code if set, otherwise the PIN)."""
        if code is None:
            return False
        if self._custom_code:
            return str(code) == self._custom_code
        return str(code) == str(self._code)

    async def _current_zones(self) -> list[Zone]:
        """Return the current zones."""
        return []

    async def _check_open_zones(self, groups: list[str] | None) -> None:
        """Before arming `groups` (None = full/partial arm).

        Refuse (and notify) when a blocking zone is open: every open zone of the
        groups ("block") or the chosen zones ("block_selected", "bypass"). With
        "bypass" the other open zones are bypassed (like the iRISCO app does).
        """
        mode = self._open_zones_mode
        if mode == OPEN_ZONES_OFF:
            return
        zones = await self._current_zones()
        open_zones = open_perimeter_zones(
            zones,
            None if mode == OPEN_ZONES_BLOCK else self._perimeter_zones,
            self._zone_groups,
            groups,
        )
        if open_zones:
            _LOGGER.warning("Arming refused, open zones: %s", open_zones)
            self._notify(EVENT_ARMING_REFUSED, REFUSED_TEXTS, open_zones, "refused")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="open_zones",
                translation_placeholders={"zones": ", ".join(open_zones)},
            )
        if mode != OPEN_ZONES_BYPASS:
            return
        bypass = zones_to_bypass(
            zones, self._perimeter_zones, self._zone_groups, groups
        )
        if not bypass:
            return
        names = sorted(str(getattr(z, "name", z.id)).strip() for z in bypass)
        _LOGGER.info("Bypassing open zones before arming: %s", names)
        for zone in bypass:
            await retry_when_busy(zone.bypass, True)
        self._notify(EVENT_ZONES_BYPASSED, BYPASS_TEXTS, names, "bypass")
        await asyncio.sleep(GROUP_ARM_PAUSE)

    def _notify(
        self, event: str, texts: dict[str, tuple[str, str]], names: list[str], kind: str
    ) -> None:
        """Event (for your own automations) + optional Home Assistant notification."""
        if self.hass is None:
            return
        self.hass.bus.async_fire(event, {"entity_id": self.entity_id, "zones": names})
        if not self._notifications:
            return
        title, message = texts.get((self.hass.config.language or "en")[:2], texts["en"])
        persistent_notification.async_create(
            self.hass,
            message.format(zones=", ".join(names)),
            title=title,
            notification_id=f"risco_{kind}_{self.unique_id}",
        )

    @override
    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if self._code_disarm_required and not self._validate_code(code):
            self._refuse_code("disarming")
        await self._call_alarm_method("disarm")

    @override
    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        await self._arm(AlarmControlPanelState.ARMED_HOME, code)

    @override
    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        await self._arm(AlarmControlPanelState.ARMED_AWAY, code)

    @override
    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""
        await self._arm(AlarmControlPanelState.ARMED_NIGHT, code)

    @override
    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Send arm custom bypass command."""
        await self._arm(AlarmControlPanelState.ARMED_CUSTOM_BYPASS, code)

    async def _arm(self, mode: AlarmControlPanelState, code: str | None) -> None:
        if self.code_arm_required and not self._validate_code(code):
            self._refuse_code(str(mode))

        risco_state = self._ha_to_risco.get(mode)
        if not risco_state or risco_state == RISCO_NOT_USED:
            _LOGGER.warning("No mapping for mode %s", mode)
            return

        if groups := groups_of(risco_state):
            # one group ("C") or several groups ("BC")
            await self._arm_groups(groups)
        else:
            await self._check_open_zones(None)
            await self._call_alarm_method(risco_state)

    async def async_arm_groups(
        self, groups: list[str], code: str | None = None
    ) -> None:
        """Arm the selected groups (action risco_plus.arm_groups)."""
        if self.code_arm_required and not self._validate_code(code):
            self._refuse_code("arming groups")
        await self._arm_groups(groups)

    async def _arm_groups(self, groups: list[str]) -> None:
        """Arm the groups one after the other (open zones checked first)."""
        groups = list(dict.fromkeys(groups))
        await self._check_open_zones(groups)
        for index, group in enumerate(groups):
            if index:
                await asyncio.sleep(GROUP_ARM_PAUSE)
            await self._call_alarm_method("group_arm", group)

    async def _call_alarm_method(self, method: str, *args: Any) -> None:
        raise NotImplementedError


class RiscoCloudAlarm(RiscoAlarm, RiscoCloudEntity):
    """Representation of a Risco partition."""

    def __init__(
        self,
        coordinator: RiscoDataUpdateCoordinator,
        partition_id: int,
        code: str,
        options: dict[str, Any],
    ) -> None:
        """Init the partition."""
        super().__init__(
            partition_id=partition_id,
            partition=coordinator.data.partitions[partition_id],
            coordinator=coordinator,
            code=code,
            options=options,
        )
        self._attr_unique_id = f"{self._risco.site_uuid}_{partition_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=f"Risco {self._risco.site_name} Partition {partition_id}",
            manufacturer="Risco",
        )

    @override
    def _get_data_from_coordinator(self) -> None:
        self._partition = self.coordinator.data.partitions[self._partition_id]

    @override
    async def _current_zones(self) -> list[Zone]:
        """Fresh zones; when reading live, give the panel time before a command."""
        await self.coordinator.async_refresh()
        if not use_cloud_cache(self.coordinator.config_entry):
            await asyncio.sleep(2)
        data = self.coordinator.data
        return list(data.zones.values()) if data else []

    @override
    async def _call_alarm_method(self, method: str, *args: Any) -> None:
        alarm = await retry_when_busy(
            getattr(self._risco, method), self._partition_id, *args
        )
        try:
            partitions = alarm.partitions
        except (KeyError, TypeError):
            partitions = None
        if partitions and self._partition_id in partitions:
            self._partition = partitions[self._partition_id]
        else:
            await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class RiscoLocalAlarm(RiscoAlarm):
    """Representation of a Risco local, partition."""

    _attr_should_poll = False

    def __init__(
        self,
        system_id: str,
        partition_id: int,
        partition: LocalPartition,
        partition_updates: dict[int, Callable[[], Any]],
        code: str,
        options: dict[str, Any],
        zones: dict[int, Zone] | None = None,
    ) -> None:
        """Init the partition."""
        super().__init__(
            partition_id=partition_id, partition=partition, code=code, options=options
        )
        self._system_id = system_id
        self._partition_updates = partition_updates
        self._zones = zones or {}
        self._attr_unique_id = f"{system_id}_{partition_id}_local"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=partition.name,
            manufacturer="Risco",
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self._partition_updates[self._partition_id] = self.async_write_ha_state

    @override
    async def _current_zones(self) -> list[Zone]:
        """Local zones are pushed by the panel: already up to date."""
        return list(self._zones.values())

    @override
    async def _call_alarm_method(self, method: str, *args: Any) -> None:
        await getattr(self._partition, method)(*args)
