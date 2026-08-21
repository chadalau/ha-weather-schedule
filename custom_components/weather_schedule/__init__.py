"""Weather Schedule: room climate as entities, plus the card that drives it."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CARD_FILENAME, CARD_REGISTERED, CARD_URL_PATH, DOMAIN, VERSION
from .coordinator import RoomCoordinator
from .cycles import FanCycles

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type WeatherScheduleEntry = ConfigEntry[RoomCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: WeatherScheduleEntry) -> bool:
    """Set up one room."""
    await _async_serve_card(hass)

    coordinator = RoomCoordinator(hass, entry)
    coordinator.async_start_listening()
    await coordinator.async_config_entry_first_refresh()
    coordinator.cycles = FanCycles(hass, entry, coordinator)
    # `async_shutdown`, não `async_stop`: o unload precisa esperar os comandos
    # em voo, senão um `turn_on` parado dentro de uma integração lenta ainda
    # aciona o ventilador de uma sala que já não existe mais.
    entry.async_on_unload(coordinator.cycles.async_shutdown)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WeatherScheduleEntry) -> bool:
    """Unload one room."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: WeatherScheduleEntry) -> None:
    """Reload the room after its options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_serve_card(hass: HomeAssistant) -> None:
    """Publish the card and load it in the frontend.

    Doing it here is what saves the user from copying files into www and
    registering a Lovelace resource by hand. It runs once per Home Assistant
    start, no matter how many rooms are configured.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(CARD_REGISTERED):
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL_PATH,
                str(Path(__file__).parent / "www"),
                cache_headers=False,
            )
        ]
    )
    add_extra_js_url(hass, f"{CARD_URL_PATH}/{CARD_FILENAME}?v={VERSION}")
    # Marcado no fim, não no começo: erguer a flag antes de servir o arquivo
    # fazia uma falha aqui convencer a próxima sala de que já estava tudo
    # publicado, e o card nunca chegava ao frontend.
    domain_data[CARD_REGISTERED] = True
