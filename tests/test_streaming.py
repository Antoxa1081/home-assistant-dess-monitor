"""Tests for ``sdk.streaming`` — :class:`DeviceStream` + its reconnect loop.

No real socket is ever opened: ``aiohttp.ClientSession.ws_connect`` is patched
to return a fake async-context-manager WebSocket that yields canned frames.
Every test is bounded — the fake ws yields a finite number of frames then
breaks/raises, and the stream is always stopped at the end.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.dess_monitor.sdk.models import DeviceIdentity
from custom_components.dess_monitor.sdk.streaming import (
    DEFAULT_BASE_HOST,
    DEFAULT_WS_PATH,
    DeviceStream,
    StreamFrame,
)


def _identity() -> DeviceIdentity:
    return DeviceIdentity(devaddr=1, devcode=2376, pn="PN123", sn="SN456")


class FakeMsg:
    """Stand-in for an aiohttp WSMessage."""

    def __init__(self, msg_type: aiohttp.WSMsgType, data: Any = None) -> None:
        self.type = msg_type
        self.data = data

    def json(self) -> Any:
        return json.loads(self.data)


class FakeWS:
    """Async-iterable, async-context-manager fake WebSocket.

    ``frames`` is a list of FakeMsg (or exceptions to raise mid-iteration).
    ``exception`` backs ``ws.exception()`` for the ERROR branch.
    """

    def __init__(self, frames: list[Any], exception: BaseException | None = None) -> None:
        self._frames = frames
        self._exc = exception
        self.send_json = AsyncMock()
        self.send_str = AsyncMock()
        self.receive = AsyncMock()
        self.close = AsyncMock()
        self.closed = False

    def exception(self) -> BaseException | None:
        return self._exc

    async def __aenter__(self) -> FakeWS:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __aiter__(self) -> FakeWS:
        self._it = iter(self._frames)
        return self

    async def __anext__(self) -> FakeMsg:
        try:
            item = next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(item, BaseException):
            raise item
        return item


def _patch_ws_connect(stream: DeviceStream, fake_ws_factory: Any) -> Any:
    """Patch the stream's session ``ws_connect`` to return ``fake_ws_factory()``.

    The source calls ``self._session.ws_connect(url, headers=..., heartbeat=...,
    autoping=True)`` and uses the result as an ``async with`` context manager,
    so ``ws_connect`` is a *plain* (non-async) function returning an async CM.
    """
    session = MagicMock()
    session.ws_connect = MagicMock(side_effect=lambda *a, **k: fake_ws_factory())
    session.close = AsyncMock()
    stream._session = session
    stream._owns_session = False
    return session


# --------------------------------------------------------------------------- #
# Pure helpers: url / _parse / _enqueue                                       #
# --------------------------------------------------------------------------- #
class TestUrl:
    def test_url_uses_wss_base_host_and_params(self) -> None:
        stream = DeviceStream(_identity())
        url = stream.url
        assert url.startswith(f"wss://{DEFAULT_BASE_HOST}{DEFAULT_WS_PATH}?")
        assert "pn=PN123" in url
        assert "sn=SN456" in url
        assert "devaddr=1" in url
        assert "devcode=2376" in url

    def test_identity_property(self) -> None:
        ident = _identity()
        assert DeviceStream(ident).identity is ident

    def test_custom_base_and_path(self) -> None:
        stream = DeviceStream(_identity(), base_host="alt.example", ws_path="/x")
        assert stream.url.startswith("wss://alt.example/x?")


class TestParse:
    def test_parse_plain_dict_data(self) -> None:
        stream = DeviceStream(_identity())
        frame = stream._parse(json.dumps({"data": {"a": 1, "b": 2}}))
        assert isinstance(frame, StreamFrame)
        assert frame.device_pn == "PN123"
        assert frame.data == {"a": 1, "b": 2}
        assert frame.received_at > 0

    def test_parse_stringified_inner_data(self) -> None:
        stream = DeviceStream(_identity())
        frame = stream._parse(json.dumps({"data": json.dumps({"k": "v"})}))
        assert frame is not None
        assert frame.data == {"k": "v"}

    def test_parse_invalid_outer_json_returns_none(self) -> None:
        stream = DeviceStream(_identity())
        assert stream._parse("not json {") is None

    def test_parse_inner_data_not_json_returns_none(self) -> None:
        stream = DeviceStream(_identity())
        assert stream._parse(json.dumps({"data": "definitely not json {"})) is None

    def test_parse_non_dict_outer_returns_none(self) -> None:
        stream = DeviceStream(_identity())
        assert stream._parse(json.dumps([1, 2, 3])) is None

    def test_parse_missing_data_key_returns_none(self) -> None:
        stream = DeviceStream(_identity())
        assert stream._parse(json.dumps({"other": 1})) is None

    def test_parse_data_not_dict_after_decode_returns_none(self) -> None:
        stream = DeviceStream(_identity())
        # inner "data" decodes to a list -> not a dict -> None
        assert stream._parse(json.dumps({"data": json.dumps([1, 2])})) is None


class TestEnqueue:
    def test_enqueue_appends(self) -> None:
        stream = DeviceStream(_identity())
        frame = StreamFrame(device_pn="PN123", received_at=1.0, data={"x": 1})
        stream._enqueue(frame)
        assert stream._queue.qsize() == 1

    def test_enqueue_full_then_emptied_race(self) -> None:
        """If the queue reports full then is drained before get_nowait (race),
        the QueueEmpty is swallowed and the frame still lands."""
        stream = DeviceStream(_identity(), queue_maxsize=1)
        f1 = StreamFrame(device_pn="PN123", received_at=1.0, data={"n": 1})

        real_put = stream._queue.put_nowait
        state = {"raised": False}

        def fake_put(item: Any) -> None:
            if not state["raised"]:
                state["raised"] = True
                raise asyncio.QueueFull
            real_put(item)

        # get_nowait raises QueueEmpty (queue already empty) -> swallowed branch
        stream._queue.put_nowait = fake_put  # type: ignore[assignment]
        stream._enqueue(f1)
        assert stream._queue.qsize() == 1

    def test_enqueue_drops_oldest_when_full(self) -> None:
        stream = DeviceStream(_identity(), queue_maxsize=2)
        f1 = StreamFrame(device_pn="PN123", received_at=1.0, data={"n": 1})
        f2 = StreamFrame(device_pn="PN123", received_at=2.0, data={"n": 2})
        f3 = StreamFrame(device_pn="PN123", received_at=3.0, data={"n": 3})
        stream._enqueue(f1)
        stream._enqueue(f2)
        stream._enqueue(f3)  # queue full -> drops f1
        assert stream._queue.qsize() == 2
        first = stream._queue.get_nowait()
        assert first.data == {"n": 2}


# --------------------------------------------------------------------------- #
# __anext__ guard / start / stop lifecycle                                    #
# --------------------------------------------------------------------------- #
class TestLifecycle:
    async def test_anext_before_start_raises(self) -> None:
        stream = DeviceStream(_identity())
        with pytest.raises(RuntimeError, match="not started"):
            await stream.__anext__()

    async def test_start_is_idempotent(self) -> None:
        stream = DeviceStream(_identity(), http_session=MagicMock())
        try:
            with patch.object(stream, "_run", new=AsyncMock()):
                await stream.start()
                first_task = stream._task
                await stream.start()
                assert stream._task is first_task
        finally:
            await stream.stop()

    async def test_start_creates_owned_session_when_none(self) -> None:
        stream = DeviceStream(_identity())
        with patch.object(stream, "_run", new=AsyncMock()), patch(
            "aiohttp.ClientSession"
        ) as ses_cls:
            ses_cls.return_value.close = AsyncMock()
            await stream.start()
            assert stream._session is not None
            ses_cls.assert_called_once()
        await stream.stop()
        # owned session is closed and cleared on stop
        assert stream._session is None

    async def test_stop_when_never_started_no_error(self) -> None:
        stream = DeviceStream(_identity(), http_session=MagicMock())
        await stream.stop()  # no task -> just sets stop event
        assert stream._stop.is_set()

    async def test_stop_does_not_close_borrowed_session(self) -> None:
        session = MagicMock()
        session.close = AsyncMock()
        stream = DeviceStream(_identity(), http_session=session)
        with patch.object(stream, "_run", new=AsyncMock()):
            await stream.start()
        await stream.stop()
        session.close.assert_not_called()


# --------------------------------------------------------------------------- #
# End-to-end iteration through the real _run / _connect_and_consume loop      #
# --------------------------------------------------------------------------- #
class TestIteration:
    async def test_yields_text_frames_then_stops(self) -> None:
        stream = DeviceStream(_identity(), http_session=MagicMock())

        frames = [
            FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"a": 1}})),
            FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"b": 2}})),
            # CLOSED breaks the inner loop; _run will try to reconnect, but
            # we stop the stream after collecting frames so the loop ends.
            FakeMsg(aiohttp.WSMsgType.CLOSED),
        ]
        _patch_ws_connect(stream, lambda: FakeWS(list(frames)))

        await stream.start()
        try:
            got1 = await asyncio.wait_for(stream.__anext__(), timeout=5)
            got2 = await asyncio.wait_for(stream.__anext__(), timeout=5)
            assert got1.data == {"a": 1}
            assert got2.data == {"b": 2}
        finally:
            await stream.stop()

    async def test_async_with_and_async_for(self) -> None:
        ident = _identity()
        stream = DeviceStream(ident, http_session=MagicMock())
        frames = [
            FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"v": 10}})),
            FakeMsg(aiohttp.WSMsgType.CLOSED),
        ]
        _patch_ws_connect(stream, lambda: FakeWS(list(frames)))

        collected: list[dict[str, Any]] = []

        async def _drain() -> None:
            async with stream as s:
                async for frame in s:
                    collected.append(frame.data)
                    if len(collected) >= 1:
                        # stop from inside; __aexit__ also calls stop()
                        break

        await asyncio.wait_for(_drain(), timeout=5)
        assert collected == [{"v": 10}]

    async def test_non_text_non_error_frames_ignored(self) -> None:
        """A frame whose parse returns None (bad JSON) is not enqueued."""
        stream = DeviceStream(_identity(), http_session=MagicMock())
        frames = [
            FakeMsg(aiohttp.WSMsgType.TEXT, "garbage-not-json"),
            FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"ok": 1}})),
            FakeMsg(aiohttp.WSMsgType.CLOSED),
        ]
        _patch_ws_connect(stream, lambda: FakeWS(list(frames)))
        await stream.start()
        try:
            got = await asyncio.wait_for(stream.__anext__(), timeout=5)
            # the garbage frame was dropped; first delivered is the valid one
            assert got.data == {"ok": 1}
        finally:
            await stream.stop()

    async def test_stop_unblocks_pending_anext(self) -> None:
        """__anext__ waiting on an empty queue returns StopAsyncIteration on stop."""
        stream = DeviceStream(_identity(), http_session=MagicMock())
        # ws never yields anything (empty), inner loop ends -> reconnect waits.
        _patch_ws_connect(stream, lambda: FakeWS([FakeMsg(aiohttp.WSMsgType.CLOSED)]))
        await stream.start()

        async def _consume() -> str:
            try:
                await stream.__anext__()
                return "frame"
            except StopAsyncIteration:
                return "stopped"

        consumer = asyncio.ensure_future(_consume())
        await asyncio.sleep(0.05)  # let it block on the empty queue
        await stream.stop()
        result = await asyncio.wait_for(consumer, timeout=5)
        assert result == "stopped"


# --------------------------------------------------------------------------- #
# Reconnect loop behaviour (_run)                                             #
# --------------------------------------------------------------------------- #
class TestReconnectLoop:
    async def test_error_frame_raises_and_triggers_reconnect(self) -> None:
        """A WSMsgType.ERROR frame raises ws.exception() inside consume; _run
        catches it, then backs off. We use a tiny backoff and stop quickly."""
        stream = DeviceStream(
            _identity(),
            http_session=MagicMock(),
            initial_backoff_seconds=0.05,
            max_backoff_seconds=0.05,
        )

        boom = RuntimeError("ws error")
        calls = {"n": 0}

        def factory() -> FakeWS:
            calls["n"] += 1
            if calls["n"] == 1:
                # first connection: deliver one frame then an ERROR
                return FakeWS(
                    [
                        FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"a": 1}})),
                        FakeMsg(aiohttp.WSMsgType.ERROR),
                    ],
                    exception=boom,
                )
            # subsequent reconnect: idle then closed
            return FakeWS([FakeMsg(aiohttp.WSMsgType.CLOSED)])

        _patch_ws_connect(stream, factory)
        await stream.start()
        try:
            got = await asyncio.wait_for(stream.__anext__(), timeout=5)
            assert got.data == {"a": 1}
            # give the loop time to hit the ERROR, back off, and reconnect
            await asyncio.sleep(0.2)
            assert calls["n"] >= 2  # reconnected at least once
        finally:
            await stream.stop()

    async def test_exception_during_connect_is_caught_and_retried(self) -> None:
        """ws_connect raising (e.g. connection refused) is caught by _run; the
        loop backs off and retries rather than crashing the task."""
        stream = DeviceStream(
            _identity(),
            http_session=MagicMock(),
            initial_backoff_seconds=0.05,
            max_backoff_seconds=0.05,
        )
        calls = {"n": 0}

        def factory() -> FakeWS:
            calls["n"] += 1
            if calls["n"] == 1:
                raise aiohttp.ClientError("refused")
            return FakeWS(
                [
                    FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"data": {"r": 1}})),
                    FakeMsg(aiohttp.WSMsgType.CLOSED),
                ]
            )

        # ws_connect itself raises on first call; the async-CM path is only
        # reached on the retry, so mock it to raise synchronously first.
        session = MagicMock()

        def ws_connect(*a: Any, **k: Any) -> FakeWS:
            return factory()

        session.ws_connect = MagicMock(side_effect=ws_connect)
        session.close = AsyncMock()
        stream._session = session
        stream._owns_session = False

        await stream.start()
        try:
            got = await asyncio.wait_for(stream.__anext__(), timeout=5)
            assert got.data == {"r": 1}
            assert calls["n"] >= 2
        finally:
            await stream.stop()

    async def test_stop_event_breaks_loop_without_reconnect(self) -> None:
        """If stop is set while in the backoff wait, _run exits promptly."""
        stream = DeviceStream(
            _identity(),
            http_session=MagicMock(),
            initial_backoff_seconds=10.0,  # long backoff
            max_backoff_seconds=10.0,
        )
        # ws connects, immediately closed -> _run enters the long backoff wait
        _patch_ws_connect(stream, lambda: FakeWS([FakeMsg(aiohttp.WSMsgType.CLOSED)]))
        await stream.start()
        await asyncio.sleep(0.05)  # let it reach the backoff wait_for
        # stop() sets the event; the wait_for(self._stop.wait()) returns -> break
        await asyncio.wait_for(stream.stop(), timeout=5)
        assert stream._task is None
