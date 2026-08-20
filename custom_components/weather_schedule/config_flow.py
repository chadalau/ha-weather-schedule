"""Setting up and re-editing a room."""

from __future__ import annotations

from math import isfinite
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    BOUND_CO2_MAX,
    BOUND_CO2_MIN,
    BOUND_RH_MAX,
    BOUND_RH_MIN,
    BOUND_TEMP_MAX,
    BOUND_TEMP_MIN,
    BOUND_VPD_MAX,
    BOUND_VPD_MIN,
    BOUNDS,
    CONF_AIR_TEMPERATURE,
    CONF_AMBIENT_CO2,
    CONF_CARBON_DIOXIDE,
    CONF_CLEAR_MINUTES,
    CONF_FAN_NAMES,
    CONF_FAN_CYCLES,
    CONF_FAN_POWERS,
    CONF_FANS,
    CONF_LEAF_DROP,
    CONF_LIGHT_HOURS,
    CONF_LIGHTS_ON,
    CONF_NIGHT_LEAF_DROP,
    CONF_LEAF_SENSOR,
    CONF_PROFILES,
    CONF_RELATIVE_HUMIDITY,
    CONF_TRIP_MINUTES,
    DEFAULT_CLEAR_MINUTES,
    DEFAULT_LEAF_DROP,
    DEFAULT_LIGHT_HOURS,
    DEFAULT_LIGHTS_ON,
    DEFAULT_NIGHT_LEAF_DROP,
    DEFAULT_PROFILES,
    DEFAULT_TRIP_MINUTES,
    DOMAIN,
    LEAF_DROP_CEILING,
    PHASES,
    STARTING_PHASE,
)

CONF_PHASE = "phase"

SENSOR_FIELDS = (
    CONF_AIR_TEMPERATURE,
    CONF_RELATIVE_HUMIDITY,
    CONF_LEAF_SENSOR,
    CONF_CARBON_DIOXIDE,
    CONF_LEAF_DROP,
)

# Range and step of each editable bound.
BOUND_LIMITS: dict[str, tuple[float, float, float]] = {
    BOUND_VPD_MIN: (0, 3, 0.05),
    BOUND_VPD_MAX: (0, 3, 0.05),
    BOUND_TEMP_MIN: (0, 50, 0.5),
    BOUND_TEMP_MAX: (0, 50, 0.5),
    BOUND_RH_MIN: (0, 100, 1),
    BOUND_RH_MAX: (0, 100, 1),
    BOUND_CO2_MIN: (0, 3000, 25),
    BOUND_CO2_MAX: (0, 3000, 25),
}


def _clean_cycle(raw: Any) -> dict[str, Any]:
    """Return a usable cycle out of whatever the card sent."""
    if not isinstance(raw, dict):
        return {}
    try:
        on = float(raw.get("on") or 0)
        off = float(raw.get("off") or 0)
    except (TypeError, ValueError, OverflowError):
        return {}
    if not (isfinite(on) and isfinite(off)):
        return {}
    on, off = int(on), int(off)
    if on <= 0 or off <= 0:
        return {}
    return {"on": on, "off": off, "enabled": bool(raw.get("enabled", True))}


