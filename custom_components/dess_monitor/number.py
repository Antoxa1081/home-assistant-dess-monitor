import logging
import random
import re
from datetime import datetime, timedelta

import async_timeout
from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.dess_monitor import HubConfigEntry, MainCoordinator
from custom_components.dess_monitor.api.resolvers.data_resolvers import resolve_sy_rated_battery_voltage
from custom_components.dess_monitor.const import (
    CONF_BATTERY_VIRTUAL_ENABLED,
    CONF_DYNAMIC_SETTINGS_INTERVAL,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_VIRTUAL_ENABLED,
    DEFAULT_BATTERY_VOLTAGE_FULL,
    DEFAULT_DYNAMIC_SETTINGS_INTERVAL,
    DOMAIN,
    DYNAMIC_SETTINGS_API_TIMEOUT,
    MAX_BATTERY_CAPACITY_AH,
    MAX_BATTERY_VOLTAGE_FULL,
    MAX_DYNAMIC_SETTINGS_INTERVAL,
    MIN_BATTERY_CAPACITY_AH,
    MIN_BATTERY_VOLTAGE_FULL,
    MIN_DYNAMIC_SETTINGS_INTERVAL,
)
from custom_components.dess_monitor.coordinators.coordinator import _clamp
from custom_components.dess_monitor.hub import InverterDevice
from custom_components.dess_monitor.sdk import DeviceIdentity
from custom_components.dess_monitor.util import resolve_number_with_unit

_LOGGER = logging.getLogger(__name__)

# See ``select.py`` — platform interval is the throttle-check cadence; actual
# API hit rate is bounded by ``CONF_DYNAMIC_SETTINGS_INTERVAL``.
SCAN_INTERVAL = timedelta(seconds=60)
PARALLEL_UPDATES = 1


# Map the cloud's free-form unit string onto an HA constant + matching device
# class. Entries we don't recognise fall through to no-unit/no-class so the
# entity still works, just without unit-specific UI affordances.
_UNIT_TO_HA: dict[str, tuple[str, NumberDeviceClass | None]] = {
    "V": (UnitOfElectricPotential.VOLT, NumberDeviceClass.VOLTAGE),
    "A": (UnitOfElectricCurrent.AMPERE, NumberDeviceClass.CURRENT),
    "%": (PERCENTAGE, None),
    "Hz": (UnitOfFrequency.HERTZ, NumberDeviceClass.FREQUENCY),
    "HZ": (UnitOfFrequency.HERTZ, NumberDeviceClass.FREQUENCY),
    "W": (UnitOfPower.WATT, NumberDeviceClass.POWER),
    "kW": (UnitOfPower.KILO_WATT, NumberDeviceClass.POWER),
    "\u00b0C": (UnitOfTemperature.CELSIUS, NumberDeviceClass.TEMPERATURE),
    "min": (UnitOfTime.MINUTES, NumberDeviceClass.DURATION),
    "minutes": (UnitOfTime.MINUTES, NumberDeviceClass.DURATION),
    "s": (UnitOfTime.SECONDS, NumberDeviceClass.DURATION),
    "sec": (UnitOfTime.SECONDS, NumberDeviceClass.DURATION),
    "h": (UnitOfTime.HOURS, NumberDeviceClass.DURATION),
    "hour": (UnitOfTime.HOURS, NumberDeviceClass.DURATION),
    "hours": (UnitOfTime.HOURS, NumberDeviceClass.DURATION),
    "day": (UnitOfTime.DAYS, NumberDeviceClass.DURATION),
    "days": (UnitOfTime.DAYS, NumberDeviceClass.DURATION),
}

# Match one numeric range token ("25.0~31.5", "1-900", "60.0~66"), optionally
# followed by a battery-system annotation in parens like "(24V)" / "(48V)".
# Cloud hints come in two known shapes:
#   "60.0~66V"                          — single range, optional unit suffix
#   "25.0~31.5(24V) 48.0~61.0(48V)"     — one range per battery system
# `findall` lets us tolerate either, plus stray unit suffixes after a range.
_RANGE_TOKEN_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[~\-\u2013\u2014]\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s*\(\s*(\d+)\s*V\s*\))?",
    re.IGNORECASE,
)


def _resolve_unit(raw: str | None) -> tuple[str | None, NumberDeviceClass | None]:
    if not raw:
        return None, None
    if raw in _UNIT_TO_HA:
        return _UNIT_TO_HA[raw]
    return raw, None  # unknown unit — show as-is, no device_class


