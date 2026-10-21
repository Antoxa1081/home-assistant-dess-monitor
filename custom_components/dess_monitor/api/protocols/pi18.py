"""PI18 / InfiniSolar-V protocol adapter.

Wire format::

    Request   ^P<nnn><body><CRC><CR>
    Response  ^D<nnn><payload><CRC><CR>      (success)
              ^1<CRC><CR>                      (set command ACK)
              ^0<CRC><CR>                      (set command NAK)

``nnn`` is a 3-digit decimal length covering ``<body>``/``<payload>`` plus
the trailing CRC and CR (i.e. *every* byte after ``^Pnnn`` / ``^Dnnn``).
The CRC is XMODEM CRC-16, computed over the entire frame minus the CRC and
CR bytes themselves — same polynomial as Axpert.

The decoders project PI18 fields onto the same dict keys
:class:`AxpertProtocol` produces, so sensors don't notice which dialect
sourced the data. PI18-only fields (PV2 voltage/power, MPPT temps,
direction flags) are dropped for now — adding them would require expanding
the sensor schemas, not this adapter.

Source: ``PI18_InfiniSolar-V-protocol-20170926`` spec.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Protocol, ResponseSchema
from .crc import crc16_xmodem_bytes
from .enums import (
    ACInputVoltageRange,
    BatteryType,
    ChargerSourcePriority,
    OperatingMode,
    OutputSourcePriority,
)
from .parsing import strip_frame

# Logical command name (shared across protocols) → PI18 native command body.
_LOGICAL_TO_NATIVE: Mapping[str, str] = {
    "QPIGS": "GS",
    "QPIRI": "PIRI",
    "QMOD": "MOD",
    # Auxiliary commands that don't drive sensors but are useful for probes
    # / diagnostics. ``encode`` accepts both logical and native names.
    "QPI": "PI",
    "QID": "ID",
    "QVFW": "VFW",
    "QFWS": "FWS",
    "QFLAG": "FLAG",
    "QDI": "DI",
    "QMCHGCR": "MCHGCR",
    "QMUCHGCR": "MUCHGCR",
}


_SCHEMAS: Mapping[str, ResponseSchema] = {
    cmd: ResponseSchema(cmd, ()) for cmd in _LOGICAL_TO_NATIVE
}


def _safe_int(token: str, default: int = 0) -> int:
    try:
        return int(token)
    except (TypeError, ValueError):
        return default


def _build_frame(body: str) -> bytes:
    """Wrap a request body into the PI18 ``^P<nnn>...<CRC><CR>`` envelope."""
    body_bytes = body.encode("ascii")
    # nnn covers body + 2-byte CRC + 1-byte CR.
    length = len(body_bytes) + 3
    head = f"^P{length:03d}".encode("ascii") + body_bytes
    return head + crc16_xmodem_bytes(head) + b"\r"


# ---------------------------------------------------------------------------
# GS — General status. Maps onto the ``qpigs`` section.
# ---------------------------------------------------------------------------


_GS_FIELDS = (
    "grid_voltage",                    # 0  AAAA  0.1 V
    "grid_frequency",                  # 1  BBB   0.1 Hz
    "ac_output_voltage",               # 2  CCCC  0.1 V
    "ac_output_frequency",             # 3  DDD   0.1 Hz
    "output_apparent_power",           # 4  EEEE  VA
    "output_active_power",             # 5  FFFF  W
    "load_percent",                    # 6  GGG   %
    "battery_voltage",                 # 7  HHH   0.1 V
    "scc_battery_voltage",             # 8  III   0.1 V
    "_battery_voltage_scc2",           # 9  JJJ   0.1 V (PI18 only)
    "battery_discharge_current",       # 10 KKK   A
    "battery_charging_current",        # 11 LLL   A
    "battery_capacity",                # 12 MMM   %
    "inverter_heat_sink_temperature",  # 13 NNN   °C
    "_mppt1_temp",                     # 14 OOO   °C
    "_mppt2_temp",                     # 15 PPP   °C
    "pv_charging_power",               # 16 QQQQ  W
    "_pv2_input_power",                # 17 RRRR  W
    "pv_input_voltage",                # 18 SSSS  0.1 V
    "_pv2_input_voltage",              # 19 TTTT  0.1 V
    "_settings_changed",               # 20 U     0/1
    "_mppt1_status",                   # 21 V     0/1/2
    "_mppt2_status",                   # 22 W     0/1/2
    "_load_connected",                 # 23 X     0/1
    "_battery_power_dir",              # 24 Y     0/1/2
    "_dcac_power_dir",                 # 25 Z     0/1/2
    "_line_power_dir",                 # 26 a     0/1/2
    "_local_parallel_id",              # 27 b
)


def _decode_gs(tokens: list[str]) -> dict[str, Any]:
    """Project a ``^P005GS`` reply onto the Axpert-shaped ``qpigs`` dict."""
    # Pad to schema length so missing trailing fields don't IndexError.
    padded = list(tokens) + [""] * (len(_GS_FIELDS) - len(tokens))
    raw = dict(zip(_GS_FIELDS, padded))

    # Synthesise pv_input_current — PI18 doesn't expose it directly. Compute
    # from power/voltage; clamp to 0 when voltage is zero to avoid div/0.
    pv_v_int = _safe_int(raw["pv_input_voltage"])
    pv_p_int = _safe_int(raw["pv_charging_power"])
    pv_v = pv_v_int / 10.0
    pv_input_current = pv_p_int / pv_v if pv_v else 0.0

    # Status bits aren't directly exposed in PI18; synthesise plausible
    # defaults the way the SMG-II adapter does, so any sensor reading them
    # gets a constant "running, charging from AC" baseline rather than
    # crashing on a missing key.
    status_b7_b0 = "00010001"  # inverter_on + line_fail unset by default
    status_b10_b8 = "010"

    return {
        "grid_voltage": f"{_safe_int(raw['grid_voltage']) / 10.0:.1f}",
        "grid_frequency": f"{_safe_int(raw['grid_frequency']) / 10.0:.1f}",
        "ac_output_voltage": f"{_safe_int(raw['ac_output_voltage']) / 10.0:.1f}",
        "ac_output_frequency": f"{_safe_int(raw['ac_output_frequency']) / 10.0:.1f}",
        "output_apparent_power": f"{_safe_int(raw['output_apparent_power']):04d}",
        "output_active_power": f"{_safe_int(raw['output_active_power']):04d}",
        "load_percent": f"{_safe_int(raw['load_percent']):03d}",
        # PI18 has no dedicated bus-voltage register; mirror SMG-II default.
        "bus_voltage": "400",
        "battery_voltage": f"{_safe_int(raw['battery_voltage']) / 10.0:.2f}",
        "battery_charging_current": f"{_safe_int(raw['battery_charging_current']):03d}",
        "battery_capacity": f"{_safe_int(raw['battery_capacity']):03d}",
        "inverter_heat_sink_temperature": f"{_safe_int(raw['inverter_heat_sink_temperature']):.1f}",
        "pv_input_current": f"{pv_input_current:.1f}",
        "pv_input_voltage": f"{pv_v:.1f}",
        "scc_battery_voltage": f"{_safe_int(raw['scc_battery_voltage']) / 10.0:.2f}",
        "battery_discharge_current": f"{_safe_int(raw['battery_discharge_current']):05d}",
        "device_status_bits_b7_b0": status_b7_b0,
        "battery_voltage_offset": "00",
        "eeprom_version": "00",
        "pv_charging_power": f"{pv_p_int:05d}",
        "device_status_bits_b10_b8": status_b10_b8,
    }


# ---------------------------------------------------------------------------
# PIRI — Rated information. Maps onto ``qpiri`` section.
# ---------------------------------------------------------------------------


_PIRI_FIELDS = (
    "rated_grid_voltage",                  # 0  AAAA 0.1 V
    "rated_input_current",                 # 1  BBB  0.1 A
    "rated_ac_output_voltage",             # 2  CCCC 0.1 V
    "rated_output_frequency",              # 3  DDD  0.1 Hz
    "rated_output_current",                # 4  EEE  0.1 A
    "rated_output_apparent_power",         # 5  FFFF VA
    "rated_output_active_power",           # 6  GGGG W
    "rated_battery_voltage",               # 7  HHH  0.1 V
    "battery_recharge_voltage",            # 8  III  0.1 V (utility re-charge)
    "battery_redischarge_voltage",         # 9  JJJ  0.1 V (utility re-discharge)
    "battery_under_voltage",               # 10 KKK  0.1 V
    "battery_bulk_voltage",                # 11 LLL  0.1 V
    "battery_float_voltage",               # 12 MMM  0.1 V
    "battery_type_code",                   # 13 N    0=AGM 1=Flooded 2=User
    "max_ac_charging_current",             # 14 OO   A
    "max_charging_current",                # 15 PPP  A
    "input_voltage_range_code",            # 16 Q    0=Appliance 1=UPS
    "output_priority_code",                # 17 R    0=SUB 1=SBU
    "charger_priority_code",               # 18 S    0=SolarFirst 1=Solar+Util 2=OnlySolar
    "parallel_max",                        # 19 T
    "machine_type",                        # 20 U
    "topology",                            # 21 V
    "output_model_setting",                # 22 W
    "solar_power_priority_code",           # 23 Z
    "mppt_string",                         # 24 a
)


# PI18 R (output priority) → Axpert OutputSourcePriority name.
# PI18 only describes 0=Solar-Utility-Battery and 1=Solar-Battery-Utility.
# Map the closest semantic equivalents in our shared enum.
_PI18_OUTPUT_PRIORITY: Mapping[int, str] = {
    0: OutputSourcePriority.SolarFirst.name,
    1: OutputSourcePriority.SBU.name,
}

# PI18 S (charger priority) → Axpert ChargerSourcePriority name.
_PI18_CHARGER_PRIORITY: Mapping[int, str] = {
    0: ChargerSourcePriority.SolarFirst.name,
    1: ChargerSourcePriority.SolarAndUtility.name,
    2: ChargerSourcePriority.OnlySolar.name,
}


def _decode_piri(tokens: list[str]) -> dict[str, Any]:
    padded = list(tokens) + [""] * (len(_PIRI_FIELDS) - len(tokens))
    raw = dict(zip(_PIRI_FIELDS, padded))

    # PI18 battery type codes ("0"/"1"/"2") line up with Axpert's
    # BatteryType enum directly — reuse the readback values.
    try:
        battery_type = BatteryType(raw["battery_type_code"]).name
    except ValueError:
        battery_type = raw["battery_type_code"]

    try:
        ac_range = ACInputVoltageRange(raw["input_voltage_range_code"]).name
    except ValueError:
        ac_range = raw["input_voltage_range_code"]

    output_priority = _PI18_OUTPUT_PRIORITY.get(
        _safe_int(raw["output_priority_code"], -1),
        raw["output_priority_code"],
    )
    charger_priority = _PI18_CHARGER_PRIORITY.get(
        _safe_int(raw["charger_priority_code"], -1),
        raw["charger_priority_code"],
    )

    return {
        "rated_grid_voltage": f"{_safe_int(raw['rated_grid_voltage']) / 10.0:.1f}",
        "rated_input_current": f"{_safe_int(raw['rated_input_current']) / 10.0:.1f}",
        "rated_ac_output_voltage": f"{_safe_int(raw['rated_ac_output_voltage']) / 10.0:.1f}",
        "rated_output_frequency": f"{_safe_int(raw['rated_output_frequency']) / 10.0:.1f}",
        "rated_output_current": f"{_safe_int(raw['rated_output_current']) / 10.0:.1f}",
        "rated_output_apparent_power": f"{_safe_int(raw['rated_output_apparent_power']):04d}",
        "rated_output_active_power": f"{_safe_int(raw['rated_output_active_power']):04d}",
        "rated_battery_voltage": f"{_safe_int(raw['rated_battery_voltage']) / 10.0:.1f}",
        "low_battery_to_ac_bypass_voltage": f"{_safe_int(raw['battery_redischarge_voltage']) / 10.0:.1f}",
        "shut_down_battery_voltage": f"{_safe_int(raw['battery_under_voltage']) / 10.0:.1f}",
        "bulk_charging_voltage": f"{_safe_int(raw['battery_bulk_voltage']) / 10.0:.1f}",
        "float_charging_voltage": f"{_safe_int(raw['battery_float_voltage']) / 10.0:.1f}",
        "battery_type": battery_type,
        "max_utility_charging_current": f"{_safe_int(raw['max_ac_charging_current']):02d}",
        "max_charging_current": f"{_safe_int(raw['max_charging_current']):03d}",
        "ac_input_voltage_range": ac_range,
        "output_source_priority": output_priority,
        "charger_source_priority": charger_priority,
        "parallel_max_number": raw["parallel_max"] or "0",
        "reserved_uu": "00",
        "reserved_v": "0",
        # PI18 doesn't have an explicit parallel master/slave readout in PIRI;
        # output_model_setting is the closest signal but its codes (0..4)
        # don't map cleanly to ParallelMode. Punt with a constant.
        "parallel_mode": "Standalone",
        "high_battery_voltage_to_battery_mode": f"{_safe_int(raw['battery_recharge_voltage']) / 10.0:.1f}",
        "solar_work_condition_in_parallel": "0",
        "solar_max_charging_power_auto_adjust": "1_",
        "rated_battery_capacity": "200",
        "reserved_b": "0",
        "reserved_ccc": "0",
    }


# ---------------------------------------------------------------------------
# MOD — Working mode. Maps to ``operating_mode``.
# ---------------------------------------------------------------------------


_PI18_MODE_TO_OPERATING_MODE: Mapping[int, OperatingMode] = {
    0: OperatingMode.PowerOn,
    1: OperatingMode.Standby,
    2: OperatingMode.Line,            # Bypass
    3: OperatingMode.Battery,
    4: OperatingMode.Fault,
    5: OperatingMode.Line,            # Hybrid (Line/Grid)
}


def _decode_mod(payload: str) -> dict[str, Any]:
    code = _safe_int(payload.strip(), -1)
    mode = _PI18_MODE_TO_OPERATING_MODE.get(code)
    if mode is None:
        return {"operating_mode": "Unknown"}
    return {"operating_mode": mode.name}


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class Pi18Protocol(Protocol):
    """Codec for the PI18 / InfiniSolar-V command set."""

    name = "pi18"

    @property
    def schemas(self) -> Mapping[str, ResponseSchema]:
        return _SCHEMAS

    def encode(self, command: str) -> bytes:
        cmd = command.upper()
        body = _LOGICAL_TO_NATIVE.get(cmd, cmd)
        return _build_frame(body)

    def decode(self, command: str, raw: bytes) -> dict[str, Any]:
        if not raw or raw == b"null":
            return {"error": "null response received. Command not accepted."}

        # Set commands answer with a bare ``^1``/``^0`` marker, no length
        # header. Detect those before strip_frame mangles the leading byte.
        if raw[:2] == b"^1":
            return {"status": "ACK"}
        if raw[:2] == b"^0":
            return {"status": "NAK"}

        payload_bytes = strip_frame(raw)
        payload = payload_bytes.decode("ascii", errors="ignore").strip()
        if not payload:
            return {"error": "empty PI18 payload"}

        cmd = command.upper()
        native = _LOGICAL_TO_NATIVE.get(cmd, cmd)

        # Comma-separated for everything except the few "single value" replies.
        if native == "MOD":
            return _decode_mod(payload)
        if native == "PI":
            return {"protocol_id": payload}

        tokens = [t.strip() for t in payload.split(",")]
        if native == "GS":
            return _decode_gs(tokens)
        if native == "PIRI":
            return _decode_piri(tokens)

        # Fallback for commands we encode but don't yet decode in detail.
        return {"raw_tokens": tokens}
