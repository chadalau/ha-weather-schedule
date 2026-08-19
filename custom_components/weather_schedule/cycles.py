"""Cyclic timers for the fans of a room.

A cycle is the simplest thing a grow room asks of a fan: so many minutes on,
so many minutes off, around the clock. There is no clock time and no weekday
here on purpose — and no climate either. A timer that quietly decides not to
run is a timer nobody trusts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
import logging
from math import isfinite

from homeassistant.config_entries import ConfigEntry
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
from homeassistant.util.dt import utcnow

from .const import CYCLE_ENABLED, CYCLE_OFF, CYCLE_ON, FAN_CYCLE, FAN_ENTITY_ID

_LOGGER = logging.getLogger(__name__)


class FanCycles:
    """Switches the fans of one room on and off on their own rhythm."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator
    ) -> None:
        """Set up the timers of a room."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.enabled = True
        self._cancel: dict[str, CALLBACK_TYPE] = {}
        self._watching: CALLBACK_TYPE | None = None
        self._next: dict[str, datetime] = {}
        self._running: dict[str, bool] = {}

    @property
    def status(self) -> dict[str, dict]:
        """Return what each timer is doing, for the card to show."""
        return {
            entity_id: {
                CYCLE_ON: on,
                CYCLE_OFF: off,
                "running": self._running.get(entity_id, False),
                "next": self._next[entity_id].isoformat()
                if entity_id in self._next
                else None,
            }
            for entity_id, on, off in self._configured()
        }

    @callback
    def async_set_enabled(self, enabled: bool) -> None:
        """Turn the timers of the room on or off as a whole.

        Switching them off leaves every fan exactly as it is: stopping a timer
        should not be a reason for the room to lose its ventilation.
        """
        self.enabled = enabled
        self.async_restart()

    @callback
    def async_restart(self) -> None:
        """Drop every pending step and start the configured cycles again."""
        self.async_stop()
        if not self.enabled:
            self.coordinator.async_update_listeners()
            return
        cycles = self._configured()
        for entity_id, on, off in cycles:
            # Começar sempre ligando faria cada reinício do Home Assistant acender
            # a sala inteira. O ciclo ancora no que o ventilador já é e só conta
            # a partir dali.
            state = self.hass.states.get(entity_id)
            self._reschedule(entity_id, on, off, state is not None and state.state == "on")
        # Um ventilador ligado ou desligado na mão não pode deixar o ciclo
        # mentindo: quem observa reancora a fase no que a entidade realmente é.
        if cycles:
            self._watching = async_track_state_change_event(
                self.hass, [entity_id for entity_id, _on, _off in cycles], self._changed
            )
        self.coordinator.async_update_listeners()

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        """Follow the fan when someone switches it outside the cycle."""
        entity_id = event.data["entity_id"]
        state = event.data["new_state"]
        if state is None or state.state not in ("on", "off"):
            return
        running = state.state == "on"
        if running == self._running.get(entity_id):
            return
        for candidate, on, off in self._configured():
            if candidate == entity_id:
                # Reconta a partir de agora, sem tocar no ventilador: quem mandou
                # foi o usuário, o ciclo só passa a respeitar o novo ponto de partida.
                self._reschedule(entity_id, on, off, running)
                self.coordinator.async_update_listeners()
                return

    @callback
    def async_stop(self) -> None:
        """Cancel everything pending, without touching the fans."""
        if self._watching is not None:
            self._watching()
            self._watching = None
        for cancel in self._cancel.values():
            cancel()
        self._cancel.clear()
        self._next.clear()
        self._running.clear()

    @callback
    def _configured(self) -> list[tuple[str, int, int]]:
        """Return the fans that actually have a usable cycle."""
        cycles: list[tuple[str, int, int]] = []
        for fan in self.coordinator.fans:
            entity_id = str(fan.get(FAN_ENTITY_ID) or "")
            cycle = fan.get(FAN_CYCLE) or {}
            # Opções são dados persistidos: podem vir de uma versão antiga, de um
            # backup editado à mão ou de um import. Nada aqui é confiável.
            if entity_id.split(".")[0] not in ("fan", "switch"):
                continue
            if not isinstance(cycle, dict) or not cycle.get(CYCLE_ENABLED):
                continue
            try:
                on = float(cycle.get(CYCLE_ON) or 0)
                off = float(cycle.get(CYCLE_OFF) or 0)
            except (TypeError, ValueError):
                continue
            if not (isfinite(on) and isfinite(off)) or on <= 0 or off <= 0:
                continue
            cycles.append((entity_id, int(on), int(off)))
        return cycles

    @callback
    def _step(self, entity_id: str, on: int, off: int, turn_on: bool) -> None:
        """Switch the fan and book the opposite step."""
        self.hass.async_create_task(self._switch(entity_id, turn_on))
        self._reschedule(entity_id, on, off, turn_on)

    async def _switch(self, entity_id: str, turn_on: bool) -> None:
        """Switch one fan, without letting a failure kill the cycle."""
        try:
            await self.hass.services.async_call(
                entity_id.split(".")[0],
                "turn_on" if turn_on else "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - o ciclo continua, o log explica
            _LOGGER.exception("Could not switch %s", entity_id)

    @callback
    def _reschedule(self, entity_id: str, on: int, off: int, running: bool) -> None:
        """Book the opposite step, counting from now."""
        if (cancel := self._cancel.pop(entity_id, None)) is not None:
            cancel()
        when = utcnow() + timedelta(minutes=on if running else off)
        self._running[entity_id] = running
        self._next[entity_id] = when
        self._cancel[entity_id] = async_track_point_in_utc_time(
            self.hass, partial(self._turn, entity_id, on, off, not running), when
        )

    @callback
    def _turn(self, entity_id: str, on: int, off: int, turn_on: bool, _now) -> None:
        """Take the next step of the cycle."""
        self._step(entity_id, on, off, turn_on)
        self.coordinator.async_update_listeners()
