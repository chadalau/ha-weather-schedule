"""Timers cíclicos: o que é aceito como ciclo e como ele segue a realidade."""

from __future__ import annotations

import asyncio

from conftest import FakeState, fire
import pytest

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


def test_a_sub_minute_cycle_is_refused_not_truncated_to_zero(cycles):
    """Achado M2: meio minuto virava zero, e um passo de zero reagenda no ato.

    `_configured` truncava depois de validar, então `0.5 > 0` passava e
    `int(0.5)` chegava ao agendador como zero minuto: o ciclo entrava em laço
    apertado chamando o serviço. O `_clean_cycle` do fluxo de opções sempre
    recusou o mesmo valor — as duas guardas agora concordam.
    """
    with_fans(cycles, [{"entity_id": "fan.exhaust", "cycle": cycle(0.5, 0.5)}])
    assert cycles._configured() == []


def test_a_cycle_below_a_minute_on_either_side_is_refused(cycles):
    with_fans(cycles, [{"entity_id": "fan.exhaust", "cycle": cycle(15, 0.9)}])
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
        ({"on": 0.5, "off": 0.5}, {}),  # trunca para zero: não é ciclo
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


# --------------------------------------------------------------------------- #
# A parte que atua de verdade: o comando, sua confirmação e seu cancelamento.
#
# Até aqui a suíte nunca via uma chamada de serviço acontecer — o fake fechava
# a corrotina sem executá-la. Estes testes rodam o laço de verdade.
# --------------------------------------------------------------------------- #


async def settle(tasks):
    """Espera as tarefas, com teto próprio.

    Sem o teto, uma regressão que remova o limite do comando não faria o teste
    falhar: faria a suíte inteira travar, que é o pior jeito de descobrir.
    """
    await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True), timeout=5
    )


def a_fan_that_cycles(cycles, hass, state="off"):
    """Um ventilador com ciclo, no estado físico pedido."""
    with_fans(cycles, [{"entity_id": "fan.exhaust", "cycle": cycle(15, 45)}])
    hass.states.set("fan.exhaust", state)
    return cycles


def test_a_step_switches_the_fan_and_books_the_next_one(cycles, hass):
    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        fire(hass)  # vence o descanso: hora de ligar
        hass.states.set("fan.exhaust", "on")  # o ventilador obedeceu
        await settle(cycles._tasks.values())

    asyncio.run(run())

    assert hass.calls == [("fan", "turn_on", "fan.exhaust")]
    assert cycles._running["fan.exhaust"] is True
    assert "fan.exhaust" in cycles._next


def test_a_command_still_in_flight_does_not_switch_a_stopped_room(cycles, hass):
    """Achado A1: o passo antigo atuava depois do pause e depois do unload."""

    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        hass.services.block = asyncio.Event()
        fire(hass)
        await asyncio.sleep(0)  # o comando parte e fica preso no serviço
        pending = list(cycles._tasks.values())

        cycles.async_stop()  # pause ou unload no meio do comando
        during_stop = list(hass.calls)

        hass.services.block.set()  # o serviço finalmente responde
        await settle(pending)
        return during_stop

    during_stop = asyncio.run(run())

    assert during_stop == []
    # O ciclo parado não reagenda nada, aconteça o que acontecer com o comando.
    assert cycles._next == {}
    assert cycles._running == {}


def test_shutdown_waits_for_the_command_instead_of_leaving_it_behind(cycles, hass):
    """O unload não pode voltar com um `turn_on` ainda pendurado."""

    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        hass.services.block = asyncio.Event()
        fire(hass)
        await asyncio.sleep(0)
        task = next(iter(cycles._tasks.values()))

        hass.services.block.set()
        await asyncio.wait_for(cycles.async_shutdown(), timeout=5)
        return task

    task = asyncio.run(run())

    assert task.done()
    assert cycles._tasks == {}


def test_a_refused_command_leaves_the_cycle_on_the_fan_it_actually_has(cycles, hass):
    """Achado M1: o ciclo dizia "ligado" com o ventilador parado."""

    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        hass.services.fail = True
        fire(hass)  # tenta ligar, e o serviço recusa
        await settle(cycles._tasks.values())

    asyncio.run(run())

    # O ventilador continua desligado, e a fase do ciclo diz o mesmo.
    assert hass.states.get("fan.exhaust").state == "off"
    assert cycles._running["fan.exhaust"] is False
    # E o próximo passo volta a tentar ligar, em vez de mandar desligar o que
    # nunca ligou.
    assert cycles._next["fan.exhaust"] is not None


def test_a_command_that_never_answers_gives_up_instead_of_hanging(cycles, hass, monkeypatch):
    """`blocking=True` sem teto deixaria a tarefa presa para sempre."""
    import custom_components.weather_schedule.cycles as cycles_module

    monkeypatch.setattr(cycles_module, "SWITCH_TIMEOUT", 0.01)

    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        hass.services.block = asyncio.Event()  # nunca solto
        fire(hass)
        await settle(cycles._tasks.values())

    asyncio.run(run())

    assert hass.calls == []  # o serviço nunca respondeu
    assert cycles._tasks == {}  # mas nada ficou pendurado
    assert cycles._running["fan.exhaust"] is False


def test_only_one_command_per_fan_is_ever_in_flight(cycles, hass):
    """Dois passos opostos em voo poderiam concluir fora de ordem."""

    async def run():
        a_fan_that_cycles(cycles, hass)
        cycles.async_restart()
        hass.services.block = asyncio.Event()
        fire(hass)
        await asyncio.sleep(0)
        first = next(iter(cycles._tasks.values()))

        cycles._step("fan.exhaust", 15, 45, False)  # um segundo passo chega
        await asyncio.sleep(0)
        hass.services.block.set()
        await settle([*cycles._tasks.values(), first])
        return first

    first = asyncio.run(run())

    assert first.cancelled()  # o passo anterior foi cancelado, não duplicado
