from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Coroutine
from datetime import timedelta
from time import monotonic
from typing import Any, TypeVar

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from custom_components.dess_monitor.api.helpers import get_inverter_output_priority
from custom_components.dess_monitor.const import (
    CONF_MAIN_UPDATE_INTERVAL,
    DEFAULT_MAIN_UPDATE_INTERVAL,
    DEFAULT_PARS_REFRESH_INTERVAL,
    MAX_MAIN_UPDATE_INTERVAL,
    MIN_MAIN_UPDATE_INTERVAL,
    STALE_LIVE_DATA_MAX_SECONDS,
)
from custom_components.dess_monitor.device_cache import DeviceCache
from custom_components.dess_monitor.sdk import (
    ApiError,
    AuthError,
    DessmonitorClient,
    DeviceIdentity,
    TransportError,
)

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


async def safe_call(coro: Coroutine[Any, Any, T] | Awaitable[T], default: T | None = None) -> T | None:
    try:
        return await coro
    except TransportError as err:
        # Cloud timeout / network blip — expected with this provider. Log a
        # one-line WARNING so HA logs stay readable; the upstream stack frames
        # don't add diagnostic value when we already know it's the wire.
        _LOGGER.warning("DESS cloud transient (%s): %s", _action_of(err), err)
        return default
    except TimeoutError as err:
        _LOGGER.warning("DESS cloud timed out: %s", err)
        return default
    except ApiError as err:
        # Cloud-side envelope error (e.g. err=3 rate-limit, err=6000 backend
        # crash, err=10 auth). Same treatment as TransportError above: the
        # cloud is having a bad day, not a code bug — one-line WARNING beats
        # a stack trace per failed call.
        _LOGGER.warning("DESS cloud API error (%s): %s", _action_of(err), err)
        return default
    except Exception:
        _LOGGER.exception("Error while awaiting %s", coro)
        return default


def _action_of(err: BaseException) -> str:
    """Best-effort label for which API call timed out (helps grep the logs)."""
    return getattr(err, "action", None) or type(err).__name__


