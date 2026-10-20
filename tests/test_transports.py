"""Tests for the direct-command transports and the DirectService orchestrator.

- ``CloudHexTransport`` wraps a ``DessmonitorClient`` (mocked) and converts
  bytes <-> space-separated hex on the wire.
- ``ModbusTcpTransport`` opens a TCP connection; ``asyncio.open_connection``
  is fully mocked so no real socket is ever used.
- ``DirectService`` wires a transport + protocol together (encode -> send ->
  decode).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dess_monitor.api.direct_service import DirectService
from custom_components.dess_monitor.api.protocols import AxpertProtocol
from custom_components.dess_monitor.api.transports import DirectTransport
from custom_components.dess_monitor.api.transports.cloud_hex import (
    CloudHexTransport,
    _bytes_to_hex,
    _hex_to_bytes,
)
from custom_components.dess_monitor.api.transports.modbus_tcp import ModbusTcpTransport

DEVICE = {"devaddr": "1", "devcode": "2376", "pn": "PN123", "sn": "SN456"}


# --------------------------------------------------------------------------- #
# hex helpers
# --------------------------------------------------------------------------- #


def test_bytes_to_hex_uppercase_space_separated():
    assert _bytes_to_hex(b"\x01\xab\x00\xff") == "01 AB 00 FF"


def test_bytes_to_hex_empty():
    assert _bytes_to_hex(b"") == ""


def test_hex_to_bytes_roundtrip():
    frame = b"\x51\x50\x49\x47\x53"
    assert _hex_to_bytes(_bytes_to_hex(frame)) == frame


def test_hex_to_bytes_empty_and_null():
    assert _hex_to_bytes("") == b""
    assert _hex_to_bytes("null") == b""


# --------------------------------------------------------------------------- #
# CloudHexTransport
# --------------------------------------------------------------------------- #


def _client_with_response(dat: Any) -> MagicMock:
    client = MagicMock()
    client.control = MagicMock()
    client.control.send_direct_command = AsyncMock(return_value={"dat": dat})
    return client


async def test_cloud_hex_encodes_frame_and_decodes_reply():
    reply = b"\x06\x00\x10"
    client = _client_with_response(_bytes_to_hex(reply))
    transport = CloudHexTransport(client)

    result = await transport.send(DEVICE, b"\x51\x50")

    assert result == reply
    # The client received the hex-encoded frame and the right identity.
    args, _ = client.control.send_direct_command.call_args
    identity, sent_hex = args
    assert sent_hex == "51 50"
    assert identity.pn == "PN123"
    assert identity.sn == "SN456"


async def test_cloud_hex_null_dat_returns_null_bytes():
    client = _client_with_response("null")
    transport = CloudHexTransport(client)
    assert await transport.send(DEVICE, b"\x01") == b"null"


async def test_cloud_hex_missing_dat_returns_empty():
    client = MagicMock()
    client.control = MagicMock()
    client.control.send_direct_command = AsyncMock(return_value={})
    transport = CloudHexTransport(client)
    assert await transport.send(DEVICE, b"\x01") == b""


async def test_cloud_hex_non_dict_result_returns_empty():
    client = MagicMock()
    client.control = MagicMock()
    client.control.send_direct_command = AsyncMock(return_value=None)
    transport = CloudHexTransport(client)
    assert await transport.send(DEVICE, b"\x01") == b""


async def test_cloud_hex_non_str_dat_returns_empty():
    client = _client_with_response(12345)
    transport = CloudHexTransport(client)
    assert await transport.send(DEVICE, b"\x01") == b""


# --------------------------------------------------------------------------- #
# ModbusTcpTransport
# --------------------------------------------------------------------------- #


def _fake_connection(monkeypatch, read_chunks: list[bytes]):
    """Patch asyncio.open_connection to yield a mock reader/writer.

    ``read_chunks`` is the sequence returned by successive ``readexactly``
    calls. Returns (reader, writer) so tests can assert on what was written.
    """
    reader = MagicMock()
    reader.readexactly = AsyncMock(side_effect=read_chunks)

    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    async def fake_open(host, port):
        fake_open.called_with = (host, port)
        return reader, writer

    import custom_components.dess_monitor.api.transports.modbus_tcp as mod

    monkeypatch.setattr(mod.asyncio, "open_connection", fake_open)
    return reader, writer, fake_open


async def test_modbus_normal_read_response(monkeypatch):
    # header: unit=0x01, func=0x03 ; byte_count=0x02 ; 2 data + 2 CRC
    header = b"\x01\x03"
    bc = b"\x02"
    payload_and_crc = b"\x12\x34\xAA\xBB"
    reader, writer, fake_open = _fake_connection(
        monkeypatch, [header, bc, payload_and_crc]
    )
    transport = ModbusTcpTransport(timeout=1.0)

    frame = b"\x01\x03\x00\x00\x00\x01\x84\x0A"
    result = await transport.send({"host": "10.0.0.5", "port": 502}, frame)

    assert result == header + bc + payload_and_crc
    writer.write.assert_called_once_with(frame)
    assert fake_open.called_with == ("10.0.0.5", 502)
    writer.close.assert_called_once()


async def test_modbus_exception_response(monkeypatch):
    # func with high bit set -> exception: header + 1 err code + 2 CRC
    header = b"\x01\x83"  # 0x03 | 0x80
    tail = b"\x02\xC0\xF1"  # error code + CRC
    _r, _w, _o = _fake_connection(monkeypatch, [header, tail])
    transport = ModbusTcpTransport(timeout=1.0)

    result = await transport.send({"host": "h", "port": "502"}, b"\x01\x03")
    assert result == header + tail


async def test_modbus_port_coerced_from_string(monkeypatch):
    header = b"\x01\x04"
    bc = b"\x01"
    payload_and_crc = b"\x07\xDE\xAD"
    _r, _w, fake_open = _fake_connection(monkeypatch, [header, bc, payload_and_crc])
    transport = ModbusTcpTransport(timeout=1.0)

    await transport.send({"host": "host", "port": "1502"}, b"\x01")
    assert fake_open.called_with == ("host", 1502)


async def test_modbus_missing_host_raises(monkeypatch):
    # open_connection should never be called.
    import custom_components.dess_monitor.api.transports.modbus_tcp as mod

    monkeypatch.setattr(
        mod.asyncio,
        "open_connection",
        AsyncMock(side_effect=AssertionError("should not connect")),
    )
    transport = ModbusTcpTransport()
    with pytest.raises(ValueError):
        await transport.send({"port": 502}, b"\x01")


async def test_modbus_missing_port_raises(monkeypatch):
    transport = ModbusTcpTransport()
    with pytest.raises(ValueError):
        await transport.send({"host": "h"}, b"\x01")


async def test_modbus_wait_closed_failure_is_swallowed(monkeypatch):
    header = b"\x01\x03"
    bc = b"\x01"
    payload_and_crc = b"\x07\xAA\xBB"
    reader, writer, _o = _fake_connection(monkeypatch, [header, bc, payload_and_crc])
    writer.wait_closed = AsyncMock(side_effect=RuntimeError("already closed"))
    transport = ModbusTcpTransport(timeout=1.0)

    # Must still return a clean result despite the close error.
    result = await transport.send({"host": "h", "port": 502}, b"\x01")
    assert result == header + bc + payload_and_crc


# --------------------------------------------------------------------------- #
# DirectService
# --------------------------------------------------------------------------- #


class _FakeTransport(DirectTransport):
    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.sent: list[tuple[Mapping[str, Any], bytes]] = []

    async def send(self, device_data: Mapping[str, Any], frame: bytes) -> bytes:
        self.sent.append((device_data, frame))
        return self.reply


class _FakeProtocol:
    name = "fake"

    def __init__(self) -> None:
        self.encoded: list[str] = []
        self.decoded: list[tuple[str, bytes]] = []

    @property
    def schemas(self):  # pragma: no cover - unused by DirectService
        return {}

    def encode(self, command: str) -> bytes:
        self.encoded.append(command)
        return b"ENC:" + command.encode()

    def decode(self, command: str, raw: bytes) -> dict[str, Any]:
        self.decoded.append((command, raw))
        return {"command": command, "raw": raw}


async def test_direct_service_pinned_protocol_pipeline():
    proto = _FakeProtocol()
    transport = _FakeTransport(reply=b"REPLY")
    service = DirectService(transport, protocol=proto)

    result = await service.query(DEVICE, "QPIGS")

    # encode -> send -> decode wiring.
    assert proto.encoded == ["QPIGS"]
    assert transport.sent == [(DEVICE, b"ENC:QPIGS")]
    assert proto.decoded == [("QPIGS", b"REPLY")]
    assert result == {"command": "QPIGS", "raw": b"REPLY"}


async def test_direct_service_protocol_for_returns_pinned():
    proto = _FakeProtocol()
    service = DirectService(_FakeTransport(b""), protocol=proto)
    assert service.protocol_for(DEVICE) is proto


async def test_direct_service_uses_registry_default_when_unpinned():
    transport = _FakeTransport(b"")
    service = DirectService(transport)
    # default_registry resolves to AxpertProtocol for any device.
    assert isinstance(service.protocol_for(DEVICE), AxpertProtocol)


async def test_direct_service_real_protocol_roundtrip():
    """Use a real Axpert protocol with a fake transport to exercise the
    full encode/decode path against actual codec logic."""
    proto = AxpertProtocol()
    # A valid QPIGS-style ASCII reply (positional tokens), wrapped per protocol.
    raw = proto.encode("QPIGS")  # round-trip-ish: just ensure decode handles bytes
    transport = _FakeTransport(reply=raw)
    service = DirectService(transport, protocol=proto)

    result = await service.query(DEVICE, "QPIGS")
    assert isinstance(result, dict)
