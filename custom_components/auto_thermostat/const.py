"""Constants for Auto Thermostat."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "auto_thermostat"
PLATFORMS: Final[list[Platform]] = [Platform.CLIMATE]

CONF_NAME: Final = "name"
CONF_HEATER: Final = "heater"
CONF_TEMP_SENSORS: Final = "temperature_sensors"
CONF_PERSONS: Final = "persons"
CONF_BUTTON_EVENT: Final = "button_event"
CONF_SHORT_PRESS: Final = "short_press"
CONF_LONG_PRESS: Final = "long_press"
CONF_BOOST_DURATION: Final = "boost_duration"
CONF_HOME_TEMP: Final = "home_temp"
CONF_AWAY_TEMP: Final = "away_temp"
CONF_SLEEP_TEMP: Final = "sleep_temp"
CONF_TARGET_TEMP: Final = "target_temp"
CONF_MIN_TEMP: Final = "min_temp"
CONF_MAX_TEMP: Final = "max_temp"
CONF_COLD_TOLERANCE: Final = "cold_tolerance"
CONF_HOT_TOLERANCE: Final = "hot_tolerance"
CONF_MIN_CYCLE: Final = "min_cycle_duration"
CONF_MAX_CYCLE: Final = "max_cycle_duration"
CONF_CYCLE_COOLDOWN: Final = "cycle_cooldown"
CONF_KEEP_ALIVE: Final = "keep_alive"
CONF_PRECISION: Final = "precision"
CONF_TARGET_STEP: Final = "target_temp_step"
CONF_INITIAL_HVAC_MODE: Final = "initial_hvac_mode"
CONF_AC_MODE: Final = "ac_mode"

PRESET_HOME: Final = "home"
PRESET_AWAY: Final = "away"
PRESET_SLEEP: Final = "sleep"
PRESET_BOOST: Final = "boost"
PRESET_NONE: Final = "none"

DEFAULT_BOOST_DURATION: Final = 20
DEFAULT_SHORT_PRESS: Final = "press_end"
DEFAULT_LONG_PRESS: Final = "long_press_end"
DEFAULT_TOLERANCE: Final = 0.3
