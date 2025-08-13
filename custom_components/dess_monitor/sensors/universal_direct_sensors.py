# unified_sensors.py

from __future__ import annotations
from typing import Any, Optional, Dict, Tuple, Type
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfApparentPower,
    PERCENTAGE,
    EntityCategory,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor import DirectCoordinator  # или UniversalCoordinator
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.const import DOMAIN

# =========================
# БАЗА
# =========================

class SnapshotSensorBase(CoordinatorEntity, SensorEntity):
    """
    Универсальный сенсор, который:
    1) Берёт значение из data[inverter_id]["snapshot"][snapshot_key]
    2) При необходимости, умеет падать на «raw» секции (qpigs/qpigs2/qpiri)
       через fallback_path=(section, key).
    """

    _attr_entity_category: Optional[EntityCategory] = None
    _attr_suggested_display_precision: Optional[int] = None
    _sensor_option_display_precision: Optional[int] = None

    def __init__(
        self,
        inverter_device: InverterDevice,
        coordinator: DirectCoordinator,
        snapshot_key: Optional[str],
        *,
        name_suffix: str,
        sensor_suffix: str,
        fallback_path: Optional[Tuple[str, str]] = None,
    ):
        super().__init__(coordinator)
        self._inverter_device = inverter_device
        self._snapshot_key = snapshot_key
        self._fallback_path = fallback_path

        self._attr_unique_id = f"{self._inverter_device.inverter_id}_unified_{sensor_suffix}"
        self._attr_name = f"{self._inverter_device.name} {name_suffix}"

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._inverter_device.inverter_id)},
            "name": self._inverter_device.name,
            "sw_version": self._inverter_device.firmware_version,
            "model": self._inverter_device.device_data.get("pn"),
            "serial_number": self._inverter_device.device_data.get("sn"),
            "hw_version": self._inverter_device.device_data.get("devcode"),
            "model_id": self._inverter_device.device_data.get("devaddr"),
            "manufacturer": "ESS",
        }

    @property
    def available(self) -> bool:
        return self._inverter_device.online and self._inverter_device.hub.online

    @property
    def data(self) -> Dict[str, Any]:
        return self.coordinator.data[self._inverter_device.inverter_id]

    def _value_from_snapshot(self) -> Any:
        if self._snapshot_key is None:
            return None
        snap = self.data.get("snapshot", {})
        return snap.get(self._snapshot_key)

    def _value_from_fallback(self) -> Any:
        if not self._fallback_path:
            return None
        section, key = self._fallback_path
        return self.data.get(section, {}).get(key)

    def _coerce(self, raw: Any) -> Any:
        """Переопредели в подклассах при необходимости."""
        return raw

    @callback
    def _handle_coordinator_update(self) -> None:
        raw_val = self._value_from_snapshot()
        if raw_val is None:
            raw_val = self._value_from_fallback()

        try:
            self._attr_native_value = self._coerce(raw_val)
        except Exception:
            self._attr_native_value = None

        self.async_write_ha_state()


# =========================
# ТИПИЗИРОВАННЫЕ БАЗЫ
# =========================

class SnapWattSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.POWER
    _attr_unit_of_measurement = UnitOfPower.WATT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapVoltSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.VOLTAGE
    _attr_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 1
    _sensor_option_display_precision = 1

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapCurrentSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.CURRENT
    _attr_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_suggested_display_precision = 1
    _sensor_option_display_precision = 1

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapTempSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.TEMPERATURE
    _attr_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapFreqSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.FREQUENCY
    _attr_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 2
    _sensor_option_display_precision = 2

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapApparentPowerSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.APPARENT_POWER
    _attr_unit_of_measurement = UnitOfApparentPower.VOLT_AMPERE
    _attr_native_unit_of_measurement = UnitOfApparentPower.VOLT_AMPERE
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapPercentSensor(SnapshotSensorBase):
    _attr_unit_of_measurement = PERCENTAGE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0

    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None


