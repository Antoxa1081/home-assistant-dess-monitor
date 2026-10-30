"""Tests for the pure helper functions in api/helpers.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dess_monitor.api import helpers
from custom_components.dess_monitor.api.helpers import (
    get_inverter_output_priority,
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

    async def test_set_output_priority_devcode_2449(self, monkeypatch):
        client = MagicMock()
        client.control.set_param = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(helpers.DeviceIdentity, "from_dict", staticmethod(lambda d: d))

        device = {"devcode": 2449}
        await set_inverter_output_priority(client, device, "SBU")
        client.control.set_param.assert_awaited_once_with(
            device, "bse_output_source_priority", "12338",
        )

    async def test_set_output_priority_devcode_2449_has_no_sub(self):
        client = MagicMock()
        client.control.set_param = AsyncMock()
        result = await set_inverter_output_priority(client, {"devcode": 2449}, "SUB")
        assert result is None
        client.control.set_param.assert_not_awaited()

    @pytest.mark.parametrize(
        "label,expected",
        [("Utility Solar Bat", "Utility"), ("Solar Utility Bat", "Solar"), ("Solar Bat Utility", "SBU")],
    )
    async def test_get_output_priority_devcode_2449(self, monkeypatch, label, expected):
        client = MagicMock()
        client.control.get_value = AsyncMock(return_value={"val": label})
        monkeypatch.setattr(helpers.DeviceIdentity, "from_dict", staticmethod(lambda d: d))
        assert await get_inverter_output_priority(client, {"devcode": 2449}) == expected

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
