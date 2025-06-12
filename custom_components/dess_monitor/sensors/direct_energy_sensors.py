from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass, RestoreSensor
from homeassistant.const import EntityCategory, UnitOfEnergy, PERCENTAGE
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from custom_components.dess_monitor.sensors.direct_sensor import DirectTypedSensorBase


class DirectEnergySensorBase(RestoreSensor, DirectTypedSensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_suggested_display_precision = 0
    _sensor_option_display_precision = 0

    def __init__(
            self,
            inverter_device,
            coordinator,
            data_section: str,
            data_key: str,
            sensor_suffix: str = "",
            name_suffix: str = "",
    ):
        # Инициализируем как DirectTypedSensorBase (он выставит unique_id и имя)
        super().__init__(
            inverter_device,
            coordinator,
            data_section,
            data_key,
            sensor_suffix,
            name_suffix,
        )
        # Гарантируем, что _attr_native_value сразу — число, а не None
        self._attr_native_value = 0.0

        # Для интеграции
        self._prev_power = None
        self._prev_ts = datetime.now()
        self._restored = False

    async def async_added_to_hass(self) -> None:
        # При восстановлении из базы кладём значение, но если оно None — ставим 0
        last_data = await self.async_get_last_extra_data()
        if last_data is not None:
            restored = last_data.as_dict().get("native_value", None)
            # Если в базе было None, заменяем на 0
            self._attr_native_value = float(restored) if restored is not None else 0.0
        else:
            self._attr_native_value = 0.0

        self._restored = True
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        """Сенсор доступен, только если устройство в сети и значение восстановлено."""
        return super().available and self._restored

    def update_energy_value(self, current_value: float):
        now = datetime.now()
        elapsed_seconds = (now - self._prev_ts).total_seconds()

        # Гарантируем, что self._attr_native_value не None
        if self._attr_native_value is None:
            self._attr_native_value = 0.0

        if self._prev_power is not None:
            # Добавляем накопленную энергию (усреднённая мощность за период)
            self._attr_native_value += (elapsed_seconds / 3600) * (self._prev_power + current_value) / 2

        # Обновляем предыдущее значение мощности и время
        self._prev_power = current_value
        self._prev_ts = now
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Каждое обновление координатора — берём свежую мощность и накапливаем энергию."""
        section = self.data.get(self.data_section, {})
        raw = section.get(self.data_key)
        try:
            power = float(raw)
        except (TypeError, ValueError):
            power = None

        if power is not None:
            self.update_energy_value(power)

        # Обновляем state (даже если power оказался None, рисуем текущее значение накопленной энергии)
        self.async_write_ha_state()


class DirectPVEnergySensor(DirectEnergySensorBase):
    """Энергия по мощности PV (qpigs['pv_charging_power'])."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="pv_charging_power",
            sensor_suffix="direct_pv_power_energy",
            name_suffix="PV Power Energy",
        )


class DirectPV2EnergySensor(DirectEnergySensorBase):
    """Энергия по мощности PV2 (qpigs2['pv_current']*['pv_voltage'])."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs2",
            data_key="pv2_power",
            sensor_suffix="direct_pv2_power_energy",
            name_suffix="PV2 Power Energy",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        try:
            sec = self.data["qpigs2"]
            power = float(sec["pv_current"]) * float(sec["pv_voltage"])
        except (KeyError, ValueError, TypeError):
            power = None

        if power is not None:
            self.update_energy_value(power)
        self.async_write_ha_state()


class DirectInverterOutputEnergySensor(DirectEnergySensorBase):
    """Энергия по мощности выхода инвертора (qpigs['output_active_power'])."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="output_active_power",
            sensor_suffix="direct_inverter_out_power_energy",
            name_suffix="Inverter Out Power Energy",
        )


class DirectOutputApparentEnergySensor(DirectEnergySensorBase):
    """Энергия по кажущейся мощности (qpigs['output_apparent_power'])."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="output_apparent_power",
            sensor_suffix="direct_output_apparent_power_energy",
            name_suffix="Apparent Power Energy",
        )


class DirectBatteryInEnergySensor(DirectEnergySensorBase):
    """Энергия по мощности зарядки батареи (battery_charging_current * battery_voltage)."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="battery_charging_current",
            sensor_suffix="battery_in_power_energy",
            name_suffix="Battery In Energy",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        При обновлении координатора вычисляем мощность зарядки (A * V),
        и если она > 0, накапливаем энергию.
        """
        try:
            qpigs = self.data.get("qpigs", {})
            qpiri = self.data.get("qpiri", {})
            current = float(qpigs.get("battery_charging_current", 0))
            voltage = float(qpiri.get("bulk_charging_voltage", 0))
            power = current * voltage if current > 0 else None
        except (KeyError, ValueError, TypeError):
            power = None

        if power is not None:
            self.update_energy_value(power)

        # Обновляем state (накопленную энергию), даже если power оказался None
        self.async_write_ha_state()


class DirectBatteryOutEnergySensor(DirectEnergySensorBase):
    """Энергия по мощности разрядки батареи (battery_discharge_current * battery_voltage)."""

    def __init__(self, inverter_device, coordinator):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="battery_discharge_current",
            sensor_suffix="battery_out_power_energy",
            name_suffix="Battery Out Energy",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        При обновлении координатора вычисляем мощность разрядки (A * V),
        и если она > 0, накапливаем энергию.
        """
        try:
            qpigs = self.data.get("qpigs", {})
            current = float(qpigs.get("battery_discharge_current", 0))
            voltage = float(qpigs.get("battery_voltage", 0))
            power = current * voltage if current > 0 else None
        except (KeyError, ValueError, TypeError):
            power = None

        if power is not None:
            self.update_energy_value(power)

        # Обновляем state (накопленную энергию), даже если power оказался None
        self.async_write_ha_state()


