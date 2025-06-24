from enum import Enum


def decode_ascii_response(hex_string):
    hex_values = hex_string.strip().split()
    byte_values = bytes(int(b, 16) for b in hex_values)
    ascii_str = byte_values.decode('ascii', errors='ignore').strip()
    if ascii_str.startswith('('):
        ascii_str = ascii_str[1:]
    return ascii_str


def decode_qpigs(ascii_str):
    values = ascii_str.split()
    fields = [
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
        "reserved_cccc"
    ]
    return dict(zip(fields, values))


def decode_qpigs2(ascii_str):
    values = ascii_str.split()
    fields = [
        "pv_current",
        "pv_voltage",
        "pv_daily_energy"
    ]
    return dict(zip(fields, values))


class BatteryType(Enum):
    AGM = '0'
    Flooded = '1'
    UserDefined = '2'
    LIB = '3'
    LIC = '4'
    RESERVED = '5'
    RESERVED_1 = '6'
    RESERVED_2 = '7'


class ACInputVoltageRange(Enum):
    Appliance = '0'
    UPS = '1'


class OutputSourcePriority(Enum):
    UtilityFirst = '0'  # сеть
    SolarFirst = '1'
    SBU = '2'  # Solar → Battery → Utility
    BatteryOnly = '4'
    UtilityOnly = '5'
    SolarAndUtility = '6'
    Smart = '7'  # может быть задан в некоторых прошивках


class ChargerSourcePriority(Enum):
    UtilityFirst = '0'
    SolarFirst = '1'
    SolarAndUtility = '2'
    OnlySolar = '3'


class ParallelMode(Enum):
    Master = '0'
    Slave = '1'
    Standalone = '2'


class OperatingMode(Enum):
    PowerOn = 'P'  # Power On — The inverter is powered on and operational
    Standby = 'S'  # Standby — The inverter is in standby mode (e.g., no active load)
    Line = 'L'  # Line (Bypass) — Operating from utility/grid power, possibly bypassing the inverter
    Battery = 'B'  # Battery Inverter Mode — Operating from battery via inverter
    ShutdownApproaching = 'D'  # Shutdown Approaching — Critical state, preparing to shut down
    Fault = 'F'  # Fault — Error condition; inverter is in fault mode


def transform_qpiri_value(index, value):
    try:
        match index:
            case 12:
                return BatteryType(value).name
            case 15:
                return ACInputVoltageRange(value).name
            case 16:
                return OutputSourcePriority(value).name
            case 17:
                return ChargerSourcePriority(value).name
            case 21:
                return ParallelMode(value).name
            case _:
                return value
    except ValueError:
        return value


def decode_qpiri(ascii_str):
    values = ascii_str.split()
    fields = [
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
        "reserved_uu",
        "reserved_v",
        "parallel_mode",
        "high_battery_voltage_to_battery_mode",
        "solar_work_condition_in_parallel",
        "solar_max_charging_power_auto_adjust",
        "rated_battery_capacity",
        "reserved_b",
        "reserved_ccc"
    ]

    return {
        field: transform_qpiri_value(i, value)
        for i, (field, value) in enumerate(zip(fields, values))
    }


def decode_qmod(ascii_str):
    mode_code = ascii_str.strip()[0]
    try:
        mode = OperatingMode(mode_code)
    except ValueError:
        mode = "Unknown"
    return {"operating_mode": mode}


def decode_qmn(ascii_str):
    return {"Model": ascii_str.strip()}


def decode_qid(ascii_str):
    return {"Device ID": ascii_str.strip()}


def decode_qflag(ascii_str):
    return {"Enabled/Disabled Flags": ascii_str.strip()}


def decode_qvfw(ascii_str):
    return {"Firmware Version": ascii_str.replace("VERFW:", "").strip()}


def decode_qbeqi(ascii_str):
    values = ascii_str.split()
    fields = [
        "equalization_function",
        "equalization_time",  # (min)
        "interval_days",
        "max_charging_current",
        "float_voltage",
        "reserved_1",
        "equalization_timeout",  # (min)
        "immediate_activation_flag",
        "elapsed_time"  # (min)
    ]
    return dict(zip(fields, values))

