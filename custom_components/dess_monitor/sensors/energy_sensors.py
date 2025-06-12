from datetime import datetime

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, PERCENTAGE
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from custom_components.dess_monitor.api.resolvers.data_resolvers import *
from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sensors.init_sensors import SensorBase


class MyEnergySensor(RestoreSensor, SensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0
    _attr_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._prev_value = None
        self._prev_value_timestamp = datetime.now()
        self._is_restored_value = False

    async def async_added_to_hass(self) -> None:
        if (last_sensor_data := await self.async_get_last_extra_data()) is not None:
            self._attr_native_value = last_sensor_data.as_dict().get('native_value', 0)
        else:
            self._attr_native_value = 0
        self._is_restored_value = True
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        return self._inverter_device.online and self._inverter_device.hub.online and self._is_restored_value

    def update_energy_value(self, current_value: float):
        now = datetime.now()
        elapsed_seconds = int(now.timestamp() - self._prev_value_timestamp.timestamp())
        if self._prev_value is not None:
            self._attr_native_value += (elapsed_seconds / 3600) * (self._prev_value + current_value) / 2
        self._prev_value = current_value
        self._prev_value_timestamp = now
        self.async_write_ha_state()


class FunctionBasedEnergySensor(MyEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator, unique_suffix: str,
                 name_suffix: str, resolve_function):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_{unique_suffix}"
        self._attr_name = f"{self._inverter_device.name} {name_suffix}"
        self._resolve_function = resolve_function

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.data
        device_data = self._inverter_device.device_data
        current_value = self._resolve_function(data, device_data)
        self.update_energy_value(current_value)


class PVEnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "pv_in_energy", "PV In Energy", resolve_pv_power)


class PV2EnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "pv2_in_energy", "PV2 In Energy", resolve_pv2_power)


class BatteryInEnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "battery_in_energy", "Battery In Energy",
                         resolve_battery_charging_power)


class BatteryOutEnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "battery_out_energy", "Battery Out Energy",
                         resolve_battery_discharge_power)


class InverterOutEnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "inverter_out_energy", "Inverter Out Energy",
                         resolve_active_load_power)


class InverterInEnergySensor(FunctionBasedEnergySensor):
    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator, "inverter_in_energy", "Inverter In Energy",
                         resolve_grid_in_power)


# class TypedSensorBase(SensorBase):
#     def __init__(
#             self,
#             inverter_device: InverterDevice,
#             coordinator: MainCoordinator,
#             data_section: str,
#             data_key: str,
#             sensor_suffix: str = "",
#             name_suffix: str = ""
#     ):
#         super().__init__(inverter_device, coordinator)
#         self.data_section = data_section
#         self.data_key = data_key
#
#         suffix = sensor_suffix or data_key
#         name_part = name_suffix or data_key.replace('_', ' ').title()
#
#         self._attr_unique_id = f"{self._inverter_device.inverter_id}_{suffix}"
#         self._attr_name = f"{self._inverter_device.name} {name_part}"
#
#     @callback
#     def _handle_coordinator_update(self) -> None:
#         section = self.data.get(self.data_section, {})
#         raw_value = section.get(self.data_key)
#
#         if raw_value is not None:
#             try:
#                 self._attr_native_value = float(raw_value)
#             except (ValueError, TypeError):
#                 self._attr_native_value = None
#         else:
#             self._attr_native_value = None
#
#         self.async_write_ha_state()


