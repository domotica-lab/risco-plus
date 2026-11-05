"""Constants for the Risco integration."""

from __future__ import annotations

from itertools import combinations

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.const import CONF_SCAN_INTERVAL

DOMAIN = "risco_plus"
# the standard Home Assistant integration Risco Plus can take over
CORE_DOMAIN = "risco"
CONF_MIGRATED_FROM = "migrated_from"

RISCO_EVENT = "risco_event"

DATA_COORDINATOR = "risco_plus"
EVENTS_COORDINATOR = "risco_events"

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CONCURRENCY = 4

TYPE_LOCAL = "local"

MAX_COMMUNICATION_DELAY = 3

SYSTEM_UPDATE_SIGNAL = "risco_plus_system_update"
CONF_CODE_ARM_REQUIRED = "code_arm_required"
CONF_CODE_DISARM_REQUIRED = "code_disarm_required"
CONF_RISCO_STATES_TO_HA = "risco_states_to_ha"
CONF_HA_STATES_TO_RISCO = "ha_states_to_risco"
CONF_COMMUNICATION_DELAY = "communication_delay"
CONF_CONCURRENCY = "concurrency"
CONF_MORE_OPTIONS = "more_options"

RISCO_GROUPS = ["A", "B", "C", "D"]
RISCO_ARM = "arm"
RISCO_PARTIAL_ARM = "partial_arm"
RISCO_STATES = [RISCO_ARM, RISCO_PARTIAL_ARM, *RISCO_GROUPS]

DEFAULT_RISCO_GROUPS_TO_HA = dict.fromkeys(
    RISCO_GROUPS, AlarmControlPanelState.ARMED_HOME
)
DEFAULT_RISCO_STATES_TO_HA = {
    RISCO_ARM: AlarmControlPanelState.ARMED_AWAY,
    RISCO_PARTIAL_ARM: AlarmControlPanelState.ARMED_HOME,
    **DEFAULT_RISCO_GROUPS_TO_HA,
}

DEFAULT_HA_STATES_TO_RISCO = {
    AlarmControlPanelState.ARMED_AWAY: RISCO_ARM,
    AlarmControlPanelState.ARMED_HOME: RISCO_PARTIAL_ARM,
}

DEFAULT_OPTIONS = {
    CONF_CODE_ARM_REQUIRED: False,
    CONF_CODE_DISARM_REQUIRED: False,
    CONF_RISCO_STATES_TO_HA: DEFAULT_RISCO_STATES_TO_HA,
    CONF_HA_STATES_TO_RISCO: DEFAULT_HA_STATES_TO_RISCO,
}

DEFAULT_ADVANCED_OPTIONS = {
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    CONF_CONCURRENCY: DEFAULT_CONCURRENCY,
}

SERVICE_SET_TIME = "set_time"

# ---------------------------------------------------------------------------
# Risco Plus: funzioni aggiuntive (tutte opzionali, dalle Opzioni)
# ---------------------------------------------------------------------------
CONF_EXTRA_OPTIONS = "extra_options"
# Codice per inserire/disinserire da Home Assistant. Vuoto = PIN dell'integrazione.
CONF_CUSTOM_CODE = "custom_code"
# Zone (porte/finestre) che, se aperte, impediscono l'inserimento.
CONF_PERIMETER_ZONES = "perimeter_zones"
# Gruppi delle zone, una riga per zona: "Nome zona: BC" (serve solo se la
# centrale non comunica i gruppi delle zone, come avviene di solito via cloud).
CONF_ZONE_GROUPS = "zone_groups"
# Legge stato ed eventi dalla copia del cloud invece di interrogare la centrale.
CONF_CLOUD_CACHE = "read_from_cloud_cache"