def resolve_grid_input_power(qpigs: dict, qpiri: dict) -> float:
    try:
        status_bits = qpigs["device_status_bits_b7_b0"]
        output_power = float(qpigs["output_active_power"])
        charge_current = float(qpigs["battery_charging_current"])
        bulk_voltage = float(qpiri["bulk_charging_voltage"])
    except (KeyError, ValueError):
        return 0.0

    # B2 = line mode, B1 = bypass mode (нумерация: B7 слева, B0 справа)
    is_line_mode = status_bits[5] == '1'
    is_bypass_mode = status_bits[6] == '1'
    is_grid_mode = is_line_mode or is_bypass_mode

    if not is_grid_mode:
        return 0.0

    battery_charge_power = charge_current * bulk_voltage
    return output_power + battery_charge_power


# Тестовый универсальный декодер
def decode_direct_response(command: str, hex_input: str) -> dict:
    if hex_input == 'null':
        return {"error": "null response received. Command not accepted."}
    ascii_str = decode_ascii_response(hex_input)

    if ascii_str.startswith("NAK") or "NAK" in ascii_str:
        return {"error": "NAK response received. Command not accepted."}

    match command.upper():
        case "QPIGS":
            return decode_qpigs(ascii_str)
        case "QPIGS2":
            return decode_qpigs2(ascii_str)
        case "QPIRI":
            return decode_qpiri(ascii_str)
        case "QMOD":
            return decode_qmod(ascii_str)
        case "QMN":
            return decode_qmn(ascii_str)
        case "QID" | "QSID":
            return decode_qid(ascii_str)
        case "QFLAG":
            return decode_qflag(ascii_str)
        case "QVFW":
            return decode_qvfw(ascii_str)
        case "QBEQI":
            return decode_qbeqi(ascii_str)
        case _:
            return {"Raw": ascii_str}


direct_commands = {
    "QPIGS": "51 50 49 47 53 B7 A9 0D",
    "QPIGS2": "51 50 49 47 53 32 2B 8A 0D",
    "QPIRI": "51 50 49 52 49 F8 54 0D",
    "QMOD": "51 4D 4F 44 49 C1 0D",
    "QPIWS": "51 50 49 57 53 B4 DA 0D",
    "QVFW": "51 56 46 57 62 99 0D",
    "QMCHGCR": "51 4D 43 48 47 43 52 D8 55 0D",
    "QMUCHGCR": "51 4D 55 43 48 47 43 52 26 34 0D",
    "QFLAG": "51 46 4C 41 47 98 74 0D",
    "QSID": "51 53 49 44 BB 05 0D",
    "QID": "51 49 44 D6 EA 0D",
    "QMN": "51 4D 4E BB 64 0D",
    "QBEQI": "51 42 45 51 49 31 6B 0D",  # CRC может отличаться в зависимости от устройства
}


def get_command_hex(command_name: str) -> str:
    return direct_commands.get(command_name.upper(), "Unknown command")


# Функция поиска команды по HEX
def get_command_name_by_hex(hex_string: str) -> str:
    normalized_input = hex_string.strip().upper().replace("  ", " ")
    for name, hex_cmd in direct_commands.items():
        if normalized_input == hex_cmd.upper():
            return name
    return "Unknown HEX command"

# # Пример вызова:
# hex_data = "28 32 33 31 2E 38 20 35 30 2E 30 20 32 33 31 2E 38 20 35 30 2E 30 20 30 31 31 35 20 30 30 31 36 20 30 30 32 20 34 30 38 20 32 37 2E 30 30 20 30 31 32 20 30 39 35 20 30 30 33 30 20 30 30 30 30 20 30 30 30 2E 30 20 30 30 2E 30 30 20 30 30 30 30 30 20 30 30 30 31 30 31 30 31 20 30 30 20 30 30 20 30 30 30 30 31 20 30 31 30 9E CA 0D"
# decoded = decode_direct_response('QPIGS2', hex_data)
#
# for key, value in decoded.items():
#     print(f"{key:35} : {value}")