class DirectBatteryStateOfChargeSensor(RestoreSensor, DirectTypedSensorBase):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(self, inverter_device, coordinator, hass):
        super().__init__(
            inverter_device=inverter_device,
            coordinator=coordinator,
            data_section="qpigs",
            data_key="battery_voltage",
            sensor_suffix="battery_state_of_charge",
            name_suffix="Battery State of Charge",
        )
        self._accumulated_energy_wh = 100.0
        self._prev_power = None
        self._prev_ts = datetime.now()
        self._restored = False
        self._hass = hass

        device_slug = slugify(self._inverter_device.name)
        self._capacity_entity_id = f"number.{device_slug}_vsoc_battery_capacity"
        self._battery_capacity_wh = None

        async_track_state_change_event(
            self._hass,
            [self._capacity_entity_id],
            self._handle_battery_capacity_change,
        )

    async def async_added_to_hass(self) -> None:
        state = self._hass.states.get(self._capacity_entity_id)
        self._update_battery_capacity_from_state(state)

        last_data = await self.async_get_last_extra_data()
        if last_data is not None:
            restored = last_data.as_dict().get("native_value", None)
            self._attr_native_value = float(restored) if restored is not None else None
        else:
            self._attr_native_value = None
        self._restored = True
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        # Доступен только если восстановлен и емкость задана положительно
        bulk_voltage = self.get_bulk_charging_voltage()
        return super().available and self._restored and (
                    self._battery_capacity_wh is not None and self._battery_capacity_wh > 0) and (
                    bulk_voltage is not None)

    @callback
    def _handle_battery_capacity_change(self, event):
        state = event.data.get("new_state")
        self._update_battery_capacity_from_state(state)

    def _update_battery_capacity_from_state(self, state):
        if state is None:
            self._battery_capacity_wh = None
            self._attr_native_value = None
            self.async_write_ha_state()
            return
        try:
            value = float(state.state)
            if value <= 0:
                self._battery_capacity_wh = None
                self._attr_native_value = None
            else:
                self._battery_capacity_wh = value
        except (ValueError, TypeError):
            self._battery_capacity_wh = None
            self._attr_native_value = None
        self.async_write_ha_state()

    def get_bulk_charging_voltage(self) -> float | None:
        try:
            qpiri = self.data.get("qpiri", {})
            voltage = float(qpiri.get("bulk_charging_voltage"))
            if voltage > 0:
                return voltage
        except (KeyError, ValueError, TypeError):
            pass
        return None

    def get_floating_charging_voltage(self) -> float | None:
        try:
            qpiri = self.data.get("qpiri", {})
            voltage = float(qpiri.get("float_charging_voltage"))
            if voltage > 0:
                return voltage
        except (KeyError, ValueError, TypeError):
            pass
        return None

    def update_soc(self, current_power: float, current_voltage: float):
        if self._battery_capacity_wh is None or self._battery_capacity_wh <= 0:
            # Не считаем, если емкость не задана
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        bulk_voltage = self.get_bulk_charging_voltage()
        floating_voltage = self.get_floating_charging_voltage()
        if bulk_voltage is None:
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        now = datetime.now()
        elapsed_seconds = (now - self._prev_ts).total_seconds()

        if self._prev_power is not None:
            energy_increment = (elapsed_seconds / 3600) * (self._prev_power + current_power) / 2
            self._accumulated_energy_wh += energy_increment

        self._prev_power = current_power
        self._prev_ts = now

        max_capacity = self._battery_capacity_wh

        if current_voltage >= bulk_voltage or (
                current_voltage >= floating_voltage and 0 < current_power <= 2 * bulk_voltage):
            soc_percent = 100.0
            self._accumulated_energy_wh = max_capacity
        else:
            if self._accumulated_energy_wh < 0:
                self._accumulated_energy_wh = 0.0
            elif self._accumulated_energy_wh > max_capacity:
                self._accumulated_energy_wh = max_capacity

            soc_percent = (self._accumulated_energy_wh / max_capacity) * 100

        soc_percent = max(0.0, min(100.0, soc_percent))

        self._attr_native_value = soc_percent
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        section = self.data.get(self.data_section, {})
        try:
            current_voltage = float(section.get("battery_voltage", 0))
            charging_current = float(section.get("battery_charging_current", 0))
            discharging_current = float(section.get("battery_discharge_current", 0))
            power = 0.0
            if charging_current > 0:
                power = charging_current * current_voltage
            elif discharging_current > 0:
                power = -discharging_current * current_voltage

            self.update_soc(power, current_voltage)
        except (KeyError, ValueError, TypeError):
            self._attr_native_value = None
            self.async_write_ha_state()
