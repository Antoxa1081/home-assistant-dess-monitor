from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfElectricPotential, UnitOfPower, PERCENTAGE, UnitOfFrequency, \
    UnitOfElectricCurrent, EntityCategory, UnitOfTemperature, UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor.api.resolvers.data_resolvers import *
from custom_components.dess_monitor.const import DOMAIN
from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.hub import InverterDevice


class SensorBase(CoordinatorEntity, SensorEntity):
    def __init__(
            self,
            inverter_device: InverterDevice,
            coordinator: MainCoordinator
    ):
        super().__init__(coordinator)
        self._inverter_device = inverter_device

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._inverter_device.inverter_id)},
            "name": self._inverter_device.name,
            "sw_version": self._inverter_device.firmware_version,
            "model": self._inverter_device.device_data['pn'],
            "serial_number": self._inverter_device.device_data['sn'],
            "hw_version": self._inverter_device.device_data['devcode'],
            "model_id": self._inverter_device.device_data['devaddr'],
            "manufacturer": 'ESS'
        }

    @property
    def available(self) -> bool:
        return (
                self._inverter_device.online and
                self._inverter_device.hub.online
        )

    @property
    def data(self):
        return self.coordinator.data[self._inverter_device.inverter_id]


class ValueResolvingSensor(SensorBase):
    def __init__(
            self,
            inverter_device: InverterDevice,
            coordinator: MainCoordinator,
            name_suffix: str,
            unique_suffix: str,
            resolve_fn,
            device_class: SensorDeviceClass,
            unit,
            precision: int = 0,
            entity_category=None,
            state_class=None
    ):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator
        )
        self._attr_name = f"{inverter_device.name} {name_suffix}"
        self._attr_unique_id = f"{inverter_device.inverter_id}_{unique_suffix}"
        self._resolve_fn = resolve_fn
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_unit_of_measurement = unit
        self._attr_suggested_display_precision = precision
        self._sensor_option_display_precision = precision

        if entity_category is not None:
            self._attr_entity_category = entity_category

        if state_class is not None:
            self._attr_state_class = state_class

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self._resolve_fn(
            self.data,
            self._inverter_device.device_data
        )
        self.async_write_ha_state()


class BatteryVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Voltage", "battery", resolve_battery_voltage,
                         SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, 1)


class PVPowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV Power", "pv_power", resolve_pv_power,
                         SensorDeviceClass.POWER, UnitOfPower.WATT)


class PVVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV Voltage", "pv_voltage", resolve_pv_voltage,
                         SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT)


class PV2PowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV2 Power", "pv2_power", resolve_pv2_power,
                         SensorDeviceClass.POWER, UnitOfPower.WATT)


class PV2VoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV2 Voltage", "pv2_voltage", resolve_pv2_voltage,
                         SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT)


class GridInputVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Grid In Voltage", "grid_in_voltage", resolve_grid_input_voltage,
                         SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT)


class InverterOutputVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Inverter Out Voltage", "inverter_out_voltage",
                         resolve_grid_output_voltage, SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT)


class InverterOutputPowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Inverter Out Power", "inverter_out_power",
                         resolve_active_load_power, SensorDeviceClass.POWER, UnitOfPower.WATT)


class InverterLoadSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Inverter Load", "inverter_load", resolve_active_load_percentage,
                         SensorDeviceClass.POWER_FACTOR, PERCENTAGE)


class BatteryCapacitySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Capacity", "battery_capacity", resolve_battery_capacity,
                         SensorDeviceClass.BATTERY, PERCENTAGE)


class GridInputPowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Grid In Power", "grid_in_power", resolve_grid_in_power,
                         SensorDeviceClass.POWER, UnitOfPower.WATT)


class GridInputFrequencySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Grid In Frequency", "grid_in_frequency", resolve_grid_frequency,
                         SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ, 2, EntityCategory.DIAGNOSTIC)


class BatteryChargeSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Charge Current", "battery_charge_current",
                         resolve_battery_charging_current, SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, 1)


class BatteryDischargeSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Discharge Current", "battery_discharge_current",
                         resolve_battery_discharge_current, SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, 1)


class BatteryChargePowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Charge Power", "battery_charge_power",
                         resolve_battery_charging_power, SensorDeviceClass.POWER, UnitOfPower.WATT)


class BatteryDischargePowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Discharge Power", "battery_discharge_power",
                         resolve_battery_discharge_power, SensorDeviceClass.POWER, UnitOfPower.WATT)


class InverterDCTemperatureSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Inverter DC Temperature", "inverter_dc_temperature",
                         resolve_dc_module_temperature, SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, 0,
                         EntityCategory.DIAGNOSTIC)


class InverterInvTemperatureSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Inverter INV Temperature", "inverter_inv_temperature",
                         resolve_inv_temperature, SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, 0,
                         EntityCategory.DIAGNOSTIC)


class PVPowerTotalSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV Total Energy", "pv_total_energy",
                         lambda data, _: data['device']['energyTotal'], SensorDeviceClass.ENERGY,
                         UnitOfEnergy.KILO_WATT_HOUR, 3, None, SensorStateClass.TOTAL)


class InverterStatusSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        options = ['NORMAL', 'OFFLINE', 'FAULT', 'STANDBY', 'WARNING']
        super().__init__(inverter_device, coordinator, "Status", "status",
                         lambda data, _: options[data['device']['status']], SensorDeviceClass.ENUM, None,
                         entity_category=EntityCategory.DIAGNOSTIC)


class InverterOutputPrioritySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Output Priority", "output_priority", resolve_output_priority,
                         SensorDeviceClass.ENUM, None, entity_category=EntityCategory.DIAGNOSTIC)


class InverterChargePrioritySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Charge Priority", "charge_priority", resolve_charge_priority,
                         SensorDeviceClass.ENUM, None, entity_category=EntityCategory.DIAGNOSTIC)


class InverterConfigBTUtilityChargeSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Utility Charge Current",
                         "config_bt_utility_charge_current", resolve_bt_utility_charge, SensorDeviceClass.CURRENT,
                         UnitOfElectricCurrent.AMPERE, entity_category=EntityCategory.DIAGNOSTIC)


class InverterConfigBTTotalChargeSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Total Charge Current", "config_bt_total_charge_current",
                         resolve_bt_total_charge_current, SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE,
                         entity_category=EntityCategory.DIAGNOSTIC)


class InverterConfigBTCutoffSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Cutoff Voltage", "config_bt_cutoff_voltage",
                         resolve_bt_cutoff_voltage, SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT,
                         entity_category=EntityCategory.DIAGNOSTIC)


class InverterNominalOutPowerSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Nominal Out Power", "nominal_out_power",
                         resolve_sy_nominal_out_power, SensorDeviceClass.POWER, UnitOfPower.WATT, 0,
                         EntityCategory.DIAGNOSTIC)


class InverterRatedBatteryVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Rated Battery Voltage", "rated_battery_voltage",
                         resolve_sy_rated_battery_voltage, SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, 0,
                         EntityCategory.DIAGNOSTIC)


class InverterComebackUtilityVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Comeback Utility", "comeback_utility_voltage",
                         resolve_bt_comeback_utility_voltage, SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT,
                         1, EntityCategory.DIAGNOSTIC)


class InverterComebackBatteryVoltageSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device,
            coordinator,
            "Comeback Battery",
            "comeback_battery_voltage",
            resolve_bt_comeback_battery_voltage,
            SensorDeviceClass.VOLTAGE,
            UnitOfElectricPotential.VOLT,
            1,
            EntityCategory.DIAGNOSTIC
        )
