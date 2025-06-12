from datetime import timedelta, datetime

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor import MainCoordinator, HubConfigEntry
from custom_components.dess_monitor.api import set_ctrl_device_param, get_device_ctrl_value
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
        if coordinator_data is None or item.inverter_id not in coordinator_data:
            continue
        fields = coordinator_data[item.inverter_id]['ctrl_fields']
        if fields is None:
            continue
        async_add_entities(list(
            map(
                lambda field_data: InverterDynamicSettingNumber(item, coordinator, field_data),
                filter(lambda field: 'item' not in field, fields)
            )
        )
        )
    for item in hub.items:
        new_devices.extend([
            BatteryCapacityNumber(item, hass)
        ])
    if new_devices:
        async_add_entities(new_devices)


class NumberBase(CoordinatorEntity, NumberEntity):
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


class InverterDynamicSettingNumber(NumberBase):
    _attr_native_value = None
    should_poll = True
    _attr_entity_category = EntityCategory.CONFIG

    # _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator, field_data):
        super().__init__(inverter_device, coordinator)
        self._last_updated = None
        self._service_param_id = field_data['id']
        # "hint": "25.0~31.5V 48.0~61.0V"
        # self._id
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_settings_{field_data['id']}"
        self._attr_name = f"{self._inverter_device.name} SET {field_data['name']}"
        self._attr_native_unit_of_measurement = 'V'  # field_data['unit']
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 0.1
        self._attr_mode = NumberMode.BOX

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

    async def async_update(self):
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
                self._attr_native_value = resolve_number_with_unit(response['val'])
                self._last_updated = now
                self.async_write_ha_state()
            else:
                print('get_device_ctrl_value', self._inverter_device.name, self._service_param_id, response)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        param_id = self._service_param_id
        param_value = str(value)
        # print('set_ctrl_device_param', param_id, param_value)
        await set_ctrl_device_param(
            self.coordinator.auth['token'],
            self.coordinator.auth['secret'],
            self._inverter_device.device_data,
            param_id,
            param_value
        )

        self._attr_native_value = param_value
        self.async_write_ha_state()
        # await self.coordinator.async_request_refresh()



class BatteryCapacityNumber(NumberEntity, RestoreEntity):
    def __init__(self, inverter_device, hass):
        self._inverter_device = inverter_device
        self._hass = hass
        self._attr_unique_id = f"{inverter_device.inverter_id}_battery_capacity_wh"
        self._attr_name = f"{inverter_device.name} vSoC Battery Capacity"
        self._value = None  # Начальное значение, None

        self._attr_native_min_value = 0
        self._attr_native_max_value = 100000
        self._attr_native_step = 10
        self._attr_mode = NumberMode.BOX
        self._attr_native_unit_of_measurement = "Wh"
        self._attr_icon = "mdi:battery"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, inverter_device.inverter_id)},
            name=inverter_device.name,
            manufacturer="ESS",
            model=inverter_device.device_data.get("pn"),
            sw_version=inverter_device.firmware_version,
            hw_version=inverter_device.device_data.get("devcode"),
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._value = float(state.state)
            except ValueError:
                self._value = None

    @property
    def native_value(self):
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        self.async_write_ha_state()
