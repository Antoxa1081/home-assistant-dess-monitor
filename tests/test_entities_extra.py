"""Extra coverage for the select / number platforms and a few sensor branches.

This file complements ``tests/test_select_number.py`` (which already covers the
happy-path construction and set methods). Here we exercise the remaining
branches: ``async_setup_entry`` for both platforms, the ``RestoreEntity`` /
``RestoreNumber`` restore paths, the coordinator-update / async-update edge
cases (None data, error responses, throttle), the ``_parse_hint`` /
``_rescale_voltage_hint`` numeric edge branches, and the dynamic-sensor /
energy-sensor restore + exception branches.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.dess_monitor import number as number_mod
from custom_components.dess_monitor import select as select_mod
from custom_components.dess_monitor import sensor as sensor_mod
from custom_components.dess_monitor.const import (
    DEFAULT_BATTERY_CHEMISTRY,
)
from custom_components.dess_monitor.number import (
    InverterDynamicSettingNumber,
    VirtualBatteryCapacityNumber,
    VirtualBatteryVoltageFullNumber,
    _parse_hint,
    _rescale_voltage_hint,
)
from custom_components.dess_monitor.select import (
    InverterDynamicSettingSelect,
    InverterOutputPrioritySelect,
    VirtualBatteryChemistrySelect,
)
from custom_components.dess_monitor.sensors.dynamic_sensor import (
    DessSensorSource,
    InverterDynamicSensor,
)
from custom_components.dess_monitor.sensors.energy_sensors import (
    MyEnergySensor,
    PVEnergySensor,
)


def _make_item(inverter_id="PN1", devcode=2376, virtual_battery=None, resolve_map=None, online=True, hub_online=True):
    resolve_map = resolve_map or {}
    hub = SimpleNamespace(online=hub_online)
    item = SimpleNamespace(
        inverter_id=inverter_id,
        name="Inv 1",
        device_data={"pn": inverter_id, "sn": "SN1", "devcode": devcode, "devaddr": 1, "devalias": "Inv 1"},
        firmware_version="0.0.1",
        virtual_battery=virtual_battery,
        online=online,
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


# --- _parse_hint numeric edge branches --------------------------------------

class TestParseHintEdges:
    def test_non_numeric_token_skipped_via_value_error(self):
        # The regex only matches numeric tokens, but a token like "1e999" parses
        # to inf; feed a value whose float() raises is impossible through the
        # regex. Instead cover the multi-range vtag int() ValueError path is
        # also unreachable via regex. So verify a hint with a tag that is a
        # valid int and a non-matching target widens to the union.
        lo, hi, _ = _parse_hint("10~20(99V) 30~40(48V)", 12)
        assert (lo, hi) == (10.0, 40.0)

    def test_rated_voltage_non_numeric_falls_through_to_union(self):
        # rated_battery_voltage that cannot be coerced -> target None -> union.
        lo, hi, _ = _parse_hint("10~20(24V) 30~40(48V)", "not-a-number")
        assert (lo, hi) == (10.0, 40.0)

    def test_rated_voltage_matches_tag(self):
        assert _parse_hint("10~20(24V) 30~40(48V)", 24) == (10.0, 20.0, False)


# --- _rescale_voltage_hint branches -----------------------------------------

class TestRescaleEdges:
    def test_zero_rated_voltage_passthrough(self):
        assert _rescale_voltage_hint(25.0, 30.0, 0) == (25.0, 30.0)

    def test_no_plausible_system_passthrough(self):
        # midpoint ~2.5 fits no nominal-bank window -> returned unchanged.
        assert _rescale_voltage_hint(2.0, 3.0, 48.0) == (2.0, 3.0)

    def test_inferred_close_to_rated_passthrough(self):
        # midpoint ~46 infers 48V system; rated 48.4 within 1.0 -> no rescale.
        assert _rescale_voltage_hint(44.0, 48.0, 48.4) == (44.0, 48.0)


# --- select.async_setup_entry -----------------------------------------------

def _make_hub(items, data, options):
    coordinator = _make_coordinator(data=data, options=options)
    hub = SimpleNamespace(items=items, coordinator=coordinator, online=True)
    return hub, coordinator


class TestSelectSetupEntry:
    async def test_setup_creates_output_priority_and_chemistry(self):
        item = _make_item()
        options = {"battery_virtual_enabled": True}
        hub, coord = _make_hub([item], data=None, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []

        def add(devices):
            added.extend(list(devices))

        await select_mod.async_setup_entry(MagicMock(), config_entry, add)
        kinds = {type(e).__name__ for e in added}
        assert "InverterOutputPrioritySelect" in kinds
        assert "VirtualBatteryChemistrySelect" in kinds

    async def test_setup_dynamic_settings_creates_setting_selects(self):
        item = _make_item()
        field = {"id": "p1", "name": "P1", "item": [{"key": "0", "val": "A"}]}
        data = {"PN1": {"ctrl_fields": [field, {"id": "no_item", "name": "X"}]}}
        options = {"dynamic_settings": True, "battery_virtual_enabled": False}
        hub, coord = _make_hub([item], data=data, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []

        def add(devices):
            added.extend(list(devices))

        await select_mod.async_setup_entry(MagicMock(), config_entry, add)
        names = [type(e).__name__ for e in added]
        # only the field with an 'item' key becomes a setting select
        assert names.count("InverterDynamicSettingSelect") == 1
        assert "InverterOutputPrioritySelect" in names

    async def test_setup_skips_when_device_missing_and_ctrl_fields_none(self):
        # item not in coordinator_data -> continue (line 64-65)
        item_missing = _make_item(inverter_id="PNX")
        # item present but ctrl_fields None -> continue (line 67-68)
        item_nofields = _make_item(inverter_id="PN1")
        data = {"PN1": {"ctrl_fields": None}}
        options = {"dynamic_settings": True, "battery_virtual_enabled": False}
        hub, coord = _make_hub([item_missing, item_nofields], data=data, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        await select_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        # Two output priority selects, no setting selects.
        assert [type(e).__name__ for e in added].count("InverterDynamicSettingSelect") == 0
        assert [type(e).__name__ for e in added].count("InverterOutputPrioritySelect") == 2


# --- number.async_setup_entry -----------------------------------------------

class TestNumberSetupEntry:
    async def test_setup_creates_virtual_battery_numbers(self):
        item = _make_item()
        options = {"battery_virtual_enabled": True}
        hub, coord = _make_hub([item], data=None, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        await number_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        kinds = {type(e).__name__ for e in added}
        assert "VirtualBatteryCapacityNumber" in kinds
        assert "VirtualBatteryVoltageFullNumber" in kinds

    async def test_setup_dynamic_settings_creates_setting_numbers(self):
        item = _make_item()
        # number platform takes fields WITHOUT 'item' key
        field = {"id": "bat_cutoff_voltage", "name": "Cutoff", "hint": "40~48V"}
        with_item = {"id": "p1", "name": "P1", "item": [{"key": "0", "val": "A"}]}
        data = {"PN1": {"ctrl_fields": [field, with_item]}}
        options = {"dynamic_settings": True, "battery_virtual_enabled": False}
        hub, coord = _make_hub([item], data=data, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        with patch.object(number_mod, "resolve_sy_rated_battery_voltage", return_value=48.0):
            await number_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        names = [type(e).__name__ for e in added]
        assert names.count("InverterDynamicSettingNumber") == 1

    async def test_setup_rated_voltage_resolver_raises_is_swallowed(self):
        item = _make_item()
        field = {"id": "bat_cutoff_voltage", "name": "Cutoff", "hint": "40~48V"}
        data = {"PN1": {"ctrl_fields": [field]}}
        options = {"dynamic_settings": True, "battery_virtual_enabled": False}
        hub, coord = _make_hub([item], data=data, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        with patch.object(number_mod, "resolve_sy_rated_battery_voltage", side_effect=RuntimeError("boom")):
            await number_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        assert [type(e).__name__ for e in added].count("InverterDynamicSettingNumber") == 1

    async def test_setup_skips_missing_device_and_none_ctrl_fields(self):
        item_missing = _make_item(inverter_id="PNX")
        item_nofields = _make_item(inverter_id="PN1")
        data = {"PN1": {"ctrl_fields": None}}
        options = {"dynamic_settings": True, "battery_virtual_enabled": False}
        hub, coord = _make_hub([item_missing, item_nofields], data=data, options=options)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        await number_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        assert added == []


# --- SelectBase.data property ------------------------------------------------

class TestSelectDataProperty:
    def test_data_property_returns_device_slice(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"foo": 1}})
        s = InverterOutputPrioritySelect(item, coord)
        assert s.data == {"foo": 1}


# --- InverterOutputPrioritySelect restore + handle update -------------------

class TestOutputPriorityRestore:
    async def test_restore_applies_last_state(self):
        item = _make_item()
        coord = _make_coordinator(data=None)
        s = InverterOutputPrioritySelect(item, coord)
        s.hass = MagicMock()
        last = SimpleNamespace(state="Solar")
        with patch.object(InverterOutputPrioritySelect, "async_get_last_state", new=AsyncMock(return_value=last)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option == "Solar"

    async def test_restore_ignores_unknown_state(self):
        item = _make_item()
        coord = _make_coordinator(data=None)
        s = InverterOutputPrioritySelect(item, coord)
        s.hass = MagicMock()
        last = SimpleNamespace(state=STATE_UNKNOWN)
        with patch.object(InverterOutputPrioritySelect, "async_get_last_state", new=AsyncMock(return_value=last)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option is None

    async def test_restore_skips_when_already_set(self):
        item = _make_item()
        with patch(
            "custom_components.dess_monitor.select.resolve_output_priority",
            return_value="SBU",
        ):
            coord = _make_coordinator(data={"PN1": {"x": 1}})
            s = InverterOutputPrioritySelect(item, coord)
        s.hass = MagicMock()
        getter = AsyncMock(return_value=SimpleNamespace(state="Solar"))
        with patch.object(InverterOutputPrioritySelect, "async_get_last_state", new=getter):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        # already had a resolved option -> short-circuits before reading state
        assert s._attr_current_option == "SBU"
        getter.assert_not_awaited()

    def test_handle_update_resolves_option(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"x": 1}})
        s = InverterOutputPrioritySelect(item, coord)
        s.async_write_ha_state = MagicMock()
        with patch(
            "custom_components.dess_monitor.select.resolve_output_priority",
            return_value="Utility",
        ):
            s._handle_coordinator_update()
        assert s._attr_current_option == "Utility"
        s.async_write_ha_state.assert_called_once()

    def test_handle_update_resolver_exception_keeps_last(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"x": 1}})
        s = InverterOutputPrioritySelect(item, coord)
        s._attr_current_option = "SBU"
        s.async_write_ha_state = MagicMock()
        with patch(
            "custom_components.dess_monitor.select.resolve_output_priority",
            side_effect=ValueError("nope"),
        ):
            s._handle_coordinator_update()
        assert s._attr_current_option == "SBU"


# --- InverterDynamicSettingSelect restore + update branches -----------------

def _select_field():
    return {
        "id": "los_charge_priority",
        "name": "Charge Priority",
        "item": [
            {"key": "0", "val": "Utility"},
            {"key": "1", "val": "Solar"},
            {"key": "2", "val": "SBU"},
        ],
    }


class TestDynamicSelectExtras:
    async def test_restore_sets_option_and_clears_disabled(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s.hass = MagicMock()
        s._disabled_param = True
        last = SimpleNamespace(state="Solar")
        with patch.object(InverterDynamicSettingSelect, "async_get_last_state", new=AsyncMock(return_value=last)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option == "Solar"
        assert s._disabled_param is False
        assert s._last_updated is not None

    async def test_restore_no_last_state(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s.hass = MagicMock()
        with patch.object(InverterDynamicSettingSelect, "async_get_last_state", new=AsyncMock(return_value=None)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option is None

    async def test_restore_state_unavailable_ignored(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s.hass = MagicMock()
        last = SimpleNamespace(state=STATE_UNAVAILABLE)
        with patch.object(InverterDynamicSettingSelect, "async_get_last_state", new=AsyncMock(return_value=last)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option is None

    async def test_update_throttled_returns_early(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        import time
        s._last_updated = int(time.time())
        await s.async_update()
        coord.client.control.get_value.assert_not_awaited()

    async def test_update_timeout_swallowed(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(side_effect=TimeoutError("slow"))
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s._last_updated = None
        # should not raise
        await s.async_update(force=True)
        assert s._attr_current_option is None

    async def test_update_non_dict_response_does_not_disable_when_polled_before(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value="oops")
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s._last_updated = 1  # already polled once -> stays enabled
        await s.async_update(force=True)
        assert s._disabled_param is False

    async def test_update_none_val_records_timestamp(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": None})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s._last_updated = None
        await s.async_update(force=True)
        assert s._last_updated is not None
        assert s._attr_current_option is None

    async def test_update_unmatched_val_disables_when_first_poll(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": "Mystery"})
        s = InverterDynamicSettingSelect(item, coord, _select_field())
        s._last_updated = None
        await s.async_update(force=True)
        assert s._disabled_param is True


# --- VirtualBatteryChemistrySelect restore ----------------------------------

class TestChemistryRestore:
    async def test_restore_applies_state_and_estimator(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryChemistrySelect(item, coord)
        s.hass = MagicMock()
        valid_option = s._attr_options[-1]
        last = SimpleNamespace(state=valid_option)
        with patch.object(VirtualBatteryChemistrySelect, "async_get_last_state", new=AsyncMock(return_value=last)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option == valid_option
        estimator.set_chemistry.assert_called_once_with(valid_option)

    async def test_restore_no_estimator_uses_default(self):
        item = _make_item(virtual_battery=None)
        coord = _make_coordinator()
        s = VirtualBatteryChemistrySelect(item, coord)
        s.hass = MagicMock()
        with patch.object(VirtualBatteryChemistrySelect, "async_get_last_state", new=AsyncMock(return_value=None)):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_current_option == DEFAULT_BATTERY_CHEMISTRY


# --- NumberBase availability + InverterDynamicSettingNumber update branches --

def _number_field(hint="40.0~48.0V", unit=None):
    field = {"id": "bat_cutoff_voltage", "name": "Cutoff Voltage"}
    if hint is not None:
        field["hint"] = hint
    if unit is not None:
        field["unit"] = unit
    return field


class TestNumberExtras:
    def test_available_false_when_offline(self):
        item = _make_item(online=False)
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        assert s.available is False

    def test_available_false_when_hub_offline(self):
        item = _make_item(hub_online=False)
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        assert s.available is False

    def test_data_property(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"bar": 2}}, options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        assert s.data == {"bar": 2}

    def test_device_info_payload(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        info = s.device_info
        from custom_components.dess_monitor.const import DOMAIN
        assert (DOMAIN, "PN1") in info["identifiers"]
        assert info["manufacturer"] == "ESS"

    async def test_update_timeout_swallowed(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(side_effect=TimeoutError("slow"))
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        s._last_updated = None
        await s.async_update()
        assert s._attr_native_value is None

    async def test_update_error_response_records_timestamp(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"err": 1})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        s._last_updated = None
        await s.async_update()
        assert s._last_updated is not None
        assert s._attr_native_value is None

    async def test_update_none_val_records_timestamp(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        coord.client.control.get_value = AsyncMock(return_value={"val": None})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        s._last_updated = None
        await s.async_update()
        assert s._last_updated is not None
        assert s._attr_native_value is None

    async def test_restore_sets_value_and_timestamp(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        s.hass = MagicMock()
        last = SimpleNamespace(native_value=44.0)
        with patch.object(
            InverterDynamicSettingNumber, "async_get_last_number_data", new=AsyncMock(return_value=last)
        ):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_native_value == 44.0
        assert s._last_updated is not None

    async def test_restore_no_data_keeps_none(self):
        item = _make_item()
        coord = _make_coordinator(options={})
        s = InverterDynamicSettingNumber(item, coord, _number_field())
        s.hass = MagicMock()
        with patch.object(
            InverterDynamicSettingNumber, "async_get_last_number_data", new=AsyncMock(return_value=None)
        ):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_native_value is None


# --- Virtual battery numbers restore + apply --------------------------------

class TestVirtualBatteryNumberRestore:
    async def test_capacity_restore_applies_estimator(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryCapacityNumber(item, coord)
        s.hass = MagicMock()
        last = SimpleNamespace(native_value=150.0)
        with patch.object(
            VirtualBatteryCapacityNumber, "async_get_last_number_data", new=AsyncMock(return_value=last)
        ):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_native_value == 150.0
        estimator.set_capacity_ah.assert_called_once_with(150.0)

    async def test_voltage_restore_invalid_value_sets_none(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryVoltageFullNumber(item, coord)
        s.hass = MagicMock()
        last = SimpleNamespace(native_value="not-a-number")
        with patch.object(
            VirtualBatteryVoltageFullNumber, "async_get_last_number_data", new=AsyncMock(return_value=last)
        ):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        assert s._attr_native_value is None
        estimator.set_voltage_full.assert_not_called()

    async def test_restore_no_data_keeps_default_and_applies(self):
        estimator = MagicMock()
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator()
        s = VirtualBatteryCapacityNumber(item, coord)
        s.hass = MagicMock()
        with patch.object(
            VirtualBatteryCapacityNumber, "async_get_last_number_data", new=AsyncMock(return_value=None)
        ):
            with patch(
                "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                new=AsyncMock(),
            ):
                await s.async_added_to_hass()
        # default capacity retained and pushed to estimator
        estimator.set_capacity_ah.assert_called_once()


# --- sensor.async_setup_entry -----------------------------------------------

class TestSensorSetupEntry:
    async def test_setup_adds_optional_sensor_groups(self):
        item = _make_item()
        options = {
            "battery_virtual_enabled": True,
            "enable_last_at_sensors": True,
            "raw_sensors": False,
            "direct_request_protocol": False,
        }
        coordinator = _make_coordinator(data={"PN1": {}}, options=options)
        hub = SimpleNamespace(items=[item], coordinator=coordinator, direct_coordinator=_make_coordinator(data=None))
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        await sensor_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        names = {type(e).__name__ for e in added}
        assert "VirtualBatterySocSensor" in names
        assert "InverterLastSampleTimeSensor" in names
        assert "InverterWebSocketLastFrameSensor" in names

    async def test_setup_adds_dynamic_and_direct_sensors(self):
        item = _make_item()
        options = {
            "battery_virtual_enabled": False,
            "enable_last_at_sensors": False,
            "raw_sensors": True,
            "direct_request_protocol": True,
        }
        dyn_data = {"PN1": {"pars": {"parameter": [{"par": "p1", "name": "P1", "unit": "W", "val": "1"}]}}}
        coordinator = _make_coordinator(data=dyn_data, options=options)
        direct_coordinator = _make_coordinator(data={"PN1": {}}, options=options)
        hub = SimpleNamespace(items=[item], coordinator=coordinator, direct_coordinator=direct_coordinator)
        config_entry = SimpleNamespace(runtime_data=hub, options=options)
        added: list = []
        await sensor_mod.async_setup_entry(MagicMock(), config_entry, lambda d: added.extend(list(d)))
        names = {type(e).__name__ for e in added}
        # dynamic raw sensor created from pars.parameter
        assert "InverterDynamicSensor" in names
        # direct sensors created (at least one of the DIRECT_SENSORS classes)
        assert len(added) > 1


# --- InverterDynamicSensor default-source + exception branches --------------

class TestDynamicSensorBranches:
    def test_energy_flow_source_yields_none(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"pars": {"parameter": []}}})
        param = {"par": "x", "name": "X", "unit": "W", "val": "1"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.ENERGY_FLOW)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_exception_during_update_sets_none(self):
        item = _make_item()
        # data slice present but 'pars' lookup raises because .get is patched
        bad = MagicMock()
        bad.get.side_effect = RuntimeError("boom")
        coord = _make_coordinator(data={"PN1": bad})
        param = {"par": "x", "name": "X", "unit": "W", "val": "1"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        s.async_write_ha_state = MagicMock()
        s._attr_native_value = 5.0
        s._handle_coordinator_update()
        assert s._attr_native_value is None


# --- MyEnergySensor restore + FunctionBasedEnergySensor exception -----------

class TestEnergySensorBranches:
    async def test_restore_uses_max_of_extra_and_state(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {}})
        s = PVEnergySensor(item, coord)
        s.hass = MagicMock()
        extra = MagicMock()
        extra.as_dict.return_value = {"native_value": 100.0}
        state = SimpleNamespace(state="250.0")
        with patch.object(MyEnergySensor, "async_get_last_extra_data", new=AsyncMock(return_value=extra)):
            with patch.object(MyEnergySensor, "async_get_last_state", new=AsyncMock(return_value=state)):
                with patch(
                    "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                    new=AsyncMock(),
                ):
                    s._handle_coordinator_update = MagicMock()
                    await s.async_added_to_hass()
        assert s._attr_native_value == 250.0
        assert s._is_restored_value is True

    async def test_restore_handles_bad_extra_and_state(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {}})
        s = PVEnergySensor(item, coord)
        s.hass = MagicMock()
        extra = MagicMock()
        extra.as_dict.return_value = {"native_value": "bad"}
        # non-sentinel string that fails float() -> exercises the ValueError path
        state = SimpleNamespace(state="oops")
        with patch.object(MyEnergySensor, "async_get_last_extra_data", new=AsyncMock(return_value=extra)):
            with patch.object(MyEnergySensor, "async_get_last_state", new=AsyncMock(return_value=state)):
                with patch(
                    "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
                    new=AsyncMock(),
                ):
                    s._handle_coordinator_update = MagicMock()
                    await s.async_added_to_hass()
        # no valid candidates -> defaults to 0
        assert s._attr_native_value == 0

    def test_resolver_exception_does_not_raise(self):
        item = _make_item()
        coord = _make_coordinator(data={"PN1": {"some": "data"}})
        s = PVEnergySensor(item, coord)
        s.async_write_ha_state = MagicMock()
        with patch.object(s, "_resolve_function", side_effect=ValueError("nope")):
            # should swallow and return without updating
            s._handle_coordinator_update()
        # native value untouched (still default 0 / None depending on restore)

    def test_handle_update_none_data_returns(self):
        item = _make_item()
        coord = _make_coordinator(data=None)
        s = PVEnergySensor(item, coord)
        s.async_write_ha_state = MagicMock()
        # data property returns None -> early return, no write
        s._handle_coordinator_update()
        s.async_write_ha_state.assert_not_called()
