"""Fixtures leves para testar a integração sem subir um Home Assistant inteiro.

O objetivo aqui é cobrir decisão, validação e temporização — as partes que as
revisões apontaram como frágeis — sem depender do harness completo do HA, que
exigiria fixar uma versão do core a cada release.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

# A integração só é importada dentro das fixtures: importá-la aqui puxaria o
# Home Assistant inteiro na coleta, e os testes de psicrometria não precisam
# dele.


@dataclass
class FakeState:
    """O suficiente de um estado do HA para as leituras do coordinator."""

    state: str
    attributes: dict[str, Any] = field(default_factory=dict)


class FakeStates:
    """Um repositório de estados que responde como `hass.states`."""

    def __init__(self, states: dict[str, FakeState] | None = None) -> None:
        self._states = dict(states or {})

    def get(self, entity_id: str | None) -> FakeState | None:
        return self._states.get(entity_id)

    def set(self, entity_id: str, state: str, **attributes: Any) -> None:
        self._states[entity_id] = FakeState(state, attributes)

    def drop(self, entity_id: str) -> None:
        self._states.pop(entity_id, None)


class FakeServices:
    """Um registro de serviços que anota, falha ou trava, conforme o teste.

    Sem isto a suíte não conseguia ver nada do que a integração *faz*: o fake
    antigo fechava a corrotina sem executá-la, então uma chamada de serviço
    perdida, uma que falha ou uma que nunca volta eram todas indistinguíveis
    de sucesso.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail = False
        # Quando presente, a chamada fica parada até o teste soltar o evento.
        self.block: asyncio.Event | None = None

    async def async_call(
        self, domain: str, service: str, data: dict, blocking: bool = False
    ) -> None:
        if self.block is not None:
            await self.block.wait()
        if self.fail:
            raise RuntimeError(f"{domain}.{service} recusou")
        self.calls.append((domain, service, data["entity_id"]))


class FakeEntry:
    """O pedaço do config entry que os ciclos usam: criar tarefa própria."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def async_create_task(self, hass, target, *args, **kwargs) -> asyncio.Task:
        task = asyncio.ensure_future(target)
        self.tasks.append(task)
        return task


class FakeHass:
    """Guarda o que foi agendado e chamado, para os testes conferirem."""

    def __init__(self) -> None:
        self.states = FakeStates()
        self.scheduled: list[tuple[Any, Any]] = []
        self.services = FakeServices()

    @property
    def calls(self) -> list[tuple[str, str, str]]:
        """Os serviços chamados até agora."""
        return self.services.calls

    def async_create_task(self, coroutine) -> asyncio.Task:
        return asyncio.ensure_future(coroutine)


@pytest.fixture
def hass() -> FakeHass:
    return FakeHass()


@pytest.fixture
def coordinator(hass: FakeHass, _fake_scheduling):
    """Um coordinator montado à mão, sem passar pelo DataUpdateCoordinator."""
    from custom_components.weather_schedule.const import (
        CONF_AIR_TEMPERATURE,
        CONF_CARBON_DIOXIDE,
        CONF_LEAF_SENSOR,
        CONF_RELATIVE_HUMIDITY,
    )
    from custom_components.weather_schedule.coordinator import RoomCoordinator

    room = object.__new__(RoomCoordinator)
    room.hass = hass
    room.settings = {
        CONF_AIR_TEMPERATURE: "sensor.air",
        CONF_RELATIVE_HUMIDITY: "sensor.humidity",
        CONF_CARBON_DIOXIDE: "sensor.co2",
        CONF_LEAF_SENSOR: None,
    }
    room.phase = "veg_late"
    room.leaf_drop = 2.0
    room.cycles = None
    room._alert = False
    room._drifting_since = None
    room._settled_since = None
    room._cancel_timer = None
    room._cancel_light_flip = None
    room._light_flip_at = None
    room._warned = set()
    hass.states.set("sensor.air", "24.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "60.0", unit_of_measurement="%")
    hass.states.set("sensor.co2", "900", unit_of_measurement="ppm")
    return room


@pytest.fixture
def _fake_scheduling(monkeypatch):
    """Sem loop rodando, agendar vira só registrar o pedido.

    Não é autouse de propósito: pedir isto importa a integração, e os testes de
    psicrometria rodam sem ela.
    """
    import custom_components.weather_schedule.coordinator as coordinator_module
    import custom_components.weather_schedule.cycles as cycles_module

    def fake_point_in_time(hass, action, when):
        hass.scheduled.append((when, action))
        return lambda: hass.scheduled.remove((when, action)) if (when, action) in hass.scheduled else None

    def fake_track_state(hass, entity_ids, action):
        return lambda: None

    monkeypatch.setattr(cycles_module, "async_track_point_in_utc_time", fake_point_in_time)
    monkeypatch.setattr(cycles_module, "async_track_state_change_event", fake_track_state)
    monkeypatch.setattr(coordinator_module, "async_track_point_in_utc_time", fake_point_in_time)


@pytest.fixture
def cycles(hass: FakeHass, coordinator):
    """O motor de ciclos ligado a um coordinator falso."""
    from custom_components.weather_schedule.cycles import FanCycles

    class Listeners:
        def __init__(self, room):
            self.fans: list[dict] = []
            self.room = room
            self.updates = 0

        def async_update_listeners(self) -> None:
            self.updates += 1

    holder = Listeners(coordinator)
    engine = object.__new__(FanCycles)
    engine.hass = hass
    engine.entry = FakeEntry()
    engine.coordinator = holder
    engine.enabled = True
    engine._cancel = {}
    engine._watching = None
    engine._next = {}
    engine._running = {}
    engine._pending = {}
    engine._tasks = {}
    engine._generation = 0
    return engine


def fire(hass: FakeHass, index: int = -1) -> None:
    """Dispara um passo agendado, como o relógio do Home Assistant faria."""
    when, action = hass.scheduled.pop(index)
    action(when)
