"""Pytest coverage for the protocol codec layer.

Ported from the standalone ``tests/test_protocols_smoke.py`` runner into
proper pytest, reusing its known-good wire vectors. Covers the three
protocol adapters (Axpert, PI18, SMG-II Modbus), the CRC routines, the
status-bit parsers, the set-command builders, and the registry.
"""
from __future__ import annotations

import pytest

from custom_components.dess_monitor.api.protocols import (
    AxpertProtocol,
    Pi18Protocol,
    Smg2ModbusProtocol,
    default_registry,
)
from custom_components.dess_monitor.api.protocols.axpert import set_commands as axpert_set
from custom_components.dess_monitor.api.protocols.crc import (
    crc16_modbus,
    crc16_modbus_bytes,
    crc16_xmodem,
    crc16_xmodem_bytes,
)
from custom_components.dess_monitor.api.protocols.enums import (
    BatteryTypeSetting,
    ChargeSourcePrioritySetting,
    OutputSourcePrioritySetting,
)
from custom_components.dess_monitor.api.protocols.status_bits import (
    parse_device_status_bits_b7_b0,
    parse_device_status_bits_b10_b8,
)

# ---------------------------------------------------------------------------
# Helpers for building wire frames
# ---------------------------------------------------------------------------

def _build_modbus_response(unit_id: int, registers: list[int]) -> bytes:
    body = bytes([unit_id, 0x03, len(registers) * 2])
    for r in registers:
        body += bytes([(r >> 8) & 0xFF, r & 0xFF])
    return body + crc16_modbus_bytes(body)


def _build_pi18_response(body: str) -> bytes:
    """Wrap an ASCII payload in the ``^D<nnn>...<CRC><CR>`` envelope."""
    body_bytes = body.encode("ascii")
    length = len(body_bytes) + 3
    head = f"^D{length:03d}".encode("ascii") + body_bytes
    return head + crc16_xmodem_bytes(head) + b"\r"


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------

class TestCrc:
    XMODEM_CASES = {
        "QPIGS": 0xB7A9,
        "QPIRI": 0xF854,
        "QMOD": 0x49C1,
        "QPIWS": 0xB4DA,
        "QVFW": 0x6299,
        "QMCHGCR": 0xD855,
        "QMUCHGCR": 0x2634,
        "QFLAG": 0x9874,
        "QSID": 0xBB05,
        "QID": 0xD6EA,
        "QMN": 0xBB64,
    }

    @pytest.mark.parametrize("cmd,expected", list(XMODEM_CASES.items()))
    def test_xmodem_known_commands(self, cmd, expected):
        assert crc16_xmodem(cmd.encode("ascii")) == expected

    def test_xmodem_qpigs2_and_qbeqi(self):
        # The pre-refactor table held wrong CRCs for these two; pin the
        # proper computed XMODEM result so a polynomial regression is loud.
        assert crc16_xmodem(b"QPIGS2") == 0x682D
        assert crc16_xmodem(b"QBEQI") == 0x2EA9

    def test_xmodem_empty(self):
        assert crc16_xmodem(b"") == 0x0000

    def test_xmodem_bytes_is_big_endian(self):
        crc = crc16_xmodem(b"QPIGS")
        assert crc16_xmodem_bytes(b"QPIGS") == bytes([(crc >> 8) & 0xFF, crc & 0xFF])
        assert crc16_xmodem_bytes(b"QPIGS") == bytes([0xB7, 0xA9])

    def test_modbus_reference_vector(self):
        # Modbus RTU reference: read holding regs, addr=201, count=31, unit=1
        body = bytes([0x01, 0x03, 0x00, 0xC9, 0x00, 0x1F])
        assert crc16_modbus(body) == 0x3CD4

    def test_modbus_bytes_is_little_endian(self):
        body = bytes([0x01, 0x03, 0x00, 0xC9, 0x00, 0x1F])
        assert crc16_modbus_bytes(body) == bytes([0xD4, 0x3C])
        crc = crc16_modbus(body)
        assert crc16_modbus_bytes(body) == bytes([crc & 0xFF, (crc >> 8) & 0xFF])


# ---------------------------------------------------------------------------
# AxpertProtocol — encode
# ---------------------------------------------------------------------------

