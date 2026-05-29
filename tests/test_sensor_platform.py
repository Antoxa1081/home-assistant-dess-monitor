"""Tests for the helper functions in ``custom_components.dess_monitor.sensor``.

These cover the pure logic for building the sensor entity lists:
``create_static_sensors``, ``should_add_dynamic_sensors``,
``create_dynamic_sensors`` (the dedup between ``pars.parameter`` and
``last_data.pars.<group>``), ``should_add_direct_sensors`` and
``create_direct_sensors``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.dess_monitor.sensor import (
    create_direct_sensors,
    create_dynamic_sensors,
    create_static_sensors,
    should_add_direct_sensors,
    should_add_dynamic_sensors,
)
from custom_components.dess_monitor.sensors.direct_sensor import DIRECT_SENSORS
from custom_components.dess_monitor.sensors.dynamic_sensor import DessSensorSource


def _make_item(inverter_id: str = "PN1"):
    hub = SimpleNamespace(online=True, mapping=SimpleNamespace())
    return SimpleNamespace(
        inverter_id=inverter_id,
        name="Inv 1",
        model="DESS Device",
        device_data={"pn": inverter_id, "sn": "SN1", "devcode": 2376, "devaddr": 1, "devalias": "Inv 1"},
        firmware_version="0.0.1",
        virtual_battery=None,
        online=True,
        hub=hub,
    )


def _make_coordinator(data):
    return SimpleNamespace(data=data, last_update_success=True)


class TestCreateStaticSensors:
    def test_returns_all_static_classes(self):
        item = _make_item()
        coordinator = _make_coordinator({})
        sensors = create_static_sensors(item, coordinator)
        # 37 sensor classes are listed in sensor.create_static_sensors.
        assert len(sensors) == 37
        # Unique IDs are all distinct.
        uids = {s._attr_unique_id for s in sensors}
        assert len(uids) == len(sensors)

    def test_each_sensor_bound_to_item(self):
        item = _make_item()
        coordinator = _make_coordinator({})
        sensors = create_static_sensors(item, coordinator)
        for s in sensors:
            assert s._inverter_device is item


class TestShouldAddDynamicSensors:
    def _entry(self, raw_sensors):
        return SimpleNamespace(options={"raw_sensors": raw_sensors})

    def test_true_when_enabled_and_data_present(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(coordinator=_make_coordinator({"PN1": {}}))
        assert should_add_dynamic_sensors(self._entry(True), hub, item) is True

    def test_false_when_option_disabled(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(coordinator=_make_coordinator({"PN1": {}}))
        assert should_add_dynamic_sensors(self._entry(False), hub, item) is False

    def test_false_when_data_none(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(coordinator=_make_coordinator(None))
        assert should_add_dynamic_sensors(self._entry(True), hub, item) is False

    def test_false_when_device_missing(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(coordinator=_make_coordinator({"OTHER": {}}))
        assert should_add_dynamic_sensors(self._entry(True), hub, item) is False


class TestCreateDynamicSensors:
    def test_pars_parameter_creates_sensors(self):
        item = _make_item("PN1")
        data = {
            "PN1": {
                "pars": {
                    "parameter": [
                        {"par": "bt_voltage", "name": "Battery V", "val": "53.2", "unit": "V"},
                        {"par": "load_pct", "name": "Load", "val": "40", "unit": "%"},
                    ]
                }
            }
        }
        coordinator = _make_coordinator(data)
        sensors = create_dynamic_sensors(item, coordinator)
        assert len(sensors) == 2
        assert all(s._sensor_source is DessSensorSource.PARS_ES for s in sensors)

    def test_unsupported_unit_skipped(self):
        item = _make_item("PN1")
        data = {
            "PN1": {
                "pars": {
                    "parameter": [
                        {"par": "weird", "name": "Weird", "val": "1", "unit": "xyz"},
                        {"par": "ok", "name": "OK", "val": "1", "unit": "V"},
                    ]
                }
            }
        }
        sensors = create_dynamic_sensors(item, _make_coordinator(data))
        assert len(sensors) == 1
        assert sensors[0]._sensor_par_id == "ok"

    def test_missing_par_id_skipped(self):
        item = _make_item("PN1")
        data = {
            "PN1": {
                "pars": {
                    "parameter": [
                        {"par": "", "name": "Empty", "val": "1", "unit": "V"},
                        {"name": "NoPar", "val": "1", "unit": "V"},
                    ]
                }
            }
        }
        assert create_dynamic_sensors(item, _make_coordinator(data)) == []

    def test_last_data_pars_creates_sensors(self):
        item = _make_item("PN1")
        data = {
            "PN1": {
                "last_data": {
                    "pars": {
                        "bc_": [
                            {"id": "bc_voltage", "par": "Battery V", "val": "53.2", "unit": "V"},
                        ],
                        "gd_": [
                            {"id": "gd_freq", "par": "Grid Hz", "val": "50", "unit": "Hz"},
                        ],
                    }
                }
            }
        }
        sensors = create_dynamic_sensors(item, _make_coordinator(data))
        assert len(sensors) == 2
        assert all(s._sensor_source is DessSensorSource.SP_LAST_DATA for s in sensors)
        # The 'par' field becomes the friendly name when present.
        names = {s._attr_name for s in sensors}
        assert "Inv 1 Raw Battery V" in names

    def test_dedup_prefers_pars_parameter(self):
        # Same id appears in both sources; pars.parameter wins and last_data
        # branch for the overlapping id must not run.
        item = _make_item("PN1")
        data = {
            "PN1": {
                "pars": {
                    "parameter": [
                        {"par": "shared", "name": "Shared Pars", "val": "1", "unit": "V"},
                    ]
                },
                "last_data": {
                    "pars": {
                        "sh_": [
                            {"id": "shared", "par": "Shared LastData", "val": "2", "unit": "V"},
                            {"id": "unique", "par": "Unique", "val": "3", "unit": "V"},
                        ]
                    }
                },
            }
        }
        sensors = create_dynamic_sensors(item, _make_coordinator(data))
        # 'shared' once (from pars) + 'unique' once (from last_data) = 2.
        assert len(sensors) == 2
        by_id = {s._sensor_par_id: s for s in sensors}
        assert by_id["shared"]._sensor_source is DessSensorSource.PARS_ES
        assert by_id["unique"]._sensor_source is DessSensorSource.SP_LAST_DATA
        # The friendly name came from pars.parameter, not last_data.
        assert by_id["shared"]._attr_name == "Inv 1 Raw Shared Pars"

    def test_empty_data_yields_no_sensors(self):
        item = _make_item("PN1")
        assert create_dynamic_sensors(item, _make_coordinator({"PN1": {}})) == []

    def test_last_data_missing_id_skipped(self):
        item = _make_item("PN1")
        data = {
            "PN1": {
                "last_data": {
                    "pars": {
                        "x_": [
                            {"par": "no id", "val": "1", "unit": "V"},
                            {"id": "", "par": "empty id", "val": "1", "unit": "V"},
                        ]
                    }
                }
            }
        }
        assert create_dynamic_sensors(item, _make_coordinator(data)) == []


class TestShouldAddDirectSensors:
    def _entry(self, enabled):
        return SimpleNamespace(options={"direct_request_protocol": enabled})

    def test_true_when_enabled_and_data(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(direct_coordinator=_make_coordinator({"PN1": {}}))
        assert should_add_direct_sensors(self._entry(True), hub, item) is True

    def test_false_when_disabled(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(direct_coordinator=_make_coordinator({"PN1": {}}))
        assert should_add_direct_sensors(self._entry(False), hub, item) is False

    def test_false_when_no_data(self):
        item = _make_item("PN1")
        hub = SimpleNamespace(direct_coordinator=_make_coordinator(None))
        assert should_add_direct_sensors(self._entry(True), hub, item) is False


class TestCreateDirectSensors:
    def test_returns_all_direct_classes(self):
        item = _make_item("PN1")
        coordinator = _make_coordinator({"PN1": {"qpigs": {}}})
        sensors = create_direct_sensors(item, coordinator)
        assert len(sensors) == len(DIRECT_SENSORS)
        uids = {s._attr_unique_id for s in sensors}
        assert len(uids) == len(sensors)