# class BatteryStateOfChargeSensor(RestoreSensor, TypedSensorBase):
#     _attr_device_class = SensorDeviceClass.BATTERY
#     _attr_native_unit_of_measurement = PERCENTAGE
#     _attr_suggested_display_precision = 1
#
#     def __init__(self, inverter_device, coordinator, hass):
#         super().__init__(
#             inverter_device=inverter_device,
#             coordinator=coordinator,
#             sensor_suffix="battery_state_of_charge",
#             name_suffix="Battery State of Charge",
#         )
#         self._accumulated_energy_wh = 100.0
#         self._prev_power = None
#         self._prev_ts = datetime.now()
#         self._restored = False
#         self._hass = hass
#
#         device_slug = slugify(self._inverter_device.name)
#         self._capacity_entity_id = f"number.{device_slug}_vsoc_battery_capacity"
#         self._battery_capacity_wh = None
#
#         async_track_state_change_event(
#             self._hass,
#             [self._capacity_entity_id],
#             self._handle_battery_capacity_change,
#         )
#
#     async def async_added_to_hass(self) -> None:
#         state = self._hass.states.get(self._capacity_entity_id)
#         self._update_battery_capacity_from_state(state)
#
#         last_data = await self.async_get_last_extra_data()
#         if last_data is not None:
#             restored = last_data.as_dict().get("native_value", None)
#             self._attr_native_value = float(restored) if restored is not None else None
#         else:
#             self._attr_native_value = None
#         self._restored = True
#         await super().async_added_to_hass()
#
#     @property
#     def available(self) -> bool:
#         # Доступен только если восстановлен и емкость задана положительно
#         bulk_voltage = self.get_bulk_charging_voltage()
#         return super().available and self._restored and (
#                     self._battery_capacity_wh is not None and self._battery_capacity_wh > 0) and (
#                     bulk_voltage is not None)
#
#     @callback
#     def _handle_battery_capacity_change(self, event):
#         state = event.data.get("new_state")
#         self._update_battery_capacity_from_state(state)
#
#     def _update_battery_capacity_from_state(self, state):
#         if state is None:
#             self._battery_capacity_wh = None
#             self._attr_native_value = None
#             self.async_write_ha_state()
#             return
#         try:
#             value = float(state.state)
#             if value <= 0:
#                 self._battery_capacity_wh = None
#                 self._attr_native_value = None
#             else:
#                 self._battery_capacity_wh = value
#         except (ValueError, TypeError):
#             self._battery_capacity_wh = None
#             self._attr_native_value = None
#         self.async_write_ha_state()
#
#     def get_bulk_charging_voltage(self) -> float | None:
#         try:
#             voltage = resolve_battery_charging_voltage(self.data)
#             if voltage > 0:
#                 return voltage
#         except (KeyError, ValueError, TypeError):
#             pass
#         return None
#
#     def update_soc(self, current_power: float, current_voltage: float):
#         if self._battery_capacity_wh is None or self._battery_capacity_wh <= 0:
#             # Не считаем, если емкость не задана
#             self._attr_native_value = None
#             self.async_write_ha_state()
#             return
#
#         bulk_voltage = self.get_bulk_charging_voltage()
#         if bulk_voltage is None:
#             self._attr_native_value = None
#             self.async_write_ha_state()
#             return
#
#         now = datetime.now()
#         elapsed_seconds = (now - self._prev_ts).total_seconds()
#
#         if self._prev_power is not None:
#             energy_increment = (elapsed_seconds / 3600) * (self._prev_power + current_power) / 2
#             self._accumulated_energy_wh += energy_increment
#
#         self._prev_power = current_power
#         self._prev_ts = now
#
#         max_capacity = self._battery_capacity_wh
#
#         if current_voltage >= bulk_voltage:
#             soc_percent = 100.0
#             self._accumulated_energy_wh = max_capacity
#         else:
#             if self._accumulated_energy_wh < 0:
#                 self._accumulated_energy_wh = 0.0
#             elif self._accumulated_energy_wh > max_capacity:
#                 self._accumulated_energy_wh = max_capacity
#
#             soc_percent = (self._accumulated_energy_wh / max_capacity) * 100
#
#         soc_percent = max(0.0, min(100.0, soc_percent))
#
#         self._attr_native_value = soc_percent
#         self.async_write_ha_state()
#
#     @callback
#     def _handle_coordinator_update(self) -> None:
#         try:
#             current_voltage = resolve_battery_voltage(self.data, self._inverter_device.device_data)
#             charging_power = resolve_battery_charging_power(self.data, self._inverter_device.device_data)
#             discharging_power = resolve_battery_discharge_power(self.data, self._inverter_device.device_data)
#             power = 0.0
#             if charging_power > 0:
#                 power = charging_power
#             elif discharging_power > 0:
#                 power = -discharging_power
#
#             self.update_soc(power, current_voltage)
#         except (KeyError, ValueError, TypeError):
#             self._attr_native_value = None
#             self.async_write_ha_state()
