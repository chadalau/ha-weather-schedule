"""Leitura de sensores: o que entra na conta e o que é recusado na porta.

Cada teste aqui corresponde a um achado das revisões — NaN passando por leitura
válida, °F tratado como °C, sala cega considerada saudável.
"""

from __future__ import annotations

import pytest

from custom_components.weather_schedule.const import (
    CONF_LEAF_SENSOR,
    CONF_RELATIVE_HUMIDITY,
    STATUS_ON_TARGET,
)


@pytest.mark.parametrize("reading", ["unknown", "unavailable", "", "ligado", "None"])
def test_non_numeric_states_are_refused(coordinator, hass, reading):
    hass.states.set("sensor.air", reading)
    assert coordinator._number_of("sensor.air") is None


@pytest.mark.parametrize("reading", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_nan_and_infinity_never_become_readings(coordinator, hass, reading):
    """NaN passa por qualquer comparação sem disparar nada: tem que morrer aqui."""
    hass.states.set("sensor.air", reading)
    assert coordinator._number_of("sensor.air") is None


def test_missing_entity_is_not_a_reading(coordinator):
    assert coordinator._number_of("sensor.does_not_exist") is None
    assert coordinator._number_of(None) is None


@pytest.mark.parametrize(("humidity", "accepted"), [(-1, False), (0, True), (55.5, True), (100, True), (101, False)])
def test_humidity_outside_zero_to_hundred_is_refused(coordinator, hass, humidity, accepted):
    hass.states.set("sensor.humidity", str(humidity))
    result = coordinator._percentage_of("sensor.humidity")
    assert (result is not None) is accepted


def test_fahrenheit_is_converted(coordinator, hass):
    hass.states.set("sensor.air", "75.2", unit_of_measurement="°F")
    assert coordinator._temperature_of("sensor.air") == pytest.approx(24.0)


def test_kelvin_is_converted(coordinator, hass):
    hass.states.set("sensor.air", "297.15", unit_of_measurement="K")
    assert coordinator._temperature_of("sensor.air") == pytest.approx(24.0)


def test_unknown_unit_is_assumed_celsius_but_warned_once(coordinator, hass, caplog):
    hass.states.set("sensor.air", "24.0", unit_of_measurement="graus")
    assert coordinator._temperature_of("sensor.air") == pytest.approx(24.0)
    assert coordinator._temperature_of("sensor.air") == pytest.approx(24.0)
    assert sum("assuming Celsius" in message for message in caplog.messages) == 1


def test_room_reads_every_derived_value(coordinator):
    climate = coordinator._read_room()
    assert climate.readable is True
    assert climate.leaf_temperature == pytest.approx(22.0)  # 24 - offset de 2
    assert climate.vpd == pytest.approx(0.854, abs=0.005)
    assert climate.dew_point == pytest.approx(15.76, abs=0.05)
    assert climate.absolute_humidity == pytest.approx(13.06, abs=0.05)
    assert climate.condensation_margin == pytest.approx(8.24, abs=0.05)


def test_infrared_sensor_wins_over_the_assumed_offset(coordinator, hass):
    coordinator.settings[CONF_LEAF_SENSOR] = "sensor.leaf"
    hass.states.set("sensor.leaf", "19.5", unit_of_measurement="°C")
    assert coordinator._read_room().leaf_temperature == pytest.approx(19.5)


def test_room_without_humidity_is_unreadable_and_keeps_the_alert(coordinator, hass):
    """Achado C1: sala cega não pode ser reportada como saudável."""
    coordinator._alert = True
    hass.states.set("sensor.humidity", "unavailable")

    climate = coordinator._read_room()

    assert climate.readable is False
    assert climate.status is None
    assert climate.drifts == []
    assert climate.alert is True  # o alerta que já existia continua de pé


def test_room_without_humidity_does_not_start_a_clear_countdown(coordinator, hass):
    coordinator._alert = True
    coordinator._settled_since = None
    hass.states.set("sensor.humidity", "unavailable")

    coordinator._read_room()

    assert coordinator._settled_since is None
    assert coordinator._cancel_timer is None


def test_an_outage_does_not_carry_the_old_drift_into_the_alert(coordinator, hass):
    """Achado A1: a tolerância mede um trecho contínuo, e o apagão o rompeu.

    Guardar o timestamp velho fazia `_schedule_check` mirar um instante no
    passado, e o alerta subia no segundo em que o sensor voltasse — sobre um
    trecho que ninguém mediu.
    """
    from homeassistant.util import dt as dt_util

    coordinator._read_room()
    hass.states.set("sensor.air", "35.0", unit_of_measurement="°C")
    coordinator._read_room()
    assert coordinator._drifting_since is not None  # a sala começou a desviar

    hass.states.set("sensor.air", "unavailable")
    coordinator._read_room()

    assert coordinator._drifting_since is None
    assert coordinator._settled_since is None
    assert coordinator._cancel_timer is None

    hass.states.set("sensor.air", "35.0", unit_of_measurement="°C")
    coordinator._read_room()

    # A contagem recomeça de agora: o alvo tem que estar no futuro.
    assert coordinator._drifting_since is not None
    assert hass.scheduled and hass.scheduled[-1][0] > dt_util.utcnow()


def test_an_outage_forgets_a_settled_stretch_too(coordinator, hass):
    """O espelho do mesmo defeito: não é só o alerta que subia sozinho."""
    coordinator._alert = True
    # 25 °C com 55% cai no meio da janela: a sala começa a se acalmar.
    hass.states.set("sensor.air", "25.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "55", unit_of_measurement="%")
    coordinator._read_room()
    assert coordinator._settled_since is not None

    hass.states.set("sensor.humidity", "unavailable")
    coordinator._read_room()

    assert coordinator._settled_since is None
    assert coordinator._alert is True  # nada foi limpo pelo apagão


def test_an_unreadable_room_still_reports_the_hour(coordinator, hass, monkeypatch):
    """Achado M3: a hora do dia não depende de sensor nenhum.

    Ficando no default `True`, uma sala escura e cega dizia ao card que era
    dia, e a faixa-alvo de CO₂ voltava a ser desenhada de madrugada.
    """
    import datetime

    from custom_components.weather_schedule.const import (
        CONF_LIGHT_HOURS,
        CONF_LIGHTS_ON,
    )
    import custom_components.weather_schedule.coordinator as coordinator_module

    fuso = datetime.timezone(datetime.timedelta(hours=-3))
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime.datetime(2026, 8, 20, 15, 0, tzinfo=fuso),
    )
    # Acende às 18:00 por dezoito horas, então às 15:00 a sala está escura.
    coordinator.settings[CONF_LIGHTS_ON] = "18:00:00"
    coordinator.settings[CONF_LIGHT_HOURS] = 18.0
    hass.states.set("sensor.humidity", "unavailable")

    climate = coordinator._read_room()

    assert climate.readable is False
    assert climate.daytime is False


def test_healthy_room_reports_on_target(coordinator, hass):
    # 25 °C com 55% cai no meio da janela de veg tardia: VPD 1,07 kPa.
    hass.states.set("sensor.air", "25.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "55", unit_of_measurement="%")
    hass.states.set("sensor.co2", "900", unit_of_measurement="ppm")
    coordinator.settings[CONF_RELATIVE_HUMIDITY] = "sensor.humidity"

    climate = coordinator._read_room()

    assert climate.drifts == []
    assert climate.status == STATUS_ON_TARGET


# --------------------------------------------------------------------------- #
# Duas leituras por sala: a sala é a média delas.
# --------------------------------------------------------------------------- #


@pytest.fixture
def paired(coordinator, hass):
    """Uma sala com dois pares de sensores, bem separados um do outro."""
    from custom_components.weather_schedule.const import (
        CONF_AIR_TEMPERATURE,
        CONF_RELATIVE_HUMIDITY,
    )

    coordinator.settings[CONF_AIR_TEMPERATURE] = ["sensor.air", "sensor.air_2"]
    coordinator.settings[CONF_RELATIVE_HUMIDITY] = ["sensor.humidity", "sensor.humidity_2"]
    hass.states.set("sensor.air", "22.0", unit_of_measurement="°C")
    hass.states.set("sensor.air_2", "28.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "65", unit_of_measurement="%")
    hass.states.set("sensor.humidity_2", "45", unit_of_measurement="%")
    return coordinator


def test_a_single_entity_still_works(coordinator):
    """Sala configurada antes da lista guardou um id solto."""
    assert coordinator._entities("air_temperature") == ["sensor.air"]
    assert coordinator._read_room().air_temperature == pytest.approx(24.0)


def test_the_room_reads_the_average_of_its_sensors(paired):
    climate = paired._read_room()
    assert climate.air_temperature == pytest.approx(25.0)
    assert climate.relative_humidity == pytest.approx(55.0)


def test_vpd_averages_the_points_not_the_readings(paired):
    """A conta é exponencial na temperatura: mediar antes muda o resultado."""
    from custom_components.weather_schedule import psychrometrics as psy

    per_point = (
        psy.vapour_pressure_deficit(20.0, 22.0, 65.0)
        + psy.vapour_pressure_deficit(26.0, 28.0, 45.0)
    ) / 2
    of_the_average = psy.vapour_pressure_deficit(23.0, 25.0, 55.0)

    assert paired._read_room().vpd == pytest.approx(per_point, abs=0.001)
    # e as duas contas não são a mesma coisa, que é o motivo de escolher uma
    assert abs(per_point - of_the_average) > 0.05


def test_dew_point_also_averages_the_points(paired):
    from custom_components.weather_schedule import psychrometrics as psy

    expected = (psy.dew_point(22.0, 65.0) + psy.dew_point(28.0, 45.0)) / 2
    assert paired._read_room().dew_point == pytest.approx(expected, abs=0.001)


def test_one_sensor_going_quiet_leaves_the_other_reading(paired, hass):
    hass.states.set("sensor.air_2", "unavailable")

    climate = paired._read_room()

    assert climate.readable is True
    assert climate.air_temperature == pytest.approx(22.0)


def test_the_room_is_unreadable_only_when_every_sensor_is(paired, hass):
    hass.states.set("sensor.air", "unavailable")
    hass.states.set("sensor.air_2", "unavailable")

    assert paired._read_room().readable is False


def test_mismatched_counts_fall_back_to_the_averages(coordinator, hass):
    """Três termômetros e dois higrômetros não formam pares; a média resolve."""
    from custom_components.weather_schedule import psychrometrics as psy
    from custom_components.weather_schedule.const import (
        CONF_AIR_TEMPERATURE,
        CONF_RELATIVE_HUMIDITY,
    )

    coordinator.settings[CONF_AIR_TEMPERATURE] = ["sensor.air", "sensor.air_2", "sensor.air_3"]
    coordinator.settings[CONF_RELATIVE_HUMIDITY] = ["sensor.humidity", "sensor.humidity_2"]
    for entity, value in (("sensor.air", 22.0), ("sensor.air_2", 25.0), ("sensor.air_3", 28.0)):
        hass.states.set(entity, str(value), unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "65", unit_of_measurement="%")
    hass.states.set("sensor.humidity_2", "45", unit_of_measurement="%")

    climate = coordinator._read_room()

    assert climate.air_temperature == pytest.approx(25.0)
    assert climate.vpd == pytest.approx(psy.vapour_pressure_deficit(23.0, 25.0, 55.0), abs=0.001)


def test_the_card_gets_the_first_sensor_and_the_full_list(paired):
    assert paired.sources["air_temperature"] == "sensor.air"
    assert paired.sensors["air_temperature"] == ["sensor.air", "sensor.air_2"]
    assert paired.sensors["carbon_dioxide"] == ["sensor.co2"]
