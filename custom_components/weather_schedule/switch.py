"""The master control of the fan timers of a room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import WeatherScheduleEntry
from .coordinator import RoomCoordinator
from .entity import room_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherScheduleEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the timer switch of a room."""
    async_add_entities([RoomTimersSwitch(entry.runtime_data, entry)])


class RoomTimersSwitch(SwitchEntity, RestoreEntity):
    """Runs or pauses every fan cycle of the room at once.

    Pausing never touches the fans: whatever is running keeps running, and it
    is up to you to switch it by hand. A pause that also cuts the ventilation
    would be a surprise nobody wants at two in the morning.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "timers"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self, coordinator: RoomCoordinator, entry: WeatherScheduleEntry
    ) -> None:
        """Initialise the switch."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_timers"
        self._attr_device_info = room_device(entry)
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        """Pick up whether the timers were left running."""
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None:
            self._attr_is_on = previous.state == "on"
        self._coordinator.cycles.async_set_enabled(self._attr_is_on)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what each cycle is doing."""
        return {"cycles": self._coordinator.cycles.status}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the cycles."""
        self._attr_is_on = True
        self._coordinator.cycles.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause the cycles, leaving the fans as they are."""
        self._attr_is_on = False
        self._coordinator.cycles.async_set_enabled(False)
        self.async_write_ha_state()
