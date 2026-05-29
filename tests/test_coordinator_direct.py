"""Unit tests for ``coordinators.direct_coordinator`` (DirectCoordinator).

A *fake* ``service`` is injected so the coordinator never builds a real
``CloudHexTransport``. The fake's ``query(device, command)`` returns a dict; for
PI18 it returns a multi-section dict that the coordinator splits per section.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dess_monitor.coordinators.direct_coordinator import (
    DirectCoordinator,
)
from custom_components.dess_monitor.device_cache import DeviceCache
from custom_components.dess_monitor.sdk import AuthError, TransportError


def _device(pn="PN1", sn="SN1", devcode=2376, devaddr=1, status=0, uid="u1"):
    return {
        "pn": pn,
        "sn": sn,
        "devcode": devcode,
        "devaddr": devaddr,
        "status": status,
        "uid": uid,
    }


class FakeService:
    """Records queries and returns a per-command canned reply."""

    def __init__(self, replies=None, *, default=None):
        self.replies = replies or {}
        self.default = default if default is not None else {"ok": True}
        self.calls = []  # list of (pn, command)

    async def query(self, device, command):
        self.calls.append((device["pn"], command))
        if command in self.replies:
            return self.replies[command]
        return self.default


def _make_client(devices=None):
    if devices is None:
        devices = [_device()]
    client = Mock()
    client.session.get_auth = AsyncMock(return_value={"token": "t"})
    client.session.invalidate = AsyncMock(return_value=None)
    client.devices.list = AsyncMock(return_value=devices)
    return client


def _make_entry(hass, *, options=None):
    entry = MockConfigEntry(
        domain="dess_monitor",
        data={"username": "tester", "password_hash": "0" * 40},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def _make_coordinator(hass, *, options=None, devices=None, service=None,
                      binding=None, client=None):
    entry = _make_entry(hass, options=options)
    client = client or _make_client(devices=devices)
    cache = DeviceCache(hass, entry.entry_id)
    coord = DirectCoordinator(
        hass, entry, client, cache, service=service, binding=binding
    )
    return coord, entry, client, cache


# --------------------------------------------------------------------------- #
# Protocol / binding selection
# --------------------------------------------------------------------------- #

class TestBindingSelection:
    async def test_default_axpert(self, hass):
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True},
            service=FakeService(),
        )
        assert coord._protocol_name == "axpert"
        assert set(coord._binding.sections) == {"qpigs", "qpigs2", "qpiri"}
        assert coord._binding.protocol_name == "axpert"

    async def test_smg2_binding_no_qpigs2(self, hass):
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True,
                     "direct_protocol": "smg2_modbus"},
            service=FakeService(),
        )
        assert coord._protocol_name == "smg2_modbus"
        assert set(coord._binding.sections) == {"qpigs", "qpiri"}
        assert "qpigs2" not in coord._binding.sections

    async def test_pi18_qpigs_and_qpigs2_same_command(self, hass):
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True,
                     "direct_protocol": "pi18"},
            service=FakeService(),
        )
        assert coord._protocol_name == "pi18"
        sections = coord._binding.sections
        assert sections["qpigs"] == sections["qpigs2"] == "QPIGS"
        assert sections["qpiri"] == "QPIRI"

    async def test_explicit_binding_override(self, hass):
        from custom_components.dess_monitor.api.protocols.base import ProtocolBinding

        custom = ProtocolBinding(protocol_name="custom", sections={"qpigs": "FOO"})
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True},
            service=FakeService(),
            binding=custom,
        )
        assert coord._binding is custom


# --------------------------------------------------------------------------- #
# Update interval
# --------------------------------------------------------------------------- #

class TestInterval:
    async def test_default_interval(self, hass):
        coord, *_ = _make_coordinator(
            hass, options={"direct_request_protocol": True}, service=FakeService()
        )
        assert coord.update_interval.total_seconds() == 10

    async def test_clamped_below_min(self, hass):
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True, "direct_update_interval": 1},
            service=FakeService(),
        )
        assert coord.update_interval.total_seconds() == 5

    async def test_clamped_above_max(self, hass):
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True,
                     "direct_update_interval": 99999},
            service=FakeService(),
        )
        assert coord.update_interval.total_seconds() == 600


# --------------------------------------------------------------------------- #
# get_active_devices
# --------------------------------------------------------------------------- #

class TestGetActiveDevices:
    async def test_filters_status_1(self, hass):
        devices = [
            _device(pn="A", status=0),
            _device(pn="B", status=1),
            _device(pn="C", status=3),
        ]
        coord, *_ = _make_coordinator(
            hass, devices=devices,
            options={"direct_request_protocol": True}, service=FakeService(),
        )
        active = await coord.get_active_devices()
        assert {d["pn"] for d in active} == {"A", "C"}

    async def test_filters_by_pn(self, hass):
        devices = [_device(pn="A"), _device(pn="B")]
        coord, *_ = _make_coordinator(
            hass, devices=devices,
            options={"direct_request_protocol": True, "devices": ["B"]},
            service=FakeService(),
        )
        active = await coord.get_active_devices()
        assert [d["pn"] for d in active] == ["B"]


# --------------------------------------------------------------------------- #
# _async_update_data
# --------------------------------------------------------------------------- #

class TestAsyncUpdateData:
    async def test_disabled_returns_none(self, hass):
        coord, *_ = _make_coordinator(
            hass, options={"direct_request_protocol": False}, service=FakeService()
        )
        assert await coord._async_update_data() is None

    async def test_missing_option_returns_none(self, hass):
        coord, *_ = _make_coordinator(hass, options={}, service=FakeService())
        assert await coord._async_update_data() is None

    async def test_axpert_one_query_per_section(self, hass):
        service = FakeService(replies={
            "QPIGS": {"v": "gs"},
            "QPIGS2": {"v": "gs2"},
            "QPIRI": {"v": "ri"},
        })
        coord, *_ = _make_coordinator(
            hass, options={"direct_request_protocol": True}, service=service
        )
        data = await coord._async_update_data()
        assert set(data) == {"PN1"}
        sections = data["PN1"]
        assert sections == {
            "qpigs": {"v": "gs"},
            "qpigs2": {"v": "gs2"},
            "qpiri": {"v": "ri"},
        }
        # Three distinct commands -> three queries.
        commands = sorted(c for _, c in service.calls)
        assert commands == ["QPIGS", "QPIGS2", "QPIRI"]

    async def test_pi18_single_query_split_into_sections(self, hass):
        # QPIGS used for both qpigs and qpigs2 -> one query, multi-section reply.
        service = FakeService(replies={
            "QPIGS": {"qpigs": {"pv1": 1}, "qpigs2": {"pv2": 2}},
            "QPIRI": {"rated": 5},
        })
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True, "direct_protocol": "pi18"},
            service=service,
        )
        data = await coord._async_update_data()
        sections = data["PN1"]
        assert sections["qpigs"] == {"pv1": 1}
        assert sections["qpigs2"] == {"pv2": 2}
        assert sections["qpiri"] == {"rated": 5}
        # QPIGS queried once despite serving two sections.
        qpigs_calls = [c for _, c in service.calls if c == "QPIGS"]
        assert len(qpigs_calls) == 1

    async def test_pi18_missing_subsection_becomes_empty_dict(self, hass):
        # Multi-section command but reply lacks one section.
        service = FakeService(replies={
            "QPIGS": {"qpigs": {"pv1": 1}},  # no qpigs2 key
            "QPIRI": {"rated": 5},
        })
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True, "direct_protocol": "pi18"},
            service=service,
        )
        data = await coord._async_update_data()
        assert data["PN1"]["qpigs"] == {"pv1": 1}
        assert data["PN1"]["qpigs2"] == {}

    async def test_smg2_no_qpigs2_section(self, hass):
        service = FakeService(replies={
            "QPIGS": {"v": "gs"},
            "QPIRI": {"v": "ri"},
        })
        coord, *_ = _make_coordinator(
            hass,
            options={"direct_request_protocol": True,
                     "direct_protocol": "smg2_modbus"},
            service=service,
        )
        data = await coord._async_update_data()
        assert set(data["PN1"]) == {"qpigs", "qpiri"}

    async def test_multiple_devices(self, hass):
        devices = [_device(pn="A"), _device(pn="B")]
        service = FakeService(default={"v": 1})
        coord, *_ = _make_coordinator(
            hass, devices=devices,
            options={"direct_request_protocol": True}, service=service,
        )
        data = await coord._async_update_data()
        assert set(data) == {"A", "B"}

    async def test_auth_error_invalidates_and_raises(self, hass):
        client = _make_client()
        client.devices.list = AsyncMock(side_effect=AuthError("err=10", code=10))
        coord, *_ = _make_coordinator(
            hass, options={"direct_request_protocol": True},
            service=FakeService(), client=client,
        )
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert client.session.invalidate.await_count == 1

    async def test_transport_error_becomes_update_failed(self, hass):
        client = _make_client()
        client.devices.list = AsyncMock(side_effect=TransportError("blip"))
        coord, *_ = _make_coordinator(
            hass, options={"direct_request_protocol": True},
            service=FakeService(), client=client,
        )
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert client.session.invalidate.await_count == 0
