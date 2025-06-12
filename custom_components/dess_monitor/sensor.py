"""Platform for sensor integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.dess_monitor.sensors.direct_sensor import DIRECT_SENSORS, generate_qpiri_sensors
from . import HubConfigEntry
from .sensors.direct_energy_sensors import DirectInverterOutputEnergySensor, DirectPV2EnergySensor, \
    DirectPVEnergySensor, DirectBatteryInEnergySensor, DirectBatteryOutEnergySensor, DirectBatteryStateOfChargeSensor
from .sensors.dynamic_sensor import *
from .sensors.energy_sensors import *
from .sensors.init_sensors import *


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: HubConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hub = config_entry.runtime_data
    new_devices = []

    for item in hub.items:
        new_devices.extend(create_static_sensors(item, hub.coordinator))

        if should_add_dynamic_sensors(config_entry, hub, item):
            new_devices.extend(create_dynamic_sensors(item, hub.coordinator))

        if should_add_direct_sensors(config_entry, hub, item):
            new_devices.extend(create_direct_sensors(item, hub.direct_coordinator))
            new_devices.extend(generate_qpiri_sensors(item, hub.direct_coordinator))
            new_devices.extend([
                DirectPVEnergySensor(item, hub.direct_coordinator),
                DirectPV2EnergySensor(item, hub.direct_coordinator),
                DirectInverterOutputEnergySensor(item, hub.direct_coordinator),
                DirectBatteryInEnergySensor(item, hub.direct_coordinator),
                DirectBatteryOutEnergySensor(item, hub.direct_coordinator),
                DirectBatteryStateOfChargeSensor(item, hub.direct_coordinator, hass),
            ])

    if new_devices:
        async_add_entities(new_devices)


def create_static_sensors(item, coordinator):
    """Return list of static sensors for an item."""
    sensor_classes = [
        # Grid sensors
        GridInputVoltageSensor,
        GridInputFrequencySensor,
        GridInputPowerSensor,

        # PV sensors
        PVPowerSensor,
        PV2PowerSensor,
        PVPowerTotalSensor,  # deprecated
        PVEnergySensor,
        PV2EnergySensor,
        PVVoltageSensor,
        PV2VoltageSensor,

        # Battery sensors
        BatteryVoltageSensor,
        BatteryChargeSensor,
        BatteryChargePowerSensor,
        BatteryDischargeSensor,
        BatteryDischargePowerSensor,
        BatteryInEnergySensor,
        BatteryOutEnergySensor,
        BatteryCapacitySensor,

        # Inverter sensors
        InverterStatusSensor,
        InverterOutputPrioritySensor,
        InverterOutputVoltageSensor,
        InverterOutputPowerSensor,
        InverterOutEnergySensor,
        InverterInEnergySensor,
        InverterDCTemperatureSensor,
        InverterInvTemperatureSensor,
        InverterLoadSensor,

        # Inverter config sensors
        InverterChargePrioritySensor,
        InverterConfigBTUtilityChargeSensor,
        InverterConfigBTTotalChargeSensor,
        InverterConfigBTCutoffSensor,
        InverterNominalOutPowerSensor,
        InverterRatedBatteryVoltageSensor,
        InverterComebackUtilityVoltageSensor,
        InverterComebackBatteryVoltageSensor,
    ]
    return [sensor_cls(item, coordinator) for sensor_cls in sensor_classes]


def should_add_dynamic_sensors(config_entry, hub, item):
    return (
            config_entry.options.get('raw_sensors', False)
            and hub.coordinator.data is not None
            and item.inverter_id in hub.coordinator.data
    )


def create_dynamic_sensors(item, coordinator):
    """Return dynamic sensors for an item based on parameters."""
    sensors = []
    data = coordinator.data[item.inverter_id]
    allowed_units = {'kW', 'W', 'A', 'V', 'HZ', '%'}

    def is_valid_parameter(param):
        return 'unit' in param and param['unit'] in allowed_units

    for parameter in filter(is_valid_parameter, data.get('pars', {}).get('parameter', [])):
        sensors.append(InverterDynamicSensor(item, coordinator, parameter, DessSensorSource.PARS_ES))

    for key, params in data.get('last_data', {}).get('pars', {}).items():
        for parameter in filter(is_valid_parameter, params):
            sensors.append(InverterDynamicSensor(
                item, coordinator,
                {
                    'par': parameter['id'],
                    'name': parameter['par'],
                    'val': parameter['val'],
                    'unit': parameter['unit'],
                },
                DessSensorSource.SP_LAST_DATA
            ))
    return sensors


def should_add_direct_sensors(config_entry, hub, item):
    return (
            config_entry.options.get('direct_request_protocol', False)
            and hub.direct_coordinator.data is not None
            and item.inverter_id in hub.direct_coordinator.data
    )


def create_direct_sensors(item, coordinator):
    """Return direct protocol-based sensors for an item."""
    direct_sensor_classes = DIRECT_SENSORS
    return [sensor_cls(item, coordinator) for sensor_cls in direct_sensor_classes]