class SnapEnumSensor(SnapshotSensorBase):
    device_class = SensorDeviceClass.ENUM
    _attr_device_class = SensorDeviceClass.ENUM

    # передай список опций в конструктор
    def __init__(self, *args, options: Optional[list[str]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._options = options or []

    @property
    def options(self) -> list[str]:
        return self._options

    def _coerce(self, raw: Any) -> Optional[str]:
        if raw is None:
            return None
        s = str(raw)
        return s if (not self._options or s in self._options) else None


# =========================
# УНИФИЦИРОВАННЫЕ СЕНСОРЫ
# (покрывают все твои прежние)
# =========================

class UniPVPower(SnapWattSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "pv_power_w",
                         name_suffix="PV Power", sensor_suffix="pv_power",
                         fallback_path=("qpigs", "pv_charging_power"))


class UniPVVoltage(SnapVoltSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "pv_voltage_v",
                         name_suffix="PV Voltage", sensor_suffix="pv_voltage",
                         fallback_path=("qpigs", "pv_input_voltage"))


class UniPVCurrent(SnapCurrentSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "pv_current_a",
                         name_suffix="PV Current", sensor_suffix="pv_current",
                         fallback_path=("qpigs", "pv_input_current"))


class UniPV2Voltage(SnapVoltSensor):
    """Второй МППТ — только фоллбэк (если есть qpigs2)."""
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="PV2 Voltage", sensor_suffix="pv2_voltage",
                         fallback_path=("qpigs2", "pv_voltage"))


class UniPV2Current(SnapCurrentSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="PV2 Current", sensor_suffix="pv2_current",
                         fallback_path=("qpigs2", "pv_current"))


class UniPV2Power(SnapWattSensor):
    """PV2 Power = snapshot отсутствует, берём из qpigs2 (I*V уже делал старый сенсор)."""
    @callback
    def _handle_coordinator_update(self) -> None:
        d = self.data.get("qpigs2", {})
        try:
            val = float(d["pv_current"]) * float(d["pv_voltage"])
        except Exception:
            val = None
        self._attr_native_value = val
        self.async_write_ha_state()

    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="PV2 Power", sensor_suffix="pv2_power",
                         fallback_path=None)


class UniBatteryVoltage(SnapVoltSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "battery_voltage_v",
                         name_suffix="Battery Voltage", sensor_suffix="battery_voltage",
                         fallback_path=("qpigs", "battery_voltage"))


class UniBatteryCurrentSigned(SnapCurrentSensor):
    """Единый подписанный ток батареи (+ заряд / – разряд)."""
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "battery_current_a",
                         name_suffix="Battery Current", sensor_suffix="battery_current_signed")


class UniBatteryChargingCurrent(SnapCurrentSensor):
    """Совместимость: выдаём только заряд (>=0)."""
    @callback
    def _handle_coordinator_update(self) -> None:
        val = self.data.get("snapshot", {}).get("battery_current_a")
        try:
            f = float(val) if val is not None else None
            self._attr_native_value = f if (f is not None and f > 0) else 0.0 if f is not None else None
        except Exception:
            self._attr_native_value = None
        self.async_write_ha_state()

    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="Battery Charging Current", sensor_suffix="battery_charging_current")


class UniBatteryDischargeCurrent(SnapCurrentSensor):
    """Совместимость: выдаём только разряд (>=0)."""
    @callback
    def _handle_coordinator_update(self) -> None:
        val = self.data.get("snapshot", {}).get("battery_current_a")
        try:
            f = float(val) if val is not None else None
            self._attr_native_value = (-f) if (f is not None and f < 0) else 0.0 if f is not None else None
        except Exception:
            self._attr_native_value = None
        self.async_write_ha_state()

    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="Battery Discharge Current", sensor_suffix="battery_discharge_current")


class UniBatterySOC(SnapPercentSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "battery_soc_percent",
                         name_suffix="Battery Capacity", sensor_suffix="battery_capacity",
                         fallback_path=("qpigs", "battery_capacity"))


