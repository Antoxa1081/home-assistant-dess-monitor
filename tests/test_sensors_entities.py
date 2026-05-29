"""Tests for the sensor entity classes in ``custom_components.dess_monitor.sensors``.

Focus is on PURE logic that can be exercised without adding the entity to a
running Home Assistant: unit support detection, ``native_value`` computation
given a fake coordinator + item, ``unique_id`` / ``device_info``, energy
accumulation, and the direct/QPIRI sensor factories.

Entities subclass HA's ``CoordinatorEntity``; we construct them with a
``MagicMock`` coordinator (``.data`` set, ``.last_update_success=True``) and a
``SimpleNamespace`` item whose ``resolve`` reads from a dict — exactly how the
mapping-backed resolvers fetch values.
"""
from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.dess_monitor.api.protocols.enums import BatteryType, OutputSourcePriority
from custom_components.dess_monitor.sensors.direct_sensor import (
    DIRECT_SENSORS,
    QPIRI_SENSOR_MAPPING,
    BatteryTypeSensor,
    DirectInverterOutputPowerSensor,
    DirectPV2PowerSensor,
    DirectPVPowerSensor,
    OutputSourcePrioritySensor,
    generate_qpiri_sensors,
)
from custom_components.dess_monitor.sensors.dynamic_sensor import (
    DessSensorSource,
    InverterDynamicSensor,
    _canon_unit,
    _is_supported_unit,
)
from custom_components.dess_monitor.sensors.energy_sensors import (
    InverterOutEnergySensor,
    PVEnergySensor,
)
from custom_components.dess_monitor.sensors.init_sensors import (
    BatteryVoltageSensor,
    InverterStatusSensor,
    VirtualBatterySocSensor,
    _resolve_status,
)

# --- shared fakes ------------------------------------------------------------

def _make_item(inverter_id="PN1", resolve_map=None, virtual_battery=None):
    resolve_map = resolve_map or {}

    def resolve(canonical, data):
        return resolve_map.get(canonical)

    hub = SimpleNamespace(online=True)
    item = SimpleNamespace(
        inverter_id=inverter_id,
        name="Inv 1",
        model="DESS Device",
        device_data={"pn": inverter_id, "sn": "SN1", "devcode": 2376, "devaddr": 1, "devalias": "Inv 1"},
        firmware_version="0.0.1",
        virtual_battery=virtual_battery,
        online=True,
        hub=hub,
    )
    item.resolve = resolve
    return item


def _make_coordinator(data, update_interval=None):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    if update_interval is not None:
        coord.update_interval = update_interval
    else:
        coord.update_interval = timedelta(seconds=60)
    return coord


# --- _is_supported_unit / _canon_unit ----------------------------------------

class TestSupportedUnit:
    @pytest.mark.parametrize("unit", ["V", "v", "A", "kW", "KW", "Hz", "HZ", "°C", "VA", "Wh", "kWh", "%", " W "])
    def test_accepted_units(self, unit):
        assert _is_supported_unit({"unit": unit}) is True

    @pytest.mark.parametrize("unit", ["xyz", "", "ohm", None, 5])
    def test_rejected_units(self, unit):
        assert _is_supported_unit({"unit": unit}) is False

    def test_missing_unit_key(self):
        assert _is_supported_unit({}) is False

    def test_canon_normalises_case_and_whitespace(self):
        assert _canon_unit(" hZ ") == "Hz"
        assert _canon_unit("KW") == "kW"
        assert _canon_unit(None) is None
        assert _canon_unit(12) is None


# --- InverterDynamicSensor ---------------------------------------------------