class TestAxpertEncode:
    def setup_method(self):
        self.axpert = AxpertProtocol()

    def test_encode_qpigs(self):
        assert self.axpert.encode("QPIGS") == bytes.fromhex("5150494753B7A90D")

    def test_encode_is_case_insensitive(self):
        assert self.axpert.encode("qpigs") == self.axpert.encode("QPIGS")

    def test_encode_appends_crc_and_cr(self):
        cmd = axpert_set.build_set_output_priority(OutputSourcePrioritySetting.SBU)
        assert cmd == "POP01"
        frame = self.axpert.encode(cmd)
        assert frame.endswith(b"\r")
        assert frame[:-3].decode("ascii") == "POP01"
        assert len(frame) == len("POP01") + 2 + 1

    def test_encode_crc_matches_payload(self):
        frame = self.axpert.encode("QPIGS")
        payload = frame[:-3]  # strip CRC (2) + CR (1)
        assert crc16_xmodem(payload) == (frame[-3] << 8) | frame[-2]


# ---------------------------------------------------------------------------
# AxpertProtocol — decode
# ---------------------------------------------------------------------------

class TestAxpertDecode:
    def setup_method(self):
        self.axpert = AxpertProtocol()

    def test_qpigs_fields(self):
        raw = (
            b"(231.8 50.0 231.8 50.0 0115 0016 002 408 27.00 012 095 0030 "
            b"0000 000.0 00.00 00000 00010101 00 00 00001 010\xff\xff\r"
        )
        out = self.axpert.decode("QPIGS", raw)
        assert out["grid_voltage"] == "231.8"
        assert out["grid_frequency"] == "50.0"
        assert out["battery_voltage"] == "27.00"
        assert out["battery_capacity"] == "095"
        assert out["device_status_bits_b7_b0"] == "00010101"
        assert "error" not in out and "status" not in out

    def test_qpiri_enum_mapping(self):
        raw = (
            b"(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 42.0 56.4 54.0 "
            b"2 30 060 0 1 2 9 01 0 0 54.0 0 1 480 0 000\xff\xff\r"
        )
        out = self.axpert.decode("QPIRI", raw)
        assert out["battery_type"] == "UserDefined"
        assert out["ac_input_voltage_range"] == "Appliance"
        assert out["output_source_priority"] == "SolarFirst"
        assert out["charger_source_priority"] == "SolarAndUtility"

    def test_qpigs2_three_field_pv(self):
        out = self.axpert.decode("QPIGS2", b"(02.5 245.6 1234\xff\xff\r")
        assert out == {
            "pv_current": "02.5",
            "pv_voltage": "245.6",
            "pv_daily_energy": "1234",
        }

    def test_qmod_operating_mode(self):
        out = self.axpert.decode("QMOD", b"(L\xff\xff\r")
        assert out == {"operating_mode": "Line"}

    @pytest.mark.parametrize("raw", [b"", b"null"])
    def test_empty_and_null_reply_errors(self, raw):
        out = self.axpert.decode("QPIGS", raw)
        assert out.get("error")

    def test_ack_nak_control_replies(self):
        ack = self.axpert.decode("POP01", b"(ACK\x39\x20\r")
        nak = self.axpert.decode("POP01", b"(NAK\xff\xff\r")
        assert ack == {"status": "ACK"}
        assert nak == {"status": "NAK"}


# ---------------------------------------------------------------------------
# Set-command builders
# ---------------------------------------------------------------------------

class TestAxpertSetBuilders:
    def test_priority_and_battery_codes(self):
        assert axpert_set.build_set_output_priority(
            OutputSourcePrioritySetting.UtilityFirst) == "POP00"
        assert axpert_set.build_set_output_priority(
            OutputSourcePrioritySetting.SBU) == "POP01"
        assert axpert_set.build_set_output_priority(
            OutputSourcePrioritySetting.SolarFirst) == "POP02"
        assert axpert_set.build_set_charge_source_priority(
            ChargeSourcePrioritySetting.SolarFirst) == "PCP01"
        assert axpert_set.build_set_battery_type(BatteryTypeSetting.AGM) == "PBT00"

    def test_voltage_and_current_formatting(self):
        assert axpert_set.build_set_battery_bulk_voltage(56.4) == "PBAV56.40"
        assert axpert_set.build_set_battery_float_voltage(54.0) == "PBFV54.00"
        assert axpert_set.build_set_rated_battery_voltage(48) == "PBRV48"
        assert axpert_set.build_set_max_combined_charge_current(60) == "MCHGC060"
        assert axpert_set.build_set_battery_charge_current(30) == "PBATC030"
        assert axpert_set.build_set_max_utility_charge_current(2) == "MUCHGC002"


# ---------------------------------------------------------------------------
# Status bits
# ---------------------------------------------------------------------------