def _sensor_picker(
    device_class: SensorDeviceClass, multiple: bool = False
) -> selector.EntitySelector:
    """Return a picker limited to sensors of one device class."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor", device_class=device_class, multiple=multiple
        )
    )


def _number_box(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    """Return a plain number box."""
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        # The selector schema rejects a None unit, so only set a real one.
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _sensor_schema(current: dict[str, Any]) -> vol.Schema:
    """Return the sensor form, pre-filled with what the room already uses."""

    plural = (CONF_AIR_TEMPERATURE, CONF_RELATIVE_HUMIDITY)

    def filled(key: str) -> dict[str, Any]:
        value = current.get(key)
        if value is None:
            return {}
        # Uma sala antiga guardou um id solto onde agora vai uma lista.
        if key in plural and isinstance(value, str):
            value = [value]
        return {"suggested_value": value}

    return vol.Schema(
        {
            # Mais de um sensor por sala: a sala passa a ser a média deles.
            vol.Required(
                CONF_AIR_TEMPERATURE, description=filled(CONF_AIR_TEMPERATURE)
            ): _sensor_picker(SensorDeviceClass.TEMPERATURE, multiple=True),
            vol.Required(
                CONF_RELATIVE_HUMIDITY, description=filled(CONF_RELATIVE_HUMIDITY)
            ): _sensor_picker(SensorDeviceClass.HUMIDITY, multiple=True),
            vol.Optional(
                CONF_LEAF_SENSOR, description=filled(CONF_LEAF_SENSOR)
            ): _sensor_picker(SensorDeviceClass.TEMPERATURE),
            vol.Optional(
                CONF_CARBON_DIOXIDE, description=filled(CONF_CARBON_DIOXIDE)
            ): _sensor_picker(SensorDeviceClass.CO2),
            vol.Required(
                CONF_LEAF_DROP,
                default=current.get(CONF_LEAF_DROP, DEFAULT_LEAF_DROP),
            ): _number_box(0, LEAF_DROP_CEILING, 0.1, "°C"),
        }
    )


class WeatherScheduleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Adds one room."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._name = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what the room is called."""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            await self.async_set_unique_id(slugify(self._name))
            self._abort_if_unique_id_configured()
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME): selector.TextSelector()}),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which sensors the room has."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={CONF_NAME: self._name, **user_input}
            )

        return self.async_show_form(step_id="sensors", data_schema=_sensor_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return WeatherScheduleOptionsFlow()


class WeatherScheduleOptionsFlow(OptionsFlow):
    """Re-edits the sensors, the target windows and the alert of a room."""

    def __init__(self) -> None:
        """Initialise the options flow."""
        self._phase = STARTING_PHASE

    @property
    def _current(self) -> dict[str, Any]:
        """Return the settings in force right now."""
        return {**self.config_entry.data, **self.config_entry.options}

    def _store(self, changes: dict[str, Any]) -> ConfigFlowResult:
        """Save changes without discarding what the other steps wrote."""
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what to edit."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["sensors", "fans", "cycle", "phase", "alert"],
        )

    async def async_step_cycle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the room's light cycle, and what the dark changes."""
        if user_input is not None:
            return self._store(
                {
                    CONF_LIGHTS_ON: user_input[CONF_LIGHTS_ON],
                    CONF_LIGHT_HOURS: user_input[CONF_LIGHT_HOURS],
                    CONF_NIGHT_LEAF_DROP: user_input[CONF_NIGHT_LEAF_DROP],
                }
            )

        current = self._current
        return self.async_show_form(
            step_id="cycle",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LIGHTS_ON,
                        default=current.get(CONF_LIGHTS_ON, DEFAULT_LIGHTS_ON),
                    ): selector.TimeSelector(),
                    # Vinte e quatro horas dizem "esta sala nunca escurece", que
                    # e como toda sala era julgada antes deste passo existir.
                    vol.Required(
                        CONF_LIGHT_HOURS,
                        default=current.get(CONF_LIGHT_HOURS, DEFAULT_LIGHT_HOURS),
                    ): _number_box(0, 24, 0.5, "h"),
                    vol.Required(
                        CONF_NIGHT_LEAF_DROP,
                        default=current.get(
                            CONF_NIGHT_LEAF_DROP, DEFAULT_NIGHT_LEAF_DROP
                        ),
                    ): _number_box(0, LEAF_DROP_CEILING, 0.1, "°C"),
                }
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the sensors of the room."""
        if user_input is not None:
            # Every field is written back, so clearing an optional sensor sticks
            # instead of falling back to what was picked at setup.
            return self._store({key: user_input.get(key) for key in SENSOR_FIELDS})

        return self.async_show_form(
            step_id="sensors", data_schema=_sensor_schema(self._current)
        )

    async def async_step_phase(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which phase to retune."""
        if user_input is not None:
            self._phase = user_input[CONF_PHASE]
            return await self.async_step_bounds()

        return self.async_show_form(
            step_id="phase",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHASE, default=STARTING_PHASE): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=list(PHASES),
                                translation_key="phase",
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        )
                    )
                }
            ),
        )

    async def async_step_bounds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retune one phase."""
        errors: dict[str, str] = {}
        window = {
            **DEFAULT_PROFILES[self._phase],
            **self._current.get(CONF_PROFILES, {}).get(self._phase, {}),
        }

        if user_input is not None:
            for low, high in (
                (BOUND_VPD_MIN, BOUND_VPD_MAX),
                (BOUND_TEMP_MIN, BOUND_TEMP_MAX),
                (BOUND_RH_MIN, BOUND_RH_MAX),
                (BOUND_CO2_MIN, BOUND_CO2_MAX),
            ):
                # Uma janela invertida é aceita em silêncio e depois julga a sala
                # ao contrário; melhor recusar aqui.
                if user_input[low] > user_input[high]:
                    errors[low] = "min_above_max"
            if not errors:
                profiles = {**self._current.get(CONF_PROFILES, {})}
                profiles[self._phase] = {key: user_input[key] for key in BOUNDS}
                return self._store({CONF_PROFILES: profiles})
            window = {**window, **user_input}

        return self.async_show_form(
            step_id="bounds",
            data_schema=vol.Schema(
                {
                    vol.Required(key, default=window[key]): _number_box(
                        *BOUND_LIMITS[key]
                    )
                    for key in BOUNDS
                }
            ),
            errors=errors,
            description_placeholders={"phase": self._phase},
        )

    async def async_step_fans(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store which fans belong to the room.

        The integration never switches them; it only remembers them so the card
        does not need them in YAML. The picker carries entity ids, and the card
        sends a name per fan alongside it, which the schema lets through.
        """
        if user_input is not None:
            names = user_input.get(CONF_FAN_NAMES) or {}
            powers = user_input.get(CONF_FAN_POWERS) or {}
            cycles = user_input.get(CONF_FAN_CYCLES) or {}
            fans = [
                {
                    "entity_id": entity_id,
                    "name": str(names.get(entity_id) or ""),
                    "power": str(powers.get(entity_id) or ""),
                    "cycle": _clean_cycle(cycles.get(entity_id)),
                }
                for entity_id in (user_input.get(CONF_FANS) or [])
                if entity_id
            ]
            return self._store({CONF_FANS: fans})

        chosen = [fan["entity_id"] for fan in self._current.get(CONF_FANS, [])]
        return self.async_show_form(
            step_id="fans",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_FANS, default=chosen): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["fan", "switch"], multiple=True
                        )
                    )
                },
                extra=vol.ALLOW_EXTRA,
            ),
        )

    async def async_step_alert(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the alert tolerance and the CO2 enrichment answer."""
        if user_input is not None:
            return self._store(user_input)

        current = self._current
        return self.async_show_form(
            step_id="alert",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TRIP_MINUTES,
                        default=current.get(CONF_TRIP_MINUTES, DEFAULT_TRIP_MINUTES),
                    ): _number_box(1, 240, 1, "min"),
                    vol.Required(
                        CONF_CLEAR_MINUTES,
                        default=current.get(CONF_CLEAR_MINUTES, DEFAULT_CLEAR_MINUTES),
                    ): _number_box(1, 240, 1, "min"),
                    vol.Required(
                        CONF_AMBIENT_CO2,
                        default=current.get(CONF_AMBIENT_CO2, False),
                    ): selector.BooleanSelector(),
                }
            ),
        )