class UniInverterOutPower(SnapWattSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "out_active_power_w",
                         name_suffix="Inverter Out Power", sensor_suffix="inverter_out_power",
                         fallback_path=("qpigs", "output_active_power"))


class UniInverterGridInputPower(SnapWattSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "grid_input_power_w",
                         name_suffix="Inverter Grid Input Power", sensor_suffix="inverter_grid_input_power")


class UniInverterTemperature(SnapTempSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "inverter_temp_c",
                         name_suffix="Inverter Temperature", sensor_suffix="inverter_temperature",
                         fallback_path=("qpigs", "inverter_heat_sink_temperature"))


class UniGridVoltage(SnapVoltSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "grid_voltage_v",
                         name_suffix="Grid Voltage", sensor_suffix="grid_voltage",
                         fallback_path=("qpigs", "grid_voltage"))


class UniGridFrequency(SnapFreqSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "grid_freq_hz",
                         name_suffix="Grid Frequency", sensor_suffix="grid_frequency",
                         fallback_path=("qpigs", "grid_frequency"))


class UniACOutVoltage(SnapVoltSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "ac_out_voltage_v",
                         name_suffix="AC Output Voltage", sensor_suffix="ac_output_voltage",
                         fallback_path=("qpigs", "ac_output_voltage"))


class UniACOutFrequency(SnapFreqSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "ac_out_freq_hz",
                         name_suffix="AC Output Frequency", sensor_suffix="ac_output_frequency",
                         fallback_path=("qpigs", "ac_output_frequency"))


class UniOutApparentPower(SnapApparentPowerSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "out_apparent_power_va",
                         name_suffix="Apparent Power", sensor_suffix="output_apparent_power",
                         fallback_path=("qpigs", "output_apparent_power"))


class UniLoadPercent(SnapPercentSensor):
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, "load_percent",
                         name_suffix="Load Percent", sensor_suffix="load_percent",
                         fallback_path=("qpigs", "load_percent"))


class UniBusVoltage(SnapVoltSensor):
    """В канонической модели bus не обязателен — читаем только если есть в raw."""
    def __init__(self, inv: InverterDevice, coord: DirectCoordinator):
        super().__init__(inv, coord, None,
                         name_suffix="Bus Voltage", sensor_suffix="bus_voltage",
                         fallback_path=("qpigs", "bus_voltage"))


# =========================
# «СПЕЦИФИКАЦИИ/НАСТРОЙКИ» (бывшие QPIRI)
# =========================

class SnapSpecBase(SnapshotSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, inv: InverterDevice, coord: DirectCoordinator, spec_key: str, name: str, suffix: str,
                 device_class=None, unit=None, precision: int | None = None,
                 qpiri_key: Optional[str] = None):
        # читаем сначала snapshot['spec'][spec_key], иначе raw['qpiri'][qpiri_key/spec_key]
        super().__init__(
            inv, coord, None,
            name_suffix=name, sensor_suffix=suffix,
            fallback_path=None
        )
        self._spec_key = spec_key
        self._qpiri_key = qpiri_key or spec_key
        if device_class:
            self.device_class = device_class
        if unit:
            self._attr_unit_of_measurement = unit
            self._attr_native_unit_of_measurement = unit
        if precision is not None:
            self._attr_suggested_display_precision = precision
            self._sensor_option_display_precision = precision

    def _value_from_snapshot(self) -> Any:
        snap = self.data.get("snapshot", {})
        spec = snap.get("spec", {})
        return spec.get(self._spec_key)

    def _value_from_fallback(self) -> Any:
        return self.data.get("qpiri", {}).get(self._qpiri_key)

    def _coerce(self, raw: Any) -> Any:
        return raw