class TestStatusBits:
    def test_b7_b0_named_flags(self):
        out = parse_device_status_bits_b7_b0("00010001")
        assert out["inverter_on"] is True
        assert out["line_fail"] is True
        assert out["fault"] is False
        assert out["_raw_b7_b0"] == "00010001"

    def test_b7_b0_fault_and_overload(self):
        out = parse_device_status_bits_b7_b0("10000010")
        assert out["fault"] is True
        assert out["inverter_overload"] is True
        assert out["inverter_on"] is False

    def test_b10_b8_charge_state(self):
        out = parse_device_status_bits_b10_b8("010")
        assert out["charging_ac_active"] is True
        assert out["charging_to_battery"] is False
        assert out["charging_scc_active"] is False

    def test_b10_b8_all_active(self):
        out = parse_device_status_bits_b10_b8("111")
        assert out["charging_to_battery"] is True
        assert out["charging_ac_active"] is True
        assert out["charging_scc_active"] is True

    def test_junk_input_is_clamped(self):
        assert parse_device_status_bits_b7_b0("xx10")["_raw_b7_b0"] == "00000010"
        assert parse_device_status_bits_b10_b8("")["_raw_b10_b8"] == "000"

    def test_extra_bits_are_truncated(self):
        # Only the first ``count`` valid bits are kept.
        out = parse_device_status_bits_b7_b0("1111111100")
        assert out["_raw_b7_b0"] == "11111111"


# ---------------------------------------------------------------------------
# Smg2ModbusProtocol
# ---------------------------------------------------------------------------

class TestSmg2Modbus:
    def setup_method(self):
        self.smg2 = Smg2ModbusProtocol(unit_id=1)

    def test_encode_read_frame(self):
        frame = self.smg2.encode("QPIGS")
        assert frame[:6] == bytes([0x01, 0x03, 0x00, 0xC9, 0x00, 0x1F])
        assert len(frame) == 8
        assert crc16_modbus(frame[:6]) == frame[6] | (frame[7] << 8)

    def test_encode_unsupported_command_raises(self):
        with pytest.raises(ValueError):
            self.smg2.encode("QFLAG")

    def test_decode_qpigs(self):
        regs = [0] * 31

        def setreg(addr, val):
            regs[addr - 201] = val & 0xFFFF

        setreg(202, 2305)
        setreg(210, 2300)
        setreg(213, 1500)
        setreg(215, 240)
        setreg(216, 25)
        setreg(220, 50)
        setreg(223, 1200)
        setreg(225, 30)

        out = self.smg2.decode("QPIGS", _build_modbus_response(1, regs))
        assert out["grid_voltage"] == "230.5"
        assert out["ac_output_voltage"] == "230.0"
        assert out["battery_voltage"] == "24.00"
        assert out["battery_charging_current"] == "025"
        assert out["battery_discharge_current"] == "00000"
        assert out["pv_charging_power"] == "01200"
        assert out["load_percent"] == "030"
        assert "bus_voltage" not in out

    def test_decode_qpiri_enums(self):
        regs = [0] * 38

        def setreg(addr, val):
            regs[addr - 300] = val & 0xFFFF

        setreg(301, 2)
        setreg(302, 1)
        setreg(331, 1)
        setreg(324, 568)
        setreg(332, 600)

        out = self.smg2.decode("QPIRI", _build_modbus_response(1, regs))
        assert out["output_source_priority"] == "SBU"
        assert out["ac_input_voltage_range"] == "UPS"
        assert out["charger_source_priority"] == "SolarFirst"
        assert out["bulk_charging_voltage"] == "56.8"
        assert out["max_charging_current"] == "060"

    def test_decode_qmod(self):
        regs = [0] * 31
        regs[201 - 201] = 2  # 'Mains' -> Line
        out = self.smg2.decode("QMOD", _build_modbus_response(1, regs))
        assert out == {"operating_mode": "Line"}

    def test_modbus_exception_response(self):
        body = bytes([0x01, 0x83, 0x02])  # illegal data address
        response = body + crc16_modbus_bytes(body)
        out = self.smg2.decode("QPIGS", response)
        assert "error" in out
        assert "0x02" in out["error"]

    def test_crc_mismatch_rejected(self):
        regs = [0] * 31
        response = _build_modbus_response(1, regs)
        corrupted = response[:-1] + bytes([response[-1] ^ 0xFF])
        out = self.smg2.decode("QPIGS", corrupted)
        assert out.get("error", "").lower().startswith("modbus crc")


# ---------------------------------------------------------------------------
# Pi18Protocol
# ---------------------------------------------------------------------------

