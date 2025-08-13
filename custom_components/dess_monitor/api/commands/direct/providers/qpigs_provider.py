import time
from typing import Any, Dict, Optional

from custom_components.dess_monitor.api.commands.direct_commands import (
    decode_direct_response, get_command_hex, resolve_grid_input_power,
    OperatingMode
)
from .base import InverterProvider, CanonicalSnapshot, InverterOperatingMode


class QpigsProvider(InverterProvider):
    name = "qpigs"

    def __init__(self, transport_send_hex_callable):
        """
        transport_send_hex_callable(cmd_hex: str) -> str
        Возвращает hex-строку ответа устройства.
        Ты сюда пробрасываешь свой транспорт (RS232/TCP), чтобы провайдер
        только формировал команды и парсил.
        """
        self._tx = transport_send_hex_callable

    async def probe(self) -> bool:
        # Лёгкая команда — QMOD, QMN
        try:
            resp = await self._send_and_parse("QMOD")
            return bool(resp)
        except Exception:
            return False

    async def read_snapshot(self) -> CanonicalSnapshot:
        ts = time.time()

        qpigs = await self._send_and_parse("QPIGS")
        qpiri = await self._send_and_parse("QPIRI")
        qmod = await self._send_and_parse("QMOD")
        qmn = await self._send_and_parse("QMN")
        qvfw = await self._send_and_parse("QVFW")
        # опционально: QPIGS2
        try:
            qpigs2 = await self._send_and_parse("QPIGS2")
        except Exception:
            qpigs2 = {}

        # Операционный режим
        op = InverterOperatingMode.UNKNOWN
        try:
            code = qmod.get("operating_mode")
            if isinstance(code, OperatingMode):
                op = {
                    OperatingMode.PowerOn: InverterOperatingMode.POWER_ON,
                    OperatingMode.Standby: InverterOperatingMode.STANDBY,
                    OperatingMode.Line: InverterOperatingMode.LINE,
                    OperatingMode.Battery: InverterOperatingMode.BATTERY,
                    OperatingMode.Fault: InverterOperatingMode.FAULT,
                    OperatingMode.ShutdownApproaching: InverterOperatingMode.UNKNOWN,
                }.get(code, InverterOperatingMode.UNKNOWN)
        except Exception:
            pass

        # Сетевой ввод (твоя функция)
        grid_in_w = None
        try:
            grid_in_w = float(resolve_grid_input_power(qpigs, qpiri))
        except Exception:
            pass

        snap = CanonicalSnapshot(
            ts=ts,
            model=qmn.get("Model"),
            serial=None,  # при необходимости добавь QSID/QID
            fw=qvfw.get("Firmware Version"),

            grid_voltage_v=_f(qpigs.get("grid_voltage")),
            grid_freq_hz=_f(qpigs.get("grid_frequency")),

            ac_out_voltage_v=_f(qpigs.get("ac_output_voltage")),
            ac_out_freq_hz=_f(qpigs.get("ac_output_frequency")),
            out_active_power_w=_f(qpigs.get("output_active_power")),
            out_apparent_power_va=_f(qpigs.get("output_apparent_power")),
            load_percent=_f(qpigs.get("load_percent")),

            battery_voltage_v=_f(qpigs.get("battery_voltage")),
            battery_current_a=_battery_current(qpigs),  # см. helper ниже
            battery_soc_percent=_f(qpigs.get("battery_capacity")),
            inverter_temp_c=_f(qpigs.get("inverter_heat_sink_temperature")),

            pv_voltage_v=_first_non_none(_f(qpigs.get("pv_input_voltage")),
                                         _f(qpigs2.get("pv_voltage"))),
            pv_current_a=_first_non_none(_f(qpigs.get("pv_input_current")),
                                         _f(qpigs2.get("pv_current"))),
            pv_power_w=_first_non_none(_f(qpigs.get("pv_charging_power")),
                                       _mul(_f(qpigs2.get("pv_current")),
                                            _f(qpigs2.get("pv_voltage")))),

            operating_mode=op,
            grid_input_power_w=grid_in_w,

            raw={
                "qpigs": qpigs,
                "qpiri": qpiri,
                "qmod": qmod,
                "qmn": qmn,
                "qvfw": qvfw,
                "qpigs2": qpigs2,
            }
        )
        return snap

    async def _send_and_parse(self, cmd_name: str) -> Dict[str, Any]:
        cmd_hex = get_command_hex(cmd_name)
        resp_hex = await self._tx(cmd_hex)  # transport должен вернуть строку HEX ответа
        return decode_direct_response(cmd_name, resp_hex)


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def _mul(a, b):
    return a * b if a is not None and b is not None else None


def _first_non_none(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _battery_current(qpigs: Dict[str, Any]) -> Optional[float]:
    # Если из qpigs есть раздельные токи charge/discharge — сведём в «signed»
    ci = _f(qpigs.get("battery_charging_current"))
    di = _f(qpigs.get("battery_discharge_current"))
    if ci is None and di is None:
        return None
    # Принято: заряд = +, разряд = –
    ci = ci or 0.0
    di = di or 0.0
    if ci > 0 and di == 0:
        return ci
    if di > 0 and ci == 0:
        return -di
    # если непоследовательно — вернём разницу
    return ci - di
