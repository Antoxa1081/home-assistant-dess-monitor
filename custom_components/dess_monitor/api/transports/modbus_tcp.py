"""Modbus RTU-over-TCP transport.

Opens a plain TCP connection, ships the pre-built RTU frame supplied by
the protocol, and reads the reply by walking RTU framing rules — no
external library, no ``pymodbus``.

Device dict expectations: ``{"host": str, "port": int, ...}``. Anything
else (devcode/pn/sn from the cloud schema) is ignored.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from .base import DirectTransport

DEFAULT_TIMEOUT = 30.0


class ModbusTcpTransport(DirectTransport):
    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    async def send(self, device_data: Mapping[str, Any], frame: bytes) -> bytes:
        host = device_data.get("host")
        port = device_data.get("port")
        if not host or not port:
            raise ValueError("ModbusTcpTransport requires 'host' and 'port' in device_data")

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)), timeout=self._timeout
        )
        try:
            writer.write(frame)
            await writer.drain()

            # RTU framing: [unit][func][...]. We need the function byte to know
            # whether this is a normal or exception reply, then read the rest.
            header = await asyncio.wait_for(reader.readexactly(2), timeout=self._timeout)
            func = header[1]

            if func & 0x80:
                # Exception: 1 byte error code + 2 byte CRC.
                tail = await asyncio.wait_for(reader.readexactly(3), timeout=self._timeout)
                return bytes(header) + tail

            # Normal read response (function 0x03/0x04): 1 byte byte_count, then
            # ``byte_count`` data bytes, then 2 byte CRC.
            bc_byte = await asyncio.wait_for(reader.readexactly(1), timeout=self._timeout)
            byte_count = bc_byte[0]
            payload_and_crc = await asyncio.wait_for(
                reader.readexactly(byte_count + 2), timeout=self._timeout
            )
            return bytes(header) + bytes(bc_byte) + payload_and_crc
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
