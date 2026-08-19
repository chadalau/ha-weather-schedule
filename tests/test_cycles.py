"""Timers cíclicos: o que é aceito como ciclo e como ele segue a realidade."""

from __future__ import annotations

import pytest

from conftest import FakeState
from custom_components.weather_schedule.config_flow import _clean_cycle


def with_fans(cycles, fans):
    cycles.coordinator.fans = fans
    return cycles


def cycle(on=15, off=45, enabled=True):
    return {"on": on, "off": off, "enabled": enabled}


def test_a_complete_cycle_is_accepted(cycles):
    with_fans(cycles, [{"entity_id": "fan.exhaust", "cycle": cycle()}])
    assert cycles._configured() == [("fan.exhaust", 15, 45)]


def test_switch_domain_is_accepted_too(cycles):
    with_fans(cycles, [{"entity_id": "switch.circulator", "cycle": cycle(10, 20)}])
    assert cycles._configured() == [("switch.circulator", 10, 20)]


def test_disabled_cycle_is_ignored(cycles):
    with_fans(cycles, [{"entity_id": "fan.exhaust", "cycle": cycle(enabled=False)}])
    assert cycles._configured() == []


def test_fan_without_cycle_is_ignored(cycles):
    with_fans(cycles, [{"entity_id": "fan.exhaust", "name": "Exaustor"}])
    assert cycles._configured() == []


@pytest.mark.parametrize(
    "broken",
    [
        {"entity_id": "light.kitchen", "cycle": cycle()},          # domínio que não é ventilador
        {"entity_id": "", "cycle": cycle()},                        # sem entidade
        {"entity_id": "fan.a", "cycle": cycle(on=0)},               # minuto zero
        {"entity_id": "fan.a", "cycle": cycle(off=-5)},             # minuto negativo
        {"entity_id": "fan.a", "cycle": cycle(on=float("inf"))},    # infinito
        {"entity_id": "fan.a", "cycle": cycle(on="quinze")},        # texto
        {"entity_id": "fan.a", "cycle": "ligado"},                  # ciclo que não é dicionário
        {"cycle": cycle()},                                          # dicionário sem entity_id
    ],
)
def test_corrupted_configuration_is_discarded_without_raising(cycles, broken):
    """Achado H6: opções são dados persistidos e podem vir quebradas."""
    with_fans(cycles, [broken])
    assert cycles._configured() == []


def test_valid_and_broken_entries_coexist(cycles):
    with_fans(cycles, [
        {"entity_id": "fan.a", "cycle": cycle(on="x")},
        {"entity_id": "fan.b", "cycle": cycle(5, 10)},
    ])
    assert cycles._configured() == [("fan.b", 5, 10)]


def test_restart_anchors_on_the_current_state_of_each_fan(cycles, hass):
    """Achado M3: reiniciar o HA não pode acender a sala inteira."""
    with_fans(cycles, [
        {"entity_id": "fan.running", "cycle": cycle(15, 45)},
        {"entity_id": "fan.resting", "cycle": cycle(15, 45)},
    ])
    hass.states.set("fan.running", "on")
    hass.states.set("fan.resting", "off")

    cycles.async_restart()

    assert cycles._running == {"fan.running": True, "fan.resting": False}
    assert hass.calls == []  # nenhum ventilador foi acionado no arranque


def test_disabled_timers_schedule_nothing(cycles, hass):
    with_fans(cycles, [{"entity_id": "fan.a", "cycle": cycle()}])
    cycles.async_set_enabled(False)
    assert cycles._configured() == [("fan.a", 15, 45)]
    assert cycles.status["fan.a"]["next"] is None


def test_status_reports_phase_and_deadline(cycles, hass):
    with_fans(cycles, [{"entity_id": "fan.a", "cycle": cycle(15, 45)}])
    hass.states.set("fan.a", "on")
    cycles.async_restart()

    status = cycles.status["fan.a"]

    assert status["on"] == 15 and status["off"] == 45
    assert status["running"] is True
    assert status["next"] is not None


def test_manual_switch_reanchors_the_cycle(cycles, hass):
    """Desligar na mão faz a contagem recomeçar pelo tempo de descanso."""
    with_fans(cycles, [{"entity_id": "fan.a", "cycle": cycle(15, 45)}])
    hass.states.set("fan.a", "on")
    cycles.async_restart()
    ligado = cycles._next["fan.a"]

    hass.states.set("fan.a", "off")
    cycles._changed(FakeEvent("fan.a", "off"))

    assert cycles._running["fan.a"] is False
    assert cycles._next["fan.a"] > ligado  # 45 min de descanso, não os 15 restantes


def test_switching_to_the_state_the_cycle_expected_changes_nothing(cycles, hass):
    """O próprio motor acionando não pode reagendar em cima de si mesmo."""
    with_fans(cycles, [{"entity_id": "fan.a", "cycle": cycle(15, 45)}])
    hass.states.set("fan.a", "on")
    cycles.async_restart()
    deadline = cycles._next["fan.a"]

    cycles._changed(FakeEvent("fan.a", "on"))

    assert cycles._next["fan.a"] == deadline


def test_stop_clears_every_timer_without_touching_the_fans(cycles, hass):
    with_fans(cycles, [{"entity_id": "fan.a", "cycle": cycle()}])
    hass.states.set("fan.a", "on")
    cycles.async_restart()

    cycles.async_stop()

    assert cycles._cancel == {} and cycles._next == {}
    assert hass.states.get("fan.a").state == "on"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"on": 15, "off": 45, "enabled": True}, {"on": 15, "off": 45, "enabled": True}),
        ({"on": "20", "off": "40"}, {"on": 20, "off": 40, "enabled": True}),
        ({"on": 15.7, "off": 45.2}, {"on": 15, "off": 45, "enabled": True}),
        ({"on": 0, "off": 45}, {}),
        ({"on": -1, "off": 45}, {}),
        ({"on": float("inf"), "off": 45}, {}),
        ({"on": "muitos", "off": 45}, {}),
        ("ligado", {}),
        (None, {}),
    ],
)
def test_clean_cycle_only_lets_usable_numbers_through(raw, expected):
    assert _clean_cycle(raw) == expected


class FakeEvent:
    """O mínimo de um evento de mudança de estado."""

    def __init__(self, entity_id: str, state: str) -> None:
        self.data = {"entity_id": entity_id, "new_state": FakeState(state)}
