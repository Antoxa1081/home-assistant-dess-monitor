import struct
import json

# -----------------------------------------------------------------------------
# CRC16 (Modbus RTU) calculation function
# -----------------------------------------------------------------------------
def calculate_crc16(data: bytes) -> int:
    """
    Рассчитывает CRC16 для Modbus RTU (полином 0xA001).
    Возвращает 16-битное значение CRC.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc

# -----------------------------------------------------------------------------
# Описание регистров согласно документации PDF
# Ключ: номер регистра (десятичный)
# Значение: (имя, тип, масштаб, количество регистров)
# Типы: 'UInt', 'Int', 'ULong', 'ASCII'
# -----------------------------------------------------------------------------
REGISTER_DEFINITIONS = {
    100: ("Fault Code",                    "ULong", 1, 2),
    108: ("Warning Code",                  "ULong", 1, 2),
    186: ("Series Number",                 "ASCII",  1,12),
    201: ("Working Mode",                  "UInt",   1, 1),
    202: ("Effective Mains Voltage",       "Int",   10, 1),
    203: ("Mains Frequency",               "Int",  100, 1),
    204: ("Average Mains Power",           "Int",    1, 1),
    205: ("Affective Inverter Voltage",    "Int",   10, 1),
    206: ("Affective Inverter Current",    "Int",   10, 1),
    207: ("Inverter Frequency",            "Int",  100, 1),
    208: ("Average Inverter Power",        "Int",    1, 1),
    209: ("Inverter Charging Power",       "Int",    1, 1),
    210: ("Output Effective Voltage",      "Int",   10, 1),
    211: ("Output Effective Current",      "Int",   10, 1),
    212: ("Output Frequency",              "Int",  100, 1),
    213: ("Output Active Power",           "Int",    1, 1),
    214: ("Output Apparent Power",         "Int",    1, 1),
    215: ("Battery Average Voltage",       "Int",   10, 1),
    216: ("Battery Average Current",       "Int",   10, 1),
    217: ("Battery Average Power",         "Int",    1, 1),
    219: ("PV Average Voltage",            "Int",   10, 1),
    220: ("PV Average Current",            "Int",   10, 1),
    223: ("PV Average Power",              "Int",    1, 1),
    224: ("PV Charging Avg Power",         "Int",    1, 1),
    225: ("Load Percentage",               "UInt",   1, 1),
    226: ("DCDC Temperature",              "Int",    1, 1),
    227: ("Inverter Temperature",          "Int",    1, 1),
    229: ("Battery Percentage",            "UInt",   1, 1),
    230: ("Invalid Data",                  "UInt",   1, 1),
    232: ("Battery Avg Current (Detail)",  "Int",   10, 1),
    233: ("Inverter Charging Avg Current","Int",   10, 1),
    234: ("PV Charging Avg Current",       "Int",   10, 1),
    300: ("Output Mode",                   "UInt",   1, 1),
    301: ("Output Priority",               "UInt",   1, 1),
    302: ("Input Voltage Range",           "UInt",   1, 1),
    303: ("Buzzer Mode",                   "UInt",   1, 1),
    305: ("LCD Backlight",                 "UInt",   1, 1),
    306: ("LCD Return Mode",               "UInt",   1, 1),
    307: ("Energy-Saving Mode",            "UInt",   1, 1),
    308: ("Overload Auto-Restart",         "UInt",   1, 1),
    309: ("Over Temp Auto-Restart",        "UInt",   1, 1),
    310: ("Overload Transfer to Bypass",   "UInt",   1, 1),
    313: ("Battery Eq Mode",               "UInt",   1, 1),
    320: ("Output Voltage Setting",        "Int",   10, 1),
    321: ("Output Frequency Setting",      "Int",  100, 1),
    322: ("Battery Type",                  "UInt",   1, 1),
    323: ("Battery Overvoltage Prot",      "Int",   10, 1),
    324: ("Max Charging Voltage",          "Int",   10, 1),
    325: ("Floating Charging Voltage",     "Int",   10, 1),
    326: ("Battery Discharge Recovery",    "Int",   10, 1),
    327: ("Battery Low Volt Prot (Mains)", "Int",   10, 1),
    329: ("Battery Low Volt Prot (Off-Grid)","Int", 10, 1),
    331: ("Battery Charging Priority",     "UInt",   1, 1),
    332: ("Max Charging Current",          "Int",   10, 1),
    333: ("Max Mains Charging Current",    "Int",   10, 1),
    334: ("Eq Charging Voltage",           "Int",   10, 1),
    335: ("BAT EQ Time (min)",             "Int",    1, 1),
    336: ("Eq Timeout Exit (min)",         "Int",    1, 1),
    337: ("Two Eq Intervals",              "Int",    1, 1),
    338: ("Reserve",                       "UInt",   1, 1),
    339: ("Reserve",                       "UInt",   1, 2),
    389: ("Reserve",                       "UInt",   1, 3),
    600: ("Reserve",                       "UInt",   1, 8),
    630: ("Output Voltage Setpoint 3Ph",   "Int",   10,15),
    646: ("Battery Overvoltage Prot Det",  "Int",   10, 3),
    650: ("Max Currents/Settings",         "Int",   10, 6),
    677: ("Battery EQ Details",            "Int",   10, 8),
    689: ("Turn-On & Remote Switch",       "UInt",   1, 2),
    693: ("Exit Fault Mode",               "UInt",   1, 2),
    696: ("Rated Power (W)",               "UInt",   1, 9),
}

# -----------------------------------------------------------------------------
# Список «человекочитаемых» запросов: (start_address, register_count)
# -----------------------------------------------------------------------------
human_readable_requests = [
    (0x0064,  2),   # Fault Code (100..101)
    (0x006C,  2),   # Warning Code (108..109)
    (0x00AB,  1),   # Reserve (171)
    (0x00B8,  1),   # Invalid Data (184)
    (0x00BA, 13),   # Series Number (186..198)
    (0x00C9,  1),   # Working Mode (201)
    (0x00CB,  1),   # Effective Mains Voltage (203)
    (0x00CE,  1),   # Mains Frequency (206)
    (0x00E3,  1),   # Inverter Frequency (227)
    (0x00E6,  2),   # Average Inverter Power (230..231)
    (0x00FD,  1),   # Inverter Charging Power (253)
    (0x0115,  5),   # Output V, I, f, p (277..281)
    (0x012E,  4),   # PV V, I, p (302..305)
    (0x0152,  1),   # Load Percentage (338)
    (0x0154,  1),   # DCDC Temperature (340)
    (0x0156,  3),   # Inverter Temp, Battery % (342..344)
    (0x015A,  8),   # Battery Volt, Curr, Power… (346..353)
    (0x0185,  3),   # Reserve (389..391)
    (0x0258,  8),   # Reserve (600..607)
    (0x0276, 15),   # Reserve (630..644)
    (0x0286,  3),   # Reserve (646..648)
    (0x028A,  6),   # Reserve (650..655)
    (0x02A5,  8),   # Reserve (677..684)
    (0x02B1,  2),   # Turn-On & Remote Switch (689..690)
    (0x02B5,  2),   # Exit Fault Mode (693..694)
    (0x02B8,  9),   # Rated Power (W) (696..704)
]

# -----------------------------------------------------------------------------
# Функция строит Modbus RTU кадр для чтения "Read Holding Registers" (функция 0x03)
# -----------------------------------------------------------------------------
def build_modbus_request(slave_id: int, start_address: int, register_count: int) -> bytes:
    """
    Формирует PDU + CRC16-байты для Modbus RTU (функция 0x03 Read Holding Registers).
      - slave_id      : адрес устройства (1..247)
      - start_address : начальный адрес регистра (0..)
      - register_count: количество регистров для чтения
    Возвращает: полный кадр (6 байт PDU + 2 байта CRC16).
    """
    # PDU: [Slave ID][Func=0x03][Addr Hi][Addr Lo][Count Hi][Count Lo]
    pdu = struct.pack(">B B H H", slave_id, 0x03, start_address, register_count)
    crc = calculate_crc16(pdu)
    # CRC в порядке LSb, MSb
    crc_bytes = struct.pack("<H", crc)
    return pdu + crc_bytes

# -----------------------------------------------------------------------------
# Функция собирает один «объединённый» запрос, склеивая все кадры подряд
# -----------------------------------------------------------------------------
def build_combined_modbus_query(slave_id: int, requests: list) -> bytes:
    """
    Принимает:
      - slave_id : адрес устройства (один и тот же для всех запросов)
      - requests : список (start_address, register_count)
    Возвращает: единый bytes, содержащий все Modbus RTU-кадры подряд.
    """
    combined = bytearray()
    for start_addr, count in requests:
        frame = build_modbus_request(slave_id, start_addr, count)
        combined.extend(frame)
    return bytes(combined)

# -----------------------------------------------------------------------------
# Функция разбора «сырых» байтов ответа Modbus RTU (несколько кадров подряд)
# Возвращает словарь: { 'Field Name': value, ... }
# -----------------------------------------------------------------------------
def parse_modbus_response(raw_bytes: bytes) -> dict:
    """
    Разбирает байты, которые вернуло устройство Modbus RTU, отвечая на серию запросов.
    Возвращает Python-словарь, где ключи — понятные имена полей, а значения
    — уже приведённые к нужному типу (с масштабированием, ASCII-декодом и т.п.).
    """
    def _unpack_ulong(vals):
        # Объединяет два 16-битных слова в 32-бит беззнаковое
        hi_word, lo_word = vals
        return (hi_word << 16) | lo_word

    def _unpack_ascii(vals):
        # Каждое 16-бит слово → два байта → символы ASCII (0x00 пропускаем)
        chars = []
        for word in vals:
            hi = (word >> 8) & 0xFF
            lo = word & 0xFF
            if hi != 0:
                chars.append(chr(hi))
            if lo != 0:
                chars.append(chr(lo))
        return "".join(chars)

    results = {}
    idx = 0
    req_idx = 0

    while idx < len(raw_bytes) - 4:
        # Ищём заголовок очередного кадра: [Slave ID=0x01][Func=0x03]
        if raw_bytes[idx] == 0x01 and raw_bytes[idx + 1] == 0x03:
            byte_count = raw_bytes[idx + 2]
            frame_len = 3 + byte_count + 2  # ID(1) + Func(1) + Count(1) + Data(N) + CRC(2)
            frame = raw_bytes[idx : idx + frame_len]

            # Проверяем CRC
            payload = frame[:-2]
            received_crc = (frame[-2] << 8) | frame[-1]
            calc_crc = calculate_crc16(payload)
            crc_ok = (received_crc == calc_crc)
            # Если хотите, можете логировать crc_ok == False

            data = frame[3 : 3 + byte_count]

            # Сопоставляем этот кадр с запросом из списка (по порядку)
            if req_idx < len(human_readable_requests):
                start_addr, reg_count = human_readable_requests[req_idx]
            else:
                start_addr, reg_count = (None, None)

            # Каждый регистр = 2 байта → собираем список 16-бит значений
            values = []
            for r in range(reg_count):
                hi = data[2*r]
                lo = data[2*r + 1]
                values.append((hi << 8) | lo)

            # Обрабатываем в соответствии с REGISTER_DEFINITIONS
            offset = 0
            while offset < reg_count:
                reg_addr = start_addr + offset
                if reg_addr in REGISTER_DEFINITIONS:
                    name, dtype, scale, nregs = REGISTER_DEFINITIONS[reg_addr]
                    if dtype == "ULong":
                        # Берём два регистра (nregs=2)
                        raw_val = _unpack_ulong(values[offset : offset + nregs])
                        results[name] = raw_val
                    elif dtype == "Int":
                        raw_val = values[offset]
                        # Распознаём signed 16-bit
                        if raw_val & 0x8000:
                            raw_val = -((~raw_val & 0xFFFF) + 1)
                        results[name] = raw_val / scale
                    elif dtype == "UInt":
                        results[name] = values[offset] / scale
                    elif dtype == "ASCII":
                        results[name] = _unpack_ascii(values[offset : offset + nregs])
                    else:
                        results[name] = values[offset]
                    offset += nregs
                else:
                    # Нет описания для этого адреса
                    results[f"Raw_{reg_addr}"] = values[offset]
                    offset += 1

            idx += frame_len
            req_idx += 1
        else:
            idx += 1

    return results

# -----------------------------------------------------------------------------
# Пример использования (генерация запроса + разбор ответа)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Сгенерировать объединённый Modbus RTU-запрос
    slave_id = 0x01
    combined_query = build_combined_modbus_query(slave_id, human_readable_requests)

    print("=== Combined Modbus RTU Query (RAW bytes) ===")
    print(combined_query)

    print("\n=== Combined Modbus RTU Query (HEX) ===")
    print(" ".join(f"{b:02X}" for b in combined_query))

    # 2. Допустим, мы получили ответный поток (raw_response_hex)
    raw_response_hex = """
    01 03 04 00 00 00 00 FA 33 01 03 04 00 00 00 09 3A 35 01 03 02 73 00 9D 74 
    01 03 02 00 03 F8 45 01 03 1A 39 32 42 33 32 35 30 31 31 30 30 34 36 36 00 
    00 00 00 00 00 00 00 00 00 12 51 9C C5 01 03 02 00 03 F8 45 01 03 02 00 00 
    B8 44 01 03 02 00 00 B8 44 01 03 02 13 89 74 D2 01 03 04 00 00 00 24 FA 28 
    01 03 02 13 89 74 D2 01 03 0A 02 2E 00 00 00 00 00 64 00 1C 10 CB 01 03 08 
    00 6F 00 00 00 00 00 1D CA D8 01 03 02 00 00 B8 44 01 03 02 00 00 B8 44 
    01 03 06 08 FB 00 24 00 1C 84 2B 01 03 10 08 FB 00 05 00 16 00 72 00 01 11 
    FF 00 00 00 00 65 A6 01 03 06 11 F3 00 02 00 7C 86 00 01 03 10 00 00 00 02 
    00 02 00 00 00 00 00 02 08 FC 13 88 5E 65 01 03 1E 00 02 02 76 00 03 00 00 
    00 00 00 00 00 03 02 2E 02 2E 00 00 04 B0 02 58 00 00 01 FE 01 F4 A5 47 01 
    03 06 01 E0 00 32 00 5F 40 85 01 03 0C 00 14 00 00 02 48 00 3C 00 78 00 1E 
    CB 49 01 03 10 00 01 00 03 00 01 00 00 00 00 00 01 00 01 00 01 89 A6 01 03 
    04 00 00 00 00 FA 33 01 03 04 00 00 00 01 3B F3 01 03 12 07 E9 00 01 00 1D 
    00 04 00 39 00 0A 00 7A 00 00 06 02 EA 44
    """
    raw_bytes = bytes(int(b, 16) for b in raw_response_hex.strip().split())

    # 3. Разобрать ответ в удобную структуру
    parsed_data = parse_modbus_response(raw_bytes)
    print("\n=== Parsed Response Data (JSON) ===")
    print(json.dumps(parsed_data, indent=4, ensure_ascii=False))
