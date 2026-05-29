"""Inverter protocol adapters.

Each :class:`Protocol` knows how to encode a logical command name into the
raw bytes the device expects, and how to decode the device's raw reply into
a structured dict. Protocols are pure logic — no I/O — so they can be unit
tested without a transport.
"""
from .axpert import AxpertProtocol
from .base import Field, Protocol, ResponseSchema
from .pi18 import Pi18Protocol
from .registry import ProtocolRegistry, default_registry, resolve_protocol
from .smg2_modbus import Smg2ModbusProtocol

__all__ = [
    "AxpertProtocol",
    "Field",
    "Pi18Protocol",
    "Protocol",
    "ProtocolRegistry",
    "ResponseSchema",
    "Smg2ModbusProtocol",
    "default_registry",
    "resolve_protocol",
]
