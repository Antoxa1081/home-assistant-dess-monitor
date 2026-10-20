from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

from . import errors
from .http import Endpoint, HttpClient
from .models import Auth, Credentials
from .storage import InMemoryTokenStorage, TokenStorage

_LOGGER = logging.getLogger(__name__)

_DEFAULT_REFRESH_MARGIN_SECONDS = 3600


class Session:
    """Token-aware wrapper around :class:`HttpClient`.

    Caches the current :class:`Auth`, persists it via :class:`TokenStorage`,
    refreshes proactively before ``expire``, and retries once on :class:`AuthError`
    by forcing a fresh login.
    """

    def __init__(
        self,
        http: HttpClient,
        credentials: Credentials,
        *,
        storage: TokenStorage | None = None,
        refresh_margin_seconds: int = _DEFAULT_REFRESH_MARGIN_SECONDS,
    ) -> None:
        self._http = http
        self._credentials = credentials
        self._storage: TokenStorage = storage or InMemoryTokenStorage()
        self._refresh_margin = refresh_margin_seconds
        self._lock = asyncio.Lock()
        self._auth: Auth | None = None
        self._loaded = False

    @property
    def http(self) -> HttpClient:
        return self._http

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    def _is_valid(self, auth: Auth | None) -> bool:
        if auth is None:
            return False
        return int(time.time()) < (auth.issued_at + auth.expire - self._refresh_margin)

    async def _login(self) -> Auth:
        params = {
            "usr": self._credentials.username,
            "source": "1",
            "company-key": self._http.company_key,
        }
        dat = await self._http.public_request(
            "authSource", params, password_hash=self._credentials.password_hash
        )
        auth = Auth(
            token=dat["token"],
            secret=dat["secret"],
            expire=int(dat["expire"]),
            uid=dat["uid"],
            usr=dat["usr"],
            issued_at=int(time.time()),
        )
        await self._storage.save(auth)
        return auth

    async def get_auth(self, *, force_refresh: bool = False) -> Auth:
        """Return a valid :class:`Auth`, refreshing if expired or ``force_refresh``."""
        async with self._lock:
            if not self._loaded:
                self._loaded = True
                self._auth = await self._storage.load()
            if not force_refresh and self._is_valid(self._auth):
                assert self._auth is not None
                return self._auth
            self._auth = await self._login()
            return self._auth

    async def invalidate(self) -> None:
        async with self._lock:
            self._auth = None
            await self._storage.clear()

    async def request(
        self,
        action: str,
        params: Mapping[str, object] | None = None,
        *,
        endpoint: Endpoint = "public",
        raise_on_error: bool = True,
    ) -> Any:
        """Authenticated request with one automatic re-login on :class:`AuthError`."""
        auth = await self.get_auth()
        try:
            return await self._http.authenticated_request(
                action,
                params,
                token=auth.token,
                secret=auth.secret,
                endpoint=endpoint,
                raise_on_error=raise_on_error,
            )
        except errors.AuthError:
            _LOGGER.info("Auth token rejected (action=%s) — re-authenticating", action)
            auth = await self.get_auth(force_refresh=True)
            return await self._http.authenticated_request(
                action,
                params,
                token=auth.token,
                secret=auth.secret,
                endpoint=endpoint,
                raise_on_error=raise_on_error,
            )
