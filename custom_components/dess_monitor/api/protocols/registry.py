"""Protocol resolution.

Maps a device (by ``devcode``) to the :class:`Protocol` instance that should
be used to talk to it. The default registry is Axpert-only; PI18 will be
added as a separate adapter.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .axpert import AxpertProtocol
from .base import Protocol
from .pi18 import Pi18Protocol
from .smg2_modbus import Smg2ModbusProtocol


class ProtocolRegistry:
    def __init__(self, protocols: Mapping[str, Protocol], default: Protocol) -> None:
        self._protocols = dict(protocols)
        self._default = default

    def get(self, name: str) -> Protocol:
        return self._protocols.get(name, self._default)

    def for_device(self, device_data: Mapping[str, Any]) -> Protocol:
        """Pick a protocol based on the device payload.

        Today every supported device speaks Axpert/PI30; PI18 selection will
        plug in here once the adapter lands.
        """
        return self._default


_axpert = AxpertProtocol()
_smg2 = Smg2ModbusProtocol()
_pi18 = Pi18Protocol()

default_registry = ProtocolRegistry(
    protocols={
        _axpert.name: _axpert,
        _smg2.name: _smg2,
        _pi18.name: _pi18,
    },
    default=_axpert,
)


def resolve_protocol(device_data: Mapping[str, Any]) -> Protocol:
    return default_registry.for_device(device_data)
