"""O ciclo de luz: um horário, e o que muda quando a sala escurece."""

from __future__ import annotations

import datetime

import pytest

from custom_components.weather_schedule.const import (
    CONF_LIGHT_HOURS,
    CONF_LIGHTS_ON,
    CONF_NIGHT_LEAF_DROP,
    STATUS_CO2_HIGH,
    STATUS_CO2_LOW,
)


@pytest.fixture
def relogio(monkeypatch):
    """Empurra o relógio da integração para a hora que o teste quiser."""
    import custom_components.weather_schedule.coordinator as coordinator_module

    fuso = datetime.timezone(datetime.timedelta(hours=-3))

    def marcar(hora: str) -> None:
        horas, minutos = (int(parte) for parte in hora.split(":"))
        agora = datetime.datetime(2026, 8, 20, horas, minutos, tzinfo=fuso)
        monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: agora)

    return marcar


@pytest.fixture
def ciclo(coordinator):
    """Liga o ciclo da sala: acende às 18:00, dezoito horas de luz."""
    coordinator.settings[CONF_LIGHTS_ON] = "18:00:00"
    coordinator.settings[CONF_LIGHT_HOURS] = 18.0
    return coordinator


@pytest.mark.parametrize(
    ("hora", "claro"),
    [
        ("18:00", True),   # o instante em que acende
        ("23:30", True),   # a virada da meia-noite não interrompe o dia
        ("03:00", True),
        ("11:59", True),   # último minuto antes de apagar
        ("12:00", False),  # apagou
        ("15:00", False),
        ("17:59", False),
    ],
)
def test_the_day_wraps_around_midnight(ciclo, relogio, hora, claro):
    relogio(hora)
    assert ciclo.is_daytime is claro


def test_twenty_four_hours_of_light_never_gets_dark(coordinator, relogio):
    """É o padrão: uma sala sem ciclo declarado é julgada como sempre foi."""
    relogio("03:00")
    assert coordinator.is_daytime is True


def test_zero_hours_of_light_is_always_dark(coordinator, relogio):
    coordinator.settings[CONF_LIGHT_HOURS] = 0
    relogio("12:00")
    assert coordinator.is_daytime is False


def test_carbon_dioxide_is_not_judged_in_the_dark(ciclo, hass, relogio):
    """Sem luz não há fotossíntese: cobrar a janela de CO₂ é alarme sobre nada."""
    hass.states.set("sensor.co2", "400", unit_of_measurement="ppm")

    relogio("20:00")
    aceso = ciclo._read_room()
    assert aceso.daytime is True
    assert STATUS_CO2_LOW in aceso.drifts

    relogio("13:00")
    apagado = ciclo._read_room()
    assert apagado.daytime is False
    assert apagado.carbon_dioxide_status is None
    assert STATUS_CO2_LOW not in apagado.drifts
    assert STATUS_CO2_HIGH not in apagado.drifts


def test_the_other_drifts_survive_the_dark(ciclo, hass, relogio):
    """Só o CO₂ sai do julgamento; frio, seco e VPD continuam valendo."""
    relogio("13:00")
    hass.states.set("sensor.air", "18.0", unit_of_measurement="°C")

    climate = ciclo._read_room()

    assert climate.daytime is False
    assert climate.drifts, "a sala fria continua em desvio no escuro"


def test_the_leaf_gap_shrinks_in_the_dark(ciclo, relogio):
    """No escuro não há transpiração esfriando a folha, só radiação."""
    ciclo.leaf_drop = 2.0
    ciclo.settings[CONF_NIGHT_LEAF_DROP] = 1.0

    relogio("20:00")
    assert ciclo.effective_leaf_drop == pytest.approx(2.0)
    assert ciclo._read_room().leaf_temperature == pytest.approx(22.0)

    relogio("13:00")
    assert ciclo.effective_leaf_drop == pytest.approx(1.0)
    assert ciclo._read_room().leaf_temperature == pytest.approx(23.0)


def test_drying_has_no_leaf_to_cool_whatever_the_hour(ciclo, relogio):
    ciclo.phase = "dry"
    for hora in ("20:00", "13:00"):
        relogio(hora)
        assert ciclo.effective_leaf_drop == 0.0


def test_the_room_wakes_itself_when_the_lights_flip(ciclo, relogio):
    """Sem isso a sala só notaria a virada no próximo sensor a reportar."""
    relogio("20:00")
    ciclo._read_room()

    assert ciclo._light_flip_at is not None
    # apaga às 12:00 local, que em UTC-3 são 15:00
    assert ciclo._light_flip_at.hour == 15


def test_a_room_without_a_cycle_has_nothing_to_wake_up_for(coordinator, relogio):
    relogio("20:00")
    coordinator._read_room()
    assert coordinator._light_flip_at is None
    assert coordinator._cancel_light_flip is None


def test_the_carbon_dioxide_status_is_unknown_in_the_dark_not_missing(ciclo, relogio):
    """A entidade não sumiu: é a pergunta que não se aplica agora."""
    from custom_components.weather_schedule.sensor import SENSORS

    descricao = next(s for s in SENSORS if s.key == "carbon_dioxide_status")

    relogio("13:00")
    assert ciclo._read_room().carbon_dioxide_status is None
    # a disponibilidade olha se a sala tem sensor, não se há valor agora
    assert descricao.present is not None
    assert descricao.present(ciclo) is True
