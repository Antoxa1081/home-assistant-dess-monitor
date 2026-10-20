"""Transport contract for direct inverter commands."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class DirectTransport(ABC):
    """Send a raw command frame and return the raw reply."""

    @abstractmethod
    async def send(self, device_data: Mapping[str, Any], frame: bytes) -> bytes:
        """Send ``frame`` to the device described by ``device_data``.

        Implementations are responsible for any wire-level concerns
        (auth, hex re-encoding, retries) and must return the device's
        raw reply as bytes — without parsing.
        """
