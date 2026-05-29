"""Unit tests for ``sdk.http`` — the aiohttp transport layer.

No real sockets are opened: the ``aiohttp.ClientSession`` is replaced with a
fake whose ``get(...)`` returns an async-context-manager yielding a fake
response. We verify URL/sign wiring, envelope decoding, error mapping, and the
transport-error recovery paths (HTTP >= 400, non-JSON body, ClientError,
TimeoutError, malformed envelope).
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest

from custom_components.dess_monitor.sdk import errors
from custom_components.dess_monitor.sdk.http import HttpClient


class _FakeResponse:
    """Stand-in for an aiohttp response used as an async context manager."""

    def __init__(
        self,
        *,
        status: int = 200,
        reason: str = "OK",
        json_value: Any = None,
        json_exc: Exception | None = None,
    ) -> None:
        self.status = status
        self.reason = reason
        self._json_value = json_value
        self._json_exc = json_exc

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def json(self, content_type: Any = None) -> Any:
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_value


class _FakeSession:
    """Fake aiohttp.ClientSession capturing the .get() call args."""

    def __init__(self, response: Any = None, *, get_exc: Exception | None = None) -> None:
        self._response = response
        self._get_exc = get_exc
        self.get_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self.get_calls.append((args, kwargs))
        if self._get_exc is not None:
            raise self._get_exc
        return self._response

    async def close(self) -> None:
        self.closed = True


def _client_with(response: Any = None, *, get_exc: Exception | None = None) -> tuple[HttpClient, _FakeSession]:
    session = _FakeSession(response, get_exc=get_exc)
    client = HttpClient(session)  # type: ignore[arg-type]
    return client, session


class TestConstruction:
    def test_defaults(self) -> None:
        client = HttpClient()
        assert client.base_host == "web.dessmonitor.com"
        assert client.company_key == "bnrl_frRFjEz8Mkn"
        assert client.session is None

    def test_owns_session_when_none_passed(self) -> None:
        client = HttpClient()
        assert client._owns_session is True

    def test_does_not_own_supplied_session(self) -> None:
        session = _FakeSession()
        client = HttpClient(session)  # type: ignore[arg-type]
        assert client._owns_session is False
        assert client.session is session

    def test_custom_base_host_and_company_key(self) -> None:
        client = HttpClient(base_host="example.com", company_key="KEY")
        assert client.base_host == "example.com"
        assert client.company_key == "KEY"


class TestBuildUrl:
    def test_url_structure_and_endpoint(self) -> None:
        client = HttpClient(base_host="h.example")
        url = client._build_url("public", {"a": "1", "b": "2"})
        assert url == "https://h.example/public/?a=1&b=2"

    def test_remote_endpoint(self) -> None:
        client = HttpClient(base_host="h.example")
        url = client._build_url("remote", {"x": "y"})
        assert url.startswith("https://h.example/remote/?")


class TestAclose:
    async def test_closes_owned_session(self) -> None:
        client = HttpClient()
        fake = _FakeSession()
        # Force the lazily-created owned session to our fake.
        client._session = fake  # type: ignore[assignment]
        await client.aclose()
        assert fake.closed is True
        assert client.session is None

    async def test_does_not_close_borrowed_session(self) -> None:
        fake = _FakeSession()
        client = HttpClient(fake)  # type: ignore[arg-type]
        await client.aclose()
        assert fake.closed is False
        assert client.session is fake

    async def test_aenter_creates_session_lazily(self) -> None:
        client = HttpClient()
        async with client as c:
            assert c.session is not None
        # __aexit__ closed the owned session
        assert client.session is None


class TestPublicRequest:
    async def test_returns_dat_on_success(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "desc": "ok", "dat": {"token": "T"}})
        client, _ = _client_with(resp)
        dat = await client.public_request("authSource", {"usr": "bob"}, password_hash="ph")
        assert dat == {"token": "T"}

    async def test_signs_and_targets_public_endpoint(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": {}})
        client, session = _client_with(resp)
        await client.public_request("authSource", {"usr": "bob"}, password_hash="ph")
        (args, kwargs) = session.get_calls[0]
        url = args[0]
        assert url.startswith("https://web.dessmonitor.com/public/?")
        assert "sign=" in url
        assert "salt=" in url
        assert "action=authSource" in url
        assert "usr=bob" in url
        # headers wired through
        assert "headers" in kwargs
        assert kwargs["headers"]["Host"] == "web.dessmonitor.com"

    async def test_raises_on_nonzero_err(self) -> None:
        resp = _FakeResponse(json_value={"err": 1, "desc": "nope", "dat": None})
        client, _ = _client_with(resp)
        with pytest.raises(errors.ApiError) as ei:
            await client.public_request("authSource", {}, password_hash="ph")
        assert ei.value.code == 1
        assert ei.value.action == "authSource"

    async def test_auth_error_mapping(self) -> None:
        resp = _FakeResponse(json_value={"err": 10, "desc": "expired", "dat": None})
        client, _ = _client_with(resp)
        with pytest.raises(errors.AuthError):
            await client.public_request("authSource", {}, password_hash="ph")


class TestAuthenticatedRequest:
    async def test_returns_dat_on_success(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": {"device": []}})
        client, _ = _client_with(resp)
        dat = await client.authenticated_request(
            "webQueryDeviceEs", {"page": "0"}, token="tok", secret="sec"
        )
        assert dat == {"device": []}

    async def test_signs_with_token_and_default_endpoint(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": {}})
        client, session = _client_with(resp)
        await client.authenticated_request("act", {"k": "v"}, token="tok", secret="sec")
        url = session.get_calls[0][0][0]
        assert "/public/?" in url
        assert "token=tok" in url
        assert "action=act" in url
        assert "k=v" in url

    async def test_remote_endpoint(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": {}})
        client, session = _client_with(resp)
        await client.authenticated_request(
            "act", token="tok", secret="sec", endpoint="remote"
        )
        assert "/remote/?" in session.get_calls[0][0][0]

    async def test_none_params_allowed(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": 5})
        client, _ = _client_with(resp)
        dat = await client.authenticated_request("act", None, token="t", secret="s")
        assert dat == 5

    async def test_raises_on_nonzero_when_raise_on_error_true(self) -> None:
        resp = _FakeResponse(json_value={"err": 2, "desc": "bad", "dat": None})
        client, _ = _client_with(resp)
        with pytest.raises(errors.ApiError):
            await client.authenticated_request("act", token="t", secret="s")

    async def test_returns_raw_envelope_when_raise_on_error_false(self) -> None:
        env = {"err": 4, "desc": "unsupported", "dat": None}
        resp = _FakeResponse(json_value=env)
        client, _ = _client_with(resp)
        result = await client.authenticated_request(
            "act", token="t", secret="s", raise_on_error=False
        )
        assert result == env

    async def test_rate_limit_error_mapping(self) -> None:
        resp = _FakeResponse(json_value={"err": 3, "desc": "slow", "dat": None})
        client, _ = _client_with(resp)
        with pytest.raises(errors.RateLimitError):
            await client.authenticated_request("act", token="t", secret="s")


class TestTransportErrors:
    async def test_http_status_ge_400_raises_transport_error(self) -> None:
        resp = _FakeResponse(status=503, reason="Service Unavailable")
        client, _ = _client_with(resp)
        with pytest.raises(errors.TransportError) as ei:
            await client.authenticated_request("act", token="t", secret="s")
        assert ei.value.code == 503
        assert ei.value.action == "act"
        assert "503" in str(ei.value)

    async def test_non_json_body_raises_transport_error(self) -> None:
        resp = _FakeResponse(status=200, json_exc=ValueError("not json"))
        client, _ = _client_with(resp)
        with pytest.raises(errors.TransportError) as ei:
            await client.authenticated_request("act", token="t", secret="s")
        assert ei.value.code == 200
        assert "Non-JSON" in str(ei.value)

    async def test_client_error_wrapped(self) -> None:
        client, _ = _client_with(get_exc=aiohttp.ClientError("conn reset"))
        with pytest.raises(errors.TransportError) as ei:
            await client.authenticated_request("act", token="t", secret="s")
        assert ei.value.action == "act"
        assert "transport failed" in str(ei.value)

    async def test_timeout_wrapped(self) -> None:
        client, _ = _client_with(get_exc=TimeoutError())
        with pytest.raises(errors.TransportError) as ei:
            await client.authenticated_request("act", token="t", secret="s")
        assert "timed out" in str(ei.value)

    async def test_malformed_envelope_missing_err(self) -> None:
        resp = _FakeResponse(json_value={"dat": {}})  # no "err"
        client, _ = _client_with(resp)
        with pytest.raises(errors.TransportError) as ei:
            await client.authenticated_request("act", token="t", secret="s")
        assert "Malformed envelope" in str(ei.value)

    async def test_malformed_envelope_not_a_dict(self) -> None:
        resp = _FakeResponse(json_value=[1, 2, 3])
        client, _ = _client_with(resp)
        with pytest.raises(errors.TransportError):
            await client.authenticated_request("act", token="t", secret="s")


class TestSendUsesSemaphore:
    async def test_concurrency_does_not_deadlock(self) -> None:
        resp = _FakeResponse(json_value={"err": 0, "dat": 1})
        client, _ = _client_with(resp)
        results = await asyncio.gather(
            *[client.authenticated_request("a", token="t", secret="s") for _ in range(5)]
        )
        assert results == [1, 1, 1, 1, 1]
