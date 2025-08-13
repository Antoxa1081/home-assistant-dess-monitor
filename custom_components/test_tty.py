import asyncio
import serial_asyncio

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
    return crc.to_bytes(2, byteorder='little')

def decode_qpigs(ascii_str: str) -> dict:
    """Parse QPIGS ASCII response string into dictionary with descriptive keys."""
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
            if f.is_integer():
                return int(f)
            return f
        except:
            return v

    parsed_values = list(map(parse_value, values))
    return dict(zip(fields, parsed_values))


class QPIGSProtocol(asyncio.Protocol):
    def __init__(self, on_response):
        self.transport = None
        self.buffer = bytearray()
        self.on_response = on_response

    def connection_made(self, transport):
        self.transport = transport
        print("Connection opened, sending QPIGS command...")
        # Prepare command with CRC and carriage return
        command = b'QPIGS'
        crc = crc16(command)
        packet = command + crc + b'\r'
        self.transport.write(packet)

    def data_received(self, data):
        self.buffer.extend(data)
        # Check if we have at least enough bytes for minimal response: data + CRC(2) + \r(1)
        if len(self.buffer) >= 5:
            # Try to find carriage return which marks end of response
            if b'\r' in self.buffer:
                # Split at \r
                idx = self.buffer.index(b'\r')
                response = self.buffer[:idx]
                remaining = self.buffer[idx+1:]
                self.buffer = remaining  # Keep remaining bytes for future

                # Process response
                asyncio.create_task(self.process_response(response))

    async def process_response(self, response: bytes):
        # Response format: ASCII data + 2 bytes CRC
        if len(response) < 3:
            print("Response too short:", response)
            self.transport.close()
            return

        data_part = response[:-2]
        received_crc = response[-2:]

        calc_crc = crc16(data_part)

        if calc_crc != received_crc:
            print(f"CRC mismatch! Expected: {calc_crc.hex()} Received: {received_crc.hex()}")
            self.transport.close()
            return

        try:
            decoded_str = data_part.decode('ascii').strip()
        except Exception as e:
            print("ASCII decoding error:", e)
            self.transport.close()
            return

        print("Decoded string:", decoded_str)

        decoded_data = decode_qpigs(decoded_str)
        print("Parsed data:")
        for key, val in decoded_data.items():
            print(f"  {key}: {val}")

        self.on_response()  # Signal completion
        self.transport.close()

    def connection_lost(self, exc):
        print("Connection closed.")
        asyncio.get_event_loop().stop()


async def main():
    loop = asyncio.get_running_loop()
    on_response_event = asyncio.Event()

    def on_response():
        on_response_event.set()

    # Create serial connection with our protocol
    transport, protocol = await serial_asyncio.create_serial_connection(
        loop, lambda: QPIGSProtocol(on_response),
        '/dev/ttyUSB0', baudrate=2400, bytesize=8, parity='N', stopbits=1, timeout=1
    )

    # Wait until response is processed or timeout after 5 seconds
    try:
        await asyncio.wait_for(on_response_event.wait(), timeout=5)
    except asyncio.TimeoutError:
        print("Timeout waiting for response.")
        transport.close()

if __name__ == '__main__':
    asyncio.run(main())
