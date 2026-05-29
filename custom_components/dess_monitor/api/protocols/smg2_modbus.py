"""SMG-II (InfiniSolar variant) Modbus RTU protocol adapter.

The wire format is Modbus RTU read-holding-registers (function 0x03). Each
logical command corresponds to one register block; the decoder maps raw
register values into the *same* dict keys that :class:`AxpertProtocol`
emits for ``QPIGS`` / ``QPIRI``, so downstream sensors don't notice that
the data came from a register file rather than an ASCII reply.

Pair with :class:`ModbusTcpTransport` (or any other transport that ships
opaque Modbus frames). Source for the register layout:
``dess-monitor-local`` SMG-II implementation.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import Protocol, ResponseSchema
from .crc import crc16_modbus, crc16_modbus_bytes
from .enums import (
    ACInputVoltageRange,
    ChargerSourcePriority,
    OperatingMode,
    OutputSourcePriority,
)

DEFAULT_UNIT_ID = 1


@dataclass(frozen=True, slots=True)
class _ModbusBlock:
    """Description of one read transaction backing a logical command."""

    start: int
    count: int


# The cloud-style ``qpigs``/``qpiri`` sections are produced by separate
# Modbus reads. ``QMOD`` reuses the sensor block (it derives the inverter
# state from register 201) so we don't issue a third transaction for it.
_QPIGS_BLOCK = _ModbusBlock(start=201, count=31)
_QPIRI_BLOCK = _ModbusBlock(start=300, count=38)
_QMOD_BLOCK = _QPIGS_BLOCK

_BLOCKS: Mapping[str, _ModbusBlock] = {
    "QPIGS": _QPIGS_BLOCK,
    "QPIRI": _QPIRI_BLOCK,
    "QMOD": _QMOD_BLOCK,
}


_OPERATION_MODES = {
    0: "Power On",
    1: "Standby",
    2: "Mains",
    3: "Off-Grid",
    4: "Bypass",
    5: "Charging",
    6: "Fault",
}


def _i16(v: int) -> int:
    """Signed interpretation of a 16-bit holding register."""
    return v - 65536 if v >= 32768 else v


def _build_read_request(unit_id: int, block: _ModbusBlock) -> bytes:
    body = bytes([
        unit_id & 0xFF,
        0x03,
        (block.start >> 8) & 0xFF,
        block.start & 0xFF,
        (block.count >> 8) & 0xFF,
        block.count & 0xFF,
    ])
    return body + crc16_modbus_bytes(body)


def _parse_read_response(raw: bytes, unit_id: int, block: _ModbusBlock) -> list[int]:
    if len(raw) < 5:
        raise ValueError("Modbus response truncated")
    if raw[0] != unit_id:
        raise ValueError(f"unexpected unit id {raw[0]}")
    func = raw[1]
    if func & 0x80:
        # Exception response: [uid][func|0x80][exc_code][crc_lo][crc_hi]
        if len(raw) < 5:
            raise ValueError("Modbus exception frame truncated")
        raise ValueError(f"Modbus exception {raw[2]:#04x}")
    if func != 0x03:
        raise ValueError(f"unexpected function {func:#04x}")
    byte_count = raw[2]
    if len(raw) < 3 + byte_count + 2:
        raise ValueError("Modbus data frame truncated")
    data = raw[3 : 3 + byte_count]
    crc_recv = raw[3 + byte_count] | (raw[3 + byte_count + 1] << 8)
    crc_calc = crc16_modbus(raw[: 3 + byte_count])
    if crc_recv != crc_calc:
        raise ValueError("Modbus CRC mismatch")
    if byte_count != block.count * 2:
        raise ValueError(
            f"unexpected byte count {byte_count}, want {block.count * 2}"
        )
    regs: list[int] = []
    for i in range(0, byte_count, 2):
        regs.append((data[i] << 8) | data[i + 1])
    return regs


def _decode_qpigs(regs: list[int]) -> dict[str, Any]:
    def R(addr: int) -> int:
        return regs[addr - _QPIGS_BLOCK.start]

    battery_current = _i16(R(216))
    battery_charging_current = max(0, battery_current)
    battery_discharge_current = max(0, -battery_current)

    return {
        "grid_voltage": f"{R(202) / 10.0:.1f}",
        "grid_frequency": f"{R(203) / 100.0:.1f}",
        "ac_output_voltage": f"{R(210) / 10.0:.1f}",
        "ac_output_frequency": f"{R(212) / 100.0:.2f}",
        "output_apparent_power": f"{abs(_i16(R(213))):04d}",
        "output_active_power": f"{abs(_i16(R(213))):04d}",
        "load_percent": f"{R(225):03d}",
        "bus_voltage": "400",  # SMG-II has no dedicated bus-voltage register
        "battery_voltage": f"{R(215) / 10.0:.2f}",
        "battery_charging_current": f"{battery_charging_current:03d}",
        "battery_capacity": "100",
        "inverter_heat_sink_temperature": f"{R(227):.1f}",
        "inverter_dcdc_module_temperature": f"{R(226):.1f}",
        "pv_input_current": f"{R(220) / 10.0:.1f}",
        "pv_input_voltage": f"{R(219) / 10.0:.1f}",
        "scc_battery_voltage": f"{R(215) / 10.0:.2f}",
        "battery_discharge_current": f"{battery_discharge_current:05d}",
        "device_status_bits_b7_b0": "00010000",
        "battery_voltage_offset": "00",
        "eeprom_version": "00",
        "pv_charging_power": f"{abs(_i16(R(223))):05d}",
        "device_status_bits_b10_b8": "010",
        "grid_ac_in_power": f"{abs(_i16(R(204))):05d}",
    }


def _decode_qpiri(regs: list[int]) -> dict[str, Any]:
    def R(addr: int) -> int:
        return regs[addr - _QPIRI_BLOCK.start]

    ac_range = (
        ACInputVoltageRange.UPS.name
        if R(302) == 1
        else ACInputVoltageRange.Appliance.name
    )

    output_priority_map = {
        0: OutputSourcePriority.UtilityFirst.name,
        1: OutputSourcePriority.SolarFirst.name,
        2: OutputSourcePriority.SBU.name,
    }
    output_priority = output_priority_map.get(
        R(301), OutputSourcePriority.UtilityFirst.name
    )

    charger_priority_map = {
        0: ChargerSourcePriority.UtilityFirst.name,
        1: ChargerSourcePriority.SolarFirst.name,
        2: ChargerSourcePriority.SolarAndUtility.name,
        3: ChargerSourcePriority.OnlySolar.name,
    }
    charger_priority = charger_priority_map.get(
        R(331), ChargerSourcePriority.UtilityFirst.name
    )

    return {
        "rated_grid_voltage": "230.0",
        "rated_input_current": "15.2",
        "rated_ac_output_voltage": "230.0",
        "rated_output_frequency": "50.0",
        "rated_output_current": "15.2",
        "rated_output_apparent_power": "4000",
        "rated_output_active_power": "4000",
        "rated_battery_voltage": "24.0",
        "low_battery_to_ac_bypass_voltage": f"{R(327) / 10.0:.1f}",
        "shut_down_battery_voltage": f"{R(329) / 10.0:.1f}",
        "bulk_charging_voltage": f"{R(324) / 10.0:.1f}",
        "float_charging_voltage": f"{R(325) / 10.0:.1f}",
        "battery_type": "UserDefined",
        "max_utility_charging_current": f"{int(R(333) / 10.0):02d}",
        "max_charging_current": f"{int(R(332) / 10.0):03d}",
        "ac_input_voltage_range": ac_range,
        "output_source_priority": output_priority,
        "charger_source_priority": charger_priority,
        "parallel_max_number": "6",
        "reserved_uu": "01",
        "reserved_v": "0",
        "parallel_mode": "Master",
        "high_battery_voltage_to_battery_mode": f"{R(326) / 10.0:.1f}",
        "solar_work_condition_in_parallel": "0",
        "solar_max_charging_power_auto_adjust": "1_",
        "rated_battery_capacity": "200",
        "reserved_b": "0",
        "reserved_ccc": "0",
    }


def _decode_qmod(regs: list[int]) -> dict[str, Any]:
    raw = regs[201 - _QMOD_BLOCK.start]
    label = (_OPERATION_MODES.get(raw) or "").lower()
    if any(x in label for x in ("mains", "bypass", "charging")):
        mode = OperatingMode.Line
    elif "off-grid" in label or "off grid" in label or "offgrid" in label:
        mode = OperatingMode.Battery
    elif "standby" in label:
        mode = OperatingMode.Standby
    elif "fault" in label:
        mode = OperatingMode.Fault
    else:
        mode = OperatingMode.PowerOn
    return {"operating_mode": mode.name}


_DECODERS = {
    "QPIGS": _decode_qpigs,
    "QPIRI": _decode_qpiri,
    "QMOD": _decode_qmod,
}


_SCHEMAS: Mapping[str, ResponseSchema] = {
    cmd: ResponseSchema(cmd, ()) for cmd in _BLOCKS
}


class Smg2ModbusProtocol(Protocol):
    """Read-only adapter for SMG-II inverters speaking Modbus RTU.

    Set commands aren't routed through this Protocol — register writes
    have a different shape and are handled by dedicated helpers (to be
    added when a write path lands).
    """

    name = "smg2_modbus"

    def __init__(self, unit_id: int = DEFAULT_UNIT_ID) -> None:
        self._unit_id = unit_id

    @property
    def schemas(self) -> Mapping[str, ResponseSchema]:
        return _SCHEMAS

    def encode(self, command: str) -> bytes:
        cmd = command.upper()
        block = _BLOCKS.get(cmd)
        if block is None:
            raise ValueError(f"Smg2ModbusProtocol does not support {cmd!r}")
        return _build_read_request(self._unit_id, block)

    def decode(self, command: str, raw: bytes) -> dict[str, Any]:
        if not raw:
            return {"error": "empty Modbus response"}
        cmd = command.upper()
        block = _BLOCKS.get(cmd)
        decoder = _DECODERS.get(cmd)
        if block is None or decoder is None:
            return {"error": f"unsupported command {cmd!r}"}
        try:
            regs = _parse_read_response(raw, self._unit_id, block)
        except ValueError as err:
            return {"error": str(err)}
        return decoder(regs)
