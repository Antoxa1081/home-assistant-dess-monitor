import logging
import random
from datetime import datetime, timedelta

import async_timeout
from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor import HubConfigEntry, MainCoordinator
from custom_components.dess_monitor.api.helpers import set_inverter_output_priority
from custom_components.dess_monitor.api.resolvers.data_resolvers import resolve_output_priority
from custom_components.dess_monitor.const import (
    BATTERY_CHEMISTRIES,
    CONF_BATTERY_VIRTUAL_ENABLED,
    CONF_DYNAMIC_SETTINGS_INTERVAL,
    DEFAULT_BATTERY_CHEMISTRY,
    DEFAULT_BATTERY_VIRTUAL_ENABLED,
    DEFAULT_DYNAMIC_SETTINGS_INTERVAL,
    DOMAIN,
    DYNAMIC_SETTINGS_API_TIMEOUT,
    MAX_DYNAMIC_SETTINGS_INTERVAL,
    MIN_DYNAMIC_SETTINGS_INTERVAL,
)
from custom_components.dess_monitor.coordinators.coordinator import _clamp
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sdk import DeviceIdentity
from custom_components.dess_monitor.util import resolve_number_with_unit

_LOGGER = logging.getLogger(__name__)

# Platform-level interval at which HA invokes ``async_update`` on entities with
# ``should_poll=True``. Each individual call is throttled internally against
# the user-configured ``CONF_DYNAMIC_SETTINGS_INTERVAL``, so this just bounds
# how often we *check* the throttle, not how often we hit the cloud.
SCAN_INTERVAL = timedelta(seconds=60)
PARALLEL_UPDATES = 1


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: HubConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hub = config_entry.runtime_data
    coordinator = hub.coordinator
    coordinator_data = hub.coordinator.data

    virtual_battery_enabled = config_entry.options.get(
        CONF_BATTERY_VIRTUAL_ENABLED, DEFAULT_BATTERY_VIRTUAL_ENABLED,
    )
    new_devices = []
    for item in hub.items:
        # grid sensors
        new_devices.append(InverterOutputPrioritySelect(item, coordinator))
        if virtual_battery_enabled:
            new_devices.append(VirtualBatteryChemistrySelect(item, coordinator))
        if coordinator_data is None or item.inverter_id not in coordinator_data:
            continue
        fields = coordinator_data[item.inverter_id]['ctrl_fields']
        if fields is None:
            continue
        # print(config_entry.data)
        if config_entry.options.get('dynamic_settings', False) is True:
            print("Setting up dynamic_settings")
            async_add_entities(list(
                map(
                    lambda field_data: InverterDynamicSettingSelect(item, coordinator, field_data),
                    filter(lambda field: 'item' in field, fields)
                )
            )
            )
    if new_devices:
        async_add_entities(new_devices)


