"""Tests for the Risco Plus additions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from pyrisco import OperationError
import pytest

from homeassistant.components.alarm_control_panel import (
    DOMAIN as ALARM_DOMAIN,
    AlarmControlPanelState,
)
from homeassistant.const import SERVICE_ALARM_ARM_AWAY, SERVICE_ALARM_DISARM
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.risco_plus.alarm_control_panel import (
    open_perimeter_zones,
    parse_zone_groups,
    zone_groups,
    zones_to_bypass,
)
from custom_components.risco_plus.groups import armed_groups, groups_of, parse_group_names
from custom_components.risco_plus.const import DOMAIN, open_zones_mode, zone_ids_groups

from .util import system_mock, zone_mock

ENTITY = "alarm_control_panel.risco_test_site_name_partition_0"
BUSY = OperationError(
    "{'result': 52, 'validationErrors': None, 'response': {'partitions': None}}"
)


def _partition(**kwargs: Any) -> MagicMock:
    data = {
        "triggered": False,
        "arming": False,
        "armed": False,
        "disarmed": True,
        "partially_armed": False,
        "groups": {"A": False, "B": False, "C": False, "D": False},
    }
    data.update(kwargs)
    return MagicMock(**data)


def _zone(zone_id: int, name: str, triggered: bool = False) -> MagicMock:
    zone = zone_mock()
    zone.id = zone_id
    zone.name = name
    zone.triggered = triggered
    zone.bypassed = False
    zone._raw = {}  # cloud: no groups reported
    return zone


@pytest.fixture
def panel():
    """Cloud alarm with one partition and three zones."""
    partition = _partition()
    zones = {
        1: _zone(1, "Kitchen window"),
        2: _zone(2, "Hall motion"),
        3: _zone(3, "Garage door"),
    }
    alarm = MagicMock()
    with (
        patch.object(alarm, "partitions", new_callable=PropertyMock(return_value={0: partition})),
        patch.object(alarm, "zones", new_callable=PropertyMock(return_value=zones)),
        patch("custom_components.risco_plus.RiscoCloud.get_state", return_value=alarm),
        patch("custom_components.risco_plus.alarm_control_panel.asyncio.sleep", AsyncMock()),
    ):
        yield {"alarm": alarm, "partition": partition, "zones": zones}


async def _call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(
        ALARM_DOMAIN, service, {"entity_id": ENTITY, **data}, blocking=True
    )


# ---------------------------------------------------------------- pure helpers


def test_parse_zone_groups() -> None:
    """Lines "name: groups" are parsed, junk ignored."""
    assert parse_zone_groups("Kitchen  Window : bc\nno colon\nGarage: XD\n: A") == {
        "kitchen window": "BC",
        "garage": "D",
    }


def test_zone_groups_sources() -> None:
    """Mapping first, then local groups, then cloud raw bitmask."""
    zone = _zone(1, "Kitchen window")
    assert zone_groups(zone, {"kitchen window": "C"}) == "C"
    local = MagicMock(groups=["B", "D"])
    local.name = "x"
    assert zone_groups(local, {}) == "BD"
    zone._raw = {"groups": 0b0101}
    zone.groups = None
    assert zone_groups(zone, {}) == "AC"
    zone._raw = {}
    assert zone_groups(zone, {}) is None


def test_open_perimeter_zones() -> None:
    """Only open, selected zones of the requested groups block arming."""
    zones = [
        _zone(1, "Kitchen window", True),
        _zone(2, "Hall motion", True),
        _zone(3, "Garage door", True),
    ]
    for zone in zones:
        zone.groups = None
    mapping = {"kitchen window": "C"}
    assert open_perimeter_zones(zones, ["1", 3], mapping, None) == [
        "Garage door",
        "Kitchen window",
    ]
    # group A: kitchen (C) does not block, garage (unknown groups) does
    assert open_perimeter_zones(zones, ["1", "3"], mapping, ["A"]) == ["Garage door"]
    assert open_perimeter_zones(zones, ["1"], mapping, ["A"]) == []
    assert open_perimeter_zones(zones, [], mapping, None) == []


# ------------------------------------------------------------------ the entity


async def test_arm_groups_service(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """risco_plus.arm_groups arms each group, in order, without duplicates."""
    with patch(
        "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
    ) as group_arm:
        await hass.services.async_call(
            DOMAIN,
            "arm_groups",
            {"entity_id": ENTITY, "groups": ["b", "C", "B"]},
            blocking=True,
        )
    assert [c.args for c in group_arm.call_args_list] == [(0, "B"), (0, "C")]


async def test_armed_groups_attribute(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """armed_groups lists the groups; all four groups = armed away."""
    part = panel["partition"]
    part.disarmed = False
    part.partially_armed = True
    part.groups = {"A": False, "B": True, "C": True, "D": False}
    await hass.data["entity_components"][ALARM_DOMAIN].get_entity(ENTITY).async_update_ha_state()
    coordinator = setup_risco_cloud.runtime_data.cloud_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["armed_groups"] == ["B", "C"]
    part.groups = dict.fromkeys("ABCD", True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == AlarmControlPanelState.ARMED_AWAY


@pytest.mark.parametrize(
    "options",
    [{"code_arm_required": False, "code_disarm_required": True, "custom_code": "2468"}],
)
async def test_custom_code(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """With a custom code only that code disarms (not the integration PIN)."""
    panel["partition"].disarmed = False
    panel["partition"].armed = True
    with patch(
        "custom_components.risco_plus.RiscoCloud.disarm", return_value=panel["alarm"]
    ) as disarm:
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, SERVICE_ALARM_DISARM, code="1234")  # integration PIN
        assert err.value.translation_key == "invalid_code"
        disarm.assert_not_called()
        await _call(hass, SERVICE_ALARM_DISARM, code="2468")
        disarm.assert_awaited_once()


@pytest.mark.parametrize(
    "options",
    [{"code_arm_required": False, "code_disarm_required": False, "custom_code": "2468"}],
)
async def test_custom_code_always_protects_disarm(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """A custom code is required to disarm even if the option is off."""
    panel["partition"].disarmed = False
    panel["partition"].armed = True
    state = hass.states.get(ENTITY)
    assert state.attributes["code_format"] == "number"
    assert state.attributes["code_arm_required"] is False
    with patch(
        "custom_components.risco_plus.RiscoCloud.disarm", return_value=panel["alarm"]
    ) as disarm:
        with pytest.raises(ServiceValidationError):
            await _call(hass, SERVICE_ALARM_DISARM)  # no code
        disarm.assert_not_called()
        await _call(hass, SERVICE_ALARM_DISARM, code="2468")
        disarm.assert_awaited_once()
    # arming still needs no code
    with patch(
        "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
    ) as group_arm:
        await hass.services.async_call(
            DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["B"]}, blocking=True
        )
    group_arm.assert_awaited_once()


@pytest.mark.parametrize(
    "options",
    [{"code_disarm_required": True, "custom_code": "casa24"}],
)
async def test_custom_code_with_letters(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """A code with letters asks for a normal keyboard, not the numeric keypad."""
    assert hass.states.get(ENTITY).attributes["code_format"] == "text"


@pytest.mark.parametrize(
    "options",
    [{"code_arm_required": True, "code_disarm_required": False}],
)
async def test_arm_groups_requires_code(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """With "Require code to arm", risco_plus.arm_groups needs the code too."""
    with patch(
        "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
    ) as group_arm:
        for data in ({}, {"code": "9999"}):
            with pytest.raises(ServiceValidationError):
                await hass.services.async_call(
                    DOMAIN,
                    "arm_groups",
                    {"entity_id": ENTITY, "groups": ["B"], **data},
                    blocking=True,
                )
        group_arm.assert_not_called()
        await hass.services.async_call(
            DOMAIN,
            "arm_groups",
            {"entity_id": ENTITY, "groups": ["B"], "code": "1234"},
            blocking=True,
        )
        group_arm.assert_awaited_once()


@pytest.mark.parametrize(
    "options",
    [
        {
            "perimeter_zones": ["1", "3"],
            "zone_groups": "Kitchen window: C\nGarage door: BCD",
        }
    ],
)
async def test_open_zones_block_arming(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Open perimeter zones refuse full arm and the arming of their groups."""
    panel["zones"][1].triggered = True  # kitchen window (C) open
    panel["zones"][2].triggered = True  # motion: not a perimeter zone
    with (
        patch("custom_components.risco_plus.RiscoCloud.arm", return_value=panel["alarm"]) as arm,
        patch(
            "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
        ) as group_arm,
    ):
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, SERVICE_ALARM_ARM_AWAY)
        assert err.value.translation_key == "open_zones"
        assert err.value.translation_placeholders == {"zones": "Kitchen window"}
        arm.assert_not_called()

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["A", "C"]},
                blocking=True,
            )
        group_arm.assert_not_called()

        # group A only: the kitchen window does not matter
        await hass.services.async_call(
            DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["A"]}, blocking=True
        )
        group_arm.assert_awaited_once_with(0, "A")

        # everything closed: full arm works
        panel["zones"][1].triggered = False
        await _call(hass, SERVICE_ALARM_ARM_AWAY)
        arm.assert_awaited_once()


