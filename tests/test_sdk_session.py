"""Unit tests for ``sdk.session`` — token lifecycle (cache/expiry/refresh/retry).

The ``HttpClient`` is mocked so we control ``public_request`` (login) and
``authenticated_request`` (api calls). ``time.time`` is monkeypatched where
validity windows matter.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dess_monitor.sdk import errors
from custom_components.dess_monitor.sdk import session as session_mod
from custom_components.dess_monitor.sdk.models import Auth, Credentials
from custom_components.dess_monitor.sdk.session import Session
from custom_components.dess_monitor.sdk.storage import InMemoryTokenStorage


def _creds() -> Credentials:
    return Credentials(username="bob", password_hash="ph")


def _login_dat(token: str = "tok", expire: int = 86400) -> dict[str, Any]:
    return {
        "token": token,
        "secret": "sec",
        "expire": expire,
        "uid": "uid1",
        "usr": "bob",
    }


def _make_http(login_dat: dict[str, Any] | None = None) -> MagicMock:
    http = MagicMock()
    http.company_key = "COMPANY"
    http.public_request = AsyncMock(return_value=login_dat or _login_dat())
    http.authenticated_request = AsyncMock(return_value={"ok": True})
    return http


class TestLogin:
    async def test_login_builds_params_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 1000)
        http = _make_http()
        storage = InMemoryTokenStorage()
        sess = Session(http, _creds(), storage=storage)

        auth = await sess.get_auth()

        http.public_request.assert_awaited_once()
        args, kwargs = http.public_request.call_args
        assert args[0] == "authSource"
        params = args[1]
        assert params["usr"] == "bob"
        assert params["source"] == "1"
        assert params["company-key"] == "COMPANY"
        assert kwargs["password_hash"] == "ph"

        assert isinstance(auth, Auth)
        assert auth.token == "tok"
        assert auth.issued_at == 1000
        # persisted
        assert await storage.load() is auth

    async def test_login_converts_expire_to_int(self) -> None:
        http = _make_http(_login_dat(expire="500"))  # type: ignore[arg-type]
        sess = Session(http, _creds())
        auth = await sess.get_auth()
        assert auth.expire == 500


class TestCaching:
    async def test_valid_cached_token_not_relogged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 1000)
        http = _make_http()
        sess = Session(http, _creds())
        a1 = await sess.get_auth()
        a2 = await sess.get_auth()
        assert a1 is a2
        http.public_request.assert_awaited_once()

    async def test_force_refresh_relogins(self) -> None:
        http = _make_http()
        sess = Session(http, _creds())
        await sess.get_auth()
        await sess.get_auth(force_refresh=True)
        assert http.public_request.await_count == 2

    async def test_loads_valid_token_from_storage_without_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 1000)
        # issued_at + expire - margin(3600) = 1000 + 1_000_000 - 3600 >> now -> valid
        existing = Auth(
            token="cached", secret="s", expire=1_000_000, uid="u", usr="b", issued_at=1000
        )
        storage = InMemoryTokenStorage()
        await storage.save(existing)
        http = _make_http()
        sess = Session(http, _creds(), storage=storage)
        auth = await sess.get_auth()
        assert auth is existing
        http.public_request.assert_not_awaited()

    async def test_storage_loaded_only_once(self) -> None:
        # The _loaded flag means storage.load is consulted at most once.
        storage = MagicMock()
        storage.load = AsyncMock(return_value=None)
        storage.save = AsyncMock()
        http = _make_http()
        sess = Session(http, _creds(), storage=storage)
        await sess.get_auth()
        await sess.get_auth()
        storage.load.assert_awaited_once()


class TestValidity:
    def test_is_valid_none(self) -> None:
        sess = Session(_make_http(), _creds())
        assert sess._is_valid(None) is False

    def test_is_valid_within_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 1000)
        sess = Session(_make_http(), _creds(), refresh_margin_seconds=100)
        # issued_at + expire - margin = 0 + 10000 - 100 = 9900 > 1000 -> valid
        auth = Auth(token="t", secret="s", expire=10000, uid="u", usr="b", issued_at=0)
        assert sess._is_valid(auth) is True

    def test_is_invalid_inside_refresh_margin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 9950)
        sess = Session(_make_http(), _creds(), refresh_margin_seconds=100)
        # threshold = 0 + 10000 - 100 = 9900; now 9950 >= 9900 -> invalid
        auth = Auth(token="t", secret="s", expire=10000, uid="u", usr="b", issued_at=0)
        assert sess._is_valid(auth) is False

    async def test_expired_storage_token_triggers_login(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_mod.time, "time", lambda: 10_000_000)
        stale = Auth(token="old", secret="s", expire=10, uid="u", usr="b", issued_at=0)
        storage = InMemoryTokenStorage()
        await storage.save(stale)
        http = _make_http()
        sess = Session(http, _creds(), storage=storage)
        auth = await sess.get_auth()
        assert auth.token == "tok"
        http.public_request.assert_awaited_once()


class TestInvalidate:
    async def test_invalidate_clears_cache_and_storage(self) -> None:
        storage = InMemoryTokenStorage()
        http = _make_http()
        sess = Session(http, _creds(), storage=storage)
        await sess.get_auth()
        assert await storage.load() is not None
        await sess.invalidate()
        assert sess._auth is None
        assert await storage.load() is None


class TestRequest:
    async def test_passes_token_and_secret(self) -> None:
        http = _make_http()
        sess = Session(http, _creds())
        result = await sess.request("webQueryDeviceEs", {"page": "0"})
        assert result == {"ok": True}
        http.authenticated_request.assert_awaited_once()
        args, kwargs = http.authenticated_request.call_args
        assert args[0] == "webQueryDeviceEs"
        assert args[1] == {"page": "0"}
        assert kwargs["token"] == "tok"
        assert kwargs["secret"] == "sec"
        assert kwargs["endpoint"] == "public"
        assert kwargs["raise_on_error"] is True

    async def test_forwards_endpoint_and_raise_flag(self) -> None:
        http = _make_http()
        sess = Session(http, _creds())
        await sess.request("act", endpoint="remote", raise_on_error=False)
        kwargs = http.authenticated_request.call_args.kwargs
        assert kwargs["endpoint"] == "remote"
        assert kwargs["raise_on_error"] is False

    async def test_retries_once_on_auth_error(self) -> None:
        http = _make_http()
        # First api call fails AuthError, second succeeds.
        http.authenticated_request = AsyncMock(
            side_effect=[errors.AuthError("rejected", code=10), {"retried": True}]
        )
        sess = Session(http, _creds())
        result = await sess.request("act")
        assert result == {"retried": True}
        assert http.authenticated_request.await_count == 2
        # Forced re-login happened: login called twice (initial + force_refresh)
        assert http.public_request.await_count == 2

    async def test_auth_error_propagates_if_retry_also_fails(self) -> None:
        http = _make_http()
        http.authenticated_request = AsyncMock(side_effect=errors.AuthError("rejected", code=10))
        sess = Session(http, _creds())
        with pytest.raises(errors.AuthError):
            await sess.request("act")
        assert http.authenticated_request.await_count == 2

    async def test_non_auth_error_not_retried(self) -> None:
        http = _make_http()
        http.authenticated_request = AsyncMock(side_effect=errors.RateLimitError("slow", code=3))
        sess = Session(http, _creds())
        with pytest.raises(errors.RateLimitError):
            await sess.request("act")
        assert http.authenticated_request.await_count == 1


class TestProperties:
    def test_http_and_credentials_exposed(self) -> None:
        http = _make_http()
        creds = _creds()
        sess = Session(http, creds)
        assert sess.http is http
        assert sess.credentials is creds