class SelectBase(CoordinatorEntity, SelectEntity):
    # should_poll = True

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._inverter_device = inverter_device

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._inverter_device.inverter_id)},
            # If desired, the name for the device could be different to the entity
            "name": self._inverter_device.name,
            "sw_version": self._inverter_device.firmware_version,
            "model": self._inverter_device.device_data['pn'],
            "serial_number": self._inverter_device.device_data['sn'],
            "hw_version": self._inverter_device.device_data['devcode'],
            "model_id": self._inverter_device.device_data['devaddr'],
            "manufacturer": 'ESS'
        }

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if inverter_device and hub is available."""
        return self._inverter_device.online and self._inverter_device.hub.online

    @property
    def data(self):
        return self.coordinator.data[self._inverter_device.inverter_id]

    # async def async_added_to_hass(self):
    #     """Run when this Entity has been added to HA."""
    #     # Sensors should also register callbacks to HA when their state changes
    #     self._inverter_device.register_callback(self.async_write_ha_state)
    #
    # async def async_will_remove_from_hass(self):
    #     """Entity being removed from hass."""
    #     # The opposite of async_added_to_hass. Remove any registered call backs here.
    #     self._inverter_device.remove_callback(self.async_write_ha_state)


class InverterOutputPrioritySelect(SelectBase, RestoreEntity):
    _attr_current_option = None

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_output_priority"
        self._attr_name = f"{self._inverter_device.name} Output Priority"
        self._attr_options = ['Utility', 'Solar', 'SBU', 'SUB']

        if coordinator.data is not None:
            data = coordinator.data.get(self._inverter_device.inverter_id)
            if data is not None:
                self._attr_current_option = resolve_output_priority(data, self._inverter_device)

    async def async_added_to_hass(self) -> None:
        """Hold the last known option until the next coordinator refresh.

        The cloud is slow to ACK select reads, so without restore the entity
        flickers to ``Unknown`` for the first poll after every HA restart.
        """
        await super().async_added_to_hass()
        if self._attr_current_option is not None:
            return
        last = await self.async_get_last_state()
        if last is None or last.state in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if last.state in self._attr_options:
            self._attr_current_option = last.state

    @callback
    def _handle_coordinator_update(self) -> None:
        data = (self.coordinator.data or {}).get(self._inverter_device.inverter_id)
        if data is None:
            # Keep the restored / previously-resolved option visible while
            # polling is between cycles — avoids flicker to Unknown.
            self.async_write_ha_state()
            return
        try:
            resolved = resolve_output_priority(data, self._inverter_device)
        except Exception:
            resolved = None
        if resolved is not None:
            self._attr_current_option = resolved
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        if option in self._attr_options:
            # los_output_source_priority Utility, Solar, SBU
            await set_inverter_output_priority(
                self.coordinator.client,
                self._inverter_device.device_data,
                option,
            )
            self.coordinator.device_cache.invalidate_output_priority(self._inverter_device.inverter_id)
            self._attr_current_option = option
            await self.coordinator.async_request_refresh()


class InverterDynamicSettingSelect(SelectBase, RestoreEntity):
    _attr_current_option = None
    _disabled_param = False
    should_poll = True
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore the previous option so the slow cloud doesn't blank the UI."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if last.state in self._attr_options:
            self._attr_current_option = last.state
            # The fact that we have a previously-saved option means the param
            # exists on this device — don't auto-disable on the first API miss.
            self._disabled_param = False
            self._last_updated = int(datetime.now().timestamp())

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator, field_data):
        super().__init__(inverter_device, coordinator)
        self._field_data = field_data
        self._service_param_id = field_data['id']
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_settings_{field_data['id']}"
        self._attr_name = f"{self._inverter_device.name} SET {field_data['name']}"
        self._attr_options = list(
            map(
                lambda x: x['val'] if 'unit' not in field_data else str(resolve_number_with_unit(x['val'])),
                field_data['item']
            )
        )
        self._attr_options_keys = list(map(lambda x: x['key'], field_data['item']))
        self._poll_interval = _clamp(
            coordinator.config_entry.options.get(
                CONF_DYNAMIC_SETTINGS_INTERVAL, DEFAULT_DYNAMIC_SETTINGS_INTERVAL,
            ),
            MIN_DYNAMIC_SETTINGS_INTERVAL,
            MAX_DYNAMIC_SETTINGS_INTERVAL,
        )
        # Spread initial polls across one full interval — with dozens of CONFIG
        # entities per inverter this prevents an API stampede at startup.
        now = int(datetime.now().timestamp())
        self._last_updated: int | None = now - random.randint(0, max(self._poll_interval - 1, 1))

    async def async_update(self, force: bool = False) -> None:
        now = int(datetime.now().timestamp())
        if not force and self._last_updated is not None and (now - self._last_updated) < self._poll_interval:
            return

        try:
            async with async_timeout.timeout(DYNAMIC_SETTINGS_API_TIMEOUT):
                response = await self.coordinator.client.control.get_value(
                    DeviceIdentity.from_dict(self._inverter_device.device_data),
                    self._service_param_id,
                )
        except (TimeoutError, Exception) as err:
            _LOGGER.debug(
                "Skipping update of %s: %s", self._attr_unique_id, err,
            )
            return

        if not isinstance(response, dict) or 'err' in response:
            if self._last_updated is None:
                self._disabled_param = True
            self._last_updated = now
            return

        raw_val = response.get('val')
        if raw_val is None:
            self._last_updated = now
            return
        val = raw_val if 'unit' not in self._field_data else str(resolve_number_with_unit(raw_val))
        mapped_list = [opt.lower() for opt in self._attr_options]
        try:
            index = mapped_list.index(val.lower())
        except (ValueError, AttributeError):
            if self._last_updated is None:
                self._disabled_param = True
            self._last_updated = now
            return
        self._attr_current_option = self._attr_options[index]
        self._last_updated = now
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if inverter_device and hub is available."""
        return self._inverter_device.online and self._inverter_device.hub.online and not self._disabled_param

    @property
    def native_value(self):
        return self._attr_current_option

    async def async_select_option(self, option: str):
        if option in self._attr_options:
            param_id = self._service_param_id
            param_value = self._attr_options_keys[self._attr_options.index(option)]
            await self.coordinator.client.control.set_param(
                DeviceIdentity.from_dict(self._inverter_device.device_data),
                param_id,
                param_value,
            )

            self._attr_current_option = option
            self.async_write_ha_state()


class VirtualBatteryChemistrySelect(SelectBase, RestoreEntity):
    """Battery chemistry selector for the SOC estimator.

    Currently only annotates the estimator (the math uses the user-provided
    full voltage directly), but the option is persisted and forwarded so a
    future voltage-curve correction step can be added without a config-flow
    migration.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BATTERY_CHEMISTRIES)

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{inverter_device.inverter_id}_virtual_battery_chemistry"
        self._attr_name = f"{inverter_device.name} Virtual Battery Chemistry"
        self._attr_current_option = DEFAULT_BATTERY_CHEMISTRY

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state
        estimator = self._inverter_device.virtual_battery
        if estimator is not None:
            estimator.set_chemistry(self._attr_current_option)

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        self._attr_current_option = option
        estimator = self._inverter_device.virtual_battery
        if estimator is not None:
            estimator.set_chemistry(option)
        self.async_write_ha_state()
