"""Config flow for Auto Thermostat."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_AWAY_TEMP,
    CONF_BOOST_DURATION,
    CONF_BUTTON_EVENT,
    CONF_COLD_TOLERANCE,
    CONF_CYCLE_COOLDOWN,
    CONF_HEATER,
    CONF_HOME_TEMP,
    CONF_HOT_TOLERANCE,
    CONF_INITIAL_HVAC_MODE,
    CONF_KEEP_ALIVE,
    CONF_LONG_PRESS,
    CONF_MAX_CYCLE,
    CONF_MAX_TEMP,
    CONF_MIN_CYCLE,
    CONF_MIN_TEMP,
    CONF_NAME,
    CONF_PERSONS,
    CONF_PRECISION,
    CONF_SHORT_PRESS,
    CONF_SLEEP_TEMP,
    CONF_TARGET_STEP,
    CONF_TARGET_TEMP,
    CONF_TEMP_SENSORS,
    DEFAULT_BOOST_DURATION,
    DEFAULT_LONG_PRESS,
    DEFAULT_SHORT_PRESS,
    DEFAULT_TOLERANCE,
    DOMAIN,
)
from .logic import replace_options


def _number(minimum: float, maximum: float, step: float, unit: str | None = None) -> NumberSelector:
    """Render a number box with the specified units."""
    config = NumberSelectorConfig(
        min=minimum,
        max=maximum,
        step=step,
        mode=NumberSelectorMode.BOX,
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _suggested(key: str, values: dict[str, Any]) -> Any:
    """Allow an optional entity to be cleared when editing options."""
    value = values.get(key)
    return vol.Optional(key, description={"suggested_value": value}) if value else vol.Optional(key)


def _devices_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=values.get(CONF_NAME, "Living room")): TextSelector(),
            vol.Required(CONF_HEATER, default=values.get(CONF_HEATER, vol.UNDEFINED)): EntitySelector(
                EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Required(
                CONF_TEMP_SENSORS,
                default=values.get(CONF_TEMP_SENSORS, vol.UNDEFINED),
            ): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    device_class=SensorDeviceClass.TEMPERATURE,
                    multiple=True,
                )
            ),
            _suggested(CONF_PERSONS, values): EntitySelector(
                EntitySelectorConfig(domain=["person", "device_tracker"], multiple=True)
            ),
        }
    )


def _presets_schema(values: dict[str, Any], fahrenheit: bool) -> vol.Schema:
    home, away, sleep = ((68, 60, 65) if fahrenheit else (20, 16, 18))
    return vol.Schema(
        {
            vol.Required(CONF_HOME_TEMP, default=values.get(CONF_HOME_TEMP, home)): _number(-40, 150, 0.5),
            vol.Required(CONF_AWAY_TEMP, default=values.get(CONF_AWAY_TEMP, away)): _number(-40, 150, 0.5),
            vol.Required(CONF_SLEEP_TEMP, default=values.get(CONF_SLEEP_TEMP, sleep)): _number(-40, 150, 0.5),
            vol.Required(
                CONF_BOOST_DURATION,
                default=values.get(CONF_BOOST_DURATION, DEFAULT_BOOST_DURATION),
            ): _number(1, 240, 1, "min"),
        }
    )


def _control_schema(values: dict[str, Any], fahrenheit: bool) -> vol.Schema:
    min_temp, max_temp, target_temp = ((45, 86, 68) if fahrenheit else (7, 35, 20))
    initial_mode = values.get(CONF_INITIAL_HVAC_MODE, "heat")
    if initial_mode not in ("heat", "off"):
        initial_mode = "heat"
    return vol.Schema(
        {
            vol.Required(CONF_MIN_TEMP, default=values.get(CONF_MIN_TEMP, min_temp)): _number(-40, 150, 0.5),
            vol.Required(CONF_MAX_TEMP, default=values.get(CONF_MAX_TEMP, max_temp)): _number(-40, 150, 0.5),
            vol.Required(CONF_TARGET_TEMP, default=values.get(CONF_TARGET_TEMP, target_temp)): _number(-40, 150, 0.5),
            vol.Required(
                CONF_INITIAL_HVAC_MODE,
                default=initial_mode,
            ): SelectSelector(SelectSelectorConfig(options=["heat", "off"])),
            vol.Required(
                CONF_COLD_TOLERANCE,
                default=values.get(CONF_COLD_TOLERANCE, DEFAULT_TOLERANCE),
            ): _number(0, 10, 0.1),
            vol.Required(
                CONF_HOT_TOLERANCE,
                default=values.get(CONF_HOT_TOLERANCE, DEFAULT_TOLERANCE),
            ): _number(0, 10, 0.1),
            vol.Required(CONF_MIN_CYCLE, default=values.get(CONF_MIN_CYCLE, 0)): _number(0, 86400, 1, "s"),
            vol.Required(CONF_MAX_CYCLE, default=values.get(CONF_MAX_CYCLE, 0)): _number(0, 86400, 1, "s"),
            vol.Required(
                CONF_CYCLE_COOLDOWN,
                default=values.get(CONF_CYCLE_COOLDOWN, 0),
            ): _number(0, 86400, 1, "s"),
            vol.Required(CONF_KEEP_ALIVE, default=values.get(CONF_KEEP_ALIVE, 0)): _number(0, 86400, 1, "s"),
            vol.Required(
                CONF_PRECISION,
                default=f"{float(values.get(CONF_PRECISION, 1.0 if fahrenheit else 0.1)):.1f}",
            ): SelectSelector(SelectSelectorConfig(options=["0.1", "0.5", "1.0"])),
            vol.Required(
                CONF_TARGET_STEP,
                default=f"{float(values.get(CONF_TARGET_STEP, 1.0 if fahrenheit else 0.1)):.1f}",
            ): SelectSelector(SelectSelectorConfig(options=["0.1", "0.5", "1.0"])),
        }
    )


def _button_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _suggested(CONF_BUTTON_EVENT, values): EntitySelector(EntitySelectorConfig(domain="event")),
            vol.Required(
                CONF_SHORT_PRESS,
                default=values.get(CONF_SHORT_PRESS, DEFAULT_SHORT_PRESS),
            ): TextSelector(),
            vol.Required(
                CONF_LONG_PRESS,
                default=values.get(CONF_LONG_PRESS, DEFAULT_LONG_PRESS),
            ): TextSelector(),
        }
    )


def _validate_control(control: dict[str, Any], presets: dict[str, Any]) -> dict[str, str]:
    """Check relationships that individual selectors cannot validate."""
    minimum, maximum = control[CONF_MIN_TEMP], control[CONF_MAX_TEMP]
    if minimum >= maximum:
        return {"base": "invalid_temp_range"}
    if any(
        not minimum <= float(value) <= maximum
        for value in (
            control[CONF_TARGET_TEMP],
            presets[CONF_HOME_TEMP],
            presets[CONF_AWAY_TEMP],
            presets[CONF_SLEEP_TEMP],
        )
    ):
        return {"base": "temp_out_of_range"}
    min_cycle, max_cycle = control[CONF_MIN_CYCLE], control[CONF_MAX_CYCLE]
    if max_cycle and min_cycle and max_cycle <= min_cycle:
        return {"base": "invalid_cycle_range"}
    return {}


def _validate_button(values: dict[str, Any]) -> dict[str, str]:
    if values[CONF_SHORT_PRESS].strip() == values[CONF_LONG_PRESS].strip():
        return {"base": "same_button_events"}
    return {}


class AutoThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a virtual thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def _fahrenheit(self) -> bool:
        return self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select the heater, temperature sensors and people."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presets()
        return self.async_show_form(step_id="user", data_schema=_devices_schema(self._data))

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure temperatures and the timed boost."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_control()
        return self.async_show_form(
            step_id="presets", data_schema=_presets_schema(self._data, self._fahrenheit())
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure Generic Thermostat control parameters."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_control(user_input, self._data)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_button()
        return self.async_show_form(
            step_id="control",
            data_schema=_control_schema({**self._data, **(user_input or {})}, self._fahrenheit()),
            errors=errors,
        )

    async def async_step_button(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Optionally configure the physical boost button."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_button(user_input)
            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(
            step_id="button",
            data_schema=_button_schema({**self._data, **(user_input or {})}),
            errors=errors,
            last_step=True,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AutoThermostatOptionsFlow:
        """Return the options flow."""
        return AutoThermostatOptionsFlow(config_entry)


class AutoThermostatOptionsFlow(config_entries.OptionsFlow):
    """Edit the thermostat without having to remove it."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    def _values(self) -> dict[str, Any]:
        return {**self._entry.data, **self._entry.options}

    def _fahrenheit(self) -> bool:
        return self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT

    def _save(self, fields: set[str], user_input: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Replace only the options shown on this form, including cleared ones."""
        new_options = replace_options(
            self._entry.options,
            fields,
            user_input,
            {
                CONF_PERSONS: [],
                CONF_BUTTON_EVENT: None,
            },
        )
        return self.async_create_entry(title="", data=new_options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose which group of settings to edit."""
        return self.async_show_menu(
            step_id="init", menu_options=["devices", "presets", "control", "button"]
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit the heater, sensors or people."""
        if user_input is not None:
            return self._save(
                {CONF_NAME, CONF_HEATER, CONF_TEMP_SENSORS, CONF_PERSONS},
                user_input,
            )
        return self.async_show_form(
            step_id="devices", data_schema=_devices_schema(self._values())
        )

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit preset temperatures and boost length."""
        errors: dict[str, str] = {}
        if user_input is not None:
            proposed = {**self._values(), **user_input}
            if any(
                not proposed[CONF_MIN_TEMP] <= user_input[key] <= proposed[CONF_MAX_TEMP]
                for key in (CONF_HOME_TEMP, CONF_AWAY_TEMP, CONF_SLEEP_TEMP)
            ):
                errors = {"base": "temp_out_of_range"}
            if not errors:
                return self._save(
                    {CONF_HOME_TEMP, CONF_AWAY_TEMP, CONF_SLEEP_TEMP, CONF_BOOST_DURATION},
                    user_input,
                )
        return self.async_show_form(
            step_id="presets",
            data_schema=_presets_schema({**self._values(), **(user_input or {})}, self._fahrenheit()),
            errors=errors,
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit the Generic Thermostat parameters."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_control(user_input, self._values())
            if not errors:
                return self._save(
                    {
                        CONF_MIN_TEMP, CONF_MAX_TEMP, CONF_TARGET_TEMP,
                        CONF_INITIAL_HVAC_MODE, CONF_COLD_TOLERANCE,
                        CONF_HOT_TOLERANCE, CONF_MIN_CYCLE, CONF_MAX_CYCLE,
                        CONF_CYCLE_COOLDOWN, CONF_KEEP_ALIVE,
                        CONF_PRECISION, CONF_TARGET_STEP,
                    },
                    user_input,
                )
        return self.async_show_form(
            step_id="control",
            data_schema=_control_schema({**self._values(), **(user_input or {})}, self._fahrenheit()),
            errors=errors,
        )

    async def async_step_button(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit the event button and the press event names."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_button(user_input)
            if not errors:
                return self._save(
                    {CONF_BUTTON_EVENT, CONF_SHORT_PRESS, CONF_LONG_PRESS}, user_input
                )
        return self.async_show_form(
            step_id="button",
            data_schema=_button_schema({**self._values(), **(user_input or {})}),
            errors=errors,
        )
