"""Cyclic timers for the fans of a room.

A cycle is the simplest thing a grow room asks of a fan: so many minutes on,
so many minutes off, around the clock. There is no clock time and no weekday
here on purpose — and no climate either. A timer that quietly decides not to
run is a timer nobody trusts.
"""

from __future__ import annotations

import asyncio
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

from .const import (
    CYCLE_ENABLED,
    CYCLE_OFF,
    CYCLE_ON,
    FAN_CYCLE,
    FAN_DOMAINS,
    FAN_ENTITY_ID,
)

_LOGGER = logging.getLogger(__name__)

# Um ventilador que nao responde nisto nao vai responder: o passo desiste e o
# ciclo continua, em vez de ficar um comando pendurado para sempre.
SWITCH_TIMEOUT = 30


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
        # O estado que um comando em voo esta tentando alcancar, para o
        # observador nao confundir a confirmacao dele com alguem mexendo
        # no ventilador na mao.
        self._pending: dict[str, bool] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        # Sobe a cada parada: comandos de geracoes velhas nao reagendam nada.
        self._generation = 0

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
        # A confirmacao do proprio comando nao e alguem mexendo no ventilador.
        if running == self._pending.get(entity_id):
            return
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
        """Cancel everything pending, without touching the fans.

        The generation is what makes this stick. A command already in flight
        cannot be unsent, but it can be stopped from booking the next step of
        a cycle that no longer exists — which is how a paused room used to get
        switched by the run before the pause.
        """
        self._generation += 1
        if self._watching is not None:
            self._watching()
            self._watching = None
        for cancel in self._cancel.values():
            cancel()
        self._cancel.clear()
        self._next.clear()
        self._running.clear()
        self._pending.clear()
        for task in self._tasks.values():
            task.cancel()

    async def async_shutdown(self) -> None:
        """Stop, and wait for the commands in flight to actually let go.

        Unload runs through here: returning while a `turn_on` is still parked
        inside a slow integration would let it land on a room that no longer
        has a coordinator behind it.
        """
        self.async_stop()
        pending = [task for task in self._tasks.values() if not task.done()]
        self._tasks.clear()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    @callback
    def _configured(self) -> list[tuple[str, int, int]]:
        """Return the fans that actually have a usable cycle."""
        cycles: list[tuple[str, int, int]] = []
        for fan in self.coordinator.fans:
            entity_id = str(fan.get(FAN_ENTITY_ID) or "")
            cycle = fan.get(FAN_CYCLE) or {}
            # Opções são dados persistidos: podem vir de uma versão antiga, de um
            # backup editado à mão ou de um import. Nada aqui é confiável.
            if entity_id.split(".")[0] not in FAN_DOMAINS:
                continue
            if not isinstance(cycle, dict) or not cycle.get(CYCLE_ENABLED):
                continue
            try:
                on = float(cycle.get(CYCLE_ON) or 0)
                off = float(cycle.get(CYCLE_OFF) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if not (isfinite(on) and isfinite(off)):
                continue
            # Truncar depois de validar deixava meio minuto virar zero, e um
            # passo de zero minuto reagenda no mesmo instante: o ciclo entra em
            # laço apertado chamando o serviço. Trunca primeiro, julga depois.
            on, off = int(on), int(off)
            if on <= 0 or off <= 0:
                continue
            cycles.append((entity_id, on, off))
        return cycles

    @callback
    def _step(self, entity_id: str, on: int, off: int, turn_on: bool) -> None:
        """Switch the fan, and book the next step on what actually happened."""
        self._track(entity_id, self._run_step(entity_id, on, off, turn_on))

    @callback
    def _track(self, entity_id: str, work) -> None:
        """Own the command, so a stop can find it and wait for it.

        Tied to the config entry rather than to Home Assistant at large: a
        command belongs to the room that ordered it, and dies with it.
        """
        if (previous := self._tasks.pop(entity_id, None)) is not None:
            previous.cancel()
        if self.entry is not None:
            task = self.entry.async_create_task(self.hass, work)
        else:
            task = self.hass.async_create_task(work)
        self._tasks[entity_id] = task

        def done(finished) -> None:
            if self._tasks.get(entity_id) is finished:
                del self._tasks[entity_id]

        task.add_done_callback(done)

    async def _run_step(self, entity_id: str, on: int, off: int, turn_on: bool) -> None:
        """Switch one fan and re-anchor its cycle on the fan it left behind."""
        generation = self._generation
        self._pending[entity_id] = turn_on
        try:
            await self._switch(entity_id, turn_on)
        finally:
            self._pending.pop(entity_id, None)
        # Parado, recarregado ou reconfigurado enquanto o comando estava em
        # voo: quem manda agora é a outra instância, não esta.
        if generation != self._generation:
            return
        # A fase segue o ventilador, não a intenção. Quando o serviço falha, o
        # motor continua onde estava, e dizer o contrário faria o ciclo contar
        # uma janela de ventilação que nunca aconteceu.
        state = self.hass.states.get(entity_id)
        if state is not None and state.state in ("on", "off"):
            running = state.state == "on"
        else:
            running = self._running.get(entity_id, turn_on)
        self._reschedule(entity_id, on, off, running)
        self.coordinator.async_update_listeners()

    async def _switch(self, entity_id: str, turn_on: bool) -> None:
        """Switch one fan, without letting a failure kill the cycle.

        `blocking=True` waits for the device to answer, and a device that
        never answers would park this command forever — so it is bounded.
        """
        try:
            async with asyncio.timeout(SWITCH_TIMEOUT):
                await self.hass.services.async_call(
                    entity_id.split(".")[0],
                    "turn_on" if turn_on else "turn_off",
                    {"entity_id": entity_id},
                    blocking=True,
                )
        except TimeoutError:
            _LOGGER.warning(
                "Switching %s took longer than %s s; giving up on this step",
                entity_id,
                SWITCH_TIMEOUT,
            )
        except Exception:
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
