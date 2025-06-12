from enum import Enum

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory, UnitOfPower, UnitOfElectricPotential, UnitOfFrequency, \
    UnitOfElectricCurrent, PERCENTAGE
from homeassistant.core import callback

from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sensors.init_sensors import SensorBase


class DessSensorSource(Enum):
    PARS_ES = 'pars'
    SP_LAST_DATA = 'last_data'
    ENERGY_FLOW = 'energy_flow'


class InverterDynamicSensor(SensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator, sensor_data,
                 sensor_source: DessSensorSource):
        """Initialize the sensor."""
        super().__init__(inverter_device, coordinator)
        # "par": "bt_battery_charging_current",
        # "name": "Battery Charging Current",
        # "val": "0.0000",
        # "unit": "A"
        self._sensor_par_id = sensor_data['par']
        self._sensor_source = sensor_source
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_raw_{sensor_data['par']}"
        self._attr_name = f"{self._inverter_device.name} Raw {sensor_data['name']}"

        device_class_map = {
            'kW': SensorDeviceClass.POWER,
            'W': SensorDeviceClass.POWER,
            'A': SensorDeviceClass.CURRENT,
            'V': SensorDeviceClass.VOLTAGE,
            'HZ': SensorDeviceClass.FREQUENCY,
            '%': SensorDeviceClass.BATTERY,
        }
        unit_map = {
            'kW': UnitOfPower.KILO_WATT,
            'W': UnitOfPower.WATT,
            'A': UnitOfElectricCurrent.AMPERE,
            'V': UnitOfElectricPotential.VOLT,
            'HZ': UnitOfFrequency.HERTZ,
            '%': PERCENTAGE,
        }
        display_unit = unit_map[sensor_data['unit']]
        self._attr_device_class = device_class_map[sensor_data['unit']]
        # self._unit_of_measurement = sensor_data['unit']
        self._attr_unit_of_measurement = display_unit
        self._attr_native_unit_of_measurement = display_unit
        self._attr_native_value = float(sensor_data['val'])
        # self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.data

        def get_prefix(s):
            return s.split("_", 1)[0] + "_"

        match self._sensor_source:
            case DessSensorSource.PARS_ES:
                self._attr_native_value = float(
                    next((x for x in data['pars']['parameter'] if x['par'] == self._sensor_par_id), {'val': '0'})['val']
                )
            case DessSensorSource.SP_LAST_DATA:
                key = get_prefix(self._sensor_par_id)
                self._attr_native_value = float(
                    next((x for x in data['last_data']['pars'][key] if x['id'] == self._sensor_par_id), {'val': '0'})[
                        'val']
                )
        self.async_write_ha_state()
