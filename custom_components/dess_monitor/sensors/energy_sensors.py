from datetime import datetime

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy, PERCENTAGE
from homeassistant.core import callback
from homeassistant.util import slugify

from custom_components.dess_monitor.api.resolvers.data_resolvers import *
from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sensors.init_sensors import SensorBase
from custom_components.dess_monitor.sensors.mixin_sensors import EntityStateSubscriberMixin, VoltageEntityMixin, \
    SocCalculatorMixin


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


class TypedSensorBase(SensorBase):
    def __init__(
            self,
            inverter_device: InverterDevice,
            coordinator: MainCoordinator,
            sensor_suffix: str = "",
            name_suffix: str = ""
    ):
        super().__init__(inverter_device, coordinator)

        suffix = sensor_suffix
        name_part = name_suffix

        self._attr_unique_id = f"{self._inverter_device.inverter_id}_{suffix}"
        self._attr_name = f"{self._inverter_device.name} {name_part}"


class BatteryStateOfChargeSensor(
    TypedSensorBase,
    VoltageEntityMixin,
    EntityStateSubscriberMixin,
    SocCalculatorMixin,
    RestoreSensor,
    SensorEntity,
):
    """
    SOC-сенсор для батареи, используя TypedSensorBase и миксины.
    """
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(self, inverter_device, coordinator):
        TypedSensorBase.__init__(
            self,
            inverter_device=inverter_device,
            coordinator=coordinator,
            sensor_suffix="battery_state_of_charge_ess",
            name_suffix="Battery State of Charge ESS",
        )
        hass = coordinator.hass
        slug = slugify(inverter_device.name)
        capacity_entity = f"number.{slug}_vsoc_battery_capacity"
        full_charge_entity = f"number.{slug}_battery_fully_charge_voltage"

        VoltageEntityMixin.__init__(self, hass, full_charge_entity, "battery_full_charge_voltage")
        EntityStateSubscriberMixin.__init__(self, hass, capacity_entity, "battery_capacity_wh")
        SocCalculatorMixin.__init__(self, initial_energy_wh=100.0)

        self._restored = False
        coordinator.async_add_listener(self._handle_coordinator_update)

    async def async_added_to_hass(self):
        last = await self.async_get_last_extra_data()
        if last:
            restored = last.as_dict().get("native_value")
            if restored is not None:
                try:
                    self._attr_native_value = float(restored)
                except (ValueError, TypeError):
                    self._attr_native_value = None
            else:
                self._attr_native_value = None
        self._restored = True
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        return (
                self._restored
                and self.battery_capacity_wh is not None
                and self.get_bulk_charging_voltage() is not None
        )

    def _on_subscribed_value_update(self):
        if self._attr_native_value is not None:
            self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self, *_):
        try:
            voltage = resolve_battery_voltage(self.data, self._inverter_device.device_data)
            charge_i = resolve_battery_charging_current(self.data, self._inverter_device.device_data)
            discharge_i = resolve_battery_discharge_current(self.data, self._inverter_device.device_data)
            power = charge_i * voltage if charge_i > 0 else -discharge_i * voltage

            cap = self.battery_capacity_wh
            bulk_v = self.get_bulk_charging_voltage()
            float_v = self.get_floating_charging_voltage()

            soc = self.calculate_soc(
                capacity_wh=cap,
                bulk_v=bulk_v,
                float_v=float_v,
                current_power=power,
                current_voltage=voltage,
            )
            self._attr_native_value = round(soc, 1)
        except Exception:
            self._attr_native_value = None
        self.async_write_ha_state()