def _parse_hint(
        hint: str | None,
        rated_battery_voltage: float | None = None,
) -> tuple[float, float, bool] | None:
    """Return ``(min, max, has_decimal)`` extracted from a cloud range string.

    For the multi-range shape ``"25.0~31.5(24V) 48.0~61.0(48V)"`` we prefer the
    range whose ``(NV)`` annotation matches ``rated_battery_voltage`` (rounded
    to int). When the rated voltage is unknown, or no annotation matches, we
    widen to the union of all ranges so the field stays editable rather than
    getting clamped to the wrong battery system's bounds.
    """
    if not hint or not isinstance(hint, str):
        return None

    parsed_ranges: list[tuple[float, float, bool, int | None]] = []
    for a_raw, b_raw, vtag in _RANGE_TOKEN_RE.findall(hint):
        try:
            a, b = float(a_raw), float(b_raw)
        except ValueError:
            continue
        lo, hi = (a, b) if a <= b else (b, a)
        has_decimal = "." in a_raw or "." in b_raw
        bat_v: int | None
        try:
            bat_v = int(vtag) if vtag else None
        except ValueError:
            bat_v = None
        parsed_ranges.append((lo, hi, has_decimal, bat_v))

    if not parsed_ranges:
        return None

    if rated_battery_voltage is not None:
        try:
            target = int(round(float(rated_battery_voltage)))
        except (TypeError, ValueError):
            target = None
        if target is not None:
            for lo, hi, has_decimal, bat_v in parsed_ranges:
                if bat_v is not None and bat_v == target:
                    return lo, hi, has_decimal

    lo = min(r[0] for r in parsed_ranges)
    hi = max(r[1] for r in parsed_ranges)
    has_decimal = any(r[2] for r in parsed_ranges)
    return lo, hi, has_decimal


# Standard battery-bank nominal voltages used to infer which voltage system
# the cloud's hint was sized for when the inverter's rated voltage doesn't
# match the hint's range.
_NOMINAL_BATTERY_VOLTAGES: tuple[float, ...] = (12.0, 24.0, 36.0, 48.0)


def _rescale_voltage_hint(
        lo: float, hi: float, rated_battery_voltage: float | None,
) -> tuple[float, float]:
    """Rescale a voltage range when it's clearly sized for a different system.

    Some firmwares ship a single hint sized for a 24V system regardless of the
    inverter's actual battery voltage — e.g. devcode 2449 returns
    ``hint="25.0~30.0"`` for ``bat_charging_bulk_voltage`` even when the bank
    is 48V (real bulk ≈ 58V, way outside ``[25, 30]``). When the entire range
    sits well below the rated voltage, infer the hint's nominal system from
    its midpoint (charging spans ~0.85× cutoff to ~1.40× equalisation) and
    rescale by the ratio so realistic values become enterable. Hints whose
    range already reaches into the operating window (``hi ≥ 0.9 × rated``) are
    left alone so correctly-sized hints keep their precision.
    """
    if rated_battery_voltage is None or rated_battery_voltage <= 0:
        return lo, hi
    if hi >= rated_battery_voltage * 0.9:
        return lo, hi
    midpoint = (lo + hi) / 2.0
    plausible = [
        n for n in _NOMINAL_BATTERY_VOLTAGES
        if n * 0.85 <= midpoint <= n * 1.40
    ]
    if not plausible:
        return lo, hi
    inferred = max(plausible)  # prefer the largest plausible system
    if inferred <= 0 or abs(inferred - rated_battery_voltage) < 1.0:
        return lo, hi
    factor = rated_battery_voltage / inferred
    return lo * factor, hi * factor


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: HubConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hub = config_entry.runtime_data
    coordinator = hub.coordinator
    coordinator_data = hub.coordinator.data

    # Per-device virtual-battery config entities are only created when the
    # entry-level master toggle is on; the estimator further stays dormant
    # until both numbers are non-zero.
    if config_entry.options.get(CONF_BATTERY_VIRTUAL_ENABLED, DEFAULT_BATTERY_VIRTUAL_ENABLED):
        virtual_battery_numbers: list[NumberEntity] = []
        for item in hub.items:
            virtual_battery_numbers.append(VirtualBatteryCapacityNumber(item, coordinator))
            virtual_battery_numbers.append(VirtualBatteryVoltageFullNumber(item, coordinator))
        if virtual_battery_numbers:
            async_add_entities(virtual_battery_numbers)

    new_devices = []
    for item in hub.items:
        # grid sensors
        if coordinator_data is None or item.inverter_id not in coordinator_data:
            continue
        device_data = coordinator_data[item.inverter_id]
        fields = device_data['ctrl_fields']
        if fields is None:
            continue
        if config_entry.options.get('dynamic_settings', False) is True:
            try:
                rated_v = resolve_sy_rated_battery_voltage(device_data, item)
            except Exception:  # noqa: BLE001 — resolver may raise if pars not yet seeded
                rated_v = None
            async_add_entities(list(
                map(
                    lambda field_data: InverterDynamicSettingNumber(
                        item, coordinator, field_data, rated_v,
                    ),
                    filter(lambda field: 'item' not in field, fields)
                )
            )
            )
    if new_devices:
        async_add_entities(new_devices)


