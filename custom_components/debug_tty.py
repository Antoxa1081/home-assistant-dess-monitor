import serial
import time

def crc16(data: bytes) -> bytes:
    """Calculate Modbus CRC16 (polynomial 0xA001)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    # Return CRC as 2 bytes in little-endian order
    return crc.to_bytes(2, byteorder='little')

def decode_qpigs(ascii_str: str) -> dict:
    """Parse QPIGS ASCII response string into a dictionary with meaningful keys."""
    values = ascii_str.strip().split()
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

    def parse_value(v):
        try:
            f = float(v)
            # Convert to int if no fractional part
            if f.is_integer():
                return int(f)
            return f
        except:
            # Return original if cannot convert to number
            return v

    parsed_values = list(map(parse_value, values))
    return dict(zip(fields, parsed_values))

def main():
    port = '/dev/ttyUSB0'      # Serial port device
    baudrate = 2400            # Baud rate (common for these devices)
    timeout = 1                # Read timeout in seconds

    with serial.Serial(port, baudrate=baudrate, timeout=timeout) as ser:
        command = b'QPIGS'                     # Command to request status
        crc = crc16(command)                   # Calculate CRC16 of command
        packet = command + crc + b'\r'         # Full packet = command + CRC + carriage return
        ser.write(packet)                      # Send packet to device

        time.sleep(0.3)                        # Wait briefly for response

        response = ser.read(100)               # Read up to 100 bytes from serial
        if len(response) < 5:
            print("Response too short:", response)
            return

        # Assume response structure: data ASCII + 2 bytes CRC + carriage return
        data_part = response[:-3]              # Data part without CRC and \r
        received_crc = response[-3:-1]         # CRC bytes from response

        calc_crc = crc16(data_part)            # Calculate CRC16 from received data

        if calc_crc != received_crc:
            print(f"CRC check failed! Expected: {calc_crc.hex()} Received: {received_crc.hex()}")
            return

        try:
            decoded_str = data_part.decode('ascii').strip()  # Decode ASCII data string
        except Exception as e:
            print("ASCII decoding error:", e)
            return

        print("Decoded string:", decoded_str)

        decoded_data = decode_qpigs(decoded_str)   # Parse string into structured dict
        for key, val in decoded_data.items():
            print(f"{key}: {val}")

if __name__ == '__main__':
    main()
