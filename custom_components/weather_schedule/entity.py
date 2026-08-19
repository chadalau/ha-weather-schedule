"""Shared entity plumbing for Weather Schedule."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import RoomCoordinator


def room_device(entry: ConfigEntry) -> DeviceInfo:
    """Return the device that every entity of a room belongs to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Weather Schedule",
        model="Room",
        sw_version=VERSION,
    )


class RoomEntity(CoordinatorEntity[RoomCoordinator]):
    """Base for the entities that read the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RoomCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = room_device(entry)
