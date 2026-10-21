"""Voltronic Axpert / PI30 protocol adapter.

Frame format::

    Q<COMMAND><CRC16-XMODEM><CR>          (request)
    (<payload> <CRC16-XMODEM><CR>          (response)

The schemas below preserve the field names and value semantics that the
legacy ``direct_commands`` decoders produced, so existing sensors keep
working untouched.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Field, Protocol, ResponseSchema
from .crc import crc16_xmodem_bytes
from .enums import (
    ACInputVoltageRange,
    BatteryType,
    ChargerSourcePriority,
    OperatingMode,
    OutputSourcePriority,
    ParallelMode,
)
from .parsing import is_nak, parse_positional, strip_frame

_QPIGS = ResponseSchema("QPIGS", tuple(Field(n) for n in (
    "grid_voltage",
    "grid_frequency",
    "ac_output_voltage",
    "ac_output_frequency",
    "output_apparent_power",
    "output_active_power",
    "load_percent",
    "bus_voltage",
    "battery_voltage",
    "battery_charging_current",
    "battery_capacity",
    "inverter_heat_sink_temperature",
    "pv_input_current",
    "pv_input_voltage",
    "scc_battery_voltage",
    "battery_discharge_current",
    "device_status_bits_b7_b0",
    "battery_voltage_offset",
    "eeprom_version",
    "pv_charging_power",
    "device_status_bits_b10_b8",
    "reserved_a",
    "reserved_bb",
    "reserved_cccc",
)))


_QPIGS2 = ResponseSchema("QPIGS2", (
    Field("pv_current"),
    Field("pv_voltage"),
    Field("pv_daily_energy"),
))


_QPIRI = ResponseSchema("QPIRI", (
    Field("rated_grid_voltage"),
    Field("rated_input_current"),
    Field("rated_ac_output_voltage"),
    Field("rated_output_frequency"),
    Field("rated_output_current"),
    Field("rated_output_apparent_power"),
    Field("rated_output_active_power"),
    Field("rated_battery_voltage"),
    Field("low_battery_to_ac_bypass_voltage"),
    Field("shut_down_battery_voltage"),
    Field("bulk_charging_voltage"),
    Field("float_charging_voltage"),
    Field("battery_type", enum=BatteryType),
    Field("max_utility_charging_current"),
    Field("max_charging_current"),
    Field("ac_input_voltage_range", enum=ACInputVoltageRange),
    Field("output_source_priority", enum=OutputSourcePriority),
    Field("charger_source_priority", enum=ChargerSourcePriority),
    Field("parallel_max_number"),
    Field("reserved_uu"),
    Field("reserved_v"),
    Field("parallel_mode", enum=ParallelMode),
    Field("high_battery_voltage_to_battery_mode"),
    Field("solar_work_condition_in_parallel"),
    Field("solar_max_charging_power_auto_adjust"),
    Field("rated_battery_capacity"),
    Field("reserved_b"),
    Field("reserved_ccc"),
))


_QMOD = ResponseSchema("QMOD", (
    Field("operating_mode", enum=OperatingMode),
))


_QBEQI = ResponseSchema("QBEQI", tuple(Field(n) for n in (
    "equalization_function",
    "equalization_time",
    "interval_days",
    "max_charging_current",
    "float_voltage",
    "reserved_1",
    "equalization_timeout",
    "immediate_activation_flag",
    "elapsed_time",
)))


# Single-field commands whose entire payload is a free-form string.
_QMN = ResponseSchema("QMN", (Field("Model"),))
_QID = ResponseSchema("QID", (Field("Device ID"),))
_QFLAG = ResponseSchema("QFLAG", (Field("Enabled/Disabled Flags"),))
_QVFW = ResponseSchema("QVFW", (Field("Firmware Version"),))


_SCHEMAS: Mapping[str, ResponseSchema] = {
    "QPIGS": _QPIGS,
    "QPIGS2": _QPIGS2,
    "QPIRI": _QPIRI,
    "QMOD": _QMOD,
    "QBEQI": _QBEQI,
    "QMN": _QMN,
    "QID": _QID,
    "QSID": _QID,
    "QFLAG": _QFLAG,
    "QVFW": _QVFW,
    # Commands without a structured schema — kept so encode() still works.
    "QPIWS": ResponseSchema("QPIWS", ()),
    "QMCHGCR": ResponseSchema("QMCHGCR", ()),
    "QMUCHGCR": ResponseSchema("QMUCHGCR", ()),
}


class AxpertProtocol(Protocol):
    name = "axpert"

    @property
    def schemas(self) -> Mapping[str, ResponseSchema]:
        return _SCHEMAS

    def encode(self, command: str) -> bytes:
        cmd = command.upper().encode("ascii")
        return cmd + crc16_xmodem_bytes(cmd) + b"\r"

    def decode(self, command: str, raw: bytes) -> dict[str, Any]:
        if not raw or raw == b"null":
            return {"error": "null response received. Command not accepted."}

        payload_bytes = strip_frame(raw)
        payload = payload_bytes.decode("ascii", errors="ignore").strip()

        if is_nak(payload):
            return {"error": "NAK response received. Command not accepted."}

        cmd = command.upper()
        schema = _SCHEMAS.get(cmd)

        # QVFW prefixes its payload with "VERFW:" — strip it so the schema
        # field receives the bare version string.
        if cmd == "QVFW":
            payload = payload.replace("VERFW:", "").strip()

        # QMOD is a single character, not whitespace-separated.
        if cmd == "QMOD":
            token = payload[:1]
            try:
                return {"operating_mode": OperatingMode(token).name}
            except ValueError:
                return {"operating_mode": "Unknown"}

        if schema is None or not schema.fields:
            return {"Raw": payload}

        # Single-field free-form commands take the whole payload.
        if len(schema.fields) == 1 and cmd in {"QMN", "QID", "QSID", "QFLAG", "QVFW"}:
            return {schema.fields[0].name: payload}

        return parse_positional(payload, schema)
