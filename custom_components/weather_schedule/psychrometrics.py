"""Moist air maths for Weather Schedule.

Saturation vapour pressure follows the Arden Buck equation (1996) over water,
which tracks measurements closer than the older Magnus-Tetens pair across the
range a grow room actually lives in. Everything else is derived from it, so the
whole module stays consistent with a single curve.
"""

from __future__ import annotations

from math import exp, log, sqrt

# Arden Buck coefficients over water.
_BUCK_A = 0.61121  # kPa
_BUCK_B = 18.678
_BUCK_C = 234.5  # °C
_BUCK_D = 257.14  # °C

# Molar mass of water vapour and the universal gas constant.
_WATER_MOLAR_MASS = 18.01528  # g/mol
_GAS_CONSTANT = 8.31446  # J/(mol·K)
_ZERO_CELSIUS_IN_KELVIN = 273.15

_SMALLEST_HUMIDITY = 1e-6


def _buck_gamma(temperature: float) -> float:
    """Return the exponent of the Buck equation for a temperature in °C."""
    return (_BUCK_B - temperature / _BUCK_C) * (temperature / (_BUCK_D + temperature))


def saturation_pressure(temperature: float) -> float:
    """Return the saturation vapour pressure in kPa for a temperature in °C."""
    return _BUCK_A * exp(_buck_gamma(temperature))


def partial_pressure(temperature: float, humidity: float) -> float:
    """Return the partial vapour pressure in kPa of air at a given humidity."""
    return saturation_pressure(temperature) * humidity / 100


def vapour_pressure_deficit(
    leaf_temperature: float, air_temperature: float, humidity: float
) -> float:
    """Return the leaf-to-air vapour pressure deficit in kPa.

    This is the deficit the plant experiences: saturated air inside the leaf,
    at leaf temperature, against the actual vapour pressure of the room.
    """
    return saturation_pressure(leaf_temperature) - partial_pressure(
        air_temperature, humidity
    )


def dew_point(air_temperature: float, humidity: float) -> float:
    """Return the dew point in °C, by inverting the Buck equation exactly.

    The usual closed form drops the ``T / C`` term of the exponent, which costs
    about a tenth of a degree — enough to make saturated air look like it is
    already below its own dew point. Keeping the term turns the inversion into
    a quadratic, and the lower root is the physical one.
    """
    humidity = max(humidity, _SMALLEST_HUMIDITY)
    gamma = log(humidity / 100) + _buck_gamma(air_temperature)
    linear = _BUCK_C * (_BUCK_B - gamma)
    discriminant = linear * linear - 4 * _BUCK_C * _BUCK_D * gamma
    return (linear - sqrt(max(discriminant, 0.0))) / 2


def absolute_humidity(air_temperature: float, humidity: float) -> float:
    """Return the water actually held by the air, in g/m³.

    Straight from the ideal gas law, so the constant is visible rather than
    folded into a magic number.
    """
    pressure_pa = partial_pressure(air_temperature, humidity) * 1000
    kelvin = air_temperature + _ZERO_CELSIUS_IN_KELVIN
    return pressure_pa * _WATER_MOLAR_MASS / (_GAS_CONSTANT * kelvin)


def condensation_margin(air_temperature: float, humidity: float) -> float:
    """Return how many °C the room is above its own dew point.

    Small margins are what fog windows, wet walls and grey mould look like
    before anyone notices them.
    """
    return air_temperature - dew_point(air_temperature, humidity)
