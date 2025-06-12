from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.coordinators.direct_coordinator import DirectCoordinator
from . import hub

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = [Platform.SENSOR, Platform.SELECT, Platform.NUMBER]

type HubConfigEntry = ConfigEntry[hub.Hub]


async def async_setup_entry(hass: HomeAssistant, entry: HubConfigEntry) -> bool:
    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    await _migrate_data_to_options(hass, entry)
    my_coordinator = MainCoordinator(hass, entry)
    direct_coordinator_ctx = DirectCoordinator(hass, entry)
    await asyncio.gather(
        my_coordinator.async_config_entry_first_refresh(),
        direct_coordinator_ctx.async_config_entry_first_refresh()
    )

    entry.runtime_data = hub.Hub(hass, entry.data["username"], my_coordinator, direct_coordinator_ctx)
    await entry.runtime_data.init()
    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await asyncio.gather(
        direct_coordinator_ctx.async_refresh(),
        my_coordinator.async_refresh()
    )
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry):
    # Reload the integration
    await hass.config_entries.async_reload(entry.entry_id)


async def _migrate_data_to_options(hass: HomeAssistant, entry: ConfigEntry):
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