async def test_busy_panel_retries(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Result 52 is retried; after the last try a clear error is raised."""
    with patch(
        "custom_components.risco_plus.RiscoCloud.arm",
        side_effect=[BUSY, BUSY, panel["alarm"]],
    ) as arm:
        await _call(hass, SERVICE_ALARM_ARM_AWAY)
    assert arm.await_count == 3

    with patch("custom_components.risco_plus.RiscoCloud.arm", side_effect=BUSY) as arm:
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, SERVICE_ALARM_ARM_AWAY)
    assert err.value.translation_key == "panel_busy"
    assert arm.await_count == 3

    other = OperationError("{'result': 7}")
    with patch("custom_components.risco_plus.RiscoCloud.arm", side_effect=other):
        with pytest.raises(OperationError):
            await _call(hass, SERVICE_ALARM_ARM_AWAY)


async def test_busy_response_without_partitions(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """A command answer without partitions does not crash: state is refreshed."""
    empty = MagicMock()
    type(empty).partitions = PropertyMock(side_effect=TypeError)
    with patch("custom_components.risco_plus.RiscoCloud.arm", return_value=empty):
        await _call(hass, SERVICE_ALARM_ARM_AWAY)
    assert hass.states.get(ENTITY) is not None


@pytest.mark.parametrize("options", [{"read_from_cloud_cache": True}])
async def test_cloud_cache(hass: HomeAssistant, panel, cloud_config_entry, events) -> None:
    """With the option on, state is read from the cloud copy, not the panel."""
    payload = {"state": {"status": {"partitions": [], "zones": []}}}
    with (
        patch("custom_components.risco_plus.RiscoCloud.login", return_value=True),
        patch(
            "custom_components.risco_plus.RiscoCloud.site_uuid",
            new_callable=PropertyMock(return_value="test-site-uuid"),
        ),
        patch(
            "custom_components.risco_plus.RiscoCloud.site_name",
            new_callable=PropertyMock(return_value="test-site-name"),
        ),
        patch("custom_components.risco_plus.RiscoCloud.close"),
        patch(
            "custom_components.risco_plus.RiscoCloud._authenticated_post",
            return_value=payload,
        ) as post,
        patch("custom_components.risco_plus.RiscoCloud.get_events") as get_events,
    ):
        await hass.config_entries.async_setup(cloud_config_entry.entry_id)
        await hass.async_block_till_done()
    panel_state = panel  # get_state is patched by the fixture
    assert post.call_count >= 1
    for call in post.call_args_list:
        assert call.args[1]["fromControlPanel"] is False
    get_events.assert_not_called()
    assert panel_state is not None


async def test_options_flow_extra(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """The Risco Plus section is saved (code trimmed, zones as text ids)."""
    entry = setup_risco_cloud
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "code_arm_required": True,
            "code_disarm_required": True,
            "more_options": {"scan_interval": 30, "concurrency": 4},
            "extra_options": {
                "custom_code": " 2468 ",
                "open_zones_mode": "block_selected",
                "perimeter_zones": ["1", "3"],
                "read_from_cloud_cache": True,
            },
            "zone_groups_section": {
                "zones_group_c": ["1"],
                "zone_groups": "Garage door: D",
            },
        },
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    if result.get("step_id") == "ha_to_risco":
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={}
        )
    assert entry.options["custom_code"] == "2468"
    assert entry.options["perimeter_zones"] == ["1", "3"]
    assert entry.options["read_from_cloud_cache"] is True
    assert entry.options["open_zones_mode"] == "block_selected"
    assert entry.options["zones_group_c"] == ["1"]
    assert entry.options["zone_groups"] == "Garage door: D"
    assert "extra_options" not in entry.options
    assert "zone_groups_section" not in entry.options


# --------------------------------------------------------- groups (Risco Plus)


def test_group_helpers() -> None:
    """Group names, mapping values and armed groups."""
    assert parse_group_names("b: Balconi\nX: no\nC:\nA : Primo piano") == {
        "B": "Balconi",
        "A": "Primo piano",
    }
    assert groups_of("C") == ["C"]
    assert groups_of("BC") == ["B", "C"]
    assert groups_of("arm") is None
    assert groups_of("partial_arm") is None
    assert groups_of("none") is None
    assert armed_groups(_partition(armed=True)) == ["A", "B", "C", "D"]
    assert armed_groups(_partition(groups={"A": False, "B": True, "C": True, "D": False})) == ["B", "C"]


def test_zones_to_bypass() -> None:
    """Open zones of the groups are bypassed, perimeter and bypassed ones are not."""
    zones = [
        _zone(1, "Kitchen window", True),
        _zone(2, "Hall motion", True),
        _zone(3, "Garage door", True),
        _zone(4, "Closed door", False),
    ]
    zones[2].bypassed = True
    for zone in zones:
        zone.groups = None
    mapping = {"hall motion": "A"}
    names = lambda found: [z.name for z in found]  # noqa: E731
    assert names(zones_to_bypass(zones, [], mapping, None)) == ["Kitchen window", "Hall motion"]
    assert names(zones_to_bypass(zones, ["1"], mapping, None)) == ["Hall motion"]
    # group B: hall motion (A) stays, kitchen window (unknown groups) is bypassed
    assert names(zones_to_bypass(zones, [], mapping, ["B"])) == ["Kitchen window"]


COMBO_OPTIONS = {
    "risco_states_to_ha": {
        "arm": "armed_away",
        "partial_arm": "armed_home",
        "A": "armed_home",
        "B": "armed_home",
        "C": "armed_home",
        "D": "armed_home",
    },
    "ha_states_to_risco": {
        "armed_away": "arm",
        "armed_home": "partial_arm",
        "armed_night": "BC",
    },
    "group_names": "B: Balconi\nC: Cantina",
}


@pytest.mark.parametrize("options", [COMBO_OPTIONS])
async def test_mode_with_several_groups(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """Night = B + C: arms both groups and is shown as armed night."""
    state = hass.states.get(ENTITY)
    assert state.attributes["group_names"] == {"B": "Balconi", "C": "Cantina"}
    with patch(
        "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
    ) as group_arm:
        await _call(hass, "alarm_arm_night")
    assert [c.args for c in group_arm.call_args_list] == [(0, "B"), (0, "C")]

    part = panel["partition"]
    part.disarmed = False
    part.partially_armed = True
    coordinator = setup_risco_cloud.runtime_data.cloud_data.coordinator
    part.groups = {"A": False, "B": True, "C": True, "D": False}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == AlarmControlPanelState.ARMED_NIGHT
    # only B: not the night combination -> mapping of group B
    part.groups = {"A": False, "B": True, "C": False, "D": False}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == AlarmControlPanelState.ARMED_HOME


@pytest.mark.parametrize(
    "options", [{"group_entities": True, "group_names": "B: Balconi"}]
)
async def test_group_entities(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Group sensors follow the panel, group buttons arm their group."""
    registry = er.async_get(hass)

    def entity(domain: str, unique_id: str) -> str:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        assert entity_id
        return entity_id

    sensor = entity("binary_sensor", "test-site-uuid_0_group_B")
    sensor_a = entity("binary_sensor", "test-site-uuid_0_group_A")
    button = entity("button", "test-site-uuid_0_group_B_arm")
    # the group name is part of the entity name
    assert "Balconi" in hass.states.get(sensor).attributes["friendly_name"]
    assert hass.states.get(sensor).state == "off"
    part = panel["partition"]
    part.disarmed = False
    part.partially_armed = True
    part.groups = {"A": False, "B": True, "C": False, "D": False}
    await setup_risco_cloud.runtime_data.cloud_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    assert hass.states.get(sensor_a).state == "off"
    with patch(
        "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
    ) as group_arm:
        await hass.services.async_call(
            "button", "press", {"entity_id": button}, blocking=True
        )
    group_arm.assert_awaited_once_with(0, "B")


async def test_no_group_entities_by_default(
    hass: HomeAssistant, panel, setup_risco_cloud
) -> None:
    """Without the option nothing new is created."""
    assert not hass.states.async_entity_ids("button")
    assert not [
        e for e in hass.states.async_entity_ids("binary_sensor") if "group" in e
    ]


@pytest.mark.parametrize(
    "options",
    [
        {
            "auto_bypass_open_zones": True,
            "perimeter_zones": ["3"],
            "zone_groups": "Garage door: D",
        }
    ],
)
async def test_auto_bypass(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Open zones are bypassed, then the alarm is armed and the user notified."""
    panel["zones"][1].triggered = True  # kitchen window open
    panel["zones"][3].triggered = True  # garage door: perimeter, group D
    for zone in panel["zones"].values():
        zone.groups = None
    events = []
    hass.bus.async_listen("risco_zones_bypassed", events.append)
    with (
        patch("custom_components.risco_plus.RiscoCloud.arm", return_value=panel["alarm"]) as arm,
        patch(
            "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
        ) as group_arm,
    ):
        # full arm: the open perimeter garage door still blocks
        with pytest.raises(HomeAssistantError):
            await _call(hass, SERVICE_ALARM_ARM_AWAY)
        arm.assert_not_called()
        panel["zones"][1].bypass.assert_not_called()

        # group B: garage door (D) does not matter, kitchen window is bypassed
        await hass.services.async_call(
            DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["B"]}, blocking=True
        )
        await hass.async_block_till_done()
    panel["zones"][1].bypass.assert_awaited_once_with(True)
    panel["zones"][3].bypass.assert_not_called()
    group_arm.assert_awaited_once_with(0, "B")
    assert events[0].data["zones"] == ["Kitchen window"]


async def test_options_flow_groups(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Every mode can arm several groups; unused modes are not saved."""
    entry = setup_risco_cloud
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "code_arm_required": False,
            "code_disarm_required": False,
            "more_options": {"scan_interval": 30, "concurrency": 4},
            "extra_options": {"group_names": "B: Balconi", "group_entities": True},
        },
    )
    assert result["step_id"] == "risco_to_ha"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["step_id"] == "ha_to_risco"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"armed_away": "arm", "armed_home": "b", "armed_night": "bc"},
    )
    assert entry.options["ha_states_to_risco"] == {
        "armed_away": "arm",
        "armed_home": "B",
        "armed_night": "BC",
    }
    assert entry.options["group_names"] == "B: Balconi"
    assert entry.options["group_entities"] is True


