"""A matemática do ar úmido, conferida contra valores de referência.

Estes testes não importam Home Assistant: a psicrometria é o único pedaço da
integração que não depende de nada, e é bom que continue assim.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

# Carregado pelo caminho de propósito: passar pelo pacote puxaria o
# `__init__.py` da integração, e com ele o Home Assistant.
_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "weather_schedule"
    / "psychrometrics.py"
)
_spec = importlib.util.spec_from_file_location("psychrometrics", _SOURCE)
psy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(psy)


@pytest.mark.parametrize(
    ("celsius", "expected"),
    [
        (0.0, 0.6113),
        (10.0, 1.2282),
        (20.0, 2.3392),
        (25.0, 3.1699),
        (30.0, 4.2455),
        (40.0, 7.3849),
    ],
)
def test_saturation_pressure_matches_reference_tables(celsius, expected):
    """Buck deve bater com a tabela de pressão de saturação em 0,3%."""
    assert psy.saturation_pressure(celsius) == pytest.approx(expected, rel=0.003)


def test_partial_pressure_scales_with_humidity():
    """Metade da umidade, metade da pressão parcial."""
    full = psy.partial_pressure(24.0, 100.0)
    half = psy.partial_pressure(24.0, 50.0)
    assert half == pytest.approx(full / 2)


def test_saturated_air_has_dew_point_equal_to_its_temperature():
    """A 100% de umidade o ponto de orvalho é a própria temperatura."""
    for celsius in (5.0, 18.0, 24.0, 31.0):
        assert psy.dew_point(celsius, 100.0) == pytest.approx(celsius, abs=0.05)


def test_dew_point_inverts_saturation_pressure():
    """A pressão parcial do ar é a pressão de saturação no ponto de orvalho."""
    air, humidity = 26.0, 55.0
    dew = psy.dew_point(air, humidity)
    assert psy.saturation_pressure(dew) == pytest.approx(
        psy.partial_pressure(air, humidity), rel=1e-3
    )


def test_dew_point_never_exceeds_air_temperature():
    """Orvalho acima do ar seria condensação impossível."""
    for humidity in (1, 20, 50, 80, 99.9):
        assert psy.dew_point(23.0, humidity) <= 23.0 + 1e-6


def test_dew_point_survives_zero_humidity():
    """Zero por cento levaria log(0); o piso interno evita o infinito."""
    assert math.isfinite(psy.dew_point(22.0, 0.0))


def test_vpd_is_zero_when_leaf_matches_saturated_air():
    """Folha na temperatura do ar saturado não tem para onde transpirar."""
    assert psy.vapour_pressure_deficit(24.0, 24.0, 100.0) == pytest.approx(0.0, abs=1e-6)


def test_vpd_grows_as_the_room_dries():
    """Menos umidade, mais déficit — monotonicamente."""
    values = [psy.vapour_pressure_deficit(22.0, 24.0, rh) for rh in (80, 60, 40, 20)]
    assert values == sorted(values)


def test_colder_leaf_lowers_the_deficit():
    """Cada grau a menos na folha derruba o VPD, e é isso que o offset controla."""
    warm = psy.vapour_pressure_deficit(23.0, 24.0, 50.0)
    cold = psy.vapour_pressure_deficit(21.0, 24.0, 50.0)
    assert cold < warm


def test_known_room_reproduces_the_measured_numbers():
    """O caso real medido na instalação: 23,4 °C, 43,7%, folha 2 °C abaixo.

    As referências são as de Magnus-Tetens, que é o que o card antigo usava; a
    tolerância de 0,05 é a distância normal entre as duas curvas, não folga.
    """
    air, humidity, leaf = 23.4, 43.7, 21.4
    assert psy.vapour_pressure_deficit(leaf, air, humidity) == pytest.approx(1.291, abs=0.005)
    assert psy.dew_point(air, humidity) == pytest.approx(10.345, abs=0.05)
    assert psy.absolute_humidity(air, humidity) == pytest.approx(9.19, abs=0.05)
    assert psy.condensation_margin(air, humidity) == pytest.approx(13.055, abs=0.05)


def test_absolute_humidity_follows_the_gas_law():
    """Mesma água, ar mais quente: a densidade cai."""
    cold = psy.absolute_humidity(15.0, 100.0)
    warm = psy.absolute_humidity(30.0, 100.0)
    assert warm > cold  # ar quente segura mais água quando saturado


def test_condensation_margin_is_the_distance_to_the_dew_point():
    """A margem é literalmente ar menos orvalho."""
    air, humidity = 27.0, 62.0
    assert psy.condensation_margin(air, humidity) == pytest.approx(
        air - psy.dew_point(air, humidity)
    )
