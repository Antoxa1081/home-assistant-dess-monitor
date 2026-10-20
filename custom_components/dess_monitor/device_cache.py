"""Cache for device-related metadata.

In-memory TTL cache + persistent HA Store layer for speeding up cold start
and reducing redundant API calls. Caches:

- ``get_devices()`` result               -> 5 min TTL, persistent
- ``get_device_ctrl_fields()`` per pn    -> 1 hour TTL, persistent
- ``get_inverter_output_priority()`` per pn -> 5 min TTL, in-memory only

Dynamic per-tick data (last_data, energy_flow, pars) is not cached here.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.dess_monitor.sdk import ApiError

_LOGGER = logging.getLogger(__name__)

# Cloud envelope codes that mean "this device has no record on the server".
# Treated as stable empty results so we don't re-hit the API every tick.
_NO_RECORD_CODES: frozenset[int] = frozenset({12})

_STORAGE_VERSION = 1

DEVICES_TTL = 300
CTRL_FIELDS_TTL = 3600
OUTPUT_PRIORITY_TTL = 300


def _now() -> int:
    return int(dt_util.utcnow().timestamp())


def _is_fresh(entry: dict[str, Any] | None, ttl: int) -> bool:
    if not entry:
        return False
    ts = entry.get("fetched_at")
    if not isinstance(ts, (int, float)):
        return False
    return (_now() - ts) < ttl


class DeviceCache:
    """Per-config-entry cache for device metadata."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, f"dess_monitor.cache.{entry_id}")
        self._loaded = False
        self._load_lock = asyncio.Lock()

        self._devices: dict[str, Any] | None = None
        self._ctrl_fields: dict[str, dict[str, Any]] = {}
        self._output_priority: dict[str, dict[str, Any]] = {}

        self._devices_fetch_lock = asyncio.Lock()
        self._ctrl_fields_locks: dict[str, asyncio.Lock] = {}
        self._output_priority_locks: dict[str, asyncio.Lock] = {}

    async def async_load(self) -> None:
        async with self._load_lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                stored = await self._store.async_load()
            except Exception:
                _LOGGER.exception("Failed to load device cache")
                return
            if not stored:
                return
            self._devices = stored.get("devices")
            ctrl_fields = stored.get("ctrl_fields") or {}
            if isinstance(ctrl_fields, dict):
                self._ctrl_fields = ctrl_fields

    async def _persist(self) -> None:
        try:
            await self._store.async_save({
                "devices": self._devices,
                "ctrl_fields": self._ctrl_fields,
            })
        except Exception:
            _LOGGER.exception("Failed to persist device cache")

    async def async_clear(self) -> None:
        self._devices = None
        self._ctrl_fields = {}
        self._output_priority = {}
        try:
            await self._store.async_remove()
        except Exception:
            _LOGGER.exception("Failed to remove device cache")

    # ---- devices ----

    async def async_get_devices(
            self, fetcher: Callable[[], Awaitable[list]],
    ) -> list:
        await self.async_load()
        if _is_fresh(self._devices, DEVICES_TTL):
            return self._devices["data"]
        async with self._devices_fetch_lock:
            if _is_fresh(self._devices, DEVICES_TTL):
                return self._devices["data"]
            data = await fetcher()
            self._devices = {"data": data, "fetched_at": _now()}
            await self._persist()
            return data

    async def async_invalidate_devices(self) -> None:
        self._devices = None
        await self._persist()

    # ---- ctrl_fields ----

    def _ctrl_lock(self, pn: str) -> asyncio.Lock:
        lock = self._ctrl_fields_locks.get(pn)
        if lock is None:
            lock = asyncio.Lock()
            self._ctrl_fields_locks[pn] = lock
        return lock

    async def async_get_ctrl_fields(
            self, pn: str, fetcher: Callable[[], Awaitable[Any]],
    ) -> Any:
        await self.async_load()
        entry = self._ctrl_fields.get(pn)
        if _is_fresh(entry, CTRL_FIELDS_TTL):
            return entry["data"]
        async with self._ctrl_lock(pn):
            entry = self._ctrl_fields.get(pn)
            if _is_fresh(entry, CTRL_FIELDS_TTL):
                return entry["data"]
            try:
                data = await fetcher()
            except ApiError as err:
                # err=12 "ERR_NO_RECORD" — the cloud just has no ctrl-field
                # template for this firmware (e.g. devcode 2462, issue #89).
                # Cache an empty list so we stop hammering the API every tick;
                # the regular 1h TTL still lets Eybond's catalog catch up later.
                if err.code in _NO_RECORD_CODES:
                    _LOGGER.debug(
                        "ctrl_fields missing for %s (%s); caching empty for %ss",
                        pn, err, CTRL_FIELDS_TTL,
                    )
                    data = {"field": []}
                else:
                    raise
            self._ctrl_fields[pn] = {"data": data, "fetched_at": _now()}
            await self._persist()
            return data

    async def async_invalidate_ctrl_fields(self, pn: str | None = None) -> None:
        if pn is None:
            self._ctrl_fields = {}
        else:
            self._ctrl_fields.pop(pn, None)
        await self._persist()

    # ---- output_priority (in-memory only) ----

    def _op_lock(self, pn: str) -> asyncio.Lock:
        lock = self._output_priority_locks.get(pn)
        if lock is None:
            lock = asyncio.Lock()
            self._output_priority_locks[pn] = lock
        return lock

    async def async_get_output_priority(
            self, pn: str, fetcher: Callable[[], Awaitable[Any]],
    ) -> Any:
        entry = self._output_priority.get(pn)
        if _is_fresh(entry, OUTPUT_PRIORITY_TTL):
            return entry["data"]
        async with self._op_lock(pn):
            entry = self._output_priority.get(pn)
            if _is_fresh(entry, OUTPUT_PRIORITY_TTL):
                return entry["data"]
            data = await fetcher()
            self._output_priority[pn] = {"data": data, "fetched_at": _now()}
            return data

    def invalidate_output_priority(self, pn: str | None = None) -> None:
        if pn is None:
            self._output_priority = {}
        else:
            self._output_priority.pop(pn, None)
