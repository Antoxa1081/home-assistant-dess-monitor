import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

from custom_components.dess_monitor.api.helpers import safe_float, safe_int
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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

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
        coord_data = self.coordinator.data
        if coord_data is None:
            return None
        return coord_data.get(self._inverter_device.inverter_id)


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
        data = self.data
        if data is None:
            self._attr_native_value = None
        else:
            try:
                self._attr_native_value = self._resolve_fn(
                    data,
                    self._inverter_device,
                )
            except Exception:
                _LOGGER.exception(
                    "Resolver failed for %s", self._attr_unique_id
                )
                self._attr_native_value = None
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


class VirtualBatterySocSensor(SensorBase):
    """Coulomb-counted SOC for inverters that don't publish a real battery %.

    Reads from :class:`VirtualBatteryEstimator` attached to the device.
    Stays "Unknown" until the user enters capacity/full voltage on the
    per-device CONFIG entities AND the integrator (or full-rebase) yields a
    first SOC reading.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{inverter_device.inverter_id}_virtual_battery_soc"
        self._attr_name = f"{inverter_device.name} Virtual Battery"

    @callback
    def _handle_coordinator_update(self) -> None:
        estimator = self._inverter_device.virtual_battery
        if estimator is None:
            self._attr_native_value = None
        else:
            soc = estimator.soc
            self._attr_native_value = round(soc, 1) if isinstance(soc, (int, float)) else None
        self.async_write_ha_state()


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


class BatteryPowerSensor(ValueResolvingSensor):
    """Net signed battery power: positive when charging, negative when discharging.

    Useful for energy-flow cards (Sunsynk / Power Flow) that expect a single
    signed value rather than separate charge/discharge legs.
    """

    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Battery Power", "battery_power",
                         resolve_battery_power, SensorDeviceClass.POWER, UnitOfPower.WATT)


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


def _resolve_energy_total(data, _):
    try:
        return safe_float(data['device']['energyTotal'], default=None)
    except (KeyError, TypeError):
        return None


class PVPowerTotalSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "PV Total Energy", "pv_total_energy",
                         _resolve_energy_total, SensorDeviceClass.ENERGY,
                         UnitOfEnergy.KILO_WATT_HOUR, 3, None, SensorStateClass.TOTAL)


_STATUS_OPTIONS = ['NORMAL', 'OFFLINE', 'FAULT', 'STANDBY', 'WARNING']


def _resolve_status(data, _):
    try:
        idx = safe_int(data['device']['status'])
    except (KeyError, TypeError):
        return None
    if idx is None or not 0 <= idx < len(_STATUS_OPTIONS):
        return None
    return _STATUS_OPTIONS[idx]


class InverterStatusSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Status", "status",
                         _resolve_status, SensorDeviceClass.ENUM, None,
                         entity_category=EntityCategory.DIAGNOSTIC)


class InverterOutputPrioritySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Output Priority", "output_priority", resolve_output_priority,
                         SensorDeviceClass.ENUM, None, entity_category=EntityCategory.DIAGNOSTIC)


class InverterChargePrioritySensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Charge Priority", "charge_priority", resolve_charge_priority,
                         SensorDeviceClass.ENUM, None, entity_category=EntityCategory.DIAGNOSTIC)


_MAINS_STATUS_OPTIONS = ['BATTERY', 'GRID', 'SOLAR', 'HYBRID', 'STANDBY', 'FAULT', 'OFF']


class InverterMainsStatusSensor(ValueResolvingSensor):
    """Operating mode of the inverter — drives 'is grid live?' automations."""

    _attr_options = _MAINS_STATUS_OPTIONS

    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Mains Status", "mains_status", resolve_mains_status,
                         SensorDeviceClass.ENUM, None)


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


class InverterLastSampleTimeSensor(ValueResolvingSensor):
    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "Last Sample Time", "last_sample_time",
                         resolve_last_sample_time, SensorDeviceClass.TIMESTAMP, None,
                         entity_category=EntityCategory.DIAGNOSTIC)


class InverterWebSocketLastFrameSensor(ValueResolvingSensor):
    """Timestamp of the most recent WebSocket telemetry frame for the device.

    Stays ``Unknown`` while the WS stream is disabled or hasn't connected yet.
    Useful as a freshness signal — automations can flag "WS stale" when this
    sensor lags behind ``Last Sample Time`` by more than a couple of polling
    intervals.
    """

    def __init__(self, inverter_device, coordinator):
        super().__init__(inverter_device, coordinator, "WebSocket Last Frame At", "ws_last_frame_at",
                         resolve_ws_last_frame_at, SensorDeviceClass.TIMESTAMP, None,
                         entity_category=EntityCategory.DIAGNOSTIC)