@pytest.fixture
def local_panel():
    """Local alarm with one partition; returns the partition handler mock."""
    partition = _partition()
    partition.id = 0
    partition.name = "Casa"
    system = system_mock()
    system.name = "Centrale"
    with (
        patch(
            "custom_components.risco_plus.RiscoLocal.partitions",
            new_callable=PropertyMock(return_value={0: partition}),
        ),
        patch(
            "custom_components.risco_plus.RiscoLocal.zones",
            new_callable=PropertyMock(return_value={}),
        ),
        patch("custom_components.risco_plus.RiscoLocal.add_partition_handler") as handler,
        patch(
            "custom_components.risco_plus.RiscoLocal.system",
            new_callable=PropertyMock(return_value=system),
        ),
    ):
        yield {"partition": partition, "handler": handler}


@pytest.mark.parametrize("options", [{"group_entities": True}])
async def test_local_group_entities(
    hass: HomeAssistant, local_panel, setup_risco_local
) -> None:
    """Local connection: group sensors follow the partition updates pushed by the panel."""
    registry = er.async_get(hass)
    sensor = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "test-site-uuid_0_local_group_C"
    )
    assert hass.states.get(sensor).state == "off"
    part = local_panel["partition"]
    part.disarmed = False
    part.partially_armed = True
    part.groups = {"A": False, "B": False, "C": True, "D": False}
    callback = local_panel["handler"].call_args.args[0]
    await callback(0, part)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    with patch.object(part, "group_arm", AsyncMock()) as group_arm:
        await hass.services.async_call(
            "button",
            "press",
            {
                "entity_id": registry.async_get_entity_id(
                    "button", DOMAIN, "test-site-uuid_0_local_group_A_arm"
                )
            },
            blocking=True,
        )
    group_arm.assert_awaited_once_with("A")



