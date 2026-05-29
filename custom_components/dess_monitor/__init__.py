from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.dess_monitor.auth_store import HomeAssistantTokenStorage
from custom_components.dess_monitor.const import (
    CONF_BATTERY_VIRTUAL_ENABLED,
    CONF_ENABLE_WEBSOCKET,
    DEFAULT_BATTERY_VIRTUAL_ENABLED,
    DEFAULT_ENABLE_WEBSOCKET,
)
from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.coordinators.direct_coordinator import DirectCoordinator
from custom_components.dess_monitor.device_cache import DeviceCache
from custom_components.dess_monitor.mapping import MappingDiscovery
from custom_components.dess_monitor.mapping_store import HomeAssistantMappingStorage
from custom_components.dess_monitor.sdk import Credentials, DessmonitorClient
from custom_components.dess_monitor.stream_manager import DeviceStreamManager
from custom_components.dess_monitor.virtual_battery import VirtualBatteryEstimator

from . import hub

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = [Platform.SENSOR, Platform.SELECT, Platform.NUMBER]

type HubConfigEntry = ConfigEntry[hub.Hub]


async def async_setup_entry(hass: HomeAssistant, entry: HubConfigEntry) -> bool:
    await _migrate_data_to_options(hass, entry)
    username = entry.data["username"]
    client = DessmonitorClient(
        credentials=Credentials(
            username=username,
            password_hash=entry.data["password_hash"],
        ),
        http_session=async_get_clientsession(hass),
        storage=HomeAssistantTokenStorage(hass, entry.entry_id, username),
    )
    device_cache = DeviceCache(hass, entry.entry_id)
    mapping = MappingDiscovery(HomeAssistantMappingStorage(hass, entry.entry_id))
    await mapping.async_load()
    my_coordinator = MainCoordinator(hass, entry, client, device_cache)
    direct_coordinator_ctx = DirectCoordinator(hass, entry, client, device_cache)
    await asyncio.gather(
        my_coordinator.async_config_entry_first_refresh(),
        direct_coordinator_ctx.async_config_entry_first_refresh()
    )

    entry.runtime_data = hub.Hub(hass, username, client, my_coordinator, direct_coordinator_ctx, mapping)
    await entry.runtime_data.init()

    # Attach virtual-battery estimators BEFORE the platforms are set up, so
    # the SOC sensor and config Number/Select entities see their estimator at
    # construction time. Gated by an entry-level master toggle: when off, no
    # virtual-battery entities (Number/Select/Sensor) are created at all.
    if entry.options.get(CONF_BATTERY_VIRTUAL_ENABLED, DEFAULT_BATTERY_VIRTUAL_ENABLED):
        await _setup_virtual_battery(hass, entry, my_coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _flush_mapping_if_dirty() -> None:
        if mapping.is_dirty:
            hass.async_create_task(mapping.async_save())

    entry.async_on_unload(my_coordinator.async_add_listener(_flush_mapping_if_dirty))
    # Sensors set up above may have triggered discovery — flush once now.
    if mapping.is_dirty:
        hass.async_create_task(mapping.async_save())

    if entry.options.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET):
        stream_manager = DeviceStreamManager(hass, client, my_coordinator)
        await stream_manager.async_start()
        entry.async_on_unload(stream_manager.async_stop)

    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def _setup_virtual_battery(
        hass: HomeAssistant,
        entry: HubConfigEntry,
        coordinator: MainCoordinator,
) -> None:
    """Wire a Coulomb-counting SOC estimator to every device on the entry.

    Each tick of the main coordinator (poll or WS-driven) runs the estimator
    against fresh battery readings; a debounced background save persists the
    SOC so a brief HA restart doesn't reset the integration to ``None``.
    """
    estimators: list[VirtualBatteryEstimator] = []
    for inverter_device in entry.runtime_data.items:
        estimator = VirtualBatteryEstimator(
            hass, entry.entry_id, inverter_device.inverter_id,
        )
        await estimator.async_load()
        inverter_device.virtual_battery = estimator
        estimators.append(estimator)

    @callback
    def _tick_estimators() -> None:
        coord_data = coordinator.data
        if not isinstance(coord_data, dict):
            return
        any_dirty = False
        for inverter_device in entry.runtime_data.items:
            estimator = inverter_device.virtual_battery
            if estimator is None:
                continue
            data = coord_data.get(inverter_device.inverter_id)
            if not isinstance(data, dict):
                continue
            voltage = inverter_device.resolve("battery_voltage", data)
            try:
                voltage = float(voltage) if voltage is not None else None
            except (TypeError, ValueError):
                voltage = None
            signed_current = _resolve_signed_battery_current(inverter_device, data, voltage)
            estimator.update(voltage, signed_current)
            any_dirty = any_dirty or estimator.is_dirty
        if any_dirty:
            hass.async_create_task(_save_estimators(estimators))

    entry.async_on_unload(coordinator.async_add_listener(_tick_estimators))
    # Run once now so we don't wait a whole interval for the first SOC value.
    _tick_estimators()


def _resolve_signed_battery_current(inverter_device, data, voltage):
    """Best-effort signed battery current: + charging, − discharging.

    Tries (in order): explicit charge/discharge magnitudes, then derives
    from ``battery_power / voltage`` as a last resort. Returns ``None`` when
    nothing is resolvable so the estimator skips the tick cleanly.
    """
    cc = inverter_device.resolve("battery_charging_current", data)
    dc = inverter_device.resolve("battery_discharge_current", data)
    if cc is not None or dc is not None:
        try:
            return float(cc or 0.0) - float(dc or 0.0)
        except (TypeError, ValueError):
            pass
    power = inverter_device.resolve("battery_power", data)
    if power is None or voltage is None or voltage <= 0:
        return None
    try:
        return float(power) / float(voltage)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


async def _save_estimators(estimators: list[VirtualBatteryEstimator]) -> None:
    for estimator in estimators:
        await estimator.async_save()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the cached auth file when the entry is removed entirely."""
    storage = HomeAssistantTokenStorage(
        hass,
        entry.entry_id,
        entry.data.get("username", ""),
    )
    await storage.clear()
    await DeviceCache(hass, entry.entry_id).async_clear()
    await HomeAssistantMappingStorage(hass, entry.entry_id).clear()


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _migrate_data_to_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    new_data = dict(entry.data)
    new_options = dict(entry.options)
    fields = [
        'dynamic_settings',
        'direct_request_protocol',
        'devices',
        'raw_sensors',
    ]
    k = 0
    for field in fields:
        if field in new_data:
            k += 1
            new_options[field] = new_data.pop(field)
    if k > 0:
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options
        )
