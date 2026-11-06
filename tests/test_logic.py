"""Tests that do not require a running Home Assistant installation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components/auto_thermostat/logic.py"
spec = importlib.util.spec_from_file_location("auto_thermostat_logic", MODULE)
assert spec and spec.loader
logic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logic)


class TestTemperature(unittest.TestCase):
    def test_average(self) -> None:
        self.assertAlmostEqual(logic.average_temperature([18, 20, "22"]), 20)

    def test_ignore_invalid_and_missing(self) -> None:
        self.assertEqual(
            logic.average_temperature(["unknown", None, "nan", "inf", True, 19]),
            19,
        )
        self.assertIsNone(logic.average_temperature(["unknown", None, "nan"]))


class TestPresence(unittest.TestCase):
    def test_anyone_home(self) -> None:
        self.assertTrue(logic.occupancy(["home", "not_home", "unknown"]))

    def test_everyone_away(self) -> None:
        self.assertFalse(logic.occupancy(["not_home", "work", "school"]))

    def test_unknown_does_not_mark_away(self) -> None:
        self.assertIsNone(logic.occupancy(["not_home", "unavailable"]))

    def test_no_persons_stays_home(self) -> None:
        self.assertTrue(logic.occupancy([]))


class TestHysteresis(unittest.TestCase):
    def test_heating_switch_on_and_off(self) -> None:
        def heat(current: float | None, active: bool) -> bool | None:
            return logic.should_run(
                current=current, target=20, active=active, cooling=False,
                cold_tolerance=0.3, hot_tolerance=0.3,
            )

        self.assertTrue(heat(19, False))
        self.assertFalse(heat(19.9, False))
        self.assertTrue(heat(20.1, True))
        self.assertFalse(heat(20.3, True))
        self.assertIsNone(heat(None, False))

    def test_cooling_switch_on_and_off(self) -> None:
        def cool(current: float, active: bool) -> bool | None:
            return logic.should_run(
                current=current, target=20, active=active, cooling=True,
                cold_tolerance=0.3, hot_tolerance=0.3,
            )

        self.assertTrue(cool(21, False))
        self.assertFalse(cool(20.1, False))
        self.assertTrue(cool(19.9, True))
        self.assertFalse(cool(19.7, True))


class TestButton(unittest.TestCase):
    def test_short_starts_and_long_cancels(self) -> None:
        self.assertEqual(logic.classify_press("press_end", "press_end", "long_press_end"), "boost")
        self.assertEqual(logic.classify_press("long_press_end", "press_end", "long_press_end"), "cancel")
        self.assertIsNone(logic.classify_press("press_start", "press_end", "long_press_end"))


class TestOptions(unittest.TestCase):
    def test_cleared_values_override_initial_setup(self) -> None:
        options = logic.replace_options(
            {"persons": ["person.old"], "unrelated": "kept"},
            {"name", "persons", "button_event"},
            {"name": "Living room"},
            {"persons": [], "button_event": None},
        )

        self.assertEqual(
            options,
            {
                "name": "Living room",
                "persons": [],
                "button_event": None,
                "unrelated": "kept",
            },
        )
        merged = logic.settings(
            {
                "persons": ["person.initial"],
                "button_event": "event.initial",
            },
            options,
        )
        self.assertEqual(merged["persons"], [])
        self.assertIsNone(merged["button_event"])


if __name__ == "__main__":
    unittest.main()
