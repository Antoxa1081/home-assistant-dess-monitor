"""Tests for ``custom_components.dess_monitor.hub`` (Hub + InverterDevice)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.dess_monitor.hub import Hub, InverterDevice


def _device(pn="PN1", alias="Inv 1"):
    return {"pn": pn, "devalias": alias, "devcode": 2376}


def _make_hub(hass, *, devices=None, last_update_success=True, data=None,
              username="Tester"):
    coordinator = SimpleNamespace(
        devices=devices if devices is not None else [],
        last_update_success=last_update_success,
        data=data,
    )
    direct_coordinator = SimpleNamespace(data={})
    mapping = MagicMock()
    client = MagicMock()
    hub = Hub(hass, username, client, coordinator, direct_coordinator, mapping)
    return hub, mapping


class TestHub:
    async def test_hub_id_is_lowercased_username(self, hass) -> None:
        hub, _ = _make_hub(hass, username="TeStEr")
        assert hub.hub_id == "tester"

    async def test_client_and_mapping_properties(self, hass) -> None:
        hub, mapping = _make_hub(hass)
        assert hub.mapping is mapping
        assert hub.client is hub._client

    async def test_online_true_when_last_update_success(self, hass) -> None:
        hub, _ = _make_hub(hass, last_update_success=True)
        assert hub.online is True

    async def test_online_false_when_update_failed(self, hass) -> None:
        hub, _ = _make_hub(hass, last_update_success=False)
        assert hub.online is False

    async def test_init_populates_items(self, hass) -> None:
        devices = [_device("PN1", "Inv A"), _device("PN2", "Inv B")]
        hub, _ = _make_hub(hass, devices=devices)
        assert hub.items == []
        await hub.init()
        assert len(hub.items) == 2
        assert all(isinstance(i, InverterDevice) for i in hub.items)
        assert hub.items[0].inverter_id == "PN1"
        assert hub.items[0].name == "Inv A"
        assert hub.items[1].inverter_id == "PN2"

    async def test_init_with_no_devices(self, hass) -> None:
        hub, _ = _make_hub(hass, devices=[])
        await hub.init()
        assert hub.items == []


class TestInverterDevice:
    def _device_obj(self, hass, *, data=None):
        hub, mapping = _make_hub(hass, data=data)
        dev = InverterDevice("PN1", "Inv 1", _device("PN1"), hub)
        return dev, mapping

    async def test_defaults(self, hass) -> None:
        dev, _ = self._device_obj(hass)
        assert dev.inverter_id == "PN1"
        assert dev.name == "Inv 1"
        assert dev.firmware_version == "0.0.1"
        assert dev.model == "DESS Device"
        assert dev.virtual_battery is None

    async def test_online_false_when_data_none(self, hass) -> None:
        dev, _ = self._device_obj(hass, data=None)
        assert dev.online is False

    async def test_online_false_when_id_missing(self, hass) -> None:
        dev, _ = self._device_obj(hass, data={"OTHER": {}})
        assert dev.online is False

    async def test_online_true_when_id_present(self, hass) -> None:
        dev, _ = self._device_obj(hass, data={"PN1": {"v": 1}})
        assert dev.online is True

    async def test_resolve_delegates_to_mapping(self, hass) -> None:
        dev, mapping = self._device_obj(hass)
        mapping.resolve.return_value = 42.0
        tick = {"some": "data"}
        result = dev.resolve("battery_voltage", tick)
        assert result == 42.0
        mapping.resolve.assert_called_once_with("PN1", "battery_voltage", tick)