def test_open_zones_mode_from_old_options() -> None:
    """Entries saved by older versions keep their behaviour."""
    assert open_zones_mode({}) == "off"
    assert open_zones_mode({"perimeter_zones": ["1"]}) == "block_selected"
    assert open_zones_mode({"auto_bypass_open_zones": True}) == "bypass"
    assert open_zones_mode({"open_zones_mode": "block", "perimeter_zones": ["1"]}) == "block"
    assert zone_ids_groups({"zones_group_b": ["1", 2], "zones_group_c": ["1"]}) == {
        "1": "BC",
        "2": "B",
    }


@pytest.mark.parametrize(
    "options",
    [
        {
            "open_zones_mode": "block",
            "zones_group_a": ["2"],
            "zones_group_c": ["1"],
        }
    ],
)
async def test_block_any_open_zone(hass: HomeAssistant, panel, setup_risco_cloud) -> None:
    """Any open zone of the groups blocks, without choosing zones; a notification says why."""
    panel["zones"][1].triggered = True  # kitchen window, group C
    for zone in panel["zones"].values():
        zone.groups = None
    events = []
    hass.bus.async_listen("risco_arming_refused", events.append)
    with (
        patch("custom_components.risco_plus.RiscoCloud.arm", return_value=panel["alarm"]) as arm,
        patch(
            "custom_components.risco_plus.RiscoCloud.group_arm", return_value=panel["alarm"]
        ) as group_arm,
    ):
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, SERVICE_ALARM_ARM_AWAY)
        assert err.value.translation_placeholders == {"zones": "Kitchen window"}
        arm.assert_not_called()
        await hass.async_block_till_done()
        assert events[-1].data["zones"] == ["Kitchen window"]
        notifications = hass.data["persistent_notification"]
        assert any("Kitchen window" in n["message"] for n in notifications.values())

        # group A: the kitchen window is in group C only, arming goes on
        await hass.services.async_call(
            DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["A"]}, blocking=True
        )
        group_arm.assert_awaited_once_with(0, "A")

        # group C: blocked
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN, "arm_groups", {"entity_id": ENTITY, "groups": ["C"]}, blocking=True
            )
        assert group_arm.await_count == 1
        panel["zones"][1].bypass.assert_not_called()
