"""O julgamento da sala: o que conta como desvio e o que entra no alerta."""

from __future__ import annotations

import pytest

from custom_components.weather_schedule.const import (
    CO2_ON_TARGET,
    CO2_OVER,
    CO2_UNDER,
    CONF_AMBIENT_CO2,
    DEFAULT_PROFILES,
    PHASES,
    STATUS_CO2_HIGH,
    STATUS_CO2_LOW,
    STATUS_ON_TARGET,
    STATUS_TOO_COLD,
    STATUS_TOO_DRY,
    STATUS_TOO_HUMID,
    STATUS_TOO_WARM,
    STATUS_VPD_HIGH,
    STATUS_VPD_LOW,
)
from custom_components.weather_schedule.coordinator import RoomClimate


@pytest.fixture
def window(coordinator):
    return coordinator.bounds


def climate(**values) -> RoomClimate:
    return RoomClimate(**values)


def test_every_phase_ships_a_complete_and_ordered_window():
    """Faixa invertida ou faltando vira julgamento sem sentido."""
    for phase in PHASES:
        profile = DEFAULT_PROFILES[phase]
        for low, high in (
            ("vpd_min", "vpd_max"),
            ("temp_min", "temp_max"),
            ("rh_min", "rh_max"),
            ("co2_min", "co2_max"),
        ):
            assert low in profile and high in profile, f"{phase} sem {low}/{high}"
            assert profile[low] < profile[high], f"{phase} tem {low} acima de {high}"


def test_reading_inside_the_window_has_no_drift(coordinator, window):
    assert coordinator._drifts_of(
        climate(vpd=1.1, air_temperature=24.0, relative_humidity=60.0), window
    ) == []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("vpd", 0.5, STATUS_VPD_LOW),
        ("vpd", 1.9, STATUS_VPD_HIGH),
        ("air_temperature", 18.0, STATUS_TOO_COLD),
        ("air_temperature", 31.0, STATUS_TOO_WARM),
        ("relative_humidity", 40.0, STATUS_TOO_DRY),
        ("relative_humidity", 80.0, STATUS_TOO_HUMID),
    ],
)
def test_each_reading_reports_its_own_drift(coordinator, window, field, value, expected):
    values = {"vpd": 1.1, "air_temperature": 24.0, "relative_humidity": 60.0}
    values[field] = value
    assert expected in coordinator._drifts_of(climate(**values), window)


def test_vpd_leads_the_drift_list(coordinator, window):
    """O status mostra o primeiro desvio, e o VPD é o que se dirige a sala por."""
    drifts = coordinator._drifts_of(
        climate(vpd=1.9, air_temperature=31.0, relative_humidity=40.0), window
    )
    assert drifts[0] == STATUS_VPD_HIGH
    assert set(drifts) == {STATUS_VPD_HIGH, STATUS_TOO_WARM, STATUS_TOO_DRY}


def test_missing_readings_are_skipped_not_guessed(coordinator, window):
    assert coordinator._drifts_of(climate(vpd=None, air_temperature=None), window) == []


def test_boundaries_belong_to_the_window(coordinator, window):
    """Exatamente no limite ainda é dentro: 1,0 e 1,2 não são desvio."""
    low = coordinator._drifts_of(climate(vpd=window["vpd_min"]), window)
    high = coordinator._drifts_of(climate(vpd=window["vpd_max"]), window)
    assert low == [] and high == []


@pytest.mark.parametrize(
    ("reading", "expected"),
    [(700, CO2_UNDER), (800, CO2_ON_TARGET), (1000, CO2_ON_TARGET), (1200, CO2_ON_TARGET), (1400, CO2_OVER)],
)
def test_carbon_dioxide_status(coordinator, window, reading, expected):
    assert coordinator._carbon_dioxide_status(reading, window) == expected


def test_room_without_carbon_dioxide_sensor_has_no_status(coordinator, window):
    assert coordinator._carbon_dioxide_status(None, window) is None


def test_unenriched_room_never_reports_low_carbon_dioxide(coordinator, window):
    """Sala sem injeção vive no CO₂ ambiente: 'baixo' seria alarme permanente."""
    coordinator.settings[CONF_AMBIENT_CO2] = True
    assert coordinator._carbon_dioxide_status(450, window) == CO2_ON_TARGET
    assert coordinator._carbon_dioxide_status(1400, window) == CO2_OVER


def test_carbon_dioxide_enters_the_alert(coordinator, hass):
    """Achado H1: o CO₂ tem janela, logo tem que contar como desvio."""
    hass.states.set("sensor.co2", "400", unit_of_measurement="ppm")
    climate_now = coordinator._read_room()
    assert STATUS_CO2_LOW in climate_now.drifts

    hass.states.set("sensor.co2", "1600", unit_of_measurement="ppm")
    climate_now = coordinator._read_room()
    assert STATUS_CO2_HIGH in climate_now.drifts


def test_carbon_dioxide_alone_is_enough_to_leave_on_target(coordinator, hass):
    hass.states.set("sensor.air", "25.0", unit_of_measurement="°C")
    hass.states.set("sensor.humidity", "55", unit_of_measurement="%")
    hass.states.set("sensor.co2", "1600", unit_of_measurement="ppm")

    climate_now = coordinator._read_room()

    assert climate_now.status != STATUS_ON_TARGET
    assert climate_now.drifts == [STATUS_CO2_HIGH]


def test_phase_change_swaps_the_whole_window(coordinator):
    veg = coordinator.bounds
    coordinator.phase = "flower_late"
    flower = coordinator.bounds
    assert veg["vpd_max"] < flower["vpd_min"]
    assert flower["rh_max"] < veg["rh_max"]


def test_room_overrides_beat_the_default_profile(coordinator):
    coordinator.settings["profiles"] = {"veg_late": {"vpd_min": 0.9, "vpd_max": 1.4}}
    window = coordinator.bounds
    assert window["vpd_min"] == 0.9 and window["vpd_max"] == 1.4
    # o que não foi sobrescrito continua vindo do padrão
    assert window["temp_min"] == DEFAULT_PROFILES["veg_late"]["temp_min"]
