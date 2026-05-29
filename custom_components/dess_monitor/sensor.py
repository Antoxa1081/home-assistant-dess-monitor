"""Platform for sensor integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.dess_monitor.const import (
    CONF_BATTERY_VIRTUAL_ENABLED,
    CONF_ENABLE_LAST_AT_SENSORS,
    DEFAULT_BATTERY_VIRTUAL_ENABLED,
    DEFAULT_ENABLE_LAST_AT_SENSORS,
)
from custom_components.dess_monitor.sensors.direct_sensor import DIRECT_SENSORS, generate_qpiri_sensors

from . import HubConfigEntry
from .sensors.dynamic_sensor import *
from .sensors.dynamic_sensor import _is_supported_unit  # noqa: F401  (used in create_dynamic_sensors)
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

    virtual_battery_enabled = config_entry.options.get(
        CONF_BATTERY_VIRTUAL_ENABLED, DEFAULT_BATTERY_VIRTUAL_ENABLED,
    )
    last_at_enabled = config_entry.options.get(
        CONF_ENABLE_LAST_AT_SENSORS, DEFAULT_ENABLE_LAST_AT_SENSORS,
    )
    for item in hub.items:
        new_devices.extend(create_static_sensors(item, hub.coordinator))

        if last_at_enabled:
            new_devices.append(InverterLastSampleTimeSensor(item, hub.coordinator))
            new_devices.append(InverterWebSocketLastFrameSensor(item, hub.coordinator))

        if virtual_battery_enabled:
            new_devices.append(VirtualBatterySocSensor(item, hub.coordinator))

        if should_add_dynamic_sensors(config_entry, hub, item):
            new_devices.extend(create_dynamic_sensors(item, hub.coordinator))

        if should_add_direct_sensors(config_entry, hub, item):
            new_devices.extend(create_direct_sensors(item, hub.direct_coordinator))
            new_devices.extend(generate_qpiri_sensors(item, hub.direct_coordinator))

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
        BatteryPowerSensor,
        BatteryInEnergySensor,
        BatteryOutEnergySensor,
        BatteryCapacitySensor,

        # Inverter sensors
        InverterStatusSensor,
        InverterMainsStatusSensor,
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
    """Return dynamic sensors for an item based on parameters.

    Cloud responses overlap heavily — the same provider key shows up in both
    ``pars.parameter`` and ``last_data.pars.<group>``. Without dedup the second
    sensor is silently rejected by HA (duplicate ``unique_id``) and that
    source's branch never runs. We prefer ``pars.parameter`` because it
    carries a friendly ``name`` field; ``last_data`` fills in everything that
    was absent there.
    """
    sensors = []
    seen_ids: set[str] = set()
    data = coordinator.data[item.inverter_id]

    for parameter in data.get('pars', {}).get('parameter', []) or []:
        if not _is_supported_unit(parameter):
            continue
        par_id = parameter.get('par')
        if not par_id or par_id in seen_ids:
            continue
        seen_ids.add(par_id)
        sensors.append(InverterDynamicSensor(item, coordinator, parameter, DessSensorSource.PARS_ES))

    for _group, params in (data.get('last_data', {}).get('pars', {}) or {}).items():
        for parameter in params or []:
            if not _is_supported_unit(parameter):
                continue
            par_id = parameter.get('id')
            if not par_id or par_id in seen_ids:
                continue
            seen_ids.add(par_id)
            sensors.append(InverterDynamicSensor(
                item, coordinator,
                {
                    'par': par_id,
                    'name': parameter.get('par') or par_id,
                    'val': parameter.get('val'),
                    'unit': parameter.get('unit'),
                },
                DessSensorSource.SP_LAST_DATA,
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
