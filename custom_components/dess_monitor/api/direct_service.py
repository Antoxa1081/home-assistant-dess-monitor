"""High-level orchestrator for direct inverter commands.

Sits between the coordinator and the (transport, protocol) pair. The
coordinator says *"give me QPIGS for this device"*; this service picks
the right protocol, encodes the frame, ships it through the transport,
and decodes the reply.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .protocols import Protocol, ProtocolRegistry, default_registry
from .transports import DirectTransport


class DirectService:
    def __init__(
        self,
        transport: DirectTransport,
        registry: ProtocolRegistry | None = None,
        *,
        protocol: Protocol | None = None,
    ) -> None:
        """``protocol`` pins the codec for every call, bypassing per-device
        registry lookup. Use it when the coordinator already knows there's
        only one protocol on the wire for this entry."""
        self._transport = transport
        self._registry = registry or default_registry
        self._protocol = protocol

    def protocol_for(self, device_data: Mapping[str, Any]) -> Protocol:
        if self._protocol is not None:
            return self._protocol
        return self._registry.for_device(device_data)

    async def query(
        self,
        device_data: Mapping[str, Any],
        command: str,
    ) -> dict[str, Any]:
        protocol = self.protocol_for(device_data)
        frame = protocol.encode(command)
        raw_reply = await self._transport.send(device_data, frame)
        return protocol.decode(command, raw_reply)
