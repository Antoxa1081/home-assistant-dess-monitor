"""Protocol contract shared by every inverter adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class Field:
    """One positional field in a response.

    ``enum`` — if set, the raw token is mapped to ``EnumClass(token).name``.
    ``transform`` — optional post-processing callable (raw_token -> value).
    Default behaviour preserves the raw string token; sensors handle their
    own numeric coercion (``float(x)`` etc.) for backwards compatibility.
    """

    name: str
    enum: type[Enum] | None = None
    transform: Callable[[str], Any] | None = None


@dataclass(frozen=True, slots=True)
class ResponseSchema:
    """Declarative description of a positional ASCII response.

    The parser splits the response on whitespace and zips tokens with
    ``fields``. Trailing tokens beyond the schema are ignored; missing
    tokens leave the field absent.
    """

    name: str
    fields: tuple[Field, ...]


class Protocol(ABC):
    """Pure command codec. No I/O, no device identity, no transport."""

    name: str = ""

    @property
    @abstractmethod
    def schemas(self) -> Mapping[str, ResponseSchema]:
        """Map of command name (upper-case) to its response schema."""

    @abstractmethod
    def encode(self, command: str) -> bytes:
        """Build the raw on-wire frame for ``command``."""

    @abstractmethod
    def decode(self, command: str, raw: bytes) -> dict[str, Any]:
        """Parse the device's raw reply into a structured dict.

        Returning ``{"error": "..."}`` is reserved for protocol-level errors
        (NAK, malformed frame, unknown command).
        """


@dataclass(frozen=True, slots=True)
class ProtocolBinding:
    """Tells a coordinator *what* to fetch on each poll.

    ``sections`` maps the logical section key exposed to sensors
    (e.g. ``"qpigs"``) to the protocol command issued to obtain it
    (e.g. ``"QPIGS"``). Decoupling the two lets PI18 emit the same
    ``"qpigs"`` section under a different command without rewiring sensors.
    """

    protocol_name: str
    sections: Mapping[str, str] = field(default_factory=dict)