class SnapSpecVolt(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=1):
        super().__init__(inv, coord, spec_key, name, suffix,
                         device_class=SensorDeviceClass.VOLTAGE,
                         unit=UnitOfElectricPotential.VOLT,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecCurr(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=0):
        super().__init__(inv, coord, spec_key, name, suffix,
                         device_class=SensorDeviceClass.CURRENT,
                         unit=UnitOfElectricCurrent.AMPERE,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecWatt(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=0):
        super().__init__(inv, coord, spec_key, name, suffix,
                         device_class=SensorDeviceClass.POWER,
                         unit=UnitOfPower.WATT,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecVA(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=0):
        super().__init__(inv, coord, spec_key, name, suffix,
                         device_class=SensorDeviceClass.APPARENT_POWER,
                         unit=UnitOfApparentPower.VOLT_AMPERE,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecFreq(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=1):
        super().__init__(inv, coord, spec_key, name, suffix,
                         device_class=SensorDeviceClass.FREQUENCY,
                         unit=UnitOfFrequency.HERTZ,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecPercent(SnapSpecBase):
    def _coerce(self, raw: Any) -> Optional[float]:
        return float(raw) if raw is not None else None

    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, precision=0):
        super().__init__(inv, coord, spec_key, name, suffix,
                         unit=PERCENTAGE,
                         precision=precision, qpiri_key=qpiri_key)


class SnapSpecEnum(SnapSpecBase, SnapEnumSensor):
    def __init__(self, inv, coord, spec_key, name, suffix, qpiri_key=None, options: Optional[list[str]] = None):
        SnapSpecBase.__init__(self, inv, coord, spec_key, name, suffix, qpiri_key=qpiri_key)
        SnapEnumSensor.__init__(self, inv, coord, None, name_suffix=name, sensor_suffix=suffix, options=options)

    # Переопределяем источники так, чтобы шла та же логика spec->qpiri
    def _value_from_snapshot(self) -> Any:
        return SnapSpecBase._value_from_snapshot(self)

    def _value_from_fallback(self) -> Any:
        return SnapSpecBase._value_from_fallback(self)


def generate_unified_spec_sensors(inv: InverterDevice, coord: DirectCoordinator):
    """Аналог generate_qpiri_sensors, но в унифицированном виде.
       Если провайдер положил snapshot['spec'], берём оттуда; иначе — raw['qpiri'].
    """
    sensors: list[SensorEntity] = []

    # 1) «rated/limits» (бывшие числовые из QPIRI)
    sensors += [
        SnapSpecVolt(inv, coord, "rated_grid_voltage", "Rated Grid Voltage", "spec_rated_grid_voltage", qpiri_key="rated_grid_voltage"),
        SnapSpecCurr(inv, coord, "rated_input_current", "Rated Input Current", "spec_rated_input_current", qpiri_key="rated_input_current"),
        SnapSpecVolt(inv, coord, "rated_ac_output_voltage", "Rated AC Output Voltage", "spec_rated_ac_output_voltage", qpiri_key="rated_ac_output_voltage"),
        SnapSpecFreq(inv, coord, "rated_output_frequency", "Rated Output Frequency", "spec_rated_output_frequency", qpiri_key="rated_output_frequency"),
        SnapSpecCurr(inv, coord, "rated_output_current", "Rated Output Current", "spec_rated_output_current", qpiri_key="rated_output_current"),
        SnapSpecVA(inv, coord, "rated_output_apparent_power", "Rated Output Apparent Power", "spec_rated_output_apparent_power", qpiri_key="rated_output_apparent_power"),
        SnapSpecWatt(inv, coord, "rated_output_active_power", "Rated Output Active Power", "spec_rated_output_active_power", qpiri_key="rated_output_active_power"),
        SnapSpecVolt(inv, coord, "rated_battery_voltage", "Rated Battery Voltage", "spec_rated_battery_voltage", qpiri_key="rated_battery_voltage"),
        SnapSpecVolt(inv, coord, "low_battery_to_ac_bypass_voltage", "Low Battery to AC Bypass Voltage", "spec_low_batt_to_bypass", qpiri_key="low_battery_to_ac_bypass_voltage"),
        SnapSpecVolt(inv, coord, "shut_down_battery_voltage", "Shut Down Battery Voltage", "spec_shutdown_batt_voltage", qpiri_key="shut_down_battery_voltage"),
        SnapSpecVolt(inv, coord, "bulk_charging_voltage", "Bulk Charging Voltage", "spec_bulk_voltage", qpiri_key="bulk_charging_voltage"),
        SnapSpecVolt(inv, coord, "float_charging_voltage", "Float Charging Voltage", "spec_float_voltage", qpiri_key="float_charging_voltage"),
        SnapSpecCurr(inv, coord, "max_utility_charging_current", "Max Utility Charging Current", "spec_max_utility_chg_curr", qpiri_key="max_utility_charging_current"),
        SnapSpecCurr(inv, coord, "max_charging_current", "Max Charging Current", "spec_max_chg_curr", qpiri_key="max_charging_current"),
        SnapSpecVolt(inv, coord, "high_battery_voltage_to_battery_mode", "High Battery Voltage to Battery Mode", "spec_high_batt_to_batt_mode", qpiri_key="high_battery_voltage_to_battery_mode"),
        SnapSpecPercent(inv, coord, "rated_battery_capacity", "Rated Battery Capacity", "spec_rated_battery_capacity", qpiri_key="rated_battery_capacity"),
    ]

    # 2) ENUM'ы настроек (бывшие: battery_type, ac_input_voltage_range, output_source_priority, charger_source_priority, parallel_mode)
    sensors += [
        SnapSpecEnum(inv, coord, "battery_type", "Battery Type", "spec_battery_type",
                     qpiri_key="battery_type",
                     options=[
                         "AGM", "Flooded", "UserDefined", "LIB", "LIC", "RESERVED", "RESERVED_1", "RESERVED_2"
                     ]),
        SnapSpecEnum(inv, coord, "ac_input_voltage_range", "AC Input Voltage Range", "spec_ac_input_range",
                     qpiri_key="ac_input_voltage_range",
                     options=["Appliance", "UPS"]),
        SnapSpecEnum(inv, coord, "output_source_priority", "Output Source Priority", "spec_output_src_priority",
                     qpiri_key="output_source_priority",
                     options=["UtilityFirst", "SolarFirst", "SBU", "BatteryOnly", "UtilityOnly", "SolarAndUtility", "Smart"]),
        SnapSpecEnum(inv, coord, "charger_source_priority", "Charger Source Priority", "spec_charger_src_priority",
                     qpiri_key="charger_source_priority",
                     options=["UtilityFirst", "SolarFirst", "SolarAndUtility", "OnlySolar"]),
        SnapSpecEnum(inv, coord, "parallel_mode", "Parallel Mode", "spec_parallel_mode",
                     qpiri_key="parallel_mode",
                     options=["Master", "Slave", "Standalone"]),
    ]

    # 3) Прочие «reserved_*» лучше не поднимать как сенсоры в UI

    return sensors


# =========================
# РЕЕСТР ЕДИНОГО НАБОРА
# (замена DIRECT_SENSORS)
# =========================

UNIFIED_SENSORS: list[Type[SensorEntity]] = [
    UniPVPower,
    UniPV2Power,
    UniPVVoltage,
    UniPV2Voltage,
    UniPVCurrent,
    UniPV2Current,

    UniBatteryVoltage,
    UniBatteryCurrentSigned,
    UniBatteryChargingCurrent,
    UniBatteryDischargeCurrent,
    UniBatterySOC,

    UniInverterOutPower,
    UniInverterGridInputPower,
    UniInverterTemperature,

    UniGridVoltage,
    UniGridFrequency,
    UniACOutVoltage,
    UniACOutFrequency,
    UniOutApparentPower,
    UniLoadPercent,
    UniBusVoltage,
]
