"""DESS cloud transport.

The cloud relay accepts the inverter command as a space-separated hex
string and returns the device reply in the same shape. Hex encoding is
strictly an artefact of this transport — protocol code never sees it.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from custom_components.dess_monitor.sdk import DessmonitorClient
from custom_components.dess_monitor.sdk.models import DeviceIdentity

from .base import DirectTransport


def _bytes_to_hex(frame: bytes) -> str:
    return " ".join(f"{b:02X}" for b in frame)


def _hex_to_bytes(hex_str: str) -> bytes:
    if not hex_str or hex_str == "null":
        return b""
    return bytes(int(token, 16) for token in hex_str.split())


class CloudHexTransport(DirectTransport):
    def __init__(self, client: DessmonitorClient) -> None:
        self._client = client

    async def send(self, device_data: Mapping[str, Any], frame: bytes) -> bytes:
        identity = DeviceIdentity.from_dict(dict(device_data))
        result = await self._client.control.send_direct_command(
            identity,
            _bytes_to_hex(frame),
        )
        dat = result.get("dat") if isinstance(result, dict) else None
        if not isinstance(dat, str):
            return b""
        if dat == "null":
            return b"null"
        return _hex_to_bytes(dat)
