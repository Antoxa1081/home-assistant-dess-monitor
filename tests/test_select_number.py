"""Tests for ``custom_components.dess_monitor.select`` and ``number``.

Covers option lists, current_option / native_value, hint parsing helpers, and
the async set methods with a mocked client. Entities are constructed with a
``MagicMock`` coordinator exposing ``.data``, ``.config_entry.options`` and an
``AsyncMock`` ``.client``; the async set methods are awaited directly.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.dess_monitor.const import (
    BATTERY_CHEMISTRIES,
    DEFAULT_BATTERY_CHEMISTRY,
    DEFAULT_DYNAMIC_SETTINGS_INTERVAL,
)
from custom_components.dess_monitor.number import (
    InverterDynamicSettingNumber,
    VirtualBatteryCapacityNumber,
    VirtualBatteryVoltageFullNumber,
    _parse_hint,
    _rescale_voltage_hint,
    _resolve_unit,
)
from custom_components.dess_monitor.select import (
    InverterDynamicSettingSelect,
    InverterOutputPrioritySelect,
    VirtualBatteryChemistrySelect,
)


def _make_item(inverter_id="PN1", devcode=2376, virtual_battery=None, resolve_map=None):
    resolve_map = resolve_map or {}
    hub = SimpleNamespace(online=True)
    item = SimpleNamespace(
        inverter_id=inverter_id,
        name="Inv 1",
        device_data={"pn": inverter_id, "sn": "SN1", "devcode": devcode, "devaddr": 1, "devalias": "Inv 1"},
        firmware_version="0.0.1",
        virtual_battery=virtual_battery,
        online=True,
        hub=hub,
    )
    item.resolve = lambda canonical, data: resolve_map.get(canonical)
    return item


def _make_coordinator(data=None, options=None):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.config_entry = SimpleNamespace(options=options or {})
    coord.client = MagicMock()
    coord.client.control = MagicMock()
    coord.client.control.set_param = AsyncMock(return_value={})
    coord.client.control.get_value = AsyncMock(return_value={})
    coord.device_cache = MagicMock()
    coord.async_request_refresh = AsyncMock()
    return coord


# --- number hint-parsing helpers --------------------------------------------

class TestParseHint:
    def test_single_range_with_unit_suffix(self):
        assert _parse_hint("60.0~66V") == (60.0, 66.0, True)

    def test_integer_range_dash(self):
        assert _parse_hint("1-900") == (1.0, 900.0, False)

    def test_reversed_range_normalised(self):
        lo, hi, _ = _parse_hint("66~60")
        assert (lo, hi) == (60.0, 66.0)

    def test_multi_range_picks_matching_battery(self):
        # rated 48V -> picks the (48V) range.
        assert _parse_hint("25.0~31.5(24V) 48.0~61.0(48V)", 48) == (48.0, 61.0, True)

    def test_multi_range_union_when_no_match(self):
        # rated 12V matches neither annotation -> union of ranges.
        lo, hi, _ = _parse_hint("25.0~31.5(24V) 48.0~61.0(48V)", 12)
        assert (lo, hi) == (25.0, 61.0)

    def test_multi_range_union_when_voltage_unknown(self):
        lo, hi, _ = _parse_hint("25.0~31.5(24V) 48.0~61.0(48V)")
        assert (lo, hi) == (25.0, 61.0)

    @pytest.mark.parametrize("bad", [None, "", "no numbers here", 5])
    def test_unparseable_returns_none(self, bad):
        assert _parse_hint(bad) is None


class TestResolveUnit:
    def test_known_units(self):
        from homeassistant.components.number import NumberDeviceClass
        from homeassistant.const import UnitOfElectricPotential
        unit, dc = _resolve_unit("V")
        assert unit == UnitOfElectricPotential.VOLT
        assert dc == NumberDeviceClass.VOLTAGE

    def test_percent_has_no_device_class(self):
        unit, dc = _resolve_unit("%")
        assert dc is None

    def test_unknown_unit_passthrough(self):
        assert _resolve_unit("widgets") == ("widgets", None)

    def test_empty_unit(self):
        assert _resolve_unit(None) == (None, None)
        assert _resolve_unit("") == (None, None)


class TestRescaleVoltageHint:
    def test_no_rescale_when_in_window(self):
        # hi already reaches into operating window of a 48V bank.
        assert _rescale_voltage_hint(48.0, 60.0, 48.0) == (48.0, 60.0)

    def test_rescales_undersized_hint(self):
        # 25~30 sized for a 24V system but bank is 48V -> scale by ~2.
        lo, hi = _rescale_voltage_hint(25.0, 30.0, 48.0)
        assert hi > 30.0
        assert lo == pytest.approx(50.0, abs=1.0)

    def test_no_rated_voltage_passthrough(self):
        assert _rescale_voltage_hint(25.0, 30.0, None) == (25.0, 30.0)


# --- InverterOutputPrioritySelect -------------------------------------------

class TestOutputPrioritySelect:
    def test_options_list(self):
        item = _make_item()
        coord = _make_coordinator(data=None)
        s = InverterOutputPrioritySelect(item, coord)
        assert s._attr_options == ["Utility", "Solar", "SBU", "SUB"]
        assert s._attr_unique_id == "PN1_output_priority"

    def test_initial_option_from_coordinator(self):
        item = _make_item()
        with patch(
            "custom_components.dess_monitor.select.resolve_output_priority",
            return_value="SBU",
        ):
            coord = _make_coordinator(data={"PN1": {"x": 1}})
            s = InverterOutputPrioritySelect(item, coord)
            assert s._attr_current_option == "SBU"

    def test_handle_update_keeps_last_when_no_data(self):
        item = _make_item()
        coord = _make_coordinator(data=None)
        s = InverterOutputPrioritySelect(item, coord)
        s._attr_current_option = "Solar"
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_current_option == "Solar"

    async def test_select_option_calls_setter(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"x": 1}})
        with patch(
            "custom_components.dess_monitor.select.set_inverter_output_priority",
            new=AsyncMock(),
        ) as mock_set:
            s = InverterOutputPrioritySelect(item, coord)
            s.async_write_ha_state = MagicMock()
            await s.async_select_option("Solar")
            mock_set.assert_awaited_once()
            args = mock_set.await_args.args
            assert args[0] is coord.client
            assert args[1] is item.device_data
            assert args[2] == "Solar"
        assert s._attr_current_option == "Solar"
        coord.device_cache.invalidate_output_priority.assert_called_once_with("PN1")
        coord.async_request_refresh.assert_awaited_once()

    async def test_select_option_ignores_invalid(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"x": 1}})
        with patch(
            "custom_components.dess_monitor.select.set_inverter_output_priority",
            new=AsyncMock(),
        ) as mock_set:
            s = InverterOutputPrioritySelect(item, coord)
            await s.async_select_option("Bogus")
            mock_set.assert_not_awaited()


# --- InverterDynamicSettingSelect -------------------------------------------

class TestDynamicSettingSelect:
    def _field(self, with_unit=False):
        field = {
            "id": "los_charge_priority",
            "name": "Charge Priority",
            "item": [
                {"key": "0", "val": "Utility"},
                {"key": "1", "val": "Solar"},
                {"key": "2", "val": "SBU"},
            ],
        }
        if with_unit:
            field["unit"] = "V"
            field["item"] = [{"key": "0", "val": "12.0V"}, {"key": "1", "val": "24.0V"}]
        return field

    def test_options_from_field(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        assert s._attr_options == ["Utility", "Solar", "SBU"]
        assert s._attr_options_keys == ["0", "1", "2"]
        assert s._attr_unique_id == "PN1_settings_los_charge_priority"
        assert s._poll_interval == DEFAULT_DYNAMIC_SETTINGS_INTERVAL

    def test_options_with_unit_resolved(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field(with_unit=True))
        # resolve_number_with_unit("12.0V") -> 12.0 -> str
        assert s._attr_options == ["12.0", "24.0"]

    def test_native_value_returns_current(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        s._attr_current_option = "SBU"
        assert s.native_value == "SBU"

    def test_available_false_when_disabled_param(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        assert s.available is True
        s._disabled_param = True
        assert s.available is False

    async def test_select_option_calls_set_param(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        s.async_write_ha_state = MagicMock()
        await s.async_select_option("Solar")
        coord.client.control.set_param.assert_awaited_once()
        args = coord.client.control.set_param.await_args.args
        # (DeviceIdentity, param_id, param_value=key for 'Solar')
        assert args[1] == "los_charge_priority"
        assert args[2] == "1"
        assert s._attr_current_option == "Solar"

    async def test_select_option_invalid_noop(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        await s.async_select_option("Nope")
        coord.client.control.set_param.assert_not_awaited()

    async def test_update_sets_option_from_response(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": "SBU"})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        s.async_write_ha_state = MagicMock()
        s._last_updated = None  # force update
        await s.async_update(force=True)
        assert s._attr_current_option == "SBU"

    async def test_update_error_response_disables_param(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"err": 1})
        s = InverterDynamicSettingSelect(item, coord, self._field())
        s.async_write_ha_state = MagicMock()
        s._last_updated = None
        await s.async_update(force=True)
        assert s._disabled_param is True


# --- VirtualBatteryChemistrySelect ------------------------------------------

class TestChemistrySelect:
    def test_options_and_default(self):
        item = _make_item()
        coord = _make_coordinator()
        s = VirtualBatteryChemistrySelect(item, coord)
        assert s._attr_options == list(BATTERY_CHEMISTRIES)
        assert s._attr_current_option == DEFAULT_BATTERY_CHEMISTRY
        assert s._attr_unique_id == "PN1_virtual_battery_chemistry"

    async def test_select_applies_to_estimator(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryChemistrySelect(item, coord)
        s.async_write_ha_state = MagicMock()
        await s.async_select_option("lead_acid")
        assert s._attr_current_option == "lead_acid"
        estimator.set_chemistry.assert_called_once_with("lead_acid")

    async def test_select_invalid_noop(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryChemistrySelect(item, coord)
        await s.async_select_option("plutonium")
        assert s._attr_current_option == DEFAULT_BATTERY_CHEMISTRY
        estimator.set_chemistry.assert_not_called()


# --- InverterDynamicSettingNumber -------------------------------------------

class TestDynamicSettingNumber:
    def _field(self, hint=None, unit=None):
        field = {"id": "bat_cutoff_voltage", "name": "Cutoff Voltage"}
        if hint is not None:
            field["hint"] = hint
        if unit is not None:
            field["unit"] = unit
        return field

    def test_range_from_hint(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, self._field(hint="40.0~48.0V"))
        assert s._attr_native_min_value == 40.0
        assert s._attr_native_max_value == 48.0
        assert s._attr_native_step == 0.1
        assert s._attr_unique_id == "PN1_settings_bat_cutoff_voltage"

    def test_integer_hint_step_one(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, self._field(hint="1~900", unit="min"))
        assert s._attr_native_step == 1.0
        from homeassistant.const import UnitOfTime
        assert s._attr_native_unit_of_measurement == UnitOfTime.MINUTES

    def test_no_hint_default_range(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, self._field(unit="W"))
        assert s._attr_native_min_value == 0.0
        assert s._attr_native_max_value == 1000.0

    def test_range_packed_in_unit(self):
        # Some firmwares pack the range into 'unit' instead of 'hint'.
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, self._field(unit="25.0~31.5(24V) 48.0~61.0(48V)"), )
        # Treated as voltage when unit was used as a multi-range hint.
        from homeassistant.const import UnitOfElectricPotential
        assert s._attr_native_unit_of_measurement == UnitOfElectricPotential.VOLT

    async def test_set_value_calls_set_param(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, self._field(hint="40.0~48.0V"))
        s.async_write_ha_state = MagicMock()
        await s.async_set_native_value(45.0)
        coord.client.control.set_param.assert_awaited_once()
        args = coord.client.control.set_param.await_args.args
        assert args[1] == "bat_cutoff_voltage"
        assert args[2] == "45.0"
        assert s._attr_native_value == "45.0"

    async def test_update_sets_value_from_response(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": "44.5V"})
        s = InverterDynamicSettingNumber(item, coord, self._field(hint="40.0~48.0V"))
        s.async_write_ha_state = MagicMock()
        s._last_updated = None
        await s.async_update()
        assert s._attr_native_value == 44.5

    async def test_update_throttled_skips(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": "44.5"})
        s = InverterDynamicSettingNumber(item, coord, self._field(hint="40.0~48.0V"))
        import time
        s._last_updated = int(time.time())  # just polled -> throttled
        await s.async_update()
        coord.client.control.get_value.assert_not_awaited()


# --- Virtual battery numbers -------------------------------------------------

class TestVirtualBatteryNumbers:
    def test_capacity_defaults(self):
        item = _make_item()
        coord = _make_coordinator()
        s = VirtualBatteryCapacityNumber(item, coord)
        assert s._attr_unique_id == "PN1_virtual_battery_capacity_ah"
        assert s._attr_native_unit_of_measurement == "Ah"

    def test_voltage_full_defaults(self):
        item = _make_item()
        coord = _make_coordinator()
        s = VirtualBatteryVoltageFullNumber(item, coord)
        assert s._attr_unique_id == "PN1_virtual_battery_voltage_full"

    async def test_capacity_set_applies_to_estimator(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryCapacityNumber(item, coord)
        s.async_write_ha_state = MagicMock()
        await s.async_set_native_value(200.0)
        assert s._attr_native_value == 200.0
        estimator.set_capacity_ah.assert_called_once_with(200.0)

    async def test_voltage_full_set_applies_to_estimator(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryVoltageFullNumber(item, coord)
        s.async_write_ha_state = MagicMock()
        await s.async_set_native_value(57.6)
        assert s._attr_native_value == 57.6
        estimator.set_voltage_full.assert_called_once_with(57.6)

    async def test_set_invalid_value_noop(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryCapacityNumber(item, coord)
        s.async_write_ha_state = MagicMock()
        await s.async_set_native_value("not-a-number")
        estimator.set_capacity_ah.assert_not_called()
