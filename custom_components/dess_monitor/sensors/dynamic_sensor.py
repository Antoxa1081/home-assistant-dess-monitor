from enum import Enum

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import callback

from custom_components.dess_monitor.api.helpers import safe_float
from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sensors.init_sensors import SensorBase


class DessSensorSource(Enum):
    PARS_ES = 'pars'
    SP_LAST_DATA = 'last_data'
    ENERGY_FLOW = 'energy_flow'


# Cloud sends the same physical unit with inconsistent casing (``Hz`` vs ``HZ``,
# ``kW`` vs ``KW``) — normalise to a canonical key before looking up.
_UNIT_ALIASES: dict[str, str] = {
    "kw": "kW",
    "w": "W",
    "a": "A",
    "v": "V",
    "hz": "Hz",
    "\u00b0c": "\u00b0C",
    "va": "VA",
    "wh": "Wh",
    "kwh": "kWh",
    "%": "%",
}

_UNIT_DISPLAY: dict[str, str] = {
    "kW": UnitOfPower.KILO_WATT,
    "W": UnitOfPower.WATT,
    "A": UnitOfElectricCurrent.AMPERE,
    "V": UnitOfElectricPotential.VOLT,
    "Hz": UnitOfFrequency.HERTZ,
    "\u00b0C": UnitOfTemperature.CELSIUS,
    "VA": UnitOfApparentPower.VOLT_AMPERE,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "%": PERCENTAGE,
}

_UNIT_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    "kW": SensorDeviceClass.POWER,
    "W": SensorDeviceClass.POWER,
    "A": SensorDeviceClass.CURRENT,
    "V": SensorDeviceClass.VOLTAGE,
    "Hz": SensorDeviceClass.FREQUENCY,
    "\u00b0C": SensorDeviceClass.TEMPERATURE,
    "VA": SensorDeviceClass.APPARENT_POWER,
    "Wh": SensorDeviceClass.ENERGY,
    "kWh": SensorDeviceClass.ENERGY,
    # ``%`` intentionally has no device_class — it covers SOC, load percent,
    # charge percent, etc. Mapping all of them to BATTERY mislabels load.
}

# Energy units accumulate; everything else is an instantaneous measurement.
_TOTAL_UNITS = {"Wh", "kWh"}


def _canon_unit(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    return _UNIT_ALIASES.get(raw.strip().lower())


def _is_supported_unit(param: dict) -> bool:
    return _canon_unit(param.get("unit")) is not None


class InverterDynamicSensor(SensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator, sensor_data,
                 sensor_source: DessSensorSource):
        """Initialize the sensor."""
        super().__init__(inverter_device, coordinator)
        self._sensor_par_id = sensor_data['par']
        self._sensor_source = sensor_source
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_raw_{sensor_data['par']}"
        self._attr_name = f"{self._inverter_device.name} Raw {sensor_data['name']}"

        unit = _canon_unit(sensor_data.get('unit'))
        display_unit = _UNIT_DISPLAY.get(unit) if unit else None
        self._attr_device_class = _UNIT_DEVICE_CLASS.get(unit) if unit else None
        self._attr_native_unit_of_measurement = display_unit
        if unit in _TOTAL_UNITS:
            # We can't tell from raw data whether the counter monotonically
            # increases, but TOTAL covers both monotonic and resettable cases
            # and lets long-term statistics work.
            self._attr_state_class = SensorStateClass.TOTAL
        elif unit is not None:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = safe_float(sensor_data.get('val'), default=None)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.data
        if data is None:
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        def get_prefix(s):
            return s.split("_", 1)[0] + "_"

        try:
            match self._sensor_source:
                case DessSensorSource.PARS_ES:
                    parameter = (data.get('pars') or {}).get('parameter') or []
                    found = next((x for x in parameter if x.get('par') == self._sensor_par_id), None)
                    self._attr_native_value = safe_float(found.get('val'), default=None) if found else None
                case DessSensorSource.SP_LAST_DATA:
                    key = get_prefix(self._sensor_par_id)
                    pars = ((data.get('last_data') or {}).get('pars') or {}).get(key) or []
                    found = next((x for x in pars if x.get('id') == self._sensor_par_id), None)
                    self._attr_native_value = safe_float(found.get('val'), default=None) if found else None
                case _:
                    self._attr_native_value = None
        except Exception:
            self._attr_native_value = None
        self.async_write_ha_state()
