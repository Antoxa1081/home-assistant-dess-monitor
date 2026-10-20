from __future__ import annotations

from types import TracebackType

import aiohttp

from .http import DEFAULT_BASE_HOST, HttpClient
from .models import Credentials, DeviceIdentity
from .resources import AuthResource, CollectorsResource, ControlResource, DevicesResource
from .session import Session
from .storage import TokenStorage
from .streaming import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_INITIAL_BACKOFF_SECONDS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    DEFAULT_QUEUE_MAXSIZE,
    DeviceStream,
)


class DessmonitorClient:
    """Top-level facade.

    Typical Home Assistant usage::

        client = DessmonitorClient(
            credentials=Credentials(username, password_hash),
            http_session=async_get_clientsession(hass),
            storage=HomeAssistantTokenStorage(hass, entry_id, username),
        )
        devices = await client.devices.list()

    Standalone usage (own session, in-memory token cache)::

        async with DessmonitorClient(credentials=Credentials.from_password(u, p)) as client:
            devices = await client.devices.list()
    """

    def __init__(
        self,
        *,
        credentials: Credentials,
        http_session: aiohttp.ClientSession | None = None,
        storage: TokenStorage | None = None,
        base_host: str | None = None,
        max_concurrent: int = 10,
    ) -> None:
        self._http = HttpClient(
            http_session,
            base_host=base_host or DEFAULT_BASE_HOST,
            max_concurrent=max_concurrent,
        )
        self.session = Session(self._http, credentials, storage=storage)
        self.auth = AuthResource(self.session)
        self.devices = DevicesResource(self.session)
        self.control = ControlResource(self.session)
        self.collectors = CollectorsResource(self.session)

    def stream_device(
        self,
        identity: DeviceIdentity,
        *,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ) -> DeviceStream:
        """Open a per-device WebSocket telemetry stream.

        Reuses the HTTP client's aiohttp session if one is already present, so
        connection pooling carries over to the WebSocket upgrade.
        """
        return DeviceStream(
            identity,
            http_session=self._http.session,
            base_host=self._http.base_host,
            heartbeat_seconds=heartbeat_seconds,
            initial_backoff_seconds=initial_backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
            queue_maxsize=queue_maxsize,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> DessmonitorClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
