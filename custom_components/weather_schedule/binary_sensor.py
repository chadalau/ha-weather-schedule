"""The off-target alert of a room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WeatherScheduleEntry
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherScheduleEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the alert of a room."""
    async_add_entities([RoomAlert(entry.runtime_data, entry, "alert")])


class RoomAlert(RoomEntity, BinarySensorEntity):
    """On once the room has held off target for longer than the tolerance."""

    _attr_translation_key = "alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return whether the room is in alert."""
        return self.coordinator.data.alert

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what is off target, so a notification can say it."""
        return {
            "phase": self.coordinator.phase,
            "drifts": self.coordinator.data.drifts,
        }
