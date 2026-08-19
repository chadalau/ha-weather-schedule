"""The phase a room is in."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import WeatherScheduleEntry
from .const import PHASES, STARTING_PHASE
from .coordinator import RoomCoordinator
from .entity import room_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherScheduleEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the phase select of a room."""
    async_add_entities([PhaseSelect(entry.runtime_data, entry)])


class PhaseSelect(SelectEntity, RestoreEntity):
    """The phase, which decides every target the room is judged against.

    It restores rather than living in the config entry, so switching phase is
    one click and does not reload the integration.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "phase"
    _attr_options = list(PHASES)
    _attr_should_poll = False

    def __init__(
        self, coordinator: RoomCoordinator, entry: WeatherScheduleEntry
    ) -> None:
        """Initialise the select."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_phase"
        self._attr_device_info = room_device(entry)
        self._attr_current_option = STARTING_PHASE

    async def async_added_to_hass(self) -> None:
        """Pick up the phase the room was left in."""
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state in PHASES:
            self._attr_current_option = previous.state
        self._coordinator.async_change_phase(self._attr_current_option)

    async def async_select_option(self, option: str) -> None:
        """Move the room to another phase."""
        self._attr_current_option = option
        self._coordinator.async_change_phase(option)
        self.async_write_ha_state()