class TestPi18:
    def setup_method(self):
        self.pi18 = Pi18Protocol()

    def test_encode_qpigs(self):
        frame = self.pi18.encode("QPIGS")
        assert frame.startswith(b"^P005GS")
        assert frame.endswith(b"\r")
        assert len(frame) == 10
        assert crc16_xmodem(frame[:-3]) == (frame[-3] << 8) | frame[-2]

    def test_encode_native_name(self):
        frame = self.pi18.encode("PI")
        assert frame.startswith(b"^P005PI")
        assert frame.endswith(b"\r")

    def test_encode_longer_command(self):
        frame = self.pi18.encode("QPIRI")
        assert frame.startswith(b"^P007PIRI")

    def test_decode_gs_multisection(self):
        body = (
            "2305,500,2300,500,1500,1500,030,2456,2456,0000,000,025,"
            "100,45,40,40,1200,0500,2400,1500,0,2,0,1,1,2,1,0"
        )
        out = self.pi18.decode("QPIGS", _build_pi18_response(body))

        qpigs = out["qpigs"]
        assert qpigs["grid_voltage"] == "230.5"
        assert qpigs["grid_frequency"] == "50.0"
        assert qpigs["ac_output_voltage"] == "230.0"
        assert qpigs["battery_voltage"] == "245.60"
        assert qpigs["battery_charging_current"] == "025"
        assert qpigs["battery_discharge_current"] == "00000"
        assert qpigs["pv_charging_power"] == "01200"
        assert qpigs["pv_input_voltage"] == "240.0"
        assert qpigs["load_percent"] == "030"
        assert qpigs["pv_input_current"] == "5.0"
        assert "bus_voltage" not in qpigs

        qpigs2 = out["qpigs2"]
        assert qpigs2["pv_voltage"] == "150.0"
        assert qpigs2["pv_current"].startswith("3.")

    def test_decode_piri_threshold_swap(self):
        body = (
            "2300,260,2300,500,260,6000,6000,480,480,530,420,565,565,"
            "2,2,100,0,1,2,9,0,0,0,1,1"
        )
        out = self.pi18.decode("QPIRI", _build_pi18_response(body))
        assert out["battery_type"] == "UserDefined"
        assert out["ac_input_voltage_range"] == "Appliance"
        assert out["output_source_priority"] == "SBU"
        assert out["charger_source_priority"] == "OnlySolar"
        assert out["bulk_charging_voltage"] == "56.5"
        assert out["max_charging_current"] == "100"
        assert out["low_battery_to_ac_bypass_voltage"] == "48.0"
        assert out["high_battery_voltage_to_battery_mode"] == "53.0"
        for key in ("reserved_uu", "reserved_v", "reserved_b", "reserved_ccc"):
            assert key not in out

    def test_decode_piri_drops_blank_enums(self):
        body = (
            "2300,260,2300,500,260,6000,6000,480,480,530,420,565,565,"
            ",2,100,,,,9,0,0,0,1,1"
        )
        out = self.pi18.decode("QPIRI", _build_pi18_response(body))
        for key in (
            "battery_type",
            "ac_input_voltage_range",
            "output_source_priority",
            "charger_source_priority",
        ):
            assert key not in out

    @pytest.mark.parametrize("code,expected", [
        ("00", "PowerOn"),
        ("01", "Standby"),
        ("02", "Line"),
        ("03", "Battery"),
        ("04", "Fault"),
        ("05", "Line"),
    ])
    def test_decode_mod_codes(self, code, expected):
        out = self.pi18.decode("QMOD", _build_pi18_response(code))
        assert out == {"operating_mode": expected}

    def test_decode_ack_nak_markers(self):
        ack = self.pi18.decode("POPM", b"^1\xab\xcd\r")
        nak = self.pi18.decode("POPM", b"^0\xab\xcd\r")
        assert ack == {"status": "ACK"}
        assert nak == {"status": "NAK"}

    @pytest.mark.parametrize("raw", [b"", b"null"])
    def test_decode_empty_and_null_errors(self, raw):
        assert self.pi18.decode("QPIGS", raw).get("error")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_resolves_by_name(self):
        assert isinstance(default_registry.get("axpert"), AxpertProtocol)
        assert isinstance(default_registry.get("smg2_modbus"), Smg2ModbusProtocol)
        assert isinstance(default_registry.get("pi18"), Pi18Protocol)

    def test_unknown_name_falls_back_to_axpert(self):
        assert isinstance(default_registry.get("does-not-exist"), AxpertProtocol)
