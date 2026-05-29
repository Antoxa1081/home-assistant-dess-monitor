"""Per-device WebSocket telemetry stream.

The stream is auth-less — device identity in the URL is the entire credential.
Reconnects are transparent: the iterator keeps yielding frames across drop/recover
cycles until the caller explicitly stops the stream or exits the ``async with``.

Typical usage::

    async with client.stream_device(identity) as stream:
        async for frame in stream:
            handle(frame.data)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import aiohttp

from .http import DEFAULT_BASE_HOST
from .models import DeviceIdentity

_LOGGER = logging.getLogger(__name__)

DEFAULT_WS_PATH = "/relay-ess/monitor/dataNew"
DEFAULT_HEARTBEAT_SECONDS = 30.0
DEFAULT_INITIAL_BACKOFF_SECONDS = 5.0
DEFAULT_MAX_BACKOFF_SECONDS = 300.0
DEFAULT_QUEUE_MAXSIZE = 256

_WS_HEADERS = {
    "Origin": "https://www.dessmonitor.com",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """One parsed telemetry frame."""

    device_pn: str
    received_at: float
    data: dict[str, Any]


class DeviceStream:
    """Async-iterable WebSocket stream for a single device.

    The stream owns a background task that handles connect → consume → reconnect.
    Frames land in a bounded queue; the iterator dequeues them. On consumer
    backpressure the producer drops the oldest frame to keep latency low — this is
    what you want for live telemetry, where a stale value is worse than a missed one.
    """

    def __init__(
        self,
        identity: DeviceIdentity,
        *,
        http_session: aiohttp.ClientSession | None = None,
        base_host: str = DEFAULT_BASE_HOST,
        ws_path: str = DEFAULT_WS_PATH,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ) -> None:
        self._identity = identity
        self._session = http_session
        self._owns_session = http_session is None
        self._base_host = base_host
        self._ws_path = ws_path
        self._heartbeat = heartbeat_seconds
        self._initial_backoff = initial_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._queue: asyncio.Queue[StreamFrame] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def identity(self) -> DeviceIdentity:
        return self._identity

    @property
    def url(self) -> str:
        qs = urllib.parse.urlencode(self._identity.as_params())
        return f"wss://{self._base_host}{self._ws_path}?{qs}"

    async def __aenter__(self) -> DeviceStream:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    def __aiter__(self) -> AsyncIterator[StreamFrame]:
        return self

    async def __anext__(self) -> StreamFrame:
        if self._task is None:
            raise RuntimeError("DeviceStream not started — use 'async with' or call start()")
        while True:
            getter = asyncio.create_task(self._queue.get())
            stop_waiter = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {getter, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()
            if getter in done and not getter.cancelled():
                return getter.result()
            raise StopAsyncIteration

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run(), name=f"DeviceStream({self._identity.pn})")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._connect_and_consume()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning(
                    "DeviceStream(%s) error: %s — reconnecting (attempt %d)",
                    self._identity.pn, exc, attempt + 1,
                )
            if self._stop.is_set():
                break
            delay = min(self._initial_backoff * (2 ** attempt), self._max_backoff)
            attempt += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except TimeoutError:
                continue

    async def _connect_and_consume(self) -> None:
        assert self._session is not None
        _LOGGER.debug("DeviceStream(%s) connecting %s", self._identity.pn, self.url)
        async with self._session.ws_connect(
            self.url,
            headers=_WS_HEADERS,
            heartbeat=self._heartbeat,
            autoping=True,
        ) as ws:
            _LOGGER.info("DeviceStream(%s) connected", self._identity.pn)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    frame = self._parse(msg.data)
                    if frame is not None:
                        self._enqueue(frame)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise ws.exception() or RuntimeError("WSMsgType.ERROR with no exception")
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break
            _LOGGER.info("DeviceStream(%s) disconnected", self._identity.pn)

    def _parse(self, raw: str) -> StreamFrame | None:
        try:
            outer = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.debug("DeviceStream(%s) non-JSON frame: %r", self._identity.pn, raw)
            return None
        data = outer.get("data") if isinstance(outer, dict) else None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                _LOGGER.debug("DeviceStream(%s) inner data not JSON: %r", self._identity.pn, data)
                return None
        if not isinstance(data, dict):
            return None
        return StreamFrame(
            device_pn=str(self._identity.pn),
            received_at=time.time(),
            data=data,
        )

    def _enqueue(self, frame: StreamFrame) -> None:
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(frame)
            _LOGGER.debug(
                "DeviceStream(%s) queue full — dropped oldest frame",
                self._identity.pn,
            )
