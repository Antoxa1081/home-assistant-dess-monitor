"""Unit tests for ``coordinators.coordinator`` (MainCoordinator + pure helpers).

Pure helpers (``safe_call``, ``_clamp``, ``_action_of``) are exercised directly.
The coordinator tests build a real ``DeviceCache`` and a ``Mock`` client whose
async surface is driven by ``AsyncMock`` methods, with a ``MockConfigEntry``
added to ``hass`` so ``config_entry.options`` works.
"""
from __future__ import annotations

from unittest.mock import ANY, AsyncMock, Mock

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dess_monitor.coordinators import coordinator as coord_mod
from custom_components.dess_monitor.coordinators.coordinator import (
    MainCoordinator,
    _action_of,
    _clamp,
    _synchronized_snapshot_params,
    safe_call,
)
from custom_components.dess_monitor.device_cache import DeviceCache
from custom_components.dess_monitor.sdk import ApiError, AuthError, TransportError


def _device(pn="PN1", sn="SN1", devcode=2376, devaddr=1, status=0, uid="u1",
            devalias="Inv 1"):
    return {
        "pn": pn,
        "sn": sn,
        "devcode": devcode,
        "devaddr": devaddr,
        "status": status,
        "uid": uid,
        "devalias": devalias,
    }


def _make_client(devices=None):
    """A Mock client with the async surface MainCoordinator touches."""
    if devices is None:
        devices = [_device()]
    client = Mock()
    client.session.get_auth = AsyncMock(return_value={"token": "t"})
    client.session.invalidate = AsyncMock(return_value=None)
    client.devices.list = AsyncMock(return_value=devices)
    client.devices.last_data = AsyncMock(return_value={"ld": 1})
    client.devices.energy_flow = AsyncMock(return_value={"ef": 1})
    client.devices.pars = AsyncMock(return_value={"pars": 1})
    client.devices.fields = AsyncMock(return_value=_fields_response())
    client.devices.historical_data = AsyncMock(return_value=_history_response())
    client.control.get_fields = AsyncMock(return_value={"field": [{"id": "x"}]})
    client.control.get_value = AsyncMock(return_value={"val": "SBU"})
    return client


def _history_response(*, realtime=True):
    """Minimal devcode 6515 history payload from a Powland iSolar SMG III."""
    return {
        "title": [
            {"title": "Timestamp"},
            {"title": "INV Module Termperature", "unit": "°C"},
            {"title": "DC Module Termperature", "unit": "°C"},
            {"title": "Grid Voltage", "unit": "V"},
            {"title": "PV1 Power", "unit": "W"},
        ],
        "row": [
            {
                "realtime": realtime,
                "field": ["2026-11-13 13:31:06", "44", "32", "0.0", "944"],
            }
        ],
    }


def _fields_response():
    return [
        {"id": "eybond_read_22", "name": "INV Module Termperature"},
        {"id": "eybond_read_28", "name": "DC Module Termperature"},
        {"id": "eybond_read_33", "name": "Grid Voltage"},
        {"id": "eybond_read_45", "name": "PV1 Power"},
    ]


