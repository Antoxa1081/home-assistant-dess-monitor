"""Tests for the pure helper functions in api/helpers.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dess_monitor.api import helpers
from custom_components.dess_monitor.api.helpers import (
    get_inverter_output_priority,
    get_sensor_value_simple,
    get_sensor_value_simple_entry,
    resolve_param,
    safe_float,
    safe_int,
    set_inverter_output_priority,
)

# ---------------------------------------------------------------------------
# resolve_param
# ---------------------------------------------------------------------------

class TestResolveParam:
    def test_simple_dict_match(self):
        data = {"id": "x", "val": "42"}
        assert resolve_param(data, {"id": "x"}) == data

    def test_nested_match(self):
        data = {"outer": {"items": [{"id": "a"}, {"id": "b", "val": "9"}]}}
        assert resolve_param(data, {"id": "b"}) == {"id": "b", "val": "9"}

    def test_no_match_returns_default(self):
        assert resolve_param({"id": "x"}, {"id": "z"}, default="NOPE") == "NOPE"

    def test_default_is_none(self):
        assert resolve_param({"id": "x"}, {"id": "z"}) is None

    def test_case_insensitive(self):
        data = {"id": "AbC", "val": "1"}
        assert resolve_param(data, {"id": "abc"}, case_insensitive=True) == data

    def test_case_sensitive_by_default(self):
        data = {"id": "AbC"}
        assert resolve_param(data, {"id": "abc"}) is None

    def test_and_mode_requires_all_keys(self):
        data = {"id": "x", "type": "y"}
        assert resolve_param(data, {"id": "x", "type": "y"}) == data
        assert resolve_param(data, {"id": "x", "type": "WRONG"}) is None

    def test_or_mode_with_list(self):
        data = {"id": "b"}
        assert resolve_param(data, [{"id": "a"}, {"id": "b"}]) == data

    def test_or_mode_no_match(self):
        data = {"id": "c"}
        assert resolve_param(data, [{"id": "a"}, {"id": "b"}]) is None

    def test_find_all_returns_list(self):
        data = {"items": [{"id": "x", "n": 1}, {"id": "x", "n": 2}]}
        result = resolve_param(data, {"id": "x"}, find_all=True)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_find_all_no_match_returns_default(self):
        assert resolve_param({"id": "y"}, {"id": "x"}, find_all=True, default=[]) == []

    def test_root_keys_scopes_search(self):
        data = {
            "good": [{"id": "target", "val": "1"}],
            "bad": [{"id": "target", "val": "2"}],
        }
        result = resolve_param(data, {"id": "target"}, root_keys=["bad"])
        assert result == {"id": "target", "val": "2"}

    def test_missing_key_in_condition_no_match(self):
        assert resolve_param({"val": "1"}, {"id": "x"}) is None


# ---------------------------------------------------------------------------
# safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    @pytest.mark.parametrize("value,expected", [
        ("12.5", 12.5),
        (3, 3.0),
        (3.7, 3.7),
        ("  4.2  ", 4.2),
        ("-1.5", -1.5),
    ])
    def test_valid(self, value, expected):
        assert safe_float(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", [
        None, "", "-", "--", "----", "n/a", "N/A", "na", "none", "null", "nan", "NaN",
    ])
    def test_sentinel_returns_default(self, value):
        assert safe_float(value) == 0.0

    def test_custom_default(self):
        assert safe_float(None, default=None) is None
        assert safe_float("garbage", default=-1.0) == -1.0

    def test_unparseable_string(self):
        assert safe_float("abc") == 0.0


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    @pytest.mark.parametrize("value,expected", [
        ("5", 5),
        (5.9, 5),       # truncates toward zero
        ("5.9", 5),
        (-3.9, -3),
        ("10", 10),
    ])
    def test_valid(self, value, expected):
        assert safe_int(value) == expected

    def test_default_is_none(self):
        assert safe_int(None) is None
        assert safe_int("garbage") is None

    def test_custom_default(self):
        assert safe_int("", default=0) == 0
        assert safe_int("n/a", default=-1) == -1


# ---------------------------------------------------------------------------
# get_sensor_value_simple / _entry
# ---------------------------------------------------------------------------

class TestGetSensorValueSimple:
    def test_id_match(self):
        # battery_voltage maps to keys including "bt_battery_voltage".
        data = {"params": [{"id": "bt_battery_voltage", "val": "27.0"}]}
        assert get_sensor_value_simple("battery_voltage", data, {}) == "27.0"

    def test_par_match_with_nonzero_status(self):
        data = {"params": [{"par": "bt_battery_voltage", "val": "27.0", "status": 1}]}
        assert get_sensor_value_simple("battery_voltage", data, {}) == "27.0"

    def test_par_match_status_zero_skipped(self):
        # status == 0 -> the par branch does not return, falls through to None.
        data = {"params": [{"par": "bt_battery_voltage", "val": "27.0", "status": 0}]}
        assert get_sensor_value_simple("battery_voltage", data, {}) is None

    def test_unknown_sensor_name_returns_none(self):
        assert get_sensor_value_simple("does_not_exist", {"x": 1}, {}) is None

    def test_no_match_returns_none(self):
        data = {"params": [{"id": "unrelated", "val": "1"}]}
        assert get_sensor_value_simple("battery_voltage", data, {}) is None

    def test_case_insensitive_key_match(self):
        data = {"params": [{"id": "BT_BATTERY_VOLTAGE", "val": "27.0"}]}
        assert get_sensor_value_simple("battery_voltage", data, {}) == "27.0"


class TestGetSensorValueSimpleEntry:
    def test_id_entry(self):
        data = {"params": [{"id": "bt_battery_voltage", "val": "27.0", "unit": "V"}]}
        assert get_sensor_value_simple_entry("battery_voltage", data, {}) == (
            "bt_battery_voltage", "27.0", "V",
        )

    def test_id_entry_without_unit(self):
        data = {"params": [{"id": "bt_battery_voltage", "val": "27.0"}]}
        assert get_sensor_value_simple_entry("battery_voltage", data, {}) == (
            "bt_battery_voltage", "27.0", None,
        )

    def test_par_entry_nonzero_status(self):
        data = {"params": [{"par": "bt_battery_voltage", "val": "27.0", "status": 5, "unit": "V"}]}
        assert get_sensor_value_simple_entry("battery_voltage", data, {}) == (
            "bt_battery_voltage", "27.0", "V",
        )

    def test_par_entry_status_zero_returns_none(self):
        data = {"params": [{"par": "bt_battery_voltage", "val": "27.0", "status": 0}]}
        assert get_sensor_value_simple_entry("battery_voltage", data, {}) is None

    def test_no_match_returns_none(self):
        assert get_sensor_value_simple_entry("battery_voltage", {}, {}) is None


# ---------------------------------------------------------------------------
# Async control helpers (AsyncMock client)
# ---------------------------------------------------------------------------

class TestAsyncControlHelpers:
    async def test_set_output_priority_known_devcode(self, monkeypatch):
        client = MagicMock()
        client.control.set_param = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(helpers.DeviceIdentity, "from_dict", staticmethod(lambda d: d))

        device = {"devcode": 2341}
        result = await set_inverter_output_priority(client, device, "SBU")
        assert result == {"ok": True}
        # devcode 2341 maps SBU -> '2' on param 'los_output_source_priority'.
        client.control.set_param.assert_awaited_once_with(
            device, "los_output_source_priority", "2",
        )

    async def test_set_output_priority_unknown_devcode(self):
        client = MagicMock()
        client.control.set_param = AsyncMock()
        result = await set_inverter_output_priority(client, {"devcode": 9999}, "SBU")
        assert result is None
        client.control.set_param.assert_not_awaited()

    async def test_set_output_priority_unknown_value(self):
        client = MagicMock()
        client.control.set_param = AsyncMock()
        result = await set_inverter_output_priority(client, {"devcode": 2341}, "BOGUS")
        assert result is None
        client.control.set_param.assert_not_awaited()

    async def test_get_output_priority_maps_value(self, monkeypatch):
        client = MagicMock()
        client.control.get_value = AsyncMock(return_value={"val": "Solar first"})
        monkeypatch.setattr(helpers.DeviceIdentity, "from_dict", staticmethod(lambda d: d))

        result = await get_inverter_output_priority(client, {"devcode": 2341})
        assert result == "Solar"

    async def test_get_output_priority_unknown_devcode(self):
        client = MagicMock()
        result = await get_inverter_output_priority(client, {"devcode": 9999})
        assert result is None

    async def test_get_output_priority_unknown_value(self, monkeypatch):
        client = MagicMock()
        client.control.get_value = AsyncMock(return_value={"val": "WeirdMode"})
        monkeypatch.setattr(helpers.DeviceIdentity, "from_dict", staticmethod(lambda d: d))
        result = await get_inverter_output_priority(client, {"devcode": 2341})
        assert result is None
