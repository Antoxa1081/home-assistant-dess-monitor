"""End-to-end-ish tests for ``custom_components.dess_monitor.__init__``.

The full ``async_setup_entry`` path is exercised with a faked
``DessmonitorClient`` (patched at the symbol imported in ``__init__``) so no
network is touched. We assert the entry reaches LOADED, sensor entities are
created, and unload works. The pure helpers ``_resolve_signed_battery_current``
and ``_migrate_data_to_options`` are also covered directly.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dess_monitor import (
    _migrate_data_to_options,
    _resolve_signed_battery_current,
)
from custom_components.dess_monitor.const import DOMAIN

DEVICE = {
    "pn": "PN1",
    "sn": "SN1",
    "devcode": 2376,
    "devaddr": 1,
    "status": 0,
    "uid": "u1",
    "devalias": "Inv 1",
}


def _make_fake_client():
    client = MagicMock()
    client.session = MagicMock()
    client.session.get_auth = AsyncMock(return_value={})
    client.session.invalidate = AsyncMock()
    client.devices = MagicMock()
    client.devices.list = AsyncMock(return_value=[dict(DEVICE)])
    client.devices.last_data = AsyncMock(return_value={})
    client.devices.energy_flow = AsyncMock(return_value={})
    client.devices.pars = AsyncMock(return_value={})
    client.control = MagicMock()
    client.control.get_fields = AsyncMock(return_value={"field": []})
    client.control.get_value = AsyncMock(return_value={})
    return client


# --- pure helpers ------------------------------------------------------------

class TestResolveSignedBatteryCurrent:
    def _item(self, resolve_map):
        return SimpleNamespace(resolve=lambda c, d: resolve_map.get(c))

    def test_prefers_charge_minus_discharge(self):
        item = self._item({"battery_charging_current": 10.0, "battery_discharge_current": 3.0})
        assert _resolve_signed_battery_current(item, {}, 50.0) == pytest.approx(7.0)

    def test_charge_only(self):
        item = self._item({"battery_charging_current": 12.0})
        assert _resolve_signed_battery_current(item, {}, 50.0) == pytest.approx(12.0)

    def test_discharge_negative(self):
        item = self._item({"battery_discharge_current": 5.0})
        assert _resolve_signed_battery_current(item, {}, 50.0) == pytest.approx(-5.0)

    def test_falls_back_to_power_over_voltage(self):
        item = self._item({"battery_power": 500.0})
        assert _resolve_signed_battery_current(item, {}, 50.0) == pytest.approx(10.0)

    def test_none_when_no_voltage_for_power_fallback(self):
        item = self._item({"battery_power": 500.0})
        assert _resolve_signed_battery_current(item, {}, None) is None

    def test_none_when_voltage_zero(self):
        item = self._item({"battery_power": 500.0})
        assert _resolve_signed_battery_current(item, {}, 0.0) is None

    def test_none_when_nothing_resolvable(self):
        item = self._item({})
        assert _resolve_signed_battery_current(item, {}, 50.0) is None


class TestMigrateDataToOptions:
    async def test_moves_listed_fields(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "username": "u",
                "password_hash": "0" * 40,
                "dynamic_settings": True,
                "raw_sensors": True,
                "devices": ["PN1"],
            },
            options={},
        )
        entry.add_to_hass(hass)
        await _migrate_data_to_options(hass, entry)
        # Moved out of data, into options.
        assert "dynamic_settings" not in entry.data
        assert "raw_sensors" not in entry.data
        assert "devices" not in entry.data
        assert entry.options["dynamic_settings"] is True
        assert entry.options["raw_sensors"] is True
        assert entry.options["devices"] == ["PN1"]
        # Credentials stay in data.
        assert entry.data["username"] == "u"

    async def test_noop_when_nothing_to_migrate(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password_hash": "0" * 40},
            options={"devices": ["PN1"]},
        )
        entry.add_to_hass(hass)
        before_data = dict(entry.data)
        before_options = dict(entry.options)
        await _migrate_data_to_options(hass, entry)
        assert dict(entry.data) == before_data
        assert dict(entry.options) == before_options


# --- full setup --------------------------------------------------------------

class TestAsyncSetupEntry:
    async def test_setup_loads_and_creates_sensors(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password_hash": "0" * 40},
            options={"devices": ["PN1"]},
        )
        entry.add_to_hass(hass)

        fake_client = _make_fake_client()
        with patch(
            "custom_components.dess_monitor.DessmonitorClient",
            return_value=fake_client,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        sensor_ids = hass.states.async_entity_ids("sensor")
        assert len(sensor_ids) > 0
        # Static sensors carry the device name prefix.
        assert any("inv_1" in eid for eid in sensor_ids)

    async def test_unload_entry(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password_hash": "0" * 40},
            options={"devices": ["PN1"]},
        )
        entry.add_to_hass(hass)

        fake_client = _make_fake_client()
        with patch(
            "custom_components.dess_monitor.DessmonitorClient",
            return_value=fake_client,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.state is ConfigEntryState.LOADED

            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.NOT_LOADED

    async def test_setup_creates_output_priority_select(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password_hash": "0" * 40},
            options={"devices": ["PN1"]},
        )
        entry.add_to_hass(hass)

        fake_client = _make_fake_client()
        with patch(
            "custom_components.dess_monitor.DessmonitorClient",
            return_value=fake_client,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        select_ids = hass.states.async_entity_ids("select")
        assert any("output_priority" in eid for eid in select_ids)