def _make_entry(hass, *, data=None, options=None):
    entry = MockConfigEntry(
        domain="dess_monitor",
        data=data or {"username": "tester", "password_hash": "0" * 40},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def _make_coordinator(hass, *, options=None, devices=None, client=None):
    entry = _make_entry(hass, options=options)
    client = client or _make_client(devices=devices)
    cache = DeviceCache(hass, entry.entry_id)
    coord = MainCoordinator(hass, entry, client, cache)
    return coord, entry, client, cache


# --------------------------------------------------------------------------- #
# safe_call
# --------------------------------------------------------------------------- #

class TestSafeCall:
    async def test_returns_awaited_value(self):
        async def ok():
            return 42

        assert await safe_call(ok()) == 42

    async def test_default_on_transport_error(self):
        async def boom():
            raise TransportError("wire down")

        assert await safe_call(boom(), default={"d": 1}) == {"d": 1}

    async def test_default_on_timeout(self):
        async def boom():
            raise TimeoutError()

        assert await safe_call(boom(), default="X") == "X"

    async def test_default_on_api_error(self):
        async def boom():
            raise ApiError("err=3", code=3)

        assert await safe_call(boom(), default=[]) == []

    async def test_auth_error_is_swallowed_as_api_error_subclass(self):
        # AuthError subclasses ApiError, so safe_call swallows it too.
        async def boom():
            raise AuthError("err=10", code=10)

        assert await safe_call(boom(), default=None) is None

    async def test_default_on_generic_exception(self):
        async def boom():
            raise ValueError("nope")

        assert await safe_call(boom(), default="fallback") == "fallback"

    async def test_default_defaults_to_none(self):
        async def boom():
            raise TransportError("x")

        assert await safe_call(boom()) is None


# --------------------------------------------------------------------------- #
# _action_of
# --------------------------------------------------------------------------- #

class TestActionOf:
    def test_uses_action_attribute(self):
        err = ApiError("boom", code=3, action="queryDeviceParsEs")
        assert _action_of(err) == "queryDeviceParsEs"

    def test_falls_back_to_class_name_when_action_none(self):
        err = TransportError("boom")
        assert _action_of(err) == "TransportError"

    def test_falls_back_for_plain_exception(self):
        assert _action_of(ValueError("x")) == "ValueError"


# --------------------------------------------------------------------------- #
# _clamp
# --------------------------------------------------------------------------- #

class TestClamp:
    def test_within_range(self):
        assert _clamp(50, 30, 900) == 50

    def test_below_low(self):
        assert _clamp(5, 30, 900) == 30

    def test_above_high(self):
        assert _clamp(5000, 30, 900) == 900

    def test_float_truncates_via_int(self):
        assert _clamp(60.9, 30, 900) == 60

    def test_numeric_string_coerced(self):
        assert _clamp("45", 30, 900) == 45

    def test_non_numeric_returns_low(self):
        assert _clamp("abc", 30, 900) == 30

    def test_none_returns_low(self):
        assert _clamp(None, 30, 900) == 30


# --------------------------------------------------------------------------- #
# Powland iSolar SMG III synchronized snapshot parsing
# --------------------------------------------------------------------------- #

class TestSynchronizedSnapshotParams:
    def test_extracts_dynamic_metrics_with_provider_ids_and_timestamp(self):
        assert _synchronized_snapshot_params(_history_response(), _fields_response()) == {
            "parameter": [
                {
                    "id": "eybond_read_22",
                    "par": "INV Module Termperature",
                    "val": "44",
                    "unit": "°C",
                },
                {
                    "id": "eybond_read_28",
                    "par": "DC Module Termperature",
                    "val": "32",
                    "unit": "°C",
                },
                {
                    "id": "eybond_read_33",
                    "par": "Grid Voltage",
                    "val": "0.0",
                    "unit": "V",
                },
                {
                    "id": "eybond_read_45",
                    "par": "PV1 Power",
                    "val": "944",
                    "unit": "W",
                },
            ],
            "gts": "2026-11-13 13:31:06",
        }

    def test_prefers_realtime_row(self):
        history = _history_response(realtime=False)
        history["row"].insert(
            0,
            {
                "realtime": False,
                "field": ["old", "40", "30", "229", "800"],
            },
        )
        history["row"].append(
            {
                "realtime": True,
                "field": ["now", "45", "33", "230", "900"],
            },
        )
        snapshot = _synchronized_snapshot_params(history, _fields_response())
        assert snapshot["gts"] == "now"
        assert [param["val"] for param in snapshot["parameter"]] == [
            "45", "33", "230", "900"
        ]

    @pytest.mark.parametrize("history", [{}, {"title": [], "row": []}, {"title": [], "row": [{}]}])
    def test_malformed_or_empty_payload_returns_empty(self, history):
        assert _synchronized_snapshot_params(history, _fields_response()) == {}


# --------------------------------------------------------------------------- #
# MainCoordinator construction / update interval clamping
# --------------------------------------------------------------------------- #

class TestInterval:
    def test_default_interval(self, hass):
        coord, *_ = _make_coordinator(hass)
        assert coord.update_interval.total_seconds() == 60

    def test_interval_clamped_below_min(self, hass):
        coord, *_ = _make_coordinator(hass, options={"main_update_interval": 1})
        assert coord.update_interval.total_seconds() == 30

    def test_interval_clamped_above_max(self, hass):
        coord, *_ = _make_coordinator(hass, options={"main_update_interval": 99999})
        assert coord.update_interval.total_seconds() == 900

    def test_interval_non_numeric_falls_to_min(self, hass):
        coord, *_ = _make_coordinator(hass, options={"main_update_interval": "x"})
        assert coord.update_interval.total_seconds() == 30


# --------------------------------------------------------------------------- #
# get_active_devices
# --------------------------------------------------------------------------- #

class TestGetActiveDevices:
    async def test_filters_status_1(self, hass):
        devices = [
            _device(pn="A", uid="ua", status=0),
            _device(pn="B", uid="ub", status=1),  # inactive
            _device(pn="C", uid="uc", status=2),
        ]
        coord, *_ = _make_coordinator(hass, devices=devices)
        active = await coord.get_active_devices()
        pns = {d["pn"] for d in active}
        assert pns == {"A", "C"}

    async def test_filters_by_options_devices_pn(self, hass):
        devices = [
            _device(pn="A", uid="ua"),
            _device(pn="B", uid="ub"),
        ]
        coord, *_ = _make_coordinator(
            hass, devices=devices, options={"devices": ["A"]}
        )
        active = await coord.get_active_devices()
        assert [d["pn"] for d in active] == ["A"]

    async def test_filters_by_options_devices_uid(self, hass):
        devices = [
            _device(pn="A", uid="ua"),
            _device(pn="B", uid="ub"),
        ]
        coord, *_ = _make_coordinator(
            hass, devices=devices, options={"devices": ["ub"]}
        )
        active = await coord.get_active_devices()
        assert [d["pn"] for d in active] == ["B"]

    async def test_empty_devices_filter_returns_all_active(self, hass):
        devices = [_device(pn="A", uid="ua"), _device(pn="B", uid="ub")]
        coord, *_ = _make_coordinator(
            hass, devices=devices, options={"devices": []}
        )
        active = await coord.get_active_devices()
        assert {d["pn"] for d in active} == {"A", "B"}


# --------------------------------------------------------------------------- #
# _get_pars_cached
# --------------------------------------------------------------------------- #

class TestGetParsCached:
    async def test_first_call_fetches(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        identity = coord_mod.DeviceIdentity.from_dict(_device())
        result = await coord._get_pars_cached("PN1", identity)
        assert result == {"pars": 1}
        assert client.devices.pars.call_count == 1

    async def test_second_call_within_window_uses_cache(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        identity = coord_mod.DeviceIdentity.from_dict(_device())
        await coord._get_pars_cached("PN1", identity)
        result2 = await coord._get_pars_cached("PN1", identity)
        assert result2 == {"pars": 1}
        assert client.devices.pars.call_count == 1  # not re-fetched

    async def test_stale_cache_returned_when_fetch_returns_none(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        identity = coord_mod.DeviceIdentity.from_dict(_device())
        # Prime cache.
        await coord._get_pars_cached("PN1", identity)
        # Force the refresh window open and make the fetch yield None.
        coord._pars_refresh_seconds = 0
        client.devices.pars = AsyncMock(return_value=None)
        result = await coord._get_pars_cached("PN1", identity)
        assert result == {"pars": 1}  # stale value preserved

    async def test_returns_empty_when_fetch_fails_and_no_cache(self, hass):
        client = _make_client()
        client.devices.pars = AsyncMock(side_effect=TransportError("down"))
        coord, *_ = _make_coordinator(hass, client=client)
        identity = coord_mod.DeviceIdentity.from_dict(_device())
        result = await coord._get_pars_cached("PN1", identity)
        assert result == {}

    async def test_returns_empty_when_fetch_returns_none_and_no_cache(self, hass):
        client = _make_client()
        client.devices.pars = AsyncMock(return_value=None)
        coord, *_ = _make_coordinator(hass, client=client)
        identity = coord_mod.DeviceIdentity.from_dict(_device())
        result = await coord._get_pars_cached("PN1", identity)
        assert result == {}


# --------------------------------------------------------------------------- #
# _get_synchronized_snapshot_cached
# --------------------------------------------------------------------------- #

class TestGetSynchronizedSnapshotCached:
    async def test_first_call_fetches_fields_and_history_then_uses_cache(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        identity = coord_mod.DeviceIdentity.from_dict(_device(devcode=6515))

        first = await coord._get_synchronized_snapshot_cached("PN1", identity)
        second = await coord._get_synchronized_snapshot_cached("PN1", identity)

        assert first == second
        assert first["gts"] == "2026-11-13 13:31:06"
        assert first["parameter"][0]["id"] == "eybond_read_22"
        client.devices.fields.assert_awaited_once_with(identity)
        client.devices.historical_data.assert_awaited_once_with(
            identity, ANY, page=0, pagesize=1
        )

    async def test_stale_value_survives_transient_failure(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        identity = coord_mod.DeviceIdentity.from_dict(_device(devcode=6515))
        first = await coord._get_synchronized_snapshot_cached("PN1", identity)
        coord._synchronized_snapshot_fetched_at["PN1"] = 0
        client.devices.historical_data = AsyncMock(side_effect=TransportError("down"))

        assert await coord._get_synchronized_snapshot_cached("PN1", identity) == first
        assert client.devices.fields.await_count == 1

# --------------------------------------------------------------------------- #
# _async_update_data
# --------------------------------------------------------------------------- #

class TestAsyncUpdateData:
    async def test_happy_path_shape(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        data = await coord._async_update_data()
        assert set(data.keys()) == {"PN1"}
        entry = data["PN1"]
        assert set(entry.keys()) == {
            "last_data", "energy_flow", "pars", "device",
            "ctrl_fields", "device_extra",
        }
        assert entry["last_data"] == {"ld": 1}
        assert entry["energy_flow"] == {"ef": 1}
        assert entry["pars"] == {"pars": 1}
        assert entry["device"]["pn"] == "PN1"
        assert entry["ctrl_fields"] == [{"id": "x"}]
        # devcode 2376 -> output priority resolver returns None without a call.
        assert entry["device_extra"] == {"output_priority": None}
        client.devices.historical_data.assert_not_awaited()
        client.devices.fields.assert_not_awaited()

    async def test_devcode_6515_prioritizes_synchronized_snapshot(self, hass):
        coord, _, client, _ = _make_coordinator(hass, devices=[_device(devcode=6515)])
        data = await coord._async_update_data()

        entry = data["PN1"]
        assert next(iter(entry)) == "synchronized_snapshot"
        snapshot = entry["synchronized_snapshot"]
        assert snapshot["gts"] == "2026-11-13 13:31:06"
        assert [param["id"] for param in snapshot["parameter"]] == [
            "eybond_read_22",
            "eybond_read_28",
            "eybond_read_33",
            "eybond_read_45",
        ]
        client.devices.historical_data.assert_awaited_once()
        client.devices.fields.assert_awaited_once()

    async def test_stale_live_data_reused(self, hass):
        coord, _, client, _ = _make_coordinator(hass)
        # First tick: real data populates _last_device_data.
        first = await coord._async_update_data()
        assert first["PN1"]["last_data"] == {"ld": 1}
        # Second tick: live calls come back empty; within STALE window the
        # previous tick's values are reused.
        client.devices.last_data = AsyncMock(return_value={})
        client.devices.energy_flow = AsyncMock(return_value={})
        second = await coord._async_update_data()
        assert second["PN1"]["last_data"] == {"ld": 1}
        assert second["PN1"]["energy_flow"] == {"ef": 1}

    async def test_auth_error_invalidates_and_raises_update_failed(self, hass):
        client = _make_client()
        # AuthError raised at the top level (get_active_devices -> devices.list).
        client.devices.list = AsyncMock(side_effect=AuthError("err=10", code=10))
        coord, *_ = _make_coordinator(hass, client=client)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert client.session.invalidate.await_count == 1

    async def test_transport_error_becomes_update_failed(self, hass):
        client = _make_client()
        client.devices.list = AsyncMock(side_effect=TransportError("blip"))
        coord, *_ = _make_coordinator(hass, client=client)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert client.session.invalidate.await_count == 0

    async def test_api_error_becomes_update_failed(self, hass):
        client = _make_client()
        client.devices.list = AsyncMock(side_effect=ApiError("err=6000", code=6000))
        coord, *_ = _make_coordinator(hass, client=client)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert client.session.invalidate.await_count == 0
