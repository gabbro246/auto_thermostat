"""Small, side-effect-free helpers for Auto Thermostat."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


def average_temperature(values: Iterable[object]) -> float | None:
    """Average finite sensor values, excluding missing and invalid readings."""
    readings: list[float] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(number):
            readings.append(number)
    return sum(readings) / len(readings) if readings else None


def occupancy(states: Iterable[str | None]) -> bool | None:
    """Return True for anyone home, False for everyone known away, or unknown."""
    values = list(states)
    if not values:
        return True  # No person entities configured: always use Home.
    if "home" in values:
        return True
    if all(value not in (None, "unknown", "unavailable", "") for value in values):
        return False
    return None  # A missing person must not cause a false Away transition.


def should_run(
    *,
    current: float | None,
    target: float | None,
    active: bool,
    cooling: bool,
    cold_tolerance: float,
    hot_tolerance: float,
) -> bool | None:
    """Apply Generic Thermostat's hysteresis (None means missing temperature)."""
    if current is None or target is None:
        return None
    if cooling:
        return (
            current > target + hot_tolerance
            if not active
            else current > target - cold_tolerance
        )
    return (
        current < target - cold_tolerance
        if not active
        else current < target + hot_tolerance
    )


def classify_press(event_type: object, short_press: str, long_press: str) -> str | None:
    """Map a button event to boost/cancel, ignoring unrelated press types."""
    if event_type == long_press:
        return "cancel"
    if event_type == short_press:
        return "boost"
    return None


def settings(entry_data: Mapping, entry_options: Mapping) -> dict:
    """Apply editable options to initial setup values."""
    return {**entry_data, **entry_options}


def replace_options(
    existing: Mapping,
    fields: Iterable[str],
    submitted: Mapping,
    cleared_values: Mapping[str, object],
) -> dict:
    """Replace one options form, retaining explicit values for cleared fields."""
    options = dict(existing)
    for key in fields:
        options.pop(key, None)
        if key not in submitted and key in cleared_values:
            options[key] = cleared_values[key]
    options.update(submitted)
    return options
