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
from homeassistant.util import dt as dt_util

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

# Powland iSolar SMG III (devcode 6515) spreads dynamic telemetry across
# endpoints with different cache ages.  Its queryDeviceDataOneDayPaging
# realtime row is the only atomic snapshot containing all of these values.
_SYNCHRONIZED_SNAPSHOT_DEVCODES = {"6515"}
_SYNCHRONIZED_SNAPSHOT_REFRESH_SECONDS = 60
_SYNCHRONIZED_SNAPSHOT_METRICS = {
    "Operating mode",
    "Grid Frequency",
    "Grid Voltage",
    "Grid Power",
    "Output frequency",
    "Output Voltage",
    "Output Current",
    "Output Active Power",
    "Output Aparent Power",
    "Load Percentage",
    "Battery Voltage",
    "Battery Current",
    "Battery Power",
    "SOC",
    "PV1 Voltage",
    "PV1 Current",
    "PV1 Power",
    "PV2 Voltage",
    "PV2 Current",
    "PV2 Power",
    "Total PV Power",
    "Total PV Charging Power",
    "Total PV Charging Current",
    "INV Module Termperature",
    "PV temperature",
    "DC Module Termperature",
}


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


def _synchronized_snapshot_params(
    history: dict[str, Any], fields: list[dict[str, Any]]
) -> dict[str, Any]:
    """Convert a realtime history row into one timestamped resolver snapshot.

    ``queryDeviceFields`` provides the stable provider IDs while the history
    title array supplies display names and units.  Matching both by name lets
    the existing mapping resolver consume the synchronized values without
    creating duplicate dynamic entities.
    """
    titles = history.get("title")
    rows = history.get("row")
    if not isinstance(titles, list) or not isinstance(rows, list) or not rows:
        return {}

    row = next(
        (
            candidate
            for candidate in rows
            if isinstance(candidate, dict) and candidate.get("realtime") is True
        ),
        rows[0],
    )
    values = row.get("field") if isinstance(row, dict) else None
    if not isinstance(values, list):
        return {}

    provider_ids = {
        str(field.get("name", "")).casefold(): field.get("id")
        for field in fields
        if isinstance(field, dict) and field.get("name") and field.get("id")
    }
    params: list[dict[str, Any]] = []
    sample_time: str | None = None
    for index, title in enumerate(titles):
        if not isinstance(title, dict) or index >= len(values):
            continue
        name = title.get("title")
        value = values[index]
        if name == "Timestamp":
            sample_time = str(value) if value not in (None, "") else None
            continue
        if name not in _SYNCHRONIZED_SNAPSHOT_METRICS:
            continue
        if value in (None, ""):
            continue
        provider_id = provider_ids.get(str(name).casefold(), name)
        param = {"id": provider_id, "par": name, "val": value}
        if unit := title.get("unit"):
            param["unit"] = unit
        params.append(param)

    if not params:
        return {}
    snapshot: dict[str, Any] = {"parameter": params}
    if sample_time is not None:
        snapshot["gts"] = sample_time
    return snapshot


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
        self._synchronized_snapshot_cache: dict[str, dict[str, Any]] = {}
        self._synchronized_snapshot_fetched_at: dict[str, float] = {}
        self._history_fields_cache: dict[str, list[dict[str, Any]]] = {}
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

    async def _get_synchronized_snapshot_cached(
        self, pn: str, identity: DeviceIdentity
    ) -> dict[str, Any]:
        """Fetch one coherent telemetry snapshot for Powland devcode 6515."""
        now = monotonic()
        cached = self._synchronized_snapshot_cache.get(pn)
        last = self._synchronized_snapshot_fetched_at.get(pn, 0.0)
        if cached is not None and (now - last) < _SYNCHRONIZED_SNAPSHOT_REFRESH_SECONDS:
            return cached

        fields = self._history_fields_cache.get(pn)
        if fields is None:
            fresh_fields = await safe_call(self._client.devices.fields(identity), default=None)
            if isinstance(fresh_fields, list):
                fields = fresh_fields
                self._history_fields_cache[pn] = fields
            else:
                fields = []
        history = await safe_call(
            self._client.devices.historical_data(
                identity,
                dt_util.now().date().isoformat(),
                page=0,
                pagesize=1,
            ),
            default=None,
        )
        self._synchronized_snapshot_fetched_at[pn] = now
        if history is not None:
            fresh = _synchronized_snapshot_params(history, fields)
            if fresh:
                self._synchronized_snapshot_cache[pn] = fresh
                return fresh
        return cached or {}

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
                    synchronized_snapshot = {}
                    if str(device.get('devcode')) in _SYNCHRONIZED_SNAPSHOT_DEVCODES:
                        synchronized_snapshot = await self._get_synchronized_snapshot_cached(
                            pn, identity
                        )
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

                    # Insert the synchronized snapshot first: MappingDiscovery
                    # walks dictionaries in insertion order, so Powland dynamic
                    # metrics resolve from one timestamp before the mixed-age
                    # last_data, energy_flow and cached pars blocks.
                    result = {}
                    if synchronized_snapshot:
                        result['synchronized_snapshot'] = synchronized_snapshot
                    result.update({
                        'last_data': last_data,
                        'energy_flow': energy_flow,
                        'pars': pars,
                        'device': device,
                        'ctrl_fields': ctrl_fields.get('field', []),
                        'device_extra': {
                            'output_priority': output_priority,
                        }
                    })
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
