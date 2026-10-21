"""Structural invariants for SENSOR_KEYS_MAP."""
from __future__ import annotations

import pytest

from custom_components.dess_monitor.api.resolvers.data_keys_map import SENSOR_KEYS_MAP


def test_map_is_non_empty_dict():
    assert isinstance(SENSOR_KEYS_MAP, dict)
    assert len(SENSOR_KEYS_MAP) > 0


@pytest.mark.parametrize("name", list(SENSOR_KEYS_MAP.keys()))
class TestPerEntryInvariants:
    def test_key_is_nonempty_string(self, name):
        assert isinstance(name, str)
        assert name != ""

    def test_value_is_nonempty_list(self, name):
        value = SENSOR_KEYS_MAP[name]
        assert isinstance(value, list)
        assert len(value) > 0

    def test_value_entries_are_nonempty_strings(self, name):
        for entry in SENSOR_KEYS_MAP[name]:
            assert isinstance(entry, str)
            assert entry != ""

    def test_value_entries_are_unique(self, name):
        entries = SENSOR_KEYS_MAP[name]
        assert len(entries) == len(set(entries))


def test_known_sensor_names_present():
    for expected in ("battery_voltage", "pv_power", "grid_frequency", "output_priority"):
        assert expected in SENSOR_KEYS_MAP


def test_battery_voltage_keys():
    assert SENSOR_KEYS_MAP["battery_voltage"] == [
        "bt_battery_voltage",
        "Battery Voltage",
        "eybond_read_24",
    ]
