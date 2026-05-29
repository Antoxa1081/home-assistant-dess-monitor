"""Light wiring tests for ``sdk.client.DessmonitorClient`` (the facade)."""
from __future__ import annotations

from unittest.mock import patch

from custom_components.dess_monitor.sdk.client import DessmonitorClient
from custom_components.dess_monitor.sdk.http import HttpClient
from custom_components.dess_monitor.sdk.models import Credentials, DeviceIdentity
from custom_components.dess_monitor.sdk.resources import (
    AuthResource,
    CollectorsResource,
    ControlResource,
    DevicesResource,
)
from custom_components.dess_monitor.sdk.session import Session
from custom_components.dess_monitor.sdk.streaming import DeviceStream


def _creds() -> Credentials:
    return Credentials(username="u", password_hash="ph")


class TestConstruction:
    def test_exposes_session_and_resources(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        assert isinstance(client.session, Session)
        assert isinstance(client.auth, AuthResource)
        assert isinstance(client.devices, DevicesResource)
        assert isinstance(client.control, ControlResource)
        assert isinstance(client.collectors, CollectorsResource)

    def test_resources_share_the_session(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        assert client.auth._session is client.session
        assert client.devices._session is client.session
        assert client.control._session is client.session
        assert client.collectors._session is client.session

    def test_default_http_no_session_yet(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        assert isinstance(client._http, HttpClient)
        assert client._http.base_host == "web.dessmonitor.com"
        assert client._http.session is None

    def test_custom_base_host(self) -> None:
        client = DessmonitorClient(credentials=_creds(), base_host="alt.example")
        assert client._http.base_host == "alt.example"

    def test_session_wired_to_http(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        assert client.session.http is client._http


class TestStreamDevice:
    def test_returns_device_stream(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        identity = DeviceIdentity(devaddr=1, devcode=2376, pn="PN", sn="SN")
        stream = client.stream_device(identity)
        assert isinstance(stream, DeviceStream)


class TestLifecycle:
    async def test_aclose_closes_http(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        with patch.object(client._http, "aclose") as mock_close:
            mock_close.return_value = None

            async def _noop() -> None:
                return None

            # patch.object on async needs an awaitable return; use side_effect
            mock_close.side_effect = _noop
            await client.aclose()
            mock_close.assert_called_once()

    async def test_async_context_manager_closes(self) -> None:
        client = DessmonitorClient(credentials=_creds())
        async with client as c:
            assert c is client
        # owned session was never created, so aclose is a no-op; just ensure no error
        assert client._http.session is None
