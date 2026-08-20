"""The derived readings of a room."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WeatherScheduleEntry
from .const import (
    CO2_STATUSES,
    ROOM_STATUSES,
    UNIT_GRAMS_PER_CUBIC_METRE,
    UNIT_KPA,
)
from .coordinator import RoomClimate, RoomCoordinator
from .entity import RoomEntity


@dataclass(frozen=True, kw_only=True)
class RoomSensorDescription(SensorEntityDescription):
    """Describes one derived reading."""

    reading: Callable[[RoomClimate], float | str | None]
    extras: Callable[[RoomCoordinator], dict[str, Any]] | None = None
    wanted: Callable[[RoomCoordinator], bool] = lambda _: True
    # Uma leitura que existe mas não se aplica agora vale `unknown`, não
    # `unavailable`: a entidade não quebrou, é a pergunta que não cabe.
    present: Callable[[RoomCoordinator], bool] | None = None


SENSORS: tuple[RoomSensorDescription, ...] = (
    RoomSensorDescription(
        key="vpd",
        translation_key="vpd",
        # No pressure device class on purpose: it would drag kPa into the unit
        # system's pressure unit, and a VPD is only ever read in kPa.
        native_unit_of_measurement=UNIT_KPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        reading=lambda climate: climate.vpd,
    ),
    RoomSensorDescription(
        key="leaf_temperature",
        translation_key="leaf_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        reading=lambda climate: climate.leaf_temperature,
    ),
    RoomSensorDescription(
        key="dew_point",
        translation_key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        reading=lambda climate: climate.dew_point,
    ),
    RoomSensorDescription(
        key="condensation_margin",
        translation_key="condensation_margin",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        reading=lambda climate: climate.condensation_margin,
    ),
    RoomSensorDescription(
        key="absolute_humidity",
        translation_key="absolute_humidity",
        native_unit_of_measurement=UNIT_GRAMS_PER_CUBIC_METRE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        reading=lambda climate: climate.absolute_humidity,
    ),
    RoomSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(ROOM_STATUSES),
        reading=lambda climate: climate.status,
        # The card reads the entire target window from here in one shot, which
        # is why eight more entities are not needed to publish it.
        extras=lambda coordinator: {
            "phase": coordinator.phase,
            "drifts": coordinator.data.drifts,
            **coordinator.bounds,
            # Where each reading comes from, and what can be tuned: the card
            # fills its settings sheet from here instead of asking the user to
            # repeat the entity ids in YAML.
            "sources": coordinator.sources,
            "sensors": coordinator.sensors,
            "daytime": coordinator.data.daytime,
            "settings": coordinator.tunables,
            "fans": coordinator.fans,
            "cycles": coordinator.cycles.status if coordinator.cycles else {},
            "timers_enabled": bool(coordinator.cycles and coordinator.cycles.enabled),
        },
    ),
    RoomSensorDescription(
        key="carbon_dioxide_status",
        translation_key="carbon_dioxide_status",
        # A sala tem sensor de CO2: no escuro a janela é que não se aplica, e
        # a entidade fica sem valor em vez de fingir que sumiu.
        present=lambda coordinator: coordinator.tracks_carbon_dioxide,
        device_class=SensorDeviceClass.ENUM,
        options=list(CO2_STATUSES),
        reading=lambda climate: climate.carbon_dioxide_status,
        wanted=lambda coordinator: coordinator.tracks_carbon_dioxide,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherScheduleEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the derived readings of a room."""
    coordinator = entry.runtime_data
    async_add_entities(
        RoomSensor(coordinator, entry, description)
        for description in SENSORS
        if description.wanted(coordinator)
    )


class RoomSensor(RoomEntity, SensorEntity):
    """One derived reading of a room."""

    entity_description: RoomSensorDescription

    def __init__(
        self,
        coordinator: RoomCoordinator,
        entry: WeatherScheduleEntry,
        description: RoomSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        """Return the reading."""
        return self.entity_description.reading(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the target window, for the sensor that carries it."""
        if self.entity_description.extras is None:
            return None
        return self.entity_description.extras(self.coordinator)

    @property
    def available(self) -> bool:
        """Return whether this reading can be calculated at all right now."""
        if self.entity_description.present is not None:
            return super().available and self.entity_description.present(
                self.coordinator
            )
        return super().available and self.native_value is not None
