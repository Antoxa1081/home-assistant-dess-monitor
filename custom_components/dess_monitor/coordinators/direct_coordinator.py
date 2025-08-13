import logging
from datetime import timedelta

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.dess_monitor.api import *
from custom_components.dess_monitor.api.commands.direct.providers.registry import create_provider
from custom_components.dess_monitor.api.commands.direct_commands import resolve_grid_input_power
from custom_components.dess_monitor.api.helpers import *

_LOGGER = logging.getLogger(__name__)


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _battery_current_signed(qpigs: dict) -> float | None:
    """
    Единый подписанный ток батареи (+ заряд, – разряд), извлекаем из QPIGS:
    - battery_charging_current (A)
    - battery_discharge_current (A)
    """
    ci = _f(qpigs.get("battery_charging_current"))
    di = _f(qpigs.get("battery_discharge_current"))
    if ci is None and di is None:
        return None
    ci = ci or 0.0
    di = di or 0.0
    if ci > 0 and di == 0:
        return ci
    if di > 0 and ci == 0:
        return -di
    return ci - di


def _snapshot_from_direct(raw: dict) -> dict:
    """
    Построить унифицированный снапшот из сырых ответов Direct.
    raw = {"qpigs":..., "qpigs2":..., "qpiri":..., "qmod":..., "qmn":..., "qvfw":...}
    """
    qpigs = raw.get("qpigs", {}) or {}
    qpigs2 = raw.get("qpigs2", {}) or {}
    qpiri = raw.get("qpiri", {}) or {}
    qmn = raw.get("qmn", {}) or {}
    qvfw = raw.get("qvfw", {}) or {}

    # pv
    pv_v = _first(_f(qpigs.get("pv_input_voltage")), _f(qpigs2.get("pv_voltage")))
    pv_i = _first(_f(qpigs.get("pv_input_current")), _f(qpigs2.get("pv_current")))
    pv_p = _first(_f(qpigs.get("pv_charging_power")),
                  (_f(qpigs2.get("pv_voltage")) or 0.0) * (_f(qpigs2.get("pv_current")) or 0.0)
                  if (qpigs2.get("pv_voltage") is not None and qpigs2.get("pv_current") is not None) else None)

    # сетевой ввод: твоя функция
    grid_in = None
    try:
        grid_in = float(resolve_grid_input_power(qpigs, qpiri))
    except Exception:
        grid_in = None

    # батарея
    batt_i_signed = _battery_current_signed(qpigs)

    return {
        "ts": datetime.now().timestamp(),
        "model": qmn.get("Model"),
        "serial": None,  # при желании добавь QID/QSID в raw и впиши сюда
        "fw": qvfw.get("Firmware Version"),

        "grid_voltage_v": _f(qpigs.get("grid_voltage")),
        "grid_freq_hz": _f(qpigs.get("grid_frequency")),

        "ac_out_voltage_v": _f(qpigs.get("ac_output_voltage")),
        "ac_out_freq_hz": _f(qpigs.get("ac_output_frequency")),
        "out_active_power_w": _f(qpigs.get("output_active_power")),
        "out_apparent_power_va": _f(qpigs.get("output_apparent_power")),
        "load_percent": _f(qpigs.get("load_percent")),

        "battery_voltage_v": _f(qpigs.get("battery_voltage")),
        "battery_current_a": batt_i_signed,
        "battery_soc_percent": _f(qpigs.get("battery_capacity")),
        "inverter_temp_c": _f(qpigs.get("inverter_heat_sink_temperature")),

        "pv_voltage_v": pv_v,
        "pv_current_a": pv_i,
        "pv_power_w": pv_p,

        # operating_mode можно вывести из QMOD, если положишь его в raw
        "operating_mode": "Unknown",

        "grid_input_power_w": grid_in,

        # блок 'spec' (бывший QPIRI) — пригодится унифицированным сенсорам «настроек»
        "spec": {
            k: qpiri.get(k)
            for k in [
                "rated_grid_voltage",
                "rated_input_current",
                "rated_ac_output_voltage",
                "rated_output_frequency",
                "rated_output_current",
                "rated_output_apparent_power",
                "rated_output_active_power",
                "rated_battery_voltage",
                "low_battery_to_ac_bypass_voltage",
                "shut_down_battery_voltage",
                "bulk_charging_voltage",
                "float_charging_voltage",
                "battery_type",
                "max_utility_charging_current",
                "max_charging_current",
                "ac_input_voltage_range",
                "output_source_priority",
                "charger_source_priority",
                "parallel_max_number",
                "parallel_mode",
                "high_battery_voltage_to_battery_mode",
                "solar_work_condition_in_parallel",
                "solar_max_charging_power_auto_adjust",
                "rated_battery_capacity",
            ]
        }
    }

class DirectCoordinator(DataUpdateCoordinator):
    """Координатор, который выбирает провайдера и собирает snapshot + raw по каждому инвертору."""
    devices = []
    auth = None
    auth_issued_at = None

    def __init__(self, hass: HomeAssistant, config_entry, send_hex_callable=None):
        super().__init__(
            hass,
            _LOGGER,
            name="DESS universal coordinator",
            config_entry=config_entry,
            update_interval=timedelta(seconds=10),
            always_update=False
        )
        self.send_hex_callable = send_hex_callable
        self.provider_kind = config_entry.options.get("provider_kind", "direct")
        self.provider = create_provider(self.provider_kind, send_hex_callable=send_hex_callable)

    async def _async_setup(self):
        if self.provider_kind == "direct":
            await self._create_auth()
        self.devices = await self._get_active_devices()
        _LOGGER.info("universal coordinator setup devices count: %s (provider=%s)",
                     len(self.devices), self.provider_kind)

    async def _create_auth(self):
        username = self.config_entry.data.get("username")
        password_hash = self.config_entry.data.get("password_hash")
        if not username or not password_hash:
            return
        auth = await auth_user(username, password_hash)
        self.auth = auth
        self.auth_issued_at = int(datetime.now().timestamp())

    async def _check_auth(self):
        now = int(datetime.now().timestamp())
        if self.auth_issued_at is None or (now - (self.auth_issued_at + (self.auth['expire'])) <= 3600):
            await self._create_auth()

    async def _get_active_devices(self):
        devices = await get_devices(self.auth['token'], self.auth['secret'])
        active_devices = [d for d in devices if d['status'] != 1]

        devices_filter = self.config_entry.options.get("devices", [])
        if devices_filter:
            return [d for d in active_devices if str(d.get("pn")) in devices_filter]
        return active_devices

    async def _async_update_data(self):
        try:
            async with async_timeout.timeout(30):
                # флаги включения опроса
                if self.provider_kind == "direct" and self.config_entry.options.get('direct_request_protocol') is not True:
                    return None

                await self._check_auth()
                self.devices = await self._get_active_devices()

                async def fetch(device):
                    # для direct передаём auth, для modbus — auth не нужен
                    auth = self.auth if self.provider_kind == "direct" else {}
                    payload = await self.provider.read_for_device(
                        device=device,
                        auth=auth,
                        config_entry=self.config_entry,
                    )
                    # ключ в data — по твоей логике это PN
                    pn = device['pn'] if isinstance(device, dict) else device.inverter_id
                    return pn, payload

                data_map = dict(await asyncio.gather(*[fetch(d) for d in self.devices]))
                return data_map

        except TimeoutError as err:
            raise err
        except AuthInvalidateError:
            await self._create_auth()