class TestInverterDynamicSensor:
    def test_init_sets_unit_class_and_value(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        param = {"par": "bt_v", "name": "Battery V", "val": "53.2", "unit": "V"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        assert s._attr_unique_id == "PN1_raw_bt_v"
        assert s._attr_name == "Inv 1 Raw Battery V"
        assert s._attr_native_value == 53.2
        from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
        assert s._attr_device_class == SensorDeviceClass.VOLTAGE
        assert s._attr_state_class == SensorStateClass.MEASUREMENT

    def test_energy_unit_is_total_state_class(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        param = {"par": "e", "name": "Energy", "val": "10", "unit": "kWh"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        from homeassistant.components.sensor import SensorStateClass
        assert s._attr_state_class == SensorStateClass.TOTAL

    def test_percent_has_no_device_class(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        param = {"par": "load", "name": "Load", "val": "40", "unit": "%"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        assert s._attr_device_class is None

    def test_invalid_value_becomes_none(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        param = {"par": "x", "name": "X", "val": "notanumber", "unit": "V"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        assert s._attr_native_value is None

    def test_update_pars_source_reads_value(self):
        item = _make_item()
        data = {"PN1": {"pars": {"parameter": [{"par": "bt_v", "val": "55.0"}]}}}
        coord = _make_coordinator(data)
        param = {"par": "bt_v", "name": "Battery V", "val": "0", "unit": "V"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 55.0

    def test_update_last_data_source_reads_value(self):
        item = _make_item()
        data = {"PN1": {"last_data": {"pars": {"bt_": [{"id": "bt_voltage", "val": "48.1"}]}}}}
        coord = _make_coordinator(data)
        param = {"par": "bt_voltage", "name": "Battery V", "val": "0", "unit": "V"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.SP_LAST_DATA)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 48.1

    def test_update_handles_missing_device_data(self):
        item = _make_item()
        coord = _make_coordinator(None)
        param = {"par": "x", "name": "X", "val": "1", "unit": "V"}
        s = InverterDynamicSensor(item, coord, param, DessSensorSource.PARS_ES)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None


# --- ValueResolvingSensor family --------------------------------------------

class TestValueResolvingSensors:
    def test_battery_voltage_unique_id_and_value(self):
        item = _make_item(resolve_map={"battery_voltage": 53.4})
        coord = _make_coordinator({"PN1": {"x": 1}})
        s = BatteryVoltageSensor(item, coord)
        assert s._attr_unique_id == "PN1_battery"
        assert s._attr_name == "Inv 1 Battery Voltage"
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 53.4

    def test_value_none_when_no_device_data(self):
        item = _make_item(resolve_map={"battery_voltage": 53.4})
        coord = _make_coordinator({})  # no PN1 entry
        s = BatteryVoltageSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_resolver_exception_yields_none(self):
        item = _make_item()
        # resolve raising -> caught, value None
        def boom(canonical, data):
            raise RuntimeError("nope")
        item.resolve = boom
        coord = _make_coordinator({"PN1": {"x": 1}})
        s = BatteryVoltageSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_device_info_payload(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        s = BatteryVoltageSensor(item, coord)
        info = s.device_info
        from custom_components.dess_monitor.const import DOMAIN
        assert info["identifiers"] == {(DOMAIN, "PN1")}
        assert info["model"] == "PN1"
        assert info["serial_number"] == "SN1"
        assert info["manufacturer"] == "ESS"

    def test_available_reflects_online(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {}})
        s = BatteryVoltageSensor(item, coord)
        assert s.available is True
        item.online = False
        assert s.available is False


class TestStatusResolution:
    @pytest.mark.parametrize("idx,expected", [(0, "NORMAL"), (2, "FAULT"), (4, "WARNING")])
    def test_status_index_maps(self, idx, expected):
        assert _resolve_status({"device": {"status": idx}}, None) == expected

    @pytest.mark.parametrize("bad", [{"device": {"status": 99}}, {"device": {}}, {}, {"device": {"status": -1}}])
    def test_status_out_of_range_or_missing(self, bad):
        assert _resolve_status(bad, None) is None

    def test_status_sensor_construction(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {"device": {"status": 0}}})
        s = InverterStatusSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == "NORMAL"


# --- VirtualBatterySocSensor -------------------------------------------------

class TestVirtualBatterySoc:
    def test_none_when_no_estimator(self):
        item = _make_item(virtual_battery=None)
        coord = _make_coordinator({"PN1": {}})
        s = VirtualBatterySocSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None
        assert s._attr_unique_id == "PN1_virtual_battery_soc"

    def test_rounds_soc(self):
        estimator = SimpleNamespace(soc=87.456)
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator({"PN1": {}})
        s = VirtualBatterySocSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 87.5

    def test_non_numeric_soc_is_none(self):
        estimator = SimpleNamespace(soc=None)
        item = _make_item(virtual_battery=estimator)
        coord = _make_coordinator({"PN1": {}})
        s = VirtualBatterySocSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None


# --- Energy sensors (accumulation logic) ------------------------------------

class TestEnergyAccumulation:
    def _make_sensor(self, update_interval=timedelta(seconds=60)):
        item = _make_item(resolve_map={})
        coord = _make_coordinator({"PN1": {"x": 1}}, update_interval=update_interval)
        s = InverterOutEnergySensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._attr_native_value = 0.0
        return s

    def test_first_sample_does_not_accumulate(self):
        s = self._make_sensor()
        s.update_energy_value(100.0)
        # First reading sets prev but accumulates nothing.
        assert s._attr_native_value == 0.0
        assert s._prev_value == 100.0

    def test_trapezoidal_accumulation(self):
        # Use a long interval so a 1h gap stays within max_gap (interval * 5).
        s = self._make_sensor(update_interval=timedelta(hours=1))
        s.update_energy_value(100.0)
        # Force prev timestamp to one hour ago, prev value 100W.
        s._prev_value_timestamp = datetime.now() - timedelta(hours=1)
        s.update_energy_value(100.0)
        # 1h at avg 100W = 100 Wh.
        assert s._attr_native_value == pytest.approx(100.0, abs=0.5)

    def test_gap_too_large_skips_accumulation(self):
        s = self._make_sensor(update_interval=timedelta(seconds=10))
        s.update_energy_value(100.0)
        # Gap of 1h far exceeds 10s * 5 multiplier -> skip.
        s._prev_value_timestamp = datetime.now() - timedelta(hours=1)
        s.update_energy_value(100.0)
        assert s._attr_native_value == 0.0

    def test_none_value_ignored(self):
        s = self._make_sensor()
        s.update_energy_value(None)
        assert s._prev_value is None

    def test_no_update_interval_means_infinite_gap(self):
        item = _make_item()
        coord = _make_coordinator({"PN1": {"x": 1}})
        coord.update_interval = None
        s = InverterOutEnergySensor(item, coord)
        assert s._max_integration_gap_seconds() == float("inf")

    def test_unique_id_and_name(self):
        s = self._make_sensor()
        assert s._attr_unique_id == "PN1_inverter_out_energy"
        assert s._attr_name == "Inv 1 Inverter Out Energy"

    def test_handle_update_calls_accumulator(self):
        item = _make_item(resolve_map={"pv_power": 200.0})
        coord = _make_coordinator({"PN1": {"x": 1}})
        s = PVEnergySensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._attr_native_value = 0.0
        s._handle_coordinator_update()
        # First tick just seeds prev_value.
        assert s._prev_value == 200.0

    def test_handle_update_none_data_returns_early(self):
        item = _make_item()
        coord = _make_coordinator({})  # no PN1
        s = PVEnergySensor(item, coord)
        s.async_write_ha_state = MagicMock()
        # Should not raise.
        s._handle_coordinator_update()
        assert s._prev_value is None

    def test_energy_class_attrs(self):
        from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
        s = self._make_sensor()
        assert s.device_class == SensorDeviceClass.ENERGY
        assert s.state_class == SensorStateClass.TOTAL_INCREASING
        assert s.native_unit_of_measurement == "Wh"


# --- Direct sensors ----------------------------------------------------------

class TestDirectSensors:
    def _coord(self, data):
        coord = MagicMock()
        coord.data = {"PN1": data}
        coord.last_update_success = True
        return coord

    def test_typed_sensor_reads_section_key(self):
        item = _make_item()
        coord = self._coord({"qpigs": {"output_active_power": "1234"}})
        s = DirectInverterOutputPowerSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 1234.0
        assert s._attr_unique_id == "PN1_direct_inverter_out_power"
        assert s._attr_name == "Inv 1 Direct Inverter Out Power"

    def test_typed_sensor_missing_value_none(self):
        item = _make_item()
        coord = self._coord({"qpigs": {}})
        s = DirectPVPowerSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_typed_sensor_non_numeric_none(self):
        item = _make_item()
        coord = self._coord({"qpigs": {"pv_charging_power": "abc"}})
        s = DirectPVPowerSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_pv2_power_computed_product(self):
        item = _make_item()
        coord = self._coord({"qpigs2": {"pv_current": "5", "pv_voltage": "100"}})
        s = DirectPV2PowerSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == 500.0

    def test_pv2_power_missing_section_none(self):
        item = _make_item()
        coord = self._coord({})
        s = DirectPV2PowerSensor(item, coord)
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_enum_sensor_options_and_value(self):
        item = _make_item()
        coord = self._coord({"qpiri": {"battery_type": "AGM"}})
        s = BatteryTypeSensor(item, coord, data_section="qpiri", data_key="battery_type")
        assert s.options == [e.name for e in BatteryType]
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value == "AGM"

    def test_enum_sensor_missing_value_none(self):
        item = _make_item()
        coord = self._coord({"qpiri": {}})
        s = OutputSourcePrioritySensor(item, coord, data_section="qpiri", data_key="output_source_priority")
        assert s.options == [e.name for e in OutputSourcePriority]
        s.async_write_ha_state = MagicMock()
        s._handle_coordinator_update()
        assert s._attr_native_value is None

    def test_direct_device_info(self):
        item = _make_item()
        coord = self._coord({"qpigs": {}})
        s = DirectPVPowerSensor(item, coord)
        info = s.device_info
        from custom_components.dess_monitor.const import DOMAIN
        assert info["identifiers"] == {(DOMAIN, "PN1")}
        assert info["manufacturer"] == "ESS"


class TestGenerateQpiriSensors:
    def test_count_matches_mapping(self):
        item = _make_item()
        coord = MagicMock()
        coord.data = {"PN1": {"qpiri": {}}}
        sensors = generate_qpiri_sensors(item, coord)
        assert len(sensors) == len(QPIRI_SENSOR_MAPPING)

    def test_unique_ids_distinct_and_prefixed(self):
        item = _make_item()
        coord = MagicMock()
        coord.data = {"PN1": {"qpiri": {}}}
        sensors = generate_qpiri_sensors(item, coord)
        uids = {s._attr_unique_id for s in sensors}
        assert len(uids) == len(sensors)
        assert all(u.startswith("PN1_direct_") for u in uids)

    def test_all_use_qpiri_section(self):
        item = _make_item()
        coord = MagicMock()
        coord.data = {"PN1": {"qpiri": {}}}
        sensors = generate_qpiri_sensors(item, coord)
        assert all(s.data_section == "qpiri" for s in sensors)


def test_direct_sensors_list_nonempty():
    assert len(DIRECT_SENSORS) == 20