# Nomi dei gruppi, una riga per gruppo: "B: Balconi".
CONF_GROUP_NAMES = "group_names"
# Crea per ogni gruppo un sensore "inserito" e un pulsante "inserisci".
CONF_GROUP_ENTITIES = "group_entities"
# Vecchia opzione (sostituita da CONF_OPEN_ZONES_MODE = "bypass"), letta ancora.
CONF_AUTO_BYPASS = "auto_bypass_open_zones"
# Cosa fare con le zone aperte quando si inserisce da Home Assistant
CONF_OPEN_ZONES_MODE = "open_zones_mode"
OPEN_ZONES_OFF = "off"  # non controllare (come l'integrazione di serie)
OPEN_ZONES_BLOCK = "block"  # non inserire se e' aperta una zona dei gruppi
OPEN_ZONES_BLOCK_SELECTED = "block_selected"  # solo le zone scelte
OPEN_ZONES_BYPASS = "bypass"  # escludi le zone aperte (le scelte bloccano)
OPEN_ZONES_MODES = [
    OPEN_ZONES_OFF,
    OPEN_ZONES_BLOCK,
    OPEN_ZONES_BLOCK_SELECTED,
    OPEN_ZONES_BYPASS,
]
# Zone di ogni gruppo scelte da elenco (quando la centrale non le comunica)
CONF_ZONE_GROUPS_SECTION = "zone_groups_section"
CONF_GROUP_ZONES = {group: f"zones_group_{group.lower()}" for group in ("A", "B", "C", "D")}

DEFAULT_EXTRA_OPTIONS = {
    CONF_CUSTOM_CODE: "",
    CONF_GROUP_NAMES: "",
    CONF_GROUP_ENTITIES: False,
    CONF_PERIMETER_ZONES: [],
    CONF_ZONE_GROUPS: "",
    CONF_AUTO_BYPASS: False,
    CONF_CLOUD_CACHE: False,
    **{key: [] for key in CONF_GROUP_ZONES.values()},
}


def open_zones_mode(options: dict) -> str:
    """Open zones mode, also for entries saved by older versions."""
    if (mode := options.get(CONF_OPEN_ZONES_MODE)) in OPEN_ZONES_MODES:
        return mode
    if options.get(CONF_AUTO_BYPASS):
        return OPEN_ZONES_BYPASS
    if options.get(CONF_PERIMETER_ZONES):
        return OPEN_ZONES_BLOCK_SELECTED
    return OPEN_ZONES_OFF


def zone_ids_groups(options: dict) -> dict[str, str]:
    """{zone id: "BC"} from the per-group zone lists."""
    result: dict[str, str] = {}
    for group, key in CONF_GROUP_ZONES.items():
        for zone_id in options.get(key) or []:
            result[str(zone_id)] = result.get(str(zone_id), "") + group
    return result

# Modalita' di Home Assistant non usata (scelta "Non usato" nelle opzioni)
RISCO_NOT_USED = "none"
# Tutte le combinazioni di 2 o piu' gruppi: "AB", "AC", ... "ABCD"
RISCO_GROUP_COMBOS = [
    "".join(combo)
    for size in range(2, len(RISCO_GROUPS) + 1)
    for combo in combinations(RISCO_GROUPS, size)
]

SERVICE_ARM_GROUPS = "arm_groups"
ATTR_GROUPS = "groups"
ATTR_ARMED_GROUPS = "armed_groups"
ATTR_GROUP_NAMES = "group_names"
EVENT_ZONES_BYPASSED = "risco_zones_bypassed"
EVENT_ARMING_REFUSED = "risco_arming_refused"

# Pausa tra un gruppo e l'altro quando se ne inseriscono piu' di uno (secondi)
GROUP_ARM_PAUSE = 2
# Risposta del cloud "centrale occupata": nuovi tentativi
CLOUD_BUSY_RESULT = 52
COMMAND_RETRIES = 3
COMMAND_RETRY_DELAY = 4
# Intervallo di lettura degli eventi dal cloud (secondi)
EVENTS_INTERVAL = 60
EVENTS_INTERVAL_CLOUD_CACHE = 120
