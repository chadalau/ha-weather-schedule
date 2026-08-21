"""Constants for Weather Schedule."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "weather_schedule"

# Keep in sync with manifest.json: it also busts the browser cache of the card.
VERSION: Final = "1.4.1"

CARD_URL_PATH: Final = "/weather_schedule_card"
CARD_FILENAME: Final = "weather-schedule-card.js"
CARD_REGISTERED: Final = "card_registered"

CONF_AIR_TEMPERATURE: Final = "air_temperature"
CONF_RELATIVE_HUMIDITY: Final = "relative_humidity"
CONF_LEAF_SENSOR: Final = "leaf_sensor"
CONF_CARBON_DIOXIDE: Final = "carbon_dioxide"
CONF_LEAF_DROP: Final = "leaf_drop"
CONF_PROFILES: Final = "profiles"
CONF_AMBIENT_CO2: Final = "ambient_co2"
CONF_LIGHTS_ON: Final = "lights_on"
CONF_LIGHT_HOURS: Final = "light_hours"
CONF_NIGHT_LEAF_DROP: Final = "night_leaf_drop"
CONF_TRIP_MINUTES: Final = "trip_minutes"
CONF_FANS: Final = "fans"
CONF_FAN_NAMES: Final = "fan_names"
CONF_FAN_POWERS: Final = "fan_powers"
CONF_FAN_CYCLES: Final = "fan_cycles"

FAN_ENTITY_ID: Final = "entity_id"
FAN_NAME: Final = "name"
FAN_POWER: Final = "power"
FAN_CYCLE: Final = "cycle"
CYCLE_ON: Final = "on"
CYCLE_OFF: Final = "off"
CYCLE_ENABLED: Final = "enabled"

# Os ventiladores so podem sair destes dominios: o seletor filtra na tela,
# mas o que chega ao fluxo de opcoes pode vir de qualquer POST.
FAN_DOMAINS: Final = ("fan", "switch")

CONF_CLEAR_MINUTES: Final = "clear_minutes"

# How much colder the leaf runs than the air when there is no infrared sensor.
DEFAULT_LEAF_DROP: Final = 2.0
# Vinte e quatro horas de luz e o mesmo que nao ter ciclo: uma sala
# que nunca escurece e julgada como sempre foi.
DEFAULT_LIGHTS_ON: Final = "06:00:00"
DEFAULT_LIGHT_HOURS: Final = 24.0
# No escuro nao ha transpiracao esfriando a folha, mas ha perda por
# radiacao: medidas de campo poem a folha 1 a 3 graus abaixo do ar.
DEFAULT_NIGHT_LEAF_DROP: Final = 1.0
LEAF_DROP_CEILING: Final = 6.0

# The alert waits this long before it believes what it sees, in either direction.
DEFAULT_TRIP_MINUTES: Final = 15
DEFAULT_CLEAR_MINUTES: Final = 5

UNIT_KPA: Final = "kPa"
UNIT_GRAMS_PER_CUBIC_METRE: Final = "g/m³"

BOUND_VPD_MIN: Final = "vpd_min"
BOUND_VPD_MAX: Final = "vpd_max"
BOUND_TEMP_MIN: Final = "temp_min"
BOUND_TEMP_MAX: Final = "temp_max"
BOUND_RH_MIN: Final = "rh_min"
BOUND_RH_MAX: Final = "rh_max"
BOUND_CO2_MIN: Final = "co2_min"
BOUND_CO2_MAX: Final = "co2_max"

BOUNDS: Final = (
    BOUND_VPD_MIN,
    BOUND_VPD_MAX,
    BOUND_TEMP_MIN,
    BOUND_TEMP_MAX,
    BOUND_RH_MIN,
    BOUND_RH_MAX,
    BOUND_CO2_MIN,
    BOUND_CO2_MAX,
)

PHASE_PROPAGATION: Final = "propagation"
PHASE_VEG_EARLY: Final = "veg_early"
PHASE_VEG_LATE: Final = "veg_late"
PHASE_FLOWER_EARLY: Final = "flower_early"
PHASE_FLOWER_LATE: Final = "flower_late"
PHASE_DRY: Final = "dry"

PHASES: Final = (
    PHASE_PROPAGATION,
    PHASE_VEG_EARLY,
    PHASE_VEG_LATE,
    PHASE_FLOWER_EARLY,
    PHASE_FLOWER_LATE,
    PHASE_DRY,
)

STARTING_PHASE: Final = PHASE_VEG_LATE

# Starting points only: each room edits its own profiles in the options flow.
# CO2 bounds assume an enriched room; see CONF_AMBIENT_CO2 for rooms without it.
DEFAULT_PROFILES: Final[dict[str, dict[str, float]]] = {
    # As janelas de VPD seguem a literatura: ~0,3-0,6 kPa no enraizamento
    # (MSU Extension), 0,8-1,1 no vegetativo e 1,0-1,5 na floração (revisão
    # citada em Frontiers in Plant Science, 2025), e a secagem na regra 60/60.
    # As janelas de umidade não são independentes: cada uma é a que produz o
    # VPD da fase na temperatura média dela, com a folha 2 °C abaixo do ar —
    # declarar as três à toa deixa a sala em desvio permanente.
    PHASE_PROPAGATION: {
        BOUND_VPD_MIN: 0.4, BOUND_VPD_MAX: 0.6,
        BOUND_TEMP_MIN: 22, BOUND_TEMP_MAX: 26,
        BOUND_RH_MIN: 68, BOUND_RH_MAX: 75,
        BOUND_CO2_MIN: 400, BOUND_CO2_MAX: 800,
    },
    PHASE_VEG_EARLY: {
        BOUND_VPD_MIN: 0.8, BOUND_VPD_MAX: 1.0,
        BOUND_TEMP_MIN: 22, BOUND_TEMP_MAX: 28,
        BOUND_RH_MIN: 57, BOUND_RH_MAX: 63,
        BOUND_CO2_MIN: 700, BOUND_CO2_MAX: 1000,
    },
    PHASE_VEG_LATE: {
        BOUND_VPD_MIN: 1.0, BOUND_VPD_MAX: 1.2,
        BOUND_TEMP_MIN: 22, BOUND_TEMP_MAX: 28,
        BOUND_RH_MIN: 51, BOUND_RH_MAX: 57,
        BOUND_CO2_MIN: 800, BOUND_CO2_MAX: 1200,
    },
    PHASE_FLOWER_EARLY: {
        BOUND_VPD_MIN: 1.0, BOUND_VPD_MAX: 1.2,
        BOUND_TEMP_MIN: 21, BOUND_TEMP_MAX: 26,
        BOUND_RH_MIN: 47, BOUND_RH_MAX: 54,
        BOUND_CO2_MIN: 1000, BOUND_CO2_MAX: 1200,
    },
    PHASE_FLOWER_LATE: {
        BOUND_VPD_MIN: 1.1, BOUND_VPD_MAX: 1.3,
        BOUND_TEMP_MIN: 20, BOUND_TEMP_MAX: 25,
        BOUND_RH_MIN: 41, BOUND_RH_MAX: 48,
        BOUND_CO2_MIN: 800, BOUND_CO2_MAX: 1000,
    },
    # Na secagem não há folha transpirando, então o VPD é o do próprio ar; é
    # por isso que 60/60 dá 0,7 kPa e não os 0,5 que o desconto de folha daria.
    PHASE_DRY: {
        BOUND_VPD_MIN: 0.6, BOUND_VPD_MAX: 0.9,
        BOUND_TEMP_MIN: 15, BOUND_TEMP_MAX: 18,
        BOUND_RH_MIN: 52, BOUND_RH_MAX: 68,
        BOUND_CO2_MIN: 400, BOUND_CO2_MAX: 800,
    },
}

STATUS_ON_TARGET: Final = "on_target"
STATUS_VPD_LOW: Final = "vpd_low"
STATUS_VPD_HIGH: Final = "vpd_high"
STATUS_TOO_COLD: Final = "too_cold"
STATUS_TOO_WARM: Final = "too_warm"
STATUS_TOO_DRY: Final = "too_dry"
STATUS_TOO_HUMID: Final = "too_humid"
STATUS_CO2_LOW: Final = "co2_low"
STATUS_CO2_HIGH: Final = "co2_high"

ROOM_STATUSES: Final = (
    STATUS_ON_TARGET,
    STATUS_VPD_LOW,
    STATUS_VPD_HIGH,
    STATUS_TOO_COLD,
    STATUS_TOO_WARM,
    STATUS_TOO_DRY,
    STATUS_TOO_HUMID,
    STATUS_CO2_LOW,
    STATUS_CO2_HIGH,
)

CO2_UNDER: Final = "under"
CO2_ON_TARGET: Final = "on_target"
CO2_OVER: Final = "over"

CO2_STATUSES: Final = (CO2_UNDER, CO2_ON_TARGET, CO2_OVER)
