from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Generic, NotRequired, TypedDict, TypeVar


@dataclass(frozen=True, slots=True)
class Credentials:
    """Login credentials. Stores SHA1 hex of the plaintext password, never plaintext."""

    username: str
    password_hash: str

    @classmethod
    def from_password(cls, username: str, password: str) -> Credentials:
        return cls(username=username, password_hash=hashlib.sha1(password.encode()).hexdigest())


@dataclass(frozen=True, slots=True)
class Auth:
    """Authenticated session token returned by ``authSource``.

    ``issued_at`` is a client-side wall-clock timestamp captured at the moment the
    token was received; combined with ``expire`` it lets the SDK decide when to refresh
    without trusting server clock skew.
    """

    token: str
    secret: str
    expire: int
    uid: str
    usr: str
    issued_at: int


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Composite key required by every device-scoped endpoint."""

    devaddr: str | int
    devcode: str | int
    pn: str
    sn: str

    def as_params(self) -> dict[str, str]:
        return {
            "devaddr": str(self.devaddr),
            "devcode": str(self.devcode),
            "pn": str(self.pn),
            "sn": str(self.sn),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceIdentity:
        return cls(
            devaddr=data["devaddr"],
            devcode=data["devcode"],
            pn=data["pn"],
            sn=data["sn"],
        )


T = TypeVar("T")


class Envelope(TypedDict, Generic[T]):
    """Universal API response wrapper. ``err == 0`` ⇒ ``dat`` is valid."""

    err: int
    desc: str
    dat: T


class AuthDict(TypedDict):
    """Shape of the ``dat`` field on a successful ``authSource`` response."""

    token: str
    secret: str
    expire: int
    uid: str
    usr: str


# ---- Common building blocks ----------------------------------------------------

class Param(TypedDict, total=False):
    """Single sensor / parameter reading.

    All fields are optional because the API uses different field sets across
    endpoints and devcodes — sometimes ``id``, sometimes ``par``; ``status`` is
    only present on items that can be disabled (``status == 0`` means ignore).
    """

    id: str
    par: str
    val: str
    unit: str
    name: str
    status: int


class DeviceDict(TypedDict):
    """Item in the ``webQueryDeviceEs`` result.

    The four identity fields are always present (the API rejects requests that
    omit them); everything else is permissive because the device record carries
    devcode-specific extras that the SDK doesn't need to enumerate.
    """

    pn: str
    sn: str
    devcode: str | int
    devaddr: str | int
    devalias: NotRequired[str]
    status: NotRequired[int]
    uid: NotRequired[str]


class CtrlFieldOption(TypedDict):
    """One enum option of a :class:`CtrlField` with ``item``."""

    key: str
    val: str


class CtrlField(TypedDict):
    """One controllable parameter exposed by ``queryDeviceCtrlField``.

    Presence of ``item`` distinguishes select-style (enum) fields from numeric
    ones — the integration uses ``'item' in field`` as the discriminator.
    """

    id: str
    name: str
    hint: NotRequired[str]
    unit: NotRequired[str]
    item: NotRequired[list[CtrlFieldOption]]


class Datalogger(TypedDict):
    """Item in the ``webQueryCollectorsEs`` result."""

    pn: str
    status: NotRequired[int]
    devcode: NotRequired[str]
    devtype: NotRequired[str]


# ---- Per-endpoint response shapes ---------------------------------------------

class LastDataResponse(TypedDict, total=False):
    """``dat`` from ``querySPDeviceLastData``."""

    gts: str
    pars: dict[str, list[Param]]


class ParsResponse(TypedDict, total=False):
    """``dat`` from ``queryDeviceParsEs`` — categorized parameter snapshots."""

    pars: dict[str, list[Param]]


class EnergyFlowResponse(TypedDict, total=False):
    """``dat`` from ``webQueryDeviceEnergyFlowEs``.

    Categories vary by ``devcode``; the listed ones are the most common. Use
    ``resolve_param`` to extract values rather than accessing keys directly.
    """

    bt_status: list[Param]
    pv_status: list[Param]
    gd_status: list[Param]
    bc_status: list[Param]
    sy_status: list[Param]


class CtrlValueResponse(TypedDict, total=False):
    """Result of ``queryDeviceCtrlValue``.

    On success, only ``val`` is present (the inner ``dat``). On non-zero ``err``
    the full envelope is returned (because the resource uses
    ``raise_on_error=False``); detect via ``'err' in result``.
    """

    val: str
    err: int
    desc: str


class CtrlFieldsResponse(TypedDict, total=False):
    """``dat`` from ``queryDeviceCtrlField``."""

    field: list[CtrlField]


class CollectorListResponse(TypedDict, total=False):
    """``dat`` from ``webQueryCollectorsEs``."""

    collector: list[Datalogger]


class DirectCommandResponse(TypedDict, total=False):
    """``dat`` from ``sendCmdToDevice`` — wraps a hex-encoded inverter response."""

    dat: str


class FieldsResponse(TypedDict, total=False):
    """``dat`` from ``queryDeviceFields`` — schema varies by devcode."""

    field: list[dict[str, Any]]


class HistoricalDataResponse(TypedDict, total=False):
    """``dat`` from ``queryDeviceDataOneDayPaging``."""

    page: int
    pagesize: int
    total: int
    rows: list[dict[str, Any]]
