"""Exercise climate behavior with a minimal Home Assistant API stub.

These are logic smoke tests, not a substitute for testing in a real HA install.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import IntFlag, StrEnum
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

UTC = timezone.utc
COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/auto_thermostat"


def fake_module(path: str, **values: object) -> ModuleType:
    module = ModuleType(path)
    module.__dict__.update(values)
    return module


class Mode(StrEnum):
    HEAT = "heat"
    OFF = "off"


class Action(StrEnum):
    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"


class Feature(IntFlag):
    TARGET_TEMPERATURE = 1
    PRESET_MODE = 2
    TURN_ON = 4
    TURN_OFF = 8


class Temp(StrEnum):
    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class State:
    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = datetime.now(UTC)


class FakeStates:
    def __init__(self, hass: FakeHass):
        self.hass = hass
        self.values: dict[str, State] = {}

    def get(self, entity: str) -> State | None:
        return self.values.get(entity)

    def is_state(self, entity: str, state: str) -> bool:
        old = self.get(entity)
        return old is not None and old.state == state


class FakeServices:
    def __init__(self, hass: FakeHass) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str]] = []

    async def async_call(self, domain: str, action: str, target: dict, **kwargs) -> None:
        entity = target["entity_id"]
        self.calls.append((entity, action))
        self.hass.change(entity, "on" if action == "turn_on" else "off")


class FakeHass:
    def __init__(self) -> None:
        self.states = FakeStates(self)
        self.services = FakeServices(self)
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit=Temp.CELSIUS))
        self.listeners: list = []
        self.timers: list = []
        self.tasks: list[asyncio.Task] = []

    def async_create_task(self, awaitable):
        task = asyncio.create_task(awaitable)
        self.tasks.append(task)
        return task

    def change(self, entity: str, state: str, attributes: dict | None = None) -> None:
        previous = self.states.get(entity)
        current = State(state, attributes)
        self.states.values[entity] = current
        for watched, handler in list(self.listeners):
            if entity in watched:
                handler(SimpleNamespace(data={
                    "entity_id": entity, "old_state": previous, "new_state": current,
                }))

    async def flush(self) -> None:
        for _ in range(5):
            await asyncio.sleep(0)


class RestoreClimate:
    def __init__(self):
        self._context = None
        self._on_remove: list = []

    async def async_added_to_hass(self) -> None:
        self._context = None

    async def async_get_last_state(self) -> None:
        return None

    async def async_get_last_climate_data(self, **kwargs) -> None:
        return None

    def async_on_remove(self, handler) -> None:
        self._on_remove.append(handler)

    def async_write_ha_state(self) -> None:
        pass


def fake_modules() -> dict[str, ModuleType]:
    root = fake_module("homeassistant")
    root.__path__ = []
    components = fake_module("homeassistant.components")
    components.__path__ = []
    helpers = fake_module("homeassistant.helpers")
    helpers.__path__ = []
    util = fake_module("homeassistant.util")
    util.__path__ = []
    package = fake_module("auto_thermostat")
    package.__path__ = [str(COMPONENT)]

    class Context:
        def __init__(self, parent_id=None):
            self.id = "generated-context"
            self.parent_id = parent_id

    def state_watch(hass, names, cb):
        value = (names, cb)
        hass.listeners.append(value)
        return lambda: hass.listeners.remove(value)

    def timer(hass, callback, time_value):
        value = (callback, time_value)
        hass.timers.append(value)
        return lambda: hass.timers.remove(value) if value in hass.timers else None

    class TemperatureConverter:
        @staticmethod
        def convert(value, source, target):
            if source == target:
                return value
            if source == Temp.CELSIUS and target == Temp.FAHRENHEIT:
                return value * 1.8 + 32
            if source == Temp.FAHRENHEIT and target == Temp.CELSIUS:
                return (value - 32) / 1.8
            raise ValueError("Unsupported conversion in stub")

    dt = fake_module(
        "homeassistant.util.dt",
        utcnow=lambda: datetime.now(UTC),
        parse_datetime=datetime.fromisoformat,
    )
    return {
        "auto_thermostat": package,
        "homeassistant": root,
        "homeassistant.components": components,
        "homeassistant.components.climate": fake_module(
            "homeassistant.components.climate",
            ATTR_HVAC_MODE="hvac_mode", ClimateEntityFeature=Feature,
            HVACAction=Action, HVACMode=Mode, RestoreClimate=RestoreClimate,
        ),
        "homeassistant.config_entries": fake_module(
            "homeassistant.config_entries", ConfigEntry=object,
        ),
        "homeassistant.const": fake_module(
            "homeassistant.const",
            Platform=SimpleNamespace(CLIMATE="climate"),
            ATTR_TEMPERATURE="temperature",
            ATTR_UNIT_OF_MEASUREMENT="unit_of_measurement",
            STATE_ON="on", STATE_UNAVAILABLE="unavailable", STATE_UNKNOWN="unknown",
            UnitOfTemperature=Temp,
        ),
        "homeassistant.core": fake_module(
            "homeassistant.core", Context=Context, Event=object,
            HomeAssistant=object, State=State, callback=lambda f: f,
        ),
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_platform": fake_module(
            "homeassistant.helpers.entity_platform", AddConfigEntryEntitiesCallback=object,
        ),
        "homeassistant.helpers.event": fake_module(
            "homeassistant.helpers.event",
            async_track_point_in_time=timer,
            async_track_state_change_event=state_watch,
            async_track_time_interval=timer,
        ),
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
        "homeassistant.util.unit_conversion": fake_module(
            "homeassistant.util.unit_conversion", TemperatureConverter=TemperatureConverter,
        ),
    }


class TestThermostat(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._patch = patch.dict(sys.modules, fake_modules())
        cls._patch.start()
        cls.climate = importlib.import_module("auto_thermostat.climate")

    @classmethod
    def tearDownClass(cls) -> None:
        for key in list(sys.modules):
            if key.startswith("auto_thermostat"):
                del sys.modules[key]
        cls._patch.stop()

    async def asyncSetUp(self) -> None:
        self.hass = FakeHass()
        self.hass.change("sensor.a", "19", {"unit_of_measurement": "°C"})
        self.hass.change("sensor.b", "21", {"unit_of_measurement": "°C"})
        self.hass.change("person.a", "home")
        self.hass.change("person.b", "not_home")
        self.hass.change("switch.heat", "off")
        self.entry = SimpleNamespace(entry_id="test-id", data={
            "name": "Test", "heater": "switch.heat", "temperature_sensors": ["sensor.a", "sensor.b"],
            "persons": ["person.a", "person.b"], "home_temp": 21,
            "away_temp": 16, "sleep_temp": 18, "target_temp": 20,
            "boost_duration": 20, "min_temp": 7, "max_temp": 35,
            "cold_tolerance": 0.3, "hot_tolerance": 0.3,
            "min_cycle_duration": 0, "max_cycle_duration": 0,
            "cycle_cooldown": 0, "keep_alive": 0,
            "precision": "0.1", "target_temp_step": "0.5",
            "initial_hvac_mode": "heat", "button_event": "event.wall",
        }, options={})
        self.thermostat = self.climate.AutoThermostat(self.hass, self.entry)
        # The HA entity machinery normally initializes these fields.
        self.thermostat._context = None
        self.thermostat._on_remove = []
        await self.thermostat.async_added_to_hass()
        await self.hass.flush()

    async def test_average_and_initial_heat(self) -> None:
        self.assertEqual(self.thermostat.native_current_temperature, 20)
        self.assertEqual(self.thermostat.native_target_temperature, 21)
        self.assertEqual(self.thermostat._attr_hvac_modes, [Mode.HEAT, Mode.OFF])
        self.assertEqual(self.thermostat.hvac_action, Action.HEATING)
        self.assertTrue(self.hass.states.is_state("switch.heat", "on"))

    async def test_unsupported_saved_mode_starts_off(self) -> None:
        entry = SimpleNamespace(
            entry_id="old-entry",
            data={**self.entry.data, "initial_hvac_mode": "unsupported"},
            options={},
        )

        thermostat = self.climate.AutoThermostat(self.hass, entry)

        self.assertEqual(thermostat.hvac_mode, Mode.OFF)

    async def test_presence_switches_to_away(self) -> None:
        self.hass.change("person.a", "not_home")
        await self.hass.flush()
        self.assertEqual(self.thermostat._attr_preset_mode, "away")
        self.assertEqual(self.thermostat.native_target_temperature, 16)
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))

    async def test_sleep_ignores_presence(self) -> None:
        await self.thermostat.async_set_preset_mode("sleep")
        self.hass.change("person.a", "not_home")
        await self.hass.flush()
        self.assertEqual(self.thermostat._attr_preset_mode, "sleep")

    async def test_boost_starts_from_off_and_restores(self) -> None:
        await self.thermostat.async_set_hvac_mode(Mode.OFF)
        await self.thermostat.async_set_preset_mode("boost")
        self.assertEqual(self.thermostat._attr_preset_mode, "boost")
        self.assertTrue(self.hass.states.is_state("switch.heat", "on"))
        self.assertIsNotNone(self.thermostat.extra_state_attributes["boost_ends_at"])
        await self.thermostat._async_stop_boost()
        self.assertEqual(self.thermostat.hvac_mode, Mode.OFF)
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))

    async def test_long_press_cancels_boost(self) -> None:
        self.hass.change("event.wall", "2026-11-06T21:22:00+00:00", {"event_type": "press_start"})
        self.hass.change("event.wall", "2026-11-06T21:22:01+00:00", {"event_type": "press_end"})
        await self.hass.flush()
        self.assertEqual(self.thermostat._attr_preset_mode, "boost")
        self.hass.change("event.wall", "2026-11-06T21:22:02+00:00", {"event_type": "long_press_end"})
        await self.hass.flush()
        self.assertEqual(self.thermostat._attr_preset_mode, "home")


    async def test_boost_runs_without_temperature_readings(self) -> None:
        self.hass.change("sensor.a", "unavailable")
        self.hass.change("sensor.b", "nan")
        await self.hass.flush()
        await self.thermostat.async_set_preset_mode("boost")
        self.assertTrue(self.hass.states.is_state("switch.heat", "on"))

    async def test_max_cycle_stops_boost_early(self) -> None:
        from datetime import timedelta
        self.thermostat._max_cycle = timedelta(minutes=10)
        self.thermostat._schedule_max_timer()
        await self.thermostat._async_max_reached(datetime.now(UTC))
        self.assertEqual(self.thermostat._attr_preset_mode, "home")
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))
        await self.thermostat.async_set_preset_mode("boost")
        await self.thermostat._async_max_reached(datetime.now(UTC))
        self.assertEqual(self.thermostat._attr_preset_mode, "boost")
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))

    async def test_off_overrides_minimum_cycle(self) -> None:
        from datetime import timedelta
        self.thermostat._min_cycle = timedelta(hours=1)
        self.hass.change("sensor.a", "30", {"unit_of_measurement": "°C"})
        self.hass.change("sensor.b", "30", {"unit_of_measurement": "°C"})
        await self.hass.flush()
        self.assertTrue(self.hass.states.is_state("switch.heat", "on"))
        await self.thermostat.async_set_hvac_mode(Mode.OFF)
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))

    async def test_cooldown_can_delay_boost(self) -> None:
        from datetime import timedelta
        await self.thermostat.async_set_hvac_mode(Mode.OFF)
        self.thermostat._cooldown = timedelta(minutes=5)
        await self.thermostat.async_set_preset_mode("boost")
        self.assertEqual(self.thermostat._attr_preset_mode, "boost")
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))
        self.assertIsNotNone(self.thermostat._unsub_recheck)

    async def test_convert_sensor_units_before_averaging(self) -> None:
        self.hass.change("sensor.a", "68", {"unit_of_measurement": "°F"})
        self.hass.change("sensor.b", "22", {"unit_of_measurement": "°C"})
        await self.hass.flush()
        self.assertAlmostEqual(self.thermostat.native_current_temperature, 21)

    async def test_ignore_numeric_non_temperature_sensors(self) -> None:
        self.hass.change("sensor.a", "80", {"unit_of_measurement": "%"})
        self.hass.change("sensor.b", "22", {"unit_of_measurement": "°C"})
        await self.hass.flush()
        self.assertEqual(self.thermostat.native_current_temperature, 22)
        self.assertEqual(
            self.thermostat.extra_state_attributes["valid_temperature_sensors"], 1
        )

        self.hass.change("sensor.b", "200", {"unit_of_measurement": "W"})
        await self.hass.flush()
        self.assertIsNone(self.thermostat.native_current_temperature)
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))

    async def test_invalid_readings_stop_heating(self) -> None:
        self.hass.change("sensor.a", "unavailable")
        self.hass.change("sensor.b", "nan")
        await self.hass.flush()
        self.assertIsNone(self.thermostat.native_current_temperature)
        self.assertTrue(self.hass.states.is_state("switch.heat", "off"))


if __name__ == "__main__":
    unittest.main()