class NumberBase(CoordinatorEntity, NumberEntity):
    # should_poll = True

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._inverter_device = inverter_device

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._inverter_device.inverter_id)},
            # If desired, the name for the device could be different to the entity
            "name": self._inverter_device.name,
            "sw_version": self._inverter_device.firmware_version,
            "model": self._inverter_device.device_data['pn'],
            "serial_number": self._inverter_device.device_data['sn'],
            "hw_version": self._inverter_device.device_data['devcode'],
            "model_id": self._inverter_device.device_data['devaddr'],
            "manufacturer": 'ESS'
        }

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if inverter_device and hub is available."""
        return self._inverter_device.online and self._inverter_device.hub.online

    @property
    def data(self):
        return self.coordinator.data[self._inverter_device.inverter_id]

    # async def async_added_to_hass(self):
    #     """Run when this Entity has been added to HA."""
    #     # Sensors should also register callbacks to HA when their state changes
    #     self._inverter_device.register_callback(self.async_write_ha_state)
    #
    # async def async_will_remove_from_hass(self):
    #     """Entity being removed from hass."""
    #     # The opposite of async_added_to_hass. Remove any registered call backs here.
    #     self._inverter_device.remove_callback(self.async_write_ha_state)


class InverterDynamicSettingNumber(NumberBase, RestoreNumber):
    _attr_native_value = None
    should_poll = True
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore the previous value before the (slow) cloud confirms it."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)
            # Pretend we just polled — first real refresh will happen one
            # ``_poll_interval`` later, sparing the cloud at startup.
            self._last_updated = int(datetime.now().timestamp())

    def __init__(
            self,
            inverter_device: InverterDevice,
            coordinator: MainCoordinator,
            field_data,
            rated_battery_voltage: float | None = None,
    ):
        super().__init__(inverter_device, coordinator)
        self._service_param_id = field_data['id']
        self._attr_unique_id = f"{self._inverter_device.inverter_id}_settings_{field_data['id']}"
        self._attr_name = f"{self._inverter_device.name} SET {field_data['name']}"

        # Range and step: try the proper "hint" string first
        # ("60.0~66V", "1~900min", "1-90"). Some firmwares (e.g. devcode 2341
        # for ``bat_sp_bulk_charging_voltage``) omit ``hint`` and pack the
        # range into ``unit`` instead — fall through and parse that. When the
        # hint is multi-range (``"25.0~31.5(24V) 48.0~61.0(48V)"``) the parser
        # uses ``rated_battery_voltage`` to pick the right system, or widens to
        # the union if it can't be inferred.
        raw_hint = field_data.get('hint')
        raw_unit = field_data.get('unit')
        parsed = _parse_hint(raw_hint, rated_battery_voltage)
        unit_was_used_as_hint = False
        if parsed is None:
            parsed_from_unit = _parse_hint(raw_unit, rated_battery_voltage)
            if parsed_from_unit is not None:
                parsed = parsed_from_unit
                unit_was_used_as_hint = True

        if unit_was_used_as_hint:
            # Every observed multi-range hint has been a battery-voltage one;
            # treat the field as voltage so HA renders a sensible unit/icon
            # instead of the raw range string.
            unit, device_class = UnitOfElectricPotential.VOLT, NumberDeviceClass.VOLTAGE
        else:
            unit, device_class = _resolve_unit(raw_unit)
        self._attr_native_unit_of_measurement = unit
        if device_class is not None:
            self._attr_device_class = device_class

        if parsed is not None:
            lo, hi, has_decimal = parsed
            if unit == UnitOfElectricPotential.VOLT:
                lo, hi = _rescale_voltage_hint(lo, hi, rated_battery_voltage)
            self._attr_native_min_value = lo
            self._attr_native_max_value = hi
            self._attr_native_step = 0.1 if has_decimal else 1.0
        else:
            self._attr_native_min_value = 0.0
            self._attr_native_max_value = 1000.0
            self._attr_native_step = 0.1 if unit == UnitOfElectricPotential.VOLT else 1.0
        self._attr_mode = NumberMode.BOX
        self._poll_interval = _clamp(
            coordinator.config_entry.options.get(
                CONF_DYNAMIC_SETTINGS_INTERVAL, DEFAULT_DYNAMIC_SETTINGS_INTERVAL,
            ),
            MIN_DYNAMIC_SETTINGS_INTERVAL,
            MAX_DYNAMIC_SETTINGS_INTERVAL,
        )
        # Stagger initial polls across one interval to avoid hammering the API.
        now = int(datetime.now().timestamp())
        self._last_updated: int | None = now - random.randint(0, max(self._poll_interval - 1, 1))

    async def async_update(self) -> None:
        now = int(datetime.now().timestamp())
        if self._last_updated is not None and (now - self._last_updated) < self._poll_interval:
            return

        try:
            async with async_timeout.timeout(DYNAMIC_SETTINGS_API_TIMEOUT):
                response = await self.coordinator.client.control.get_value(
                    DeviceIdentity.from_dict(self._inverter_device.device_data),
                    self._service_param_id,
                )
        except (TimeoutError, Exception) as err:
            _LOGGER.debug(
                "Skipping update of %s: %s", self._attr_unique_id, err,
            )
            return

        if not isinstance(response, dict) or 'err' in response:
            self._last_updated = now
            return
        raw_val = response.get('val')
        if raw_val is None:
            self._last_updated = now
            return
        self._attr_native_value = resolve_number_with_unit(raw_val)
        self._last_updated = now
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        param_id = self._service_param_id
        param_value = str(value)
        await self.coordinator.client.control.set_param(
            DeviceIdentity.from_dict(self._inverter_device.device_data),
            param_id,
            param_value,
        )

        self._attr_native_value = param_value
        self.async_write_ha_state()


class _VirtualBatterySettingBase(NumberBase, RestoreNumber):
    """Common plumbing for the per-device virtual-battery config numbers.

    Values are local-only (no cloud round-trip) and persist across HA
    restarts via :class:`RestoreNumber`. On restore + on user edit we sync
    the value into the device's :class:`VirtualBatteryEstimator` so the
    next coordinator tick picks it up.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def _apply_to_estimator(self, value: float) -> None:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            try:
                self._attr_native_value = float(last.native_value)
            except (TypeError, ValueError):
                self._attr_native_value = None
        if self._attr_native_value is not None:
            self._apply_to_estimator(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        try:
            self._attr_native_value = float(value)
        except (TypeError, ValueError):
            return
        self._apply_to_estimator(self._attr_native_value)
        self.async_write_ha_state()


class VirtualBatteryCapacityNumber(_VirtualBatterySettingBase):
    """Nominal bank capacity (Ah). Setting to 0 keeps the estimator dormant."""

    _attr_native_unit_of_measurement = "Ah"
    _attr_native_min_value = MIN_BATTERY_CAPACITY_AH
    _attr_native_max_value = MAX_BATTERY_CAPACITY_AH
    _attr_native_step = 1

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{inverter_device.inverter_id}_virtual_battery_capacity_ah"
        self._attr_name = f"{inverter_device.name} Virtual Battery Capacity"
        self._attr_native_value = float(DEFAULT_BATTERY_CAPACITY_AH)

    def _apply_to_estimator(self, value: float) -> None:
        estimator = self._inverter_device.virtual_battery
        if estimator is not None:
            estimator.set_capacity_ah(value)


class VirtualBatteryVoltageFullNumber(_VirtualBatterySettingBase):
    """Absorb / full-charge voltage threshold for SOC rebase."""

    _attr_device_class = NumberDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_native_min_value = MIN_BATTERY_VOLTAGE_FULL
    _attr_native_max_value = MAX_BATTERY_VOLTAGE_FULL
    _attr_native_step = 0.1

    def __init__(self, inverter_device: InverterDevice, coordinator: MainCoordinator):
        super().__init__(inverter_device, coordinator)
        self._attr_unique_id = f"{inverter_device.inverter_id}_virtual_battery_voltage_full"
        self._attr_name = f"{inverter_device.name} Virtual Battery Full Voltage"
        self._attr_native_value = float(DEFAULT_BATTERY_VOLTAGE_FULL)

    def _apply_to_estimator(self, value: float) -> None:
        estimator = self._inverter_device.virtual_battery
        if estimator is not None:
            estimator.set_voltage_full(value)
