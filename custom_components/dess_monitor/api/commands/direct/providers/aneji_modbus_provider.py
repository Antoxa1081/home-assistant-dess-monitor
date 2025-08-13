from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from .base import InverterProvider, CanonicalSnapshot, InverterOperatingMode


###############################################################################
# CRC16/MODBUS
###############################################################################

def crc16_modbus(data: bytes) -> int:
    """
    Calculate CRC-16/MODBUS over data (poly 0xA001, init 0xFFFF).
    Returns integer CRC where low byte goes first on the wire.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(data_wo_crc: bytes) -> bytes:
    crc = crc16_modbus(data_wo_crc)
    # MODBUS sends CRC as Low byte, then High byte
    return data_wo_crc + struct.pack('<H', crc)


###############################################################################
# Frame builders
###############################################################################

def build_read_holding(slave_id: int, start_reg: int, reg_count: int) -> bytes:
    """
    Build a 0x03 Read Holding Registers request.
    - slave_id: 1..247
    - start_reg: 0..65535 (ANERN uses decimal addresses from doc)
    - reg_count: 1..125 (Modbus standard limit)
    """
    if not (1 <= slave_id <= 247):
        raise ValueError("slave_id must be 1..247")
    if not (0 <= start_reg <= 0xFFFF):
        raise ValueError("start_reg must be 0..65535")
    if not (1 <= reg_count <= 125):
        raise ValueError("reg_count must be 1..125")

    pdu = struct.pack('>BHH', 0x03, start_reg, reg_count)
    adu_wo_crc = struct.pack('>B', slave_id) + pdu
    return append_crc(adu_wo_crc)


def build_write_multiple(slave_id: int, start_reg: int, values: List[int]) -> bytes:
    """
    Build a 0x10 Write Multiple Registers request.
    'values' are 16-bit register values (0..65535). Caller applies scaling.
    """
    if not (1 <= slave_id <= 247):
        raise ValueError("slave_id must be 1..247")
    if not (0 <= start_reg <= 0xFFFF):
        raise ValueError("start_reg must be 0..65535")
    if not values:
        raise ValueError("values must be non-empty")
    if len(values) > 123:
        # 123 regs -> 246 bytes payload; still under RTU timing, but be conservative
        raise ValueError("too many registers in one write (max ~123)")

    reg_count = len(values)
    byte_count = reg_count * 2
    pdu = struct.pack('>BHHB', 0x10, start_reg, reg_count, byte_count) + struct.pack('>' + 'H' * reg_count, *values)
    adu_wo_crc = struct.pack('>B', slave_id) + pdu
    return append_crc(adu_wo_crc)


###############################################################################
# Helpers for parsing register payloads
###############################################################################

def _expect_read_response(slave_id: int, req_func: int, payload: bytes, expected_regs: int) -> Tuple[int, bytes]:
    """
    Validate RTU read response: [sid][func][byte_count][data...][crc_lo][crc_hi]
    Returns (byte_count, data_bytes).
    """
    if len(payload) < 5:
        raise ValueError("response too short")
    # CRC check
    data_wo_crc, recv_crc_le = payload[:-2], payload[-2:]
    calc_crc = crc16_modbus(data_wo_crc)
    recv_crc = struct.unpack('<H', recv_crc_le)[0]
    if recv_crc != calc_crc:
        raise ValueError(f"CRC mismatch: recv=0x{recv_crc:04X}, calc=0x{calc_crc:04X}")

    sid, func = payload[0], payload[1]
    if sid != slave_id:
        raise ValueError(f"unexpected slave id: got {sid}, expected {slave_id}")
    if func != req_func:
        # If 0x83 or 0x90 ... indicates exception
        raise ValueError(f"unexpected function code in response: 0x{func:02X}")

    byte_count = payload[2]
    data = payload[3:-2]
    if byte_count != len(data):
        raise ValueError("byte_count does not match data length")
    if expected_regs is not None and byte_count != expected_regs * 2:
        raise ValueError(f"unexpected register count in response (got {byte_count // 2}, expected {expected_regs})")
    return byte_count, data


def _u16(be2: bytes) -> int:
    return struct.unpack('>H', be2)[0]


def _i16(be2: bytes) -> int:
    return struct.unpack('>h', be2)[0]


def _u32(be4: bytes) -> int:
    # two big-endian registers: high word, low word
    return struct.unpack('>I', be4)[0]


def _ascii(bytes_seq: bytes) -> str:
    s = bytes_seq.decode('ascii', errors='ignore').rstrip('\x00').strip()
    return s


def bytes_to_u16_list(data: bytes) -> List[int]:
    if len(data) % 2:
        raise ValueError("data length must be even")
    return list(struct.unpack('>' + 'H' * (len(data) // 2), data))


###############################################################################
# Register map (subset used for parsing runtime telemetry 171..237)
###############################################################################

# Scaling and signedness per doc
# spec: (addr, name, type, scale) where type in {"uint","int","ascii","u32"}
RUNTIME_MAP: Dict[int, Tuple[str, str, float]] = {
    171: ("device_type", "uint", 1.0),
    172: ("device_name", "ascii12", 1.0),  # 12 regs ASCII
    184: ("protocol_number", "uint", 1.0),
    186: ("serial_number", "ascii12", 1.0),

    201: ("work_mode", "uint", 1.0),  # 0..6
    202: ("mains_voltage_v", "int", 0.1),
    203: ("mains_freq_hz", "int", 0.01),
    204: ("mains_power_w", "int", 1.0),

    205: ("inv_voltage_v", "int", 0.1),
    206: ("inv_current_a", "int", 0.1),
    207: ("inv_freq_hz", "int", 0.01),
    208: ("inv_power_w", "int", 1.0),
    209: ("inv_charge_power_w", "int", 1.0),

    210: ("out_voltage_v", "int", 0.1),
    211: ("out_current_a", "int", 0.1),
    212: ("out_freq_hz", "int", 0.01),
    213: ("out_active_power_w", "int", 1.0),
    214: ("out_apparent_power_va", "int", 1.0),

    215: ("bat_voltage_v", "int", 0.1),
    216: ("bat_current_a", "int", 0.1),
    217: ("bat_power_w", "int", 1.0),

    219: ("pv_voltage_v", "int", 0.1),
    220: ("pv_current_a", "int", 0.1),
    223: ("pv_power_w", "int", 1.0),
    224: ("pv_charge_power_w", "int", 1.0),

    225: ("load_percent", "int", 1.0),
    226: ("temp_dcdc_c", "int", 1.0),
    227: ("temp_inverter_c", "int", 1.0),
    229: ("soc_percent", "uint", 1.0),
    231: ("power_flow_flags", "uint", 1.0),

    233: ("inv_charge_current_a", "int", 0.1),
    234: ("pv_charge_current_a", "int", 0.1),
}

ASCII_BULKS: Dict[int, int] = {
    172: 12,  # device_name
    186: 12,  # serial_number
}


###############################################################################
# Data classes
###############################################################################

@dataclass
class PowerFlow:
    raw: int
    pv_connected: bool
    mains_connected: bool
    battery_state: str  # 'idle' | 'charging' | 'discharging'
    load_on: bool
    mains_charging: bool
    pv_charging: bool

    @staticmethod
    def from_raw(raw: int) -> 'PowerFlow':
        # bits mapping per doc
        pv_connected = (raw & 0b11) == 0b01
        mains_connected = ((raw >> 2) & 0b11) == 0b01
        bat_bits = (raw >> 4) & 0b11
        if bat_bits == 0:
            battery_state = 'idle'
        elif bat_bits == 1:
            battery_state = 'charging'
        elif bat_bits == 2:
            battery_state = 'discharging'
        else:
            battery_state = 'unknown'
        load_on = ((raw >> 6) & 0b11) == 0b01
        mains_charging = ((raw >> 8) & 0x1) == 1
        pv_charging = ((raw >> 9) & 0x1) == 1
        return PowerFlow(raw, pv_connected, mains_connected, battery_state, load_on, mains_charging, pv_charging)


@dataclass
class RuntimeTelemetry:
    # Essential identification
    device_type: Optional[int] = None
    device_name: Optional[str] = None
    protocol_number: Optional[int] = None
    serial_number: Optional[str] = None

    # Modes & flags
    work_mode: Optional[int] = None
    power_flow: Optional[PowerFlow] = None

    # Mains
    mains_voltage_v: Optional[float] = None
    mains_freq_hz: Optional[float] = None
    mains_power_w: Optional[int] = None

    # Inverter
    inv_voltage_v: Optional[float] = None
    inv_current_a: Optional[float] = None
    inv_freq_hz: Optional[float] = None
    inv_power_w: Optional[int] = None
    inv_charge_power_w: Optional[int] = None
    inv_charge_current_a: Optional[float] = None

    # Output
    out_voltage_v: Optional[float] = None
    out_current_a: Optional[float] = None
    out_freq_hz: Optional[float] = None
    out_active_power_w: Optional[int] = None
    out_apparent_power_va: Optional[int] = None
    load_percent: Optional[int] = None

    # Battery
    bat_voltage_v: Optional[float] = None
    bat_current_a: Optional[float] = None
    bat_power_w: Optional[int] = None
    soc_percent: Optional[int] = None

    # PV
    pv_voltage_v: Optional[float] = None
    pv_current_a: Optional[float] = None
    pv_power_w: Optional[int] = None
    pv_charge_power_w: Optional[int] = None
    pv_charge_current_a: Optional[float] = None

    @staticmethod
    def parse_from_block(start_reg: int, regs: List[int]) -> 'RuntimeTelemetry':
        """
        Parse a register slice that *covers* 171..237 (inclusive).
        'regs' are 16-bit unsigned values as received (big-endian per register).
        """
        # Build a dict of addr->u16 for convenience
        block: Dict[int, int] = {start_reg + i: regs[i] for i in range(len(regs))}

        def get_int(addr: int, scale: float) -> Optional[float]:
            if addr in block:
                return float(struct.unpack('>h', struct.pack('>H', block[addr]))[0]) * scale
            return None

        def get_uint(addr: int) -> Optional[int]:
            if addr in block:
                return int(block[addr])
            return None

        def get_ascii(addr: int, words: int) -> Optional[str]:
            if all((addr + i) in block for i in range(words)):
                raw = b''.join(struct.pack('>H', block[addr + i]) for i in range(words))
                # High byte first inside each word, so the byte stream is correct
                return raw.decode('ascii', errors='ignore').rstrip('\\x00').strip()
            return None

        # Fill fields
        t = RuntimeTelemetry()
        t.device_type = get_uint(171)
        t.device_name = get_ascii(172, 12)
        t.protocol_number = get_uint(184)
        t.serial_number = get_ascii(186, 12)

        t.work_mode = get_uint(201)
        pf_raw = get_uint(231)
        t.power_flow = PowerFlow.from_raw(pf_raw) if pf_raw is not None else None

        t.mains_voltage_v = get_int(202, 0.1)
        t.mains_freq_hz = get_int(203, 0.01)
        t.mains_power_w = int(get_int(204, 1.0)) if get_int(204, 1.0) is not None else None

        t.inv_voltage_v = get_int(205, 0.1)
        t.inv_current_a = get_int(206, 0.1)
        t.inv_freq_hz = get_int(207, 0.01)
        t.inv_power_w = int(get_int(208, 1.0)) if get_int(208, 1.0) is not None else None
        t.inv_charge_power_w = int(get_int(209, 1.0)) if get_int(209, 1.0) is not None else None
        t.inv_charge_current_a = get_int(233, 0.1)

        t.out_voltage_v = get_int(210, 0.1)
        t.out_current_a = get_int(211, 0.1)
        t.out_freq_hz = get_int(212, 0.01)
        t.out_active_power_w = int(get_int(213, 1.0)) if get_int(213, 1.0) is not None else None
        t.out_apparent_power_va = int(get_int(214, 1.0)) if get_int(214, 1.0) is not None else None
        t.load_percent = int(get_int(225, 1.0)) if get_int(225, 1.0) is not None else None

        t.bat_voltage_v = get_int(215, 0.1)
        t.bat_current_a = get_int(216, 0.1)
        t.bat_power_w = int(get_int(217, 1.0)) if get_int(217, 1.0) is not None else None
        t.soc_percent = get_uint(229)

        t.pv_voltage_v = get_int(219, 0.1)
        t.pv_current_a = get_int(220, 0.1)
        t.pv_power_w = int(get_int(223, 1.0)) if get_int(223, 1.0) is not None else None
        t.pv_charge_power_w = int(get_int(224, 1.0)) if get_int(224, 1.0) is not None else None
        t.pv_charge_current_a = get_int(234, 0.1)

        return t


###############################################################################
# High-level helpers
###############################################################################

def decode_read_response(slave_id: int, start_reg: int, reg_count: int, response_hex: str) -> List[int]:
    """
    Validate and decode a 0x03 read response from hex string -> list of u16 register values.
    'response_hex' may contain spaces.
    """
    payload = bytes.fromhex(response_hex.replace(' ', ''))
    _, data = _expect_read_response(slave_id, 0x03, payload, reg_count)
    return bytes_to_u16_list(data)


def parse_runtime_171_237(slave_id: int, response_hex: str) -> RuntimeTelemetry:
    """
    Convenience parser for the typical 171..237 block (67 registers).
    """
    regs = decode_read_response(slave_id, 171, 67, response_hex)
    return RuntimeTelemetry.parse_from_block(171, regs)


###############################################################################
# Utilities to expose hex frames
###############################################################################

def to_hex(frame: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in frame)


def build_runtime_read_frames(slave_id: int = 1) -> Dict[str, str]:
    """
    Return recommended read frames (hex strings) for common blocks.
    """
    frames: Dict[str, str] = {}
    frames['runtime_171_237'] = to_hex(build_read_holding(slave_id, 171, 67))
    frames['faults_warnings_100_109'] = to_hex(build_read_holding(slave_id, 100, 10))
    frames['settings_300_339'] = to_hex(build_read_holding(slave_id, 300, 40))
    frames['soc_currents_341_351'] = to_hex(build_read_holding(slave_id, 341, 11))
    frames['remote_406_426'] = to_hex(build_read_holding(slave_id, 406, 21))
    frames['version_626_644'] = to_hex(build_read_holding(slave_id, 626, 19))
    frames['faultlog_700_729'] = to_hex(build_read_holding(slave_id, 700, 30))
    return frames


class AnejiModbusProvider(InverterProvider):
    name = "aneji_modbus"

    def __init__(self, transport_send_bytes_callable, slave_id: int = 1):
        """
        transport_send_bytes_callable(frame_hex: str) -> str
        Должен принять hex запроса, вернуть hex ответа.
        """
        self._tx = transport_send_bytes_callable
        self._sid = slave_id

    async def probe(self) -> bool:
        try:
            frames = build_runtime_read_frames(self._sid)
            _ = await self._tx(frames["runtime_171_237"])
            return True
        except Exception:
            return False

    async def read_snapshot(self) -> CanonicalSnapshot:
        ts = time.time()
        frames = build_runtime_read_frames(self._sid)

        # читаем только «runtime_171_237» (MVP)
        resp_hex = await self._tx(frames["runtime_171_237"])
        telemetry = parse_runtime_171_237(self._sid, resp_hex)  # твой dataclass

        op = _map_work_mode(telemetry.work_mode)

        # Считаем «signed battery_current_a» по тем же правилам (+ заряд / – разряд)
        bat_i = telemetry.bat_current_a
        # Если протокол всегда даёт знак — оставим как есть.
        # Иначе можно учитывать power_flow.battery_state из твоей модели.

        snap = CanonicalSnapshot(
            ts=ts,
            model=telemetry.device_name,
            serial=telemetry.serial_number,
            fw=str(telemetry.protocol_number) if telemetry.protocol_number is not None else None,

            grid_voltage_v=telemetry.mains_voltage_v,
            grid_freq_hz=telemetry.mains_freq_hz,

            ac_out_voltage_v=telemetry.out_voltage_v,
            ac_out_freq_hz=telemetry.out_freq_hz,
            out_active_power_w=_fi(telemetry.out_active_power_w),
            out_apparent_power_va=_fi(telemetry.out_apparent_power_va),
            load_percent=_fi(telemetry.load_percent),

            battery_voltage_v=telemetry.bat_voltage_v,
            battery_current_a=bat_i,
            battery_soc_percent=_fi(telemetry.soc_percent),
            inverter_temp_c=telemetry.temp_inverter_c,

            pv_voltage_v=telemetry.pv_voltage_v,
            pv_current_a=telemetry.pv_current_a,
            pv_power_w=_fi(telemetry.pv_power_w),

            operating_mode=op,
            grid_input_power_w=_fi(telemetry.mains_power_w),  # в ANERN у тебя есть прямой mains_power_w

            raw={
                "anern_runtime_171_237": telemetry,  # dataclass, можно asdict() если удобнее
            }
        )
        return snap


def _fi(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _map_work_mode(mode: int | None) -> InverterOperatingMode:
    # Подстрой под свою спецификацию ANERN: 0..6
    m = {
        0: InverterOperatingMode.STANDBY,
        1: InverterOperatingMode.LINE,
        2: InverterOperatingMode.BATTERY,
        3: InverterOperatingMode.POWER_ON,  # пример, уточни по докам
        4: InverterOperatingMode.FAULT,
        5: InverterOperatingMode.UNKNOWN,
        6: InverterOperatingMode.UNKNOWN,
    }
    return m.get(mode, InverterOperatingMode.UNKNOWN)
