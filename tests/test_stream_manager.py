"""Tests for ``stream_manager.DeviceStreamManager``.

A fake client yields canned :class:`StreamFrame`s through a fake stream; the
manager folds them into a fake coordinator's ``data`` (under ``ws_data`` /
``ws_received_at``) after the debounce timer fires, then calls
``async_update_listeners``. No real WebSocket is opened.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.dess_monitor.const import WEBSOCKET_REFRESH_DEBOUNCE_SECONDS
from custom_components.dess_monitor.sdk.models import DeviceIdentity
from custom_components.dess_monitor.sdk.streaming import StreamFrame
from custom_components.dess_monitor.stream_manager import DeviceStreamManager


def _device(pn: str = "PN1") -> dict[str, Any]:
    return {"devaddr": 1, "devcode": 2376, "pn": pn, "sn": "SN1"}


class FakeStream:
    """Async-iterable fake :class:`DeviceStream`.

    ``frames`` are dicts (frame ``data`` payloads). After yielding them the
    iterator blocks forever (until cancelled) to mimic a live stream that the
    manager tears down via task.cancel() / stream.stop().
    """

    def __init__(self, identity: DeviceIdentity, frames: list[dict[str, Any]]) -> None:
        self._identity = identity
        self._frames = list(frames)
        self.started = False
        self.stopped = False

    @property
    def identity(self) -> DeviceIdentity:
        return self._identity

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def __aiter__(self) -> FakeStream:
        self._it = iter(self._frames)
        return self

    async def __anext__(self) -> StreamFrame:
        try:
            data = next(self._it)
        except StopIteration:
            # block until cancelled — emulates an idle-but-open stream
            await asyncio.Event().wait()
            raise StopAsyncIteration from None  # pragma: no cover
        return StreamFrame(
            device_pn=str(self._identity.pn), received_at=0.0, data=data
        )


class FakeClient:
    def __init__(self, frames_by_pn: dict[str, list[dict[str, Any]]]) -> None:
        self._frames_by_pn = frames_by_pn
        self.streams: dict[str, FakeStream] = {}

    def stream_device(self, identity: DeviceIdentity, **kwargs: Any) -> FakeStream:
        frames = self._frames_by_pn.get(str(identity.pn), [])
        stream = FakeStream(identity, frames)
        self.streams[str(identity.pn)] = stream
        return stream


class FakeCoordinator:
    """Minimal stand-in for MainCoordinator: just the attributes the manager uses."""

    def __init__(self, devices: list[dict[str, Any]], data: dict[str, Any]) -> None:
        self.devices = devices
        self.data = data
        self.last_update_success = False
        self.update_calls = 0

    def async_update_listeners(self) -> None:
        self.update_calls += 1


def _make_manager(
    hass: Any,
    *,
    devices: list[dict[str, Any]],
    coord_data: dict[str, Any],
    frames_by_pn: dict[str, list[dict[str, Any]]],
) -> tuple[DeviceStreamManager, FakeClient, FakeCoordinator]:
    client = FakeClient(frames_by_pn)
    coordinator = FakeCoordinator(devices, coord_data)
    manager = DeviceStreamManager(hass, client, coordinator)  # type: ignore[arg-type]
    return manager, client, coordinator


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within timeout")


class TestStart:
    async def test_starts_one_stream_per_device(self, hass: Any) -> None:
        devices = [_device("PN1"), _device("PN2")]
        manager, client, _coord = _make_manager(
            hass,
            devices=devices,
            coord_data={"PN1": {}, "PN2": {}},
            frames_by_pn={},
        )
        await manager.async_start()
        try:
            assert set(manager._streams) == {"PN1", "PN2"}
            assert client.streams["PN1"].started is True
            assert client.streams["PN2"].started is True
            assert set(manager._tasks) == {"PN1", "PN2"}
        finally:
            await manager.async_stop()

    async def test_start_is_idempotent(self, hass: Any) -> None:
        manager, client, _ = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"PN1": {}},
            frames_by_pn={},
        )
        await manager.async_start()
        try:
            first = dict(manager._streams)
            await manager.async_start()  # streams already present -> no-op
            assert manager._streams == first
            assert len(client.streams) == 1
        finally:
            await manager.async_stop()

    async def test_skips_device_with_bad_identity(self, hass: Any) -> None:
        # missing 'sn' -> DeviceIdentity.from_dict raises KeyError -> skipped
        bad = {"devaddr": 1, "devcode": 2376, "pn": "PNBAD"}
        manager, client, _ = _make_manager(
            hass,
            devices=[bad, _device("PN1")],
            coord_data={"PN1": {}},
            frames_by_pn={},
        )
        await manager.async_start()
        try:
            assert "PNBAD" not in manager._streams
            assert "PN1" in manager._streams
        finally:
            await manager.async_stop()


class TestFrameMerge:
    async def test_frame_updates_coordinator_after_debounce(self, hass: Any) -> None:
        coord_data = {"PN1": {"existing": "kept"}}
        manager, _client, coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data=coord_data,
            frames_by_pn={"PN1": [{"power": 100}]},
        )
        await manager.async_start()
        try:
            # within the debounce window nothing has been pushed yet
            await _wait_for(lambda: "PN1" in manager._pending)
            # after the debounce timer fires the coordinator gets a NEW dict
            await _wait_for(lambda: coord.update_calls >= 1)
            assert coord.last_update_success is True
            entry = coord.data["PN1"]
            assert entry["ws_data"] == {"power": 100}
            assert "ws_received_at" in entry
            assert entry["existing"] == "kept"  # polled subtree preserved
            # a NEW top-level dict reference was installed
            assert coord.data is not coord_data
        finally:
            await manager.async_stop()

    async def test_multiple_frames_merge_into_ws_data(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"PN1": {}},
            frames_by_pn={"PN1": [{"a": 1}, {"b": 2}]},
        )
        await manager.async_start()
        try:
            await _wait_for(lambda: coord.update_calls >= 1)
            # both frames arrived inside one debounce window -> merged
            await _wait_for(
                lambda: coord.data["PN1"].get("ws_data") == {"a": 1, "b": 2}
            )
            assert coord.data["PN1"]["ws_data"] == {"a": 1, "b": 2}
        finally:
            await manager.async_stop()

    async def test_merge_noop_when_pn_absent_from_coord_data(self, hass: Any) -> None:
        # device PN1 streams a frame but coordinator.data has no PN1 entry
        manager, _client, coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"OTHER": {}},
            frames_by_pn={"PN1": [{"x": 1}]},
        )
        await manager.async_start()
        try:
            await asyncio.sleep(WEBSOCKET_REFRESH_DEBOUNCE_SECONDS + 0.2)
            # _merge_frame returns early -> nothing pending, no refresh pushed
            assert "PN1" not in manager._pending
            assert coord.update_calls == 0
        finally:
            await manager.async_stop()

    async def test_merge_noop_when_coord_data_not_dict(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        coord.data = None  # type: ignore[assignment]
        manager._merge_frame("PN1", {"x": 1})
        assert manager._pending == {}
        assert manager._dirty_pns == set()

    async def test_merge_noop_when_device_entry_not_dict(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": "not-a-dict"}, frames_by_pn={}
        )
        manager._merge_frame("PN1", {"x": 1})
        assert "PN1" not in manager._pending

    async def test_merge_direct_call_preserves_prior_ws_data(self, hass: Any) -> None:
        """Unit-level: _merge_frame folds new data over the device entry's
        existing ws_data when there is no pending buffer yet."""
        manager, _client, coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"PN1": {"ws_data": {"old": 1}}},
            frames_by_pn={},
        )
        manager._merge_frame("PN1", {"new": 2})
        assert manager._pending["PN1"]["ws_data"] == {"old": 1, "new": 2}
        assert "PN1" in manager._dirty_pns
        # clean up the scheduled timer handle
        if manager._refresh_handle is not None:
            manager._refresh_handle.cancel()


class TestDispatch:
    async def test_dispatch_noop_when_no_dirty(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        manager._dirty_pns = set()
        manager._dispatch_refresh()
        assert coord.update_calls == 0

    async def test_dispatch_noop_when_stopped(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        manager._dirty_pns = {"PN1"}
        manager._stopped = True
        manager._dispatch_refresh()
        assert coord.update_calls == 0

    async def test_dispatch_skips_pn_missing_from_coord_data(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        manager._pending = {
            "PN1": {"ws_data": {"a": 1}, "ws_received_at": 0.0},
            "GONE": {"ws_data": {"b": 2}, "ws_received_at": 0.0},
        }
        manager._dirty_pns = {"PN1", "GONE"}
        manager._dispatch_refresh()
        assert coord.update_calls == 1
        assert coord.data["PN1"]["ws_data"] == {"a": 1}
        assert "GONE" not in coord.data

    async def test_dispatch_skips_dirty_pn_without_pending_patch(
        self, hass: Any
    ) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        # dirty but no matching pending entry -> patch is None -> skipped
        manager._dirty_pns = {"PN1"}
        manager._pending = {}
        manager._dispatch_refresh()
        # still pushes a refresh (dirty was non-empty) but no ws_data merged
        assert coord.update_calls == 1
        assert "ws_data" not in coord.data["PN1"]

    async def test_dispatch_clears_pending_when_coord_data_not_dict(
        self, hass: Any
    ) -> None:
        manager, _client, coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        coord.data = None  # type: ignore[assignment]
        manager._pending = {"PN1": {"ws_data": {"a": 1}, "ws_received_at": 0.0}}
        manager._dirty_pns = {"PN1"}
        manager._dispatch_refresh()
        assert manager._pending == {}
        assert coord.update_calls == 0


class TestConsumer:
    async def test_consumer_swallows_stream_exception(self, hass: Any) -> None:
        """If the stream iterator raises a non-Cancelled error, _consume logs
        and returns cleanly rather than propagating."""
        manager, _client, coord = _make_manager(
            hass, devices=[_device("PN1")], coord_data={"PN1": {}}, frames_by_pn={}
        )

        class BoomStream(FakeStream):
            async def __anext__(self) -> StreamFrame:
                raise RuntimeError("stream blew up")

        boom = BoomStream(
            DeviceIdentity(devaddr=1, devcode=2376, pn="PN1", sn="SN1"), []
        )
        await manager._consume("PN1", boom)  # should not raise
        # nothing merged
        assert "PN1" not in manager._pending

    async def test_consumer_stops_when_manager_stopped(self, hass: Any) -> None:
        """A frame arriving after the manager is stopped is not merged."""
        manager, _client, coord = _make_manager(
            hass, devices=[_device("PN1")], coord_data={"PN1": {}}, frames_by_pn={}
        )
        manager._stopped = True
        stream = FakeStream(
            DeviceIdentity(devaddr=1, devcode=2376, pn="PN1", sn="SN1"),
            [{"a": 1}],
        )
        await manager._consume("PN1", stream)
        assert "PN1" not in manager._pending


class TestStop:
    async def test_stop_cancels_tasks_and_stops_streams(self, hass: Any) -> None:
        manager, client, _coord = _make_manager(
            hass,
            devices=[_device("PN1"), _device("PN2")],
            coord_data={"PN1": {}, "PN2": {}},
            frames_by_pn={},
        )
        await manager.async_start()
        tasks = list(manager._tasks.values())
        await manager.async_stop()
        assert manager._stopped is True
        assert manager._streams == {}
        assert manager._tasks == {}
        assert client.streams["PN1"].stopped is True
        assert client.streams["PN2"].stopped is True
        assert all(t.done() for t in tasks)

    async def test_stop_cancels_pending_refresh_timer(self, hass: Any) -> None:
        manager, _client, coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"PN1": {}},
            frames_by_pn={"PN1": [{"a": 1}]},
        )
        await manager.async_start()
        # let a frame arrive and schedule the debounce timer
        await _wait_for(lambda: manager._refresh_handle is not None or coord.update_calls >= 1)
        await manager.async_stop()
        assert manager._refresh_handle is None
        assert manager._pending == {}
        assert manager._dirty_pns == set()

    async def test_stop_swallows_stream_stop_error(self, hass: Any) -> None:
        """If a stream's stop() raises, async_stop logs and continues to the rest."""
        manager, client, _coord = _make_manager(
            hass,
            devices=[_device("PN1")],
            coord_data={"PN1": {}},
            frames_by_pn={},
        )
        await manager.async_start()

        async def boom() -> None:
            raise RuntimeError("stop failed")

        client.streams["PN1"].stop = boom  # type: ignore[assignment]
        await manager.async_stop()  # exception caught -> no raise
        assert manager._streams == {}

    async def test_stop_idempotent_when_never_started(self, hass: Any) -> None:
        manager, _client, _coord = _make_manager(
            hass, devices=[], coord_data={}, frames_by_pn={}
        )
        await manager.async_stop()  # no tasks/streams -> no error
        assert manager._stopped is True

    async def test_schedule_refresh_noop_after_stop(self, hass: Any) -> None:
        manager, _client, _coord = _make_manager(
            hass, devices=[], coord_data={"PN1": {}}, frames_by_pn={}
        )
        manager._stopped = True
        manager._schedule_refresh()
        assert manager._refresh_handle is None
