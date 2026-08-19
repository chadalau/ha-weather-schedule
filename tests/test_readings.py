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


def test_healthy_room_reports_on_target(coordinator, hass):
    # 25 °C com 55% cai no meio da janela de veg tardia: VPD 1,07 kPa.
    hass.states.set("sensor.air", "25.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "55", unit_of_measurement="%")
    hass.states.set("sensor.co2", "900", unit_of_measurement="ppm")
    coordinator.settings[CONF_RELATIVE_HUMIDITY] = "sensor.humidity"

    climate = coordinator._read_room()

    assert climate.drifts == []
    assert climate.status == STATUS_ON_TARGET
