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
    CONF_PROFILES,
    CONF_RELATIVE_HUMIDITY,
    CONF_TRIP_MINUTES,
    DEFAULT_CLEAR_MINUTES,
    DEFAULT_LEAF_DROP,
    DEFAULT_PROFILES,
    DEFAULT_TRIP_MINUTES,
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


class RoomCoordinator(DataUpdateCoordinator[RoomClimate]):
    """Recalculates a room whenever one of its sensors reports.

    Nothing here is polled. The source sensors push, the coordinator listens,
    and the only timer in the class is the one that keeps the alert honest.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the coordinator for one configured room."""
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry)
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
    def sources(self) -> dict[str, str | None]:
        """Return which entity feeds each reading, for the card to show."""
        return {
            key: self.settings.get(key)
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
            if (entity_id := self.settings.get(key))
        ]
        if self.config_entry is None:
            return
        self.config_entry.async_on_unload(
            async_track_state_change_event(self.hass, watched, self._sensor_reported)
        )
        self.config_entry.async_on_unload(self._cancel_alert_timer)

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

    @callback
    def _read_room(self) -> RoomClimate:
        """Build the climate from whatever the sensors are willing to report.

        A sensor that is missing, unavailable or not a number costs only the
        readings that depend on it; the rest of the room carries on.
        """
        air = self._temperature_of(self.settings.get(CONF_AIR_TEMPERATURE))
        humidity = self._percentage_of(self.settings.get(CONF_RELATIVE_HUMIDITY))
        leaf = self._temperature_of(self.settings.get(CONF_LEAF_SENSOR))
        co2 = self._number_of(self.settings.get(CONF_CARBON_DIOXIDE))

        if leaf is None and air is not None:
            leaf = air - self.leaf_drop

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
            climate.dew_point = psychrometrics.dew_point(air, humidity)
            climate.absolute_humidity = psychrometrics.absolute_humidity(air, humidity)
            climate.condensation_margin = psychrometrics.condensation_margin(
                air, humidity
            )
            if leaf is not None:
                climate.vpd = psychrometrics.vapour_pressure_deficit(leaf, air, humidity)

        window = self.bounds
        climate.drifts = self._drifts_of(climate, window)
        climate.carbon_dioxide_status = self._carbon_dioxide_status(co2, window)
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
