"""Config flow for Risco integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, override

import probatio
from pyrisco import CannotConnectError, RiscoCloud, RiscoLocal, UnauthorizedError

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AUTO_BYPASS,
    CONF_GROUP_ZONES,
    CONF_MIGRATED_FROM,
    CONF_NOTIFY,
    CORE_DOMAIN,
    CONF_OPEN_ZONES_MODE,
    CONF_ZONE_GROUPS_SECTION,
    OPEN_ZONES_MODES,
    open_zones_mode,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_COMMUNICATION_DELAY,
    CONF_CLOUD_CACHE,
    CONF_CONCURRENCY,
    CONF_CUSTOM_CODE,
    CONF_EXTRA_OPTIONS,
    CONF_GROUP_ENTITIES,
    CONF_GROUP_NAMES,
    CONF_HA_STATES_TO_RISCO,
    CONF_PERIMETER_ZONES,
    CONF_ZONE_GROUPS,
    CONF_MORE_OPTIONS,
    CONF_RISCO_STATES_TO_HA,
    DEFAULT_ADVANCED_OPTIONS,
    DEFAULT_EXTRA_OPTIONS,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_COMMUNICATION_DELAY,
    RISCO_GROUP_COMBOS,
    RISCO_NOT_USED,
    RISCO_STATES,
    TYPE_LOCAL,
)
from .groups import groups_of
from .models import RiscoConfigEntry


def _to_choice(risco_state: str) -> str:
    """Group values are lowercase in the selector ("bc"), saved uppercase ("BC")."""
    return risco_state.lower() if groups_of(risco_state) else risco_state


def _from_choice(choice: str) -> str:
    return choice.upper() if groups_of(choice.upper()) else choice

_LOGGER = logging.getLogger(__name__)


CLOUD_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        probatio.Required(probatio.Secret(CONF_PIN)): str,
    }
)
LOCAL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_PORT, default=1000): int,
        probatio.Required(probatio.Secret(CONF_PIN)): str,
    }
)
HA_STATES = [
    AlarmControlPanelState.ARMED_AWAY.value,
    AlarmControlPanelState.ARMED_HOME.value,
    AlarmControlPanelState.ARMED_NIGHT.value,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS.value,
]


async def validate_cloud_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Validate the user input allows us to connect to Risco Cloud.

    Data has the keys from CLOUD_SCHEMA with values provided by the user.
    """
    risco = RiscoCloud(data[CONF_USERNAME], data[CONF_PASSWORD], data[CONF_PIN])

    try:
        await risco.login(async_get_clientsession(hass))
    finally:
        await risco.close()

    return {"title": risco.site_name}


async def validate_local_input(
    hass: HomeAssistant, data: Mapping[str, str]
) -> dict[str, Any]:
    """Validate the user input allows us to connect to a local panel.

    Data has the keys from LOCAL_SCHEMA with values provided by the user.
    """
    comm_delay = 0
    while True:
        risco = RiscoLocal(
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_PIN],
            communication_delay=comm_delay,
        )
        try:
            await risco.connect()
        except CannotConnectError:
            if comm_delay >= MAX_COMMUNICATION_DELAY:
                raise
            comm_delay += 1
        else:
            break

    site_id = risco.id
    await risco.disconnect()
    return {"title": site_id, "comm_delay": comm_delay}


class RiscoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Risco."""

    VERSION = 1

    def __init__(self) -> None:
        """Init the config flow."""
        self._reauth_entry: RiscoConfigEntry | None = None

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: RiscoConfigEntry,
    ) -> RiscoOptionsFlowHandler:
        """Define the config flow to handle options."""
        return RiscoOptionsFlowHandler(config_entry)

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        menu = ["cloud", "local"]
        if self._core_entries():
            menu.insert(0, "migrate")
        return self.async_show_menu(step_id="user", menu_options=menu)

    def _core_entries(self) -> list[ConfigEntry]:
        """Entries of the standard Risco integration not taken over yet."""
        taken = {
            entry.unique_id for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        return [
            entry
            for entry in self.hass.config_entries.async_entries(CORE_DOMAIN)
            if entry.unique_id not in taken
        ]

    async def async_step_migrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Copy account and options from the standard Risco integration."""
        entries = {entry.entry_id: entry for entry in self._core_entries()}
        if not entries:
            return self.async_abort(reason="nothing_to_migrate")
        if user_input is not None or len(entries) == 1:
            entry_id = (user_input or {}).get("entry") or next(iter(entries))
            old = entries[entry_id]
            await self.async_set_unique_id(old.unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=old.title,
                data={**old.data, CONF_MIGRATED_FROM: old.entry_id},
                options=dict(old.options),
            )
        return self.async_show_form(
            step_id="migrate",
            data_schema=probatio.Schema(
                {
                    probatio.Required("entry"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=i, label=e.title)
                                for i, e in entries.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a cloud based alarm."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not self._reauth_entry:
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()

            try:
                info = await validate_cloud_input(self.hass, user_input)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except UnauthorizedError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if not self._reauth_entry:
                    return self.async_create_entry(title=info["title"], data=user_input)
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data=user_input,
                    unique_id=user_input[CONF_USERNAME],
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="cloud", data_schema=CLOUD_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle configuration by re-auth."""
        self._reauth_entry = await self.async_set_unique_id(entry_data[CONF_USERNAME])
        return await self.async_step_cloud()

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a local based alarm."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_local_input(self.hass, user_input)
            except CannotConnectError as ex:
                _LOGGER.debug("Cannot connect", exc_info=ex)
                errors["base"] = "cannot_connect"
            except UnauthorizedError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["title"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data={
                        **user_input,
                        CONF_TYPE: TYPE_LOCAL,
                        CONF_COMMUNICATION_DELAY: info["comm_delay"],
                    },
                )

        return self.async_show_form(
            step_id="local", data_schema=LOCAL_SCHEMA, errors=errors
        )


class RiscoOptionsFlowHandler(OptionsFlow):
    """Handle a Risco options flow."""

    def __init__(self, config_entry: RiscoConfigEntry) -> None:
        """Initialize."""
        self._entry = config_entry
        self._data = {**DEFAULT_OPTIONS, **config_entry.options}

    def _zone_options(self, key: str = CONF_PERIMETER_ZONES) -> list[SelectOptionDict]:
        """Zones of the panel, for the zone selectors."""
        zones: dict[Any, Any] = {}
        runtime = getattr(self._entry, "runtime_data", None)
        if runtime is not None:
            if runtime.local_data:
                zones = runtime.local_data.system.zones
            elif runtime.cloud_data and runtime.cloud_data.coordinator.data:
                zones = runtime.cloud_data.coordinator.data.zones
        result = [
            SelectOptionDict(value=str(zone_id), label=f"{zone.name} ({zone_id})")
            for zone_id, zone in sorted(zones.items())
        ]
        # keep zones already selected even if the panel did not report them now
        known = {item["value"] for item in result}
        result.extend(
            SelectOptionDict(value=str(zone_id), label=str(zone_id))
            for zone_id in self._data.get(key) or []
            if str(zone_id) not in known
        )
        return result

    def _options_schema(self) -> probatio.Schema:
        self._data = {
            **DEFAULT_ADVANCED_OPTIONS,
            **DEFAULT_EXTRA_OPTIONS,
            **self._data,
        }
        return probatio.Schema(
            {
                probatio.Required(
                    CONF_CODE_ARM_REQUIRED, default=self._data[CONF_CODE_ARM_REQUIRED]
                ): bool,
                probatio.Required(
                    CONF_CODE_DISARM_REQUIRED,
                    default=self._data[CONF_CODE_DISARM_REQUIRED],
                ): bool,
                probatio.Optional(CONF_EXTRA_OPTIONS): section(
                    probatio.Schema(
                        {
                            probatio.Optional(
                                CONF_CUSTOM_CODE,
                                default=self._data[CONF_CUSTOM_CODE],
                            ): TextSelector(
                                TextSelectorConfig(type=TextSelectorType.PASSWORD)
                            ),
                            probatio.Optional(
                                CONF_GROUP_NAMES,
                                default=self._data[CONF_GROUP_NAMES],
                            ): TextSelector(TextSelectorConfig(multiline=True)),
                            probatio.Required(
                                CONF_GROUP_ENTITIES,
                                default=self._data[CONF_GROUP_ENTITIES],
                            ): BooleanSelector(),
                            probatio.Required(
                                CONF_OPEN_ZONES_MODE,
                                default=open_zones_mode(self._data),
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=OPEN_ZONES_MODES,
                                    translation_key="open_zones_mode",
                                    mode=SelectSelectorMode.LIST,
                                )
                            ),
                            probatio.Required(
                                CONF_NOTIFY,
                                default=self._data[CONF_NOTIFY],
                            ): BooleanSelector(),
                            probatio.Optional(
                                CONF_PERIMETER_ZONES,
                                default=[
                                    str(z) for z in self._data[CONF_PERIMETER_ZONES]
                                ],
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=self._zone_options(),
                                    multiple=True,
                                    mode=SelectSelectorMode.DROPDOWN,
                                )
                            ),
                            probatio.Required(
                                CONF_CLOUD_CACHE,
                                default=self._data[CONF_CLOUD_CACHE],
                            ): BooleanSelector(),
                        }
                    ),
                    SectionConfig(collapsed=False),
                ),
                probatio.Optional(CONF_ZONE_GROUPS_SECTION): section(
                    probatio.Schema(
                        {
                            **{
                                probatio.Optional(
                                    key,
                                    default=[str(z) for z in self._data.get(key) or []],
                                ): SelectSelector(
                                    SelectSelectorConfig(
                                        options=self._zone_options(key),
                                        multiple=True,
                                        mode=SelectSelectorMode.DROPDOWN,
                                    )
                                )
                                for key in CONF_GROUP_ZONES.values()
                            },
                            probatio.Optional(
                                CONF_ZONE_GROUPS,
                                default=self._data[CONF_ZONE_GROUPS],
                            ): TextSelector(TextSelectorConfig(multiline=True)),
                        }
                    ),
                    SectionConfig(collapsed=True),
                ),
                probatio.Required(CONF_MORE_OPTIONS): section(
                    probatio.Schema(
                        {
                            # Polling interval is user-configurable,
                            # which is no longer allowed
                            # pylint: disable-next=home-assistant-config-flow-polling-field
                            probatio.Required(
                                CONF_SCAN_INTERVAL,
                                default=self._data[CONF_SCAN_INTERVAL],
                            ): int,
                            probatio.Required(
                                CONF_CONCURRENCY,
                                default=self._data[CONF_CONCURRENCY],
                            ): int,
                        }
                    ),
                    SectionConfig(collapsed=True),
                ),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            more_options = user_input.pop(CONF_MORE_OPTIONS, {})
            user_input.update(more_options)
            extra_options = user_input.pop(CONF_EXTRA_OPTIONS, {})
            zone_groups_section = user_input.pop(CONF_ZONE_GROUPS_SECTION, {})
            user_input.update(
                {**DEFAULT_EXTRA_OPTIONS, **extra_options, **zone_groups_section}
            )
            # the open zones mode replaces the old "bypass open zones" switch
            user_input[CONF_AUTO_BYPASS] = False
            user_input[CONF_CUSTOM_CODE] = str(
                user_input.get(CONF_CUSTOM_CODE) or ""
            ).strip()
            self._data = {**self._data, **user_input}
            return await self.async_step_risco_to_ha()

        return self.async_show_form(step_id="init", data_schema=self._options_schema())

    async def async_step_risco_to_ha(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Map Risco states to HA states."""
        if user_input is not None:
            self._data[CONF_RISCO_STATES_TO_HA] = user_input
            return await self.async_step_ha_to_risco()

        risco_to_ha = self._data[CONF_RISCO_STATES_TO_HA]
        options = probatio.Schema(
            {
                probatio.Required(
                    risco_state, default=risco_to_ha[risco_state]
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=HA_STATES,
                        translation_key="ha_state",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
                for risco_state in RISCO_STATES
            }
        )

        return self.async_show_form(step_id="risco_to_ha", data_schema=options)

    async def async_step_ha_to_risco(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Map HA states to Risco states."""
        if user_input is not None:
            # "not used" modes are not saved (same format as the core integration)
            self._data[CONF_HA_STATES_TO_RISCO] = {
                ha_state: _from_choice(choice)
                for ha_state, choice in user_input.items()
                if choice != RISCO_NOT_USED
            }
            return self.async_create_entry(title="", data=self._data)

        options = {}
        risco_to_ha = self._data[CONF_RISCO_STATES_TO_HA]
        # we iterate over HA_STATES, instead of set(self._risco_to_ha.values())
        # to ensure a consistent order
        for ha_state in HA_STATES:
            values = [
                risco_state
                for risco_state in RISCO_STATES
                if risco_to_ha[risco_state] == ha_state
            ]
            # Risco Plus: every mode can also arm several groups (e.g. B + C);
            # a mode no Risco state reports can be left unused
            choices = [
                _to_choice(c) for c in (values or [RISCO_NOT_USED]) + RISCO_GROUP_COMBOS
            ]
            current = _to_choice(self._data[CONF_HA_STATES_TO_RISCO].get(ha_state) or "")
            if current not in choices:
                current = choices[0]
            options[probatio.Required(ha_state, default=current)] = SelectSelector(
                SelectSelectorConfig(
                    options=choices,
                    translation_key="risco_state",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        return self.async_show_form(
            step_id="ha_to_risco", data_schema=probatio.Schema(options)
        )
