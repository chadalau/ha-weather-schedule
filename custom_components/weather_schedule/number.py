"""How much colder the leaf runs than the air."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WeatherScheduleEntry
from .const import LEAF_DROP_CEILING
from .coordinator import RoomCoordinator
from .entity import room_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherScheduleEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the leaf drop of a room."""
    async_add_entities([LeafDropNumber(entry.runtime_data, entry)])


class LeafDropNumber(RestoreNumber):
    """The assumed leaf-to-air temperature gap.

    Ignored while an infrared leaf sensor is configured: a measurement always
    beats an assumption.

    This entity is where the gap lives. The config entry only seeds it, once,
    at setup. Keeping it in the options as well gave the value two homes: the
    coordinator started from the option, this entity restored its own state a
    moment later, and whatever had just been saved in Configure was quietly
    overwritten by the older number.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "leaf_drop"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = LEAF_DROP_CEILING
    _attr_native_step = 0.1
    # A temperature difference, not a temperature: with a device class, a
    # Fahrenheit household would see the gap converted as if it were a reading.
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(
        self, coordinator: RoomCoordinator, entry: WeatherScheduleEntry
    ) -> None:
        """Initialise the number."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_leaf_drop"
        self._attr_device_info = room_device(entry)
        self._attr_native_value = coordinator.leaf_drop

    async def async_added_to_hass(self) -> None:
        """Pick up the value the room was left with."""
        await super().async_added_to_hass()
        previous = await self.async_get_last_number_data()
        if previous is not None and previous.native_value is not None:
            # Estado restaurado é dado antigo: pode ter vindo de outra faixa.
            self._attr_native_value = min(
                max(float(previous.native_value), self._attr_native_min_value),
                self._attr_native_max_value,
            )
        self._coordinator.async_change_leaf_drop(float(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        """Change the assumed gap."""
        self._attr_native_value = value
        self._coordinator.async_change_leaf_drop(value)
        self.async_write_ha_state()