def _clamp(value: object, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low


class MainCoordinator(DataUpdateCoordinator):
    devices: list[dict[str, Any]] = []

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Any,
        client: DessmonitorClient,
        device_cache: DeviceCache,
    ) -> None:
        interval_seconds = _clamp(
            config_entry.options.get(CONF_MAIN_UPDATE_INTERVAL, DEFAULT_MAIN_UPDATE_INTERVAL),
            MIN_MAIN_UPDATE_INTERVAL,
            MAX_MAIN_UPDATE_INTERVAL,
        )
        super().__init__(
            hass,
            _LOGGER,
            name="Main coordinator",
            config_entry=config_entry,
            update_interval=timedelta(seconds=interval_seconds),
            always_update=False,
        )
        self._update_timeout = max(interval_seconds, 30)
        self._client = client
        self._device_cache = device_cache
        self._pars_refresh_seconds = DEFAULT_PARS_REFRESH_INTERVAL
        self._stale_live_seconds = STALE_LIVE_DATA_MAX_SECONDS
        self._pars_cache: dict[str, dict[str, Any]] = {}
        self._pars_fetched_at: dict[str, float] = {}
        self._last_device_data: dict[str, dict[str, Any]] = {}
        self._last_live_fetch_at: dict[str, dict[str, float]] = {}

    @property
    def client(self) -> DessmonitorClient:
        return self._client

    @property
    def device_cache(self) -> DeviceCache:
        return self._device_cache

    async def _async_setup(self) -> None:
        async with async_timeout.timeout(30):
            await self._client.session.get_auth()
            self.devices = await self.get_active_devices()
            _LOGGER.debug("coordinator setup devices count: %s", len(self.devices))

    async def get_active_devices(self) -> list[dict[str, Any]]:
        devices = await self._device_cache.async_get_devices(
            lambda: self._client.devices.list()
        )
        active_devices = [device for device in devices if device['status'] != 1]
        if "devices" in self.config_entry.options and len(self.config_entry.options["devices"]) > 0:
            return [
                device for device in active_devices
                if str(device['pn']) in self.config_entry.options["devices"]
                or str(device['uid']) in self.config_entry.options["devices"]
            ]
        return active_devices

    async def _get_pars_cached(self, pn: str, identity: DeviceIdentity) -> dict[str, Any]:
        # ``queryDeviceParsEs`` returns mostly static configuration (output
        # priority, charging current, voltage thresholds…). Polling it at the
        # live-data cadence was tripping the cloud's per-action rate limit
        # (err=3) under summer peak load and cascading into err=6000 outages
        # on the live-data endpoint. On fetch failure with an existing cache,
        # we keep the stale value and defer the next attempt by a full
        # interval so we don't pound an already-failing API.
        now = monotonic()
        cached = self._pars_cache.get(pn)
        last = self._pars_fetched_at.get(pn, 0.0)
        if cached is not None and (now - last) < self._pars_refresh_seconds:
            return cached
        fresh = await safe_call(self._client.devices.pars(identity), default=None)
        if fresh is not None:
            self._pars_cache[pn] = fresh
            self._pars_fetched_at[pn] = now
            return fresh
        if cached is not None:
            self._pars_fetched_at[pn] = now
            return cached
        return {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            async with async_timeout.timeout(self._update_timeout):
                _LOGGER.debug("coordinator update data devices")

                self.devices = await self.get_active_devices()

                async def build_device_data(device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                    pn = device['pn']
                    identity = DeviceIdentity.from_dict(device)
                    last_data = await safe_call(self._client.devices.last_data(identity), default={})
                    energy_flow = await safe_call(self._client.devices.energy_flow(identity), default={})
                    pars = await self._get_pars_cached(pn, identity)
                    ctrl_fields = await safe_call(
                        self._device_cache.async_get_ctrl_fields(
                            pn, lambda: self._client.control.get_fields(identity)
                        ),
                        default={'field': []},
                    )
                    output_priority = await safe_call(
                        self._device_cache.async_get_output_priority(
                            pn, lambda: get_inverter_output_priority(self._client, device)
                        ),
                        default=None,
                    )

                    # Graceful degradation: when a single live call comes back
                    # empty (cloud err=6000, transient timeout, etc.), reuse
                    # the previous tick's value instead of letting sensors
                    # flap to Unavailable for one cycle. Capped at
                    # ``_stale_live_seconds`` so a real outage eventually
                    # surfaces as Unavailable rather than yesterday's reading.
                    now = monotonic()
                    prev = self._last_device_data.get(pn) or {}
                    fetched_at = self._last_live_fetch_at.setdefault(pn, {})

                    if last_data:
                        fetched_at['last_data'] = now
                    elif (now - fetched_at.get('last_data', 0.0)) <= self._stale_live_seconds:
                        last_data = prev.get('last_data') or {}

                    if energy_flow:
                        fetched_at['energy_flow'] = now
                    elif (now - fetched_at.get('energy_flow', 0.0)) <= self._stale_live_seconds:
                        energy_flow = prev.get('energy_flow') or {}

                    result = {
                        'last_data': last_data,
                        'energy_flow': energy_flow,
                        'pars': pars,
                        'device': device,
                        'ctrl_fields': ctrl_fields.get('field', []),
                        'device_extra': {
                            'output_priority': output_priority,
                        }
                    }
                    self._last_device_data[pn] = result
                    return pn, result

                tasks = [build_device_data(device) for device in self.devices]
                device_data = await asyncio.gather(*tasks)
                return {pn: data for pn, data in device_data}
        except TimeoutError:
            raise
        except AuthError as err:
            await self._client.session.invalidate()
            raise UpdateFailed("auth token invalidated, will re-issue next tick") from err
        except TransportError as err:
            # Wrap as UpdateFailed so HA's DataUpdateCoordinator logs a single
            # WARNING line ("Error fetching ... data: ...") instead of the
            # full aiohttp + SDK traceback.
            raise UpdateFailed(f"DESS cloud transient: {err}") from err
        except ApiError as err:
            # Top-level call (e.g. ``get_active_devices``) failed with a
            # non-auth envelope error. Same rationale as TransportError above.
            raise UpdateFailed(f"DESS cloud API error: {err}") from err
