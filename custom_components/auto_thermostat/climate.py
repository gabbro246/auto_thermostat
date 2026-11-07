"""Climate entity for Auto Thermostat."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    RestoreClimate,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

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
    DEFAULT_LONG_PRESS,
    DEFAULT_SHORT_PRESS,
    DOMAIN,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_HOME,
    PRESET_NONE,
    PRESET_SLEEP,
)
from .logic import average_temperature, classify_press, occupancy, settings, should_run

_LOGGER = logging.getLogger(__name__)


def _seconds(value: Any) -> timedelta:
    """Convert a UI-configured number of seconds to a duration."""
    return timedelta(seconds=max(0, float(value or 0)))


def _from_iso(value: object) -> datetime | None:
    """Read an aware UTC datetime saved in HA state attributes."""
    if not isinstance(value, str):
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one standard climate entity per thermostat entry."""
    async_add_entities([AutoThermostat(hass, entry)])


class AutoThermostat(RestoreClimate):
    """Switch-backed thermostat with averaged sensing and timed boost."""

    _attr_should_poll = False
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_preset_modes = [PRESET_NONE, PRESET_HOME, PRESET_AWAY, PRESET_SLEEP, PRESET_BOOST]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize values. Live state and timers are established when added."""
        self.hass = hass
        self._entry = entry
        values = settings(entry.data, entry.options)
        self._settings = values
        self._attr_name = values[CONF_NAME]
        self._attr_unique_id = entry.entry_id
        self._attr_native_temperature_unit = hass.config.units.temperature_unit
        self._heater = values[CONF_HEATER]
        self._sensors: list[str] = list(values[CONF_TEMP_SENSORS])
        self._persons: list[str] = list(values.get(CONF_PERSONS) or [])
        self._button: str | None = values.get(CONF_BUTTON_EVENT)
        self._short_press = str(values.get(CONF_SHORT_PRESS, DEFAULT_SHORT_PRESS)).strip()
        self._long_press = str(values.get(CONF_LONG_PRESS, DEFAULT_LONG_PRESS)).strip()
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        initial_mode = values.get(CONF_INITIAL_HVAC_MODE, HVACMode.HEAT)
        self._hvac_mode = (
            HVACMode(initial_mode)
            if initial_mode in (HVACMode.HEAT, HVACMode.OFF)
            else HVACMode.OFF
        )

        self._min_temp = float(values[CONF_MIN_TEMP])
        self._max_temp = float(values[CONF_MAX_TEMP])
        self._cold_tolerance = float(values[CONF_COLD_TOLERANCE])
        self._hot_tolerance = float(values[CONF_HOT_TOLERANCE])
        self._min_cycle = _seconds(values.get(CONF_MIN_CYCLE, 0))
        self._max_cycle = _seconds(values.get(CONF_MAX_CYCLE, 0))
        self._cooldown = _seconds(values.get(CONF_CYCLE_COOLDOWN, 0))
        self._keep_alive = _seconds(values.get(CONF_KEEP_ALIVE, 0))
        self._precision = float(values[CONF_PRECISION])
        self._step = float(values[CONF_TARGET_STEP])
        self._boost_duration = timedelta(minutes=float(values[CONF_BOOST_DURATION]))
        self._presets = {
            PRESET_HOME: float(values[CONF_HOME_TEMP]),
            PRESET_AWAY: float(values[CONF_AWAY_TEMP]),
            PRESET_SLEEP: float(values[CONF_SLEEP_TEMP]),
        }
        self._manual_target = float(values[CONF_TARGET_TEMP])
        self._target = self._presets[PRESET_HOME]
        self._attr_preset_mode = PRESET_HOME
        self._auto_presence = True
        self._occupied: bool | None = None
        self._cur_temp: float | None = None
        self._valid_sensors = 0

        self._boost_until: datetime | None = None
        self._boost_previous_preset = PRESET_HOME
        self._boost_previous_hvac = HVACMode.HEAT
        self._last_transition: datetime | None = None
        self._max_cycle_blocked = False
        self._lock = asyncio.Lock()
        self._unsub_recheck: Any = None
        self._unsub_max: Any = None
        self._unsub_boost: Any = None
        self._recheck_at: datetime | None = None
        self._max_cycle_at: datetime | None = None

    @property
    def device_info(self) -> dict[str, Any]:
        """Group the thermostat under its own device in Home Assistant."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": "Auto Thermostat",
            "model": "Virtual thermostat",
        }

    @property
    def native_current_temperature(self) -> float | None:
        return self._cur_temp

    @property
    def native_target_temperature(self) -> float | None:
        return self._target

    @property
    def hvac_mode(self) -> HVACMode:
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._is_heater_on():
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def min_temp(self) -> float:
        return self._min_temp

    @property
    def max_temp(self) -> float:
        return self._max_temp

    @property
    def precision(self) -> float:
        return self._precision

    @property
    def target_temperature_step(self) -> float:
        return self._step

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the inputs and boost end time without replacing climate attributes."""
        return {
            "temperature_sensors": self._sensors,
            "valid_temperature_sensors": self._valid_sensors,
            "persons": self._persons,
            "anyone_home": self._occupied,
            "presence_automatic": self._auto_presence,
            "boost_ends_at": self._boost_until.isoformat() if self._boost_until else None,
            "boost_previous_preset": self._boost_previous_preset,
            "boost_previous_hvac": self._boost_previous_hvac.value,
            "manual_target": self._manual_target,
        }

    async def async_added_to_hass(self) -> None:
        """Restore selections, listen for changes and resume active boost timers."""
        await super().async_added_to_hass()
        old = await self.async_get_last_state()
        if old is not None:
            if old.state in self._attr_hvac_modes:
                self._hvac_mode = HVACMode(old.state)
            old_auto = old.attributes.get("presence_automatic")
            if isinstance(old_auto, bool):
                self._auto_presence = old_auto
            old_manual = old.attributes.get("manual_target")
            try:
                if old_manual is not None and self.min_temp <= float(old_manual) <= self.max_temp:
                    self._manual_target = float(old_manual)
            except (ValueError, TypeError):
                pass
            saved = old.attributes.get("preset_mode")
            if saved in self._attr_preset_modes:
                self._attr_preset_mode = saved
            self._boost_until = _from_iso(old.attributes.get("boost_ends_at"))
            previous = old.attributes.get("boost_previous_preset")
            if previous in (PRESET_HOME, PRESET_AWAY, PRESET_SLEEP, PRESET_NONE):
                self._boost_previous_preset = previous
            previous_hvac = old.attributes.get("boost_previous_hvac")
            if previous_hvac in self._attr_hvac_modes:
                self._boost_previous_hvac = HVACMode(previous_hvac)
            if saved == PRESET_NONE:
                climate = await self.async_get_last_climate_data(validate_range=True)
                if climate and climate.native_target_temperature is not None:
                    self._manual_target = float(climate.native_target_temperature)
        if self._attr_preset_mode == PRESET_BOOST and self._boost_until is None:
            self._attr_preset_mode = self._boost_previous_preset
        if self._boost_until:
            if self._boost_until <= dt_util.utcnow():
                self._finish_boost()
            else:
                self._attr_preset_mode = PRESET_BOOST
                self._schedule_boost()

        watched = [*self._sensors, *self._persons, self._heater]
        if self._button:
            watched.append(self._button)
        self.async_on_remove(
            async_track_state_change_event(self.hass, watched, self._async_state_changed)
        )
        self.async_on_remove(self._cancel_timers)
        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(self.hass, self._async_keep_alive, self._keep_alive)
            )
        self._refresh_inputs()
        heater_state = self.hass.states.get(self._heater)
        if heater_state and heater_state.state in ("on", "off"):
            self._last_transition = heater_state.last_changed
        self._apply_normal_preset()
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _refresh_inputs(self) -> None:
        """Average available numeric sensors in the configured temperature unit."""
        temperatures: list[float] = []
        for entity_id in self._sensors:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            reading = average_temperature([state.state])
            if reading is None:
                continue
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if unit not in (
                UnitOfTemperature.CELSIUS,
                UnitOfTemperature.FAHRENHEIT,
                UnitOfTemperature.KELVIN,
            ):
                continue
            try:
                reading = TemperatureConverter.convert(
                    reading, unit, self._attr_native_temperature_unit
                )
            except (ValueError, TypeError):
                continue
            temperatures.append(reading)
        self._valid_sensors = len(temperatures)
        self._cur_temp = average_temperature(temperatures)
        self._occupied = occupancy(
            self.hass.states.get(person).state if self.hass.states.get(person) else None
            for person in self._persons
        )

    @callback
    def _apply_normal_preset(self) -> None:
        """Follow presence only outside Sleep, manual temperature and Boost."""
        if self._attr_preset_mode == PRESET_BOOST:
            return
        if self._auto_presence and self._occupied is not None:
            self._attr_preset_mode = PRESET_HOME if self._occupied else PRESET_AWAY
        if self._attr_preset_mode == PRESET_NONE:
            self._target = self._manual_target
        else:
            self._target = self._presets.get(self._attr_preset_mode, self._manual_target)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Schedule state-driven updates without blocking the event bus."""
        entity_id = event.data["entity_id"]
        old: State | None = event.data["old_state"]
        new: State | None = event.data["new_state"]
        if entity_id == self._button:
            # Event entities keep a timestamp in state and an event_type attribute.
            # Ignore the restored previous event when first added to HA.
            if new is None or old is None or new.state == old.state:
                return
            press = classify_press(
                new.attributes.get("event_type"), self._short_press, self._long_press
            )
            if press == "boost":
                self.hass.async_create_task(self._async_start_boost())
            elif press == "cancel":
                self.hass.async_create_task(self._async_stop_boost())
            return
        if entity_id == self._heater and new is not None:
            if old is not None and old.state != new.state and new.state in ("on", "off"):
                self._last_transition = new.last_changed
                if new.state == "off":
                    self._cancel_max_timer()
                elif self._max_cycle:
                    self._schedule_max_timer()
        if entity_id in self._sensors or entity_id in self._persons:
            if self._boost_until is None:
                self._max_cycle_blocked = False
            self._refresh_inputs()
            self._apply_normal_preset()
        self.hass.async_create_task(self._async_control())
        self.async_write_ha_state()

    def _is_heater_on(self) -> bool:
        return self.hass.states.is_state(self._heater, STATE_ON)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Use the standard climate service for turning the device on or off."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")
        if hvac_mode == HVACMode.OFF and self._boost_until:
            self._finish_boost()
        self._hvac_mode = HVACMode(hvac_mode)
        self._max_cycle_blocked = False
        await self._async_control(force_off=True)
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """A manually chosen temperature uses the standard 'none' preset."""
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is not None:
            temperature = float(value)
            if not self.min_temp <= temperature <= self.max_temp:
                raise ValueError("Temperature is outside configured limits")
            if self._boost_until:
                self._finish_boost()
            self._manual_target = temperature
            self._max_cycle_blocked = False
            self._auto_presence = False
            self._attr_preset_mode = PRESET_NONE
            self._apply_normal_preset()
        if kwargs.get(ATTR_HVAC_MODE) is not None:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])
        else:
            await self._async_control()
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch to Home, Away, Sleep, a manual setpoint or timed Boost."""
        if preset_mode not in self._attr_preset_modes:
            raise ValueError(f"Unsupported preset: {preset_mode}")
        if preset_mode == PRESET_BOOST:
            await self._async_start_boost()
            return
        if self._boost_until:
            self._finish_boost()
        self._attr_preset_mode = preset_mode
        self._max_cycle_blocked = False
        self._auto_presence = preset_mode in (PRESET_HOME, PRESET_AWAY)
        if preset_mode in (PRESET_HOME, PRESET_AWAY):
            # Honor the selected preset now. Changes to person entities resume auto selection.
            self._target = self._presets[preset_mode]
        else:
            self._apply_normal_preset()
        await self._async_control()
        self.async_write_ha_state()

    async def _async_start_boost(self) -> None:
        """Force the controlled switch on for the configured duration."""
        if self._boost_until is None:
            self._boost_previous_preset = self._attr_preset_mode
            self._boost_previous_hvac = self._hvac_mode
        self._boost_until = dt_util.utcnow() + self._boost_duration
        self._attr_preset_mode = PRESET_BOOST
        self._hvac_mode = HVACMode.HEAT
        self._max_cycle_blocked = False
        self._schedule_boost()
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _finish_boost(self) -> None:
        """Restore exactly the preset and HVAC mode that preceded Boost."""
        self._cancel_boost_timer()
        if self._boost_until is None:
            return
        self._boost_until = None
        self._max_cycle_blocked = False
        self._attr_preset_mode = self._boost_previous_preset
        self._hvac_mode = self._boost_previous_hvac
        self._apply_normal_preset()

    async def _async_stop_boost(self) -> None:
        """End Boost early, including from a long button press."""
        if self._boost_until is None:
            return
        self._finish_boost()
        await self._async_control(force_off=self._hvac_mode == HVACMode.OFF)
        self.async_write_ha_state()

    @callback
    def _schedule_boost(self) -> None:
        self._cancel_boost_timer()
        if self._boost_until:
            self._unsub_boost = async_track_point_in_time(
                self.hass, self._async_boost_expired, self._boost_until
            )

    async def _async_boost_expired(self, _: datetime) -> None:
        self._unsub_boost = None
        await self._async_stop_boost()

    async def _async_keep_alive(self, _: datetime) -> None:
        await self._async_control(keepalive=True)

    async def _async_recheck(self, _: datetime) -> None:
        self._unsub_recheck = None
        self._recheck_at = None
        await self._async_control()

    async def _async_max_reached(self, _: datetime) -> None:
        self._unsub_max = None
        self._max_cycle_at = None
        # Do not immediately restart the heater after reaching its safety cap.
        self._max_cycle_blocked = True
        await self._async_control(force_off=True)
        self.async_write_ha_state()

    @callback
    def _schedule_recheck(self, when: datetime) -> None:
        if self._recheck_at is not None and self._recheck_at <= when:
            return
        self._cancel_recheck()
        self._recheck_at = when
        self._unsub_recheck = async_track_point_in_time(self.hass, self._async_recheck, when)

    @callback
    def _schedule_max_timer(self) -> None:
        if not self._max_cycle or not self._is_heater_on():
            self._cancel_max_timer()
            return
        now = dt_util.utcnow()
        start = self._last_transition or now
        deadline = max(now, start + self._max_cycle)
        if self._max_cycle_at == deadline:
            return
        self._cancel_max_timer()
        self._max_cycle_at = deadline
        self._unsub_max = async_track_point_in_time(
            self.hass, self._async_max_reached, deadline
        )

    @callback
    def _cancel_boost_timer(self) -> None:
        if self._unsub_boost:
            self._unsub_boost()
            self._unsub_boost = None

    @callback
    def _cancel_recheck(self) -> None:
        if self._unsub_recheck:
            self._unsub_recheck()
            self._unsub_recheck = None
        self._recheck_at = None

    @callback
    def _cancel_max_timer(self) -> None:
        if self._unsub_max:
            self._unsub_max()
            self._unsub_max = None
        self._max_cycle_at = None

    @callback
    def _cancel_timers(self) -> None:
        self._cancel_boost_timer()
        self._cancel_recheck()
        self._cancel_max_timer()

    async def _async_set_heater(self, turn_on: bool, *, keepalive: bool = False) -> None:
        """Call the heater with a child context to identify our own changes."""
        context = Context(parent_id=self._context.id if self._context else None)
        await self.hass.services.async_call(
            "homeassistant",
            "turn_on" if turn_on else "turn_off",
            {"entity_id": self._heater},
            blocking=True,
            context=context,
        )
        if not keepalive:
            self._last_transition = dt_util.utcnow()
            self._cancel_recheck()
            if turn_on:
                self._schedule_max_timer()
            else:
                self._cancel_max_timer()

    async def _async_control(self, *, keepalive: bool = False, force_off: bool = False) -> None:
        """Reconcile the heater with hysteresis, cycle timers and active Boost."""
        async with self._lock:
            switch = self.hass.states.get(self._heater)
            if switch is None or switch.state not in ("on", "off"):
                return
            is_on = switch.state == "on"
            now = dt_util.utcnow()
            if self._last_transition is None:
                self._last_transition = switch.last_changed
            if self._hvac_mode == HVACMode.OFF:
                desired = False
            elif self._boost_until:
                desired = True
            else:
                desired = should_run(
                    current=self._cur_temp,
                    target=self._target,
                    active=is_on,
                    cold_tolerance=self._cold_tolerance,
                    hot_tolerance=self._hot_tolerance,
                )
                # No valid sensors: stop heating rather than run blind.
                if desired is None:
                    desired = False
                    force_off = True
            if not desired:
                self._max_cycle_blocked = False
            if self._max_cycle_blocked:
                desired = False
                force_off = True

            if is_on and self._max_cycle:
                if self._last_transition + self._max_cycle <= now:
                    self._max_cycle_blocked = True
                    desired = False
                    force_off = True
                elif self._unsub_max is None:
                    self._schedule_max_timer()
            if desired == is_on:
                self._cancel_recheck()
                if keepalive and self._hvac_mode != HVACMode.OFF:
                    await self._async_set_heater(desired, keepalive=True)
                return
            if desired:
                deadline = self._last_transition + self._cooldown
                if deadline > now:
                    self._schedule_recheck(deadline)
                    return
            elif is_on and not force_off:
                deadline = self._last_transition + self._min_cycle
                if deadline > now:
                    self._schedule_recheck(deadline)
                    return
            self._cancel_recheck()
            await self._async_set_heater(desired)
            self.async_write_ha_state()
