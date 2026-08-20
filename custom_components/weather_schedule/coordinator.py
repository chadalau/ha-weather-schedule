"""Reads the sensors of one room and derives its climate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from math import isfinite

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import utcnow
from homeassistant.util.unit_conversion import TemperatureConverter

from . import psychrometrics
from .const import (
    BOUND_CO2_MAX,
    BOUND_CO2_MIN,
    BOUND_RH_MAX,
    BOUND_RH_MIN,
    BOUND_TEMP_MAX,
    BOUND_TEMP_MIN,
    BOUND_VPD_MAX,
    BOUND_VPD_MIN,
    CO2_ON_TARGET,
    CO2_OVER,
    CO2_UNDER,
    CONF_AIR_TEMPERATURE,
    CONF_AMBIENT_CO2,
    CONF_CARBON_DIOXIDE,
    CONF_CLEAR_MINUTES,
    CONF_FANS,
    CONF_LEAF_DROP,
    CONF_LEAF_SENSOR,
    CONF_LIGHT_HOURS,
    CONF_LIGHTS_ON,
    CONF_NIGHT_LEAF_DROP,
    CONF_PROFILES,
    CONF_RELATIVE_HUMIDITY,
    CONF_TRIP_MINUTES,
    DEFAULT_CLEAR_MINUTES,
    DEFAULT_LEAF_DROP,
    DEFAULT_LIGHT_HOURS,
    DEFAULT_LIGHTS_ON,
    DEFAULT_NIGHT_LEAF_DROP,
    DEFAULT_PROFILES,
    DEFAULT_TRIP_MINUTES,
    PHASE_DRY,
    STARTING_PHASE,
    STATUS_CO2_HIGH,
    STATUS_CO2_LOW,
    STATUS_ON_TARGET,
    STATUS_TOO_COLD,
    STATUS_TOO_DRY,
    STATUS_TOO_HUMID,
    STATUS_TOO_WARM,
    STATUS_VPD_HIGH,
    STATUS_VPD_LOW,
)

_LOGGER = logging.getLogger(__name__)


def _mean(values: list[float]) -> float | None:
    """Return the average of what was actually read, or None if nothing was."""
    return sum(values) / len(values) if values else None


@dataclass(slots=True)
class RoomClimate:
    """The climate of one room at one moment."""

    air_temperature: float | None = None
    relative_humidity: float | None = None
    leaf_temperature: float | None = None
    carbon_dioxide: float | None = None
    vpd: float | None = None
    dew_point: float | None = None
    absolute_humidity: float | None = None
    condensation_margin: float | None = None
    status: str | None = None
    carbon_dioxide_status: str | None = None
    drifts: list[str] = field(default_factory=list)
    alert: bool = False
    # Falso quando falta alguma leitura obrigatória: sem isso, uma sala cega
    # passaria por sala saudável.
    readable: bool = True
    daytime: bool = True


class RoomCoordinator(DataUpdateCoordinator[RoomClimate]):
    """Recalculates a room whenever one of its sensors reports.

    Nothing here is polled. The source sensors push, the coordinator listens,
    and the only timer in the class is the one that keeps the alert honest.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the coordinator for one configured room."""
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry)
        self._cancel_light_flip: CALLBACK_TYPE | None = None
        self._light_flip_at: datetime | None = None
        self.settings = {**entry.data, **entry.options}
        self.phase = STARTING_PHASE
        self.leaf_drop = float(self.settings.get(CONF_LEAF_DROP, DEFAULT_LEAF_DROP))
        self.cycles = None
        self._alert = False
        self._drifting_since: datetime | None = None
        self._settled_since: datetime | None = None
        self._cancel_timer: CALLBACK_TYPE | None = None
        self._warned: set[str] = set()

    @property
    def tracks_carbon_dioxide(self) -> bool:
        """Return whether a CO2 sensor was configured for this room."""
        return bool(self.settings.get(CONF_CARBON_DIOXIDE))

    @property
    def is_daytime(self) -> bool:
        """Return whether the room's lights are on right now.

        The cycle is a schedule, not an entity: it describes what the grow
        intends, which is what the plant lives by. A relay can be flipped by
        hand at three in the morning without the night having ended.
        """
        hours = float(self.settings.get(CONF_LIGHT_HOURS, DEFAULT_LIGHT_HOURS))
        if hours >= 24:
            return True
        if hours <= 0:
            return False
        start = dt_util.parse_time(
            str(self.settings.get(CONF_LIGHTS_ON, DEFAULT_LIGHTS_ON))
        ) or dt_util.parse_time(DEFAULT_LIGHTS_ON)
        now = dt_util.now()
        # Minutos desde que a luz acendeu, dando a volta na meia-noite.
        since = (
            (now.hour * 60 + now.minute + now.second / 60)
            - (start.hour * 60 + start.minute)
        ) % (24 * 60)
        return since < hours * 60

    @property
    def effective_leaf_drop(self) -> float:
        """Return how far below the air the leaf sits, right now.

        Under the lamps it is transpiration doing the cooling; in the dark it
        is radiation, and the gap shrinks but does not close. Drying has no
        leaf to cool at all.
        """
        if self.phase == PHASE_DRY:
            return 0.0
        if self.is_daytime:
            return self.leaf_drop
        return float(
            self.settings.get(CONF_NIGHT_LEAF_DROP, DEFAULT_NIGHT_LEAF_DROP)
        )

    def _next_light_change(self) -> datetime | None:
        """Return when the lights next flip, so the room notices on its own."""
        hours = float(self.settings.get(CONF_LIGHT_HOURS, DEFAULT_LIGHT_HOURS))
        if hours >= 24 or hours <= 0:
            return None
        start = dt_util.parse_time(
            str(self.settings.get(CONF_LIGHTS_ON, DEFAULT_LIGHTS_ON))
        ) or dt_util.parse_time(DEFAULT_LIGHTS_ON)
        now = dt_util.now()
        dawn = now.replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
        marks = [
            dawn + timedelta(days=day) + timedelta(hours=hours * step)
            for day in (-1, 0, 1)
            for step in (0, 1)
        ]
        upcoming = sorted(mark for mark in marks if mark > now)
        return dt_util.as_utc(upcoming[0]) if upcoming else None

    @callback
    def _cancel_light_timer(self) -> None:
        """Drop the pending lights-flip wake-up, if there is one."""
        if self._cancel_light_flip is not None:
            self._cancel_light_flip()
            self._cancel_light_flip = None
        self._light_flip_at = None

    @callback
    def _watch_light_cycle(self) -> None:
        """Refresh the room when the lights are due to flip."""
        when = self._next_light_change()
        if when is None or when == self._light_flip_at:
            return
        if self._cancel_light_flip is not None:
            self._cancel_light_flip()
        self._light_flip_at = when

        @callback
        def flipped(_now: datetime) -> None:
            self._cancel_light_flip = None
            self._light_flip_at = None
            self.async_set_updated_data(self._read_room())

        self._cancel_light_flip = async_track_point_in_utc_time(
            self.hass, flipped, when
        )

    def _entities(self, key: str) -> list[str]:
        """Return every entity configured for a reading.

        Temperature and humidity accept more than one sensor, and a room set up
        before that still has a single entity id saved; both shapes read the
        same from here.
        """
        value = self.settings.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        return [entity for entity in value if entity]

    @property
    def sources(self) -> dict[str, str | None]:
        """Return the first entity of each reading, for the card to show."""
        return {
            key: (self._entities(key) or [None])[0]
            for key in (
                CONF_AIR_TEMPERATURE,
                CONF_RELATIVE_HUMIDITY,
                CONF_CARBON_DIOXIDE,
                CONF_LEAF_SENSOR,
            )
        }

    @property
    def sensors(self) -> dict[str, list[str]]:
        """Return every entity of each reading, in the order they were picked."""
        return {
            key: self._entities(key)
            for key in (
                CONF_AIR_TEMPERATURE,
                CONF_RELATIVE_HUMIDITY,
                CONF_CARBON_DIOXIDE,
                CONF_LEAF_SENSOR,
            )
        }

    @property
    def fans(self) -> list[dict[str, str]]:
        """Return the fans this room shows on its card.

        The integration never switches them; it only remembers which ones
        belong to the room, so the card does not need them in YAML.
        """
        return list(self.settings.get(CONF_FANS, []))

    @property
    def tunables(self) -> dict[str, float | bool]:
        """Return the settings a user may want to change without a reload."""
        return {
            CONF_LEAF_DROP: self.leaf_drop,
            CONF_LIGHTS_ON: str(self.settings.get(CONF_LIGHTS_ON, DEFAULT_LIGHTS_ON)),
            CONF_LIGHT_HOURS: float(
                self.settings.get(CONF_LIGHT_HOURS, DEFAULT_LIGHT_HOURS)
            ),
            CONF_NIGHT_LEAF_DROP: float(
                self.settings.get(CONF_NIGHT_LEAF_DROP, DEFAULT_NIGHT_LEAF_DROP)
            ),
            CONF_TRIP_MINUTES: float(
                self.settings.get(CONF_TRIP_MINUTES, DEFAULT_TRIP_MINUTES)
            ),
            CONF_CLEAR_MINUTES: float(
                self.settings.get(CONF_CLEAR_MINUTES, DEFAULT_CLEAR_MINUTES)
            ),
            CONF_AMBIENT_CO2: bool(self.settings.get(CONF_AMBIENT_CO2, False)),
        }

    @property
    def bounds(self) -> dict[str, float]:
        """Return the target window of the phase the room is in."""
        window = dict(DEFAULT_PROFILES[self.phase])
        window.update(self.settings.get(CONF_PROFILES, {}).get(self.phase, {}))
        return window

    @callback
    def async_start_listening(self) -> None:
        """Follow every sensor this room was configured with."""
        watched = [
            entity_id
            for key in (
                CONF_AIR_TEMPERATURE,
                CONF_RELATIVE_HUMIDITY,
                CONF_LEAF_SENSOR,
                CONF_CARBON_DIOXIDE,
            )
            for entity_id in self._entities(key)
        ]
        if self.config_entry is None:
            return
        self.config_entry.async_on_unload(
            async_track_state_change_event(self.hass, watched, self._sensor_reported)
        )
        self.config_entry.async_on_unload(self._cancel_alert_timer)
        self.config_entry.async_on_unload(self._cancel_light_timer)

    @callback
    def async_change_phase(self, phase: str) -> None:
        """Move the room to another phase, which swaps the whole target window."""
        self.phase = phase
        self.async_set_updated_data(self._read_room())

    @callback
    def async_change_leaf_drop(self, drop: float) -> None:
        """Change how far under air temperature the leaf is assumed to sit."""
        self.leaf_drop = drop
        self.async_set_updated_data(self._read_room())

    @callback
    def _sensor_reported(self, event: Event[EventStateChangedData]) -> None:
        """Recalculate after one of the sensors changed."""
        self.async_set_updated_data(self._read_room())

    async def _async_update_data(self) -> RoomClimate:
        """Return the current climate of the room."""
        return self._read_room()

    def _readings(self, key: str, read) -> list[float]:
        """Return every reading a role could produce, skipping what is silent."""
        values = [read(entity_id) for entity_id in self._entities(key)]
        return [value for value in values if value is not None]

    @callback
    def _read_room(self) -> RoomClimate:
        """Build the climate from whatever the sensors are willing to report.

        A sensor that is missing, unavailable or not a number costs only the
        readings that depend on it; the rest of the room carries on.
        """
        airs = self._readings(CONF_AIR_TEMPERATURE, self._temperature_of)
        humidities = self._readings(CONF_RELATIVE_HUMIDITY, self._percentage_of)
        leaves = self._readings(CONF_LEAF_SENSOR, self._temperature_of)
        co2s = self._readings(CONF_CARBON_DIOXIDE, self._number_of)

        air = _mean(airs)
        humidity = _mean(humidities)
        leaf = _mean(leaves)
        co2 = _mean(co2s)

        self._watch_light_cycle()
        if leaf is None and air is not None:
            # Material colhido não transpira, logo não fica abaixo do ar: na
            # secagem o VPD é o do próprio ar, e é assim que 60/60 dá 0,7 kPa.
            leaf = air - self.effective_leaf_drop

        climate = RoomClimate(
            air_temperature=air,
            relative_humidity=humidity,
            leaf_temperature=leaf,
            carbon_dioxide=co2,
        )

        # Uma sala sem temperatura ou sem umidade não pode ser julgada. Calar o
        # alerta aqui seria dizer que está tudo bem justamente quando não se sabe.
        if air is None or humidity is None:
            climate.readable = False
            self._cancel_alert_timer()
            climate.alert = self._alert
            return climate

        if air is not None and humidity is not None:
            # A psicrometria é exponencial na temperatura, então a média das
            # contas não é a conta das médias. Com dois sensores a diferença
            # chega a 7% num ambiente mal misturado: conta-se ponto a ponto e
            # a média vem depois.
            pairs = (
                list(zip(airs, humidities))
                if len(airs) == len(humidities) and len(airs) > 1
                else [(air, humidity)]
            )
            drop = self.effective_leaf_drop
            climate.dew_point = _mean(
                [psychrometrics.dew_point(t, rh) for t, rh in pairs]
            )
            climate.absolute_humidity = _mean(
                [psychrometrics.absolute_humidity(t, rh) for t, rh in pairs]
            )
            climate.condensation_margin = _mean(
                [psychrometrics.condensation_margin(t, rh) for t, rh in pairs]
            )
            if leaves:
                # Um termômetro de folha mede a folha inteira da sala: ele vale
                # para todos os pontos, e não há par a montar.
                climate.vpd = _mean(
                    [
                        psychrometrics.vapour_pressure_deficit(leaf, t, rh)
                        for t, rh in pairs
                    ]
                )
            else:
                climate.vpd = _mean(
                    [
                        psychrometrics.vapour_pressure_deficit(t - drop, t, rh)
                        for t, rh in pairs
                    ]
                )

        window = self.bounds
        climate.daytime = self.is_daytime
        climate.drifts = self._drifts_of(climate, window)
        # Sem luz não há fotossíntese, então não há alvo de CO2 a cobrar: a
        # janela é de dia, e cobrá-la de madrugada é alarme sobre nada.
        climate.carbon_dioxide_status = (
            self._carbon_dioxide_status(co2, window) if climate.daytime else None
        )
        # O CO2 faz parte da janela da fase, então também faz parte do desvio:
        # um alerta que ignora metade do que promete julgar não serve.
        if climate.carbon_dioxide_status == CO2_UNDER:
            climate.drifts.append(STATUS_CO2_LOW)
        elif climate.carbon_dioxide_status == CO2_OVER:
            climate.drifts.append(STATUS_CO2_HIGH)
        climate.status = climate.drifts[0] if climate.drifts else STATUS_ON_TARGET

        self._watch_alert(bool(climate.drifts))
        climate.alert = self._alert
        return climate

    @callback
    def _drifts_of(self, climate: RoomClimate, window: dict[str, float]) -> list[str]:
        """Return every way the room is off target, most telling first.

        VPD leads because it is what the room is steered by; temperature and
        humidity follow as the explanation for it.
        """
        checks = (
            (
                climate.vpd,
                BOUND_VPD_MIN,
                BOUND_VPD_MAX,
                STATUS_VPD_LOW,
                STATUS_VPD_HIGH,
            ),
            (
                climate.air_temperature,
                BOUND_TEMP_MIN,
                BOUND_TEMP_MAX,
                STATUS_TOO_COLD,
                STATUS_TOO_WARM,
            ),
            (
                climate.relative_humidity,
                BOUND_RH_MIN,
                BOUND_RH_MAX,
                STATUS_TOO_DRY,
                STATUS_TOO_HUMID,
            ),
        )
        drifts: list[str] = []
        for value, low_key, high_key, under, over in checks:
            if value is None:
                continue
            if value < window[low_key]:
                drifts.append(under)
            elif value > window[high_key]:
                drifts.append(over)
        return drifts

    @callback
    def _carbon_dioxide_status(
        self, co2: float | None, window: dict[str, float]
    ) -> str | None:
        """Return the CO2 status, or None when the room has no CO2 sensor.

        A room that is not enriched sits at ambient CO2 by design, so calling
        that under target would be a false alarm that never clears.
        """
        if co2 is None:
            return None
        if co2 > window[BOUND_CO2_MAX]:
            return CO2_OVER
        if co2 < window[BOUND_CO2_MIN]:
            return CO2_ON_TARGET if self.settings.get(CONF_AMBIENT_CO2) else CO2_UNDER
        return CO2_ON_TARGET

    @callback
    def _watch_alert(self, drifting: bool) -> None:
        """Remember how long the room has been like this, and set a check."""
        now = utcnow()
        if drifting:
            self._settled_since = None
            self._drifting_since = self._drifting_since or now
            if not self._alert:
                self._schedule_check(
                    self._drifting_since, CONF_TRIP_MINUTES, DEFAULT_TRIP_MINUTES
                )
        else:
            self._drifting_since = None
            self._settled_since = self._settled_since or now
            if self._alert:
                self._schedule_check(
                    self._settled_since, CONF_CLEAR_MINUTES, DEFAULT_CLEAR_MINUTES
                )

    @callback
    def _schedule_check(self, since: datetime, key: str, fallback: int) -> None:
        """Arrange to look again once the tolerance has elapsed."""
        self._cancel_alert_timer()
        minutes = float(self.settings.get(key, fallback))
        self._cancel_timer = async_track_point_in_utc_time(
            self.hass, self._tolerance_elapsed, since + timedelta(minutes=minutes)
        )

    @callback
    def _tolerance_elapsed(self, _now: datetime) -> None:
        """Flip the alert if the room really did hold this way."""
        self._cancel_timer = None
        self._alert = self._drifting_since is not None
        self.async_set_updated_data(self._read_room())

    @callback
    def _cancel_alert_timer(self) -> None:
        """Drop a pending alert check."""
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    @callback
    def _number_of(self, entity_id: str | None) -> float | None:
        """Return the numeric state of an entity, or None when unusable."""
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        return self._value_of(state)

    @callback
    def _value_of(self, state) -> float | None:
        """Return a finite number out of a state, or None."""
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        # NaN e infinito atravessam comparações sem disparar nada: um valor
        # desses passaria por "dentro da faixa" em todos os testes.
        return value if isfinite(value) else None

    @callback
    def _temperature_of(self, entity_id: str | None) -> float | None:
        """Return a temperature in Celsius, whatever unit the sensor reports in."""
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        value = self._value_of(state)
        if value is None:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.KELVIN):
            return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        if unit != UnitOfTemperature.CELSIUS and entity_id not in self._warned:
            # Unidade estranha é assumida como Celsius, mas em silêncio isso vira
            # um erro de cálculo que ninguém encontra.
            self._warned.add(entity_id)
            _LOGGER.warning(
                "%s reports temperature in %r; assuming Celsius", entity_id, unit
            )
        return value

    @callback
    def _percentage_of(self, entity_id: str | None) -> float | None:
        """Return a humidity reading, rejecting what cannot be a percentage."""
        value = self._number_of(entity_id)
        if value is None or not 0 <= value <= 100:
            return None
        return value
