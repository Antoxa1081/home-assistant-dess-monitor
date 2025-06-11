from datetime import timedelta, datetime

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor import MainCoordinator, HubConfigEntry
from custom_components.dess_monitor.api import set_ctrl_device_param, get_device_ctrl_value
from custom_components.dess_monitor.api.helpers import set_inverter_output_priority
from custom_components.dess_monitor.api.resolvers.data_resolvers import resolve_output_priority
from custom_components.dess_monitor.const import DOMAIN
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.util import resolve_number_with_unit

SCAN_INTERVAL = timedelta(seconds=30)
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

    new_devices = []
    for item in hub.items:
        # grid sensors
        new_devices.append(InverterOutputPrioritySelect(item, coordinator))
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


class InverterOutputPrioritySelect(SelectBase):
    _attr_current_option = None

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_output_priority"
        self._attr_name = f"{self._inverter_device.name} Output Priority"
        self._attr_options = ['Utility', 'Solar', 'SBU', 'SUB', 'SUB']

        if coordinator.data is not None:
            data = coordinator.data[self._inverter_device.inverter_id]
            device_data = self._inverter_device.device_data
            self._attr_current_option = resolve_output_priority(data, device_data)

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data[self._inverter_device.inverter_id]
        device_data = self._inverter_device.device_data
        self._attr_current_option = resolve_output_priority(data, device_data)
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        if option in self._attr_options:
            # los_output_source_priority Utility, Solar, SBU
            await set_inverter_output_priority(
                self.coordinator.auth['token'],
                self.coordinator.auth['secret'],
                self._inverter_device.device_data,
                option
            )
            self._attr_current_option = option
            await self.coordinator.async_request_refresh()


class InverterDynamicSettingSelect(SelectBase):
    _attr_current_option = None
    _last_updated = None
    _disabled_param = False
    should_poll = True
    _attr_entity_category = EntityCategory.CONFIG

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

    # async def async_added_to_hass(self) -> None:
    #     """Handle entity which will be added."""
    #
    #     if (last_sensor_data := await self.async_get_last_extra_data()) is not None:
    #         # print('last_sensor_data', last_sensor_data.as_dict())
    #         self._attr_current_option = (last_sensor_data.as_dict())['native_value']
    #     else:
    #         self._attr_current_option = None
    #     # await self.async_update()
    #     await super().async_added_to_hass()

    async def async_update(self, force=False):
        now = int(datetime.now().timestamp())
        if self._last_updated is not None and now - self._last_updated > 300:
            pass
        else:
            if self._last_updated is None:
                pass

        if self.coordinator.auth['token'] is not None:
            response = await get_device_ctrl_value(self.coordinator.auth['token'],
                                                   self.coordinator.auth['secret'],
                                                   self._inverter_device.device_data,
                                                   self._service_param_id)

            if 'err' not in response:
                val = response['val'] if 'unit' not in self._field_data else str(
                    resolve_number_with_unit(response['val']))
                mapped_list = list(map(lambda x: x.lower(), self._attr_options))
                try:
                    index = mapped_list.index(val.lower())
                    real_val = self._attr_options[index]
                    self._attr_current_option = real_val
                    self._last_updated = now
                    self.async_write_ha_state()
                except ValueError:
                    if self._last_updated is None:
                        self._disabled_param = True
                    self._last_updated = now
            else:
                if self._last_updated is None:
                    self._disabled_param = True
                # print('get_device_ctrl_value', self._inverter_device.name, self._service_param_id, response)

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
            # print('set_ctrl_device_param', param_id, param_value)
            await set_ctrl_device_param(
                self.coordinator.auth['token'],
                self.coordinator.auth['secret'],
                self._inverter_device.device_data,
                param_id,
                param_value
            )

            self._attr_current_option = option
            self.async_write_ha_state()
            # await self.coordinator.async_request_refresh()
