from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal

import aiohttp

from . import errors, signing

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_HOST = "web.dessmonitor.com"
DEFAULT_COMPANY_KEY = "bnrl_frRFjEz8Mkn"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10)
DEFAULT_MAX_CONCURRENT = 10

def _default_headers(host: str) -> dict[str, str]:
    return {
        "Host": host,
        "Origin": host,
        "Referer": "https://www.dessmonitor.com/",
        "DNT": "1",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
    }


Endpoint = Literal["public", "remote"]


class HttpClient:
    """Stateless HTTP transport: signs, sends, unwraps the envelope.

    Holds an :class:`aiohttp.ClientSession` and a concurrency semaphore. Knows
    nothing about login state — the caller (typically :class:`Session`) supplies
    ``token``/``secret`` per request.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        base_host: str = DEFAULT_BASE_HOST,
        company_key: str = DEFAULT_COMPANY_KEY,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        timeout: aiohttp.ClientTimeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_host = base_host
        self._company_key = company_key
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session = session
        self._owns_session = session is None
        self._headers = _default_headers(base_host)

    @property
    def company_key(self) -> str:
        return self._company_key

    @property
    def base_host(self) -> str:
        return self._base_host

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Underlying aiohttp session (may be None until first request)."""
        return self._session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def aclose(self) -> None:
        """Close the underlying session if (and only if) we created it."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> HttpClient:
        await self._get_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _build_url(self, endpoint: Endpoint, payload: Mapping[str, object]) -> str:
        qs = signing.encode_query(payload)
        return f"https://{self._base_host}/{endpoint}/?{qs}"

    async def _send(self, url: str, action: str | None) -> Any:
        session = await self._get_session()
        async with self._semaphore:
            try:
                async with session.get(url, headers=self._headers) as resp:
                    # The cloud's upstream balancer occasionally returns
                    # 502/503/504 with an HTML body — parsing that as JSON
                    # would raise json.JSONDecodeError (a ValueError, NOT
                    # aiohttp.ClientError) and propagate unhandled, leaving
                    # the coordinator to log a traceback every tick until the
                    # upstream recovers. Check status first and convert to a
                    # TransportError the coordinator already knows how to wrap.
                    if resp.status >= 400:
                        raise errors.TransportError(
                            f"HTTP {resp.status} {resp.reason or ''}".rstrip(),
                            code=resp.status,
                            action=action,
                        )
                    try:
                        body = await resp.json(content_type=None)
                    except ValueError as exc:
                        # 2xx with a non-JSON body (maintenance pages, CDN
                        # interstitials). Same recovery path as 5xx above.
                        raise errors.TransportError(
                            f"Non-JSON response: {exc}",
                            code=resp.status,
                            action=action,
                        ) from exc
            except aiohttp.ClientError as exc:
                raise errors.TransportError(f"HTTP transport failed: {exc}", action=action) from exc
            except TimeoutError as exc:
                raise errors.TransportError("HTTP request timed out", action=action) from exc

        if not isinstance(body, dict) or "err" not in body:
            raise errors.TransportError(f"Malformed envelope: {body!r}", action=action)
        return body

    async def public_request(
        self,
        action: str,
        params: Mapping[str, object],
        *,
        password_hash: str,
    ) -> Any:
        """Unauthenticated request — used only for ``authSource`` (login)."""
        merged = {"action": action, **params}
        payload = signing.build_public_payload(password_hash, merged)
        url = self._build_url("public", payload)
        body = await self._send(url, action=action)
        if body["err"] != 0:
            raise errors.from_envelope(body["err"], body.get("desc", ""), action)
        return body["dat"]

    async def authenticated_request(
        self,
        action: str,
        params: Mapping[str, object] | None = None,
        *,
        token: str,
        secret: str,
        endpoint: Endpoint = "public",
        raise_on_error: bool = True,
    ) -> Any:
        """Signed request using a valid ``token``/``secret`` pair.

        When ``raise_on_error=False`` the raw envelope is returned on non-zero ``err``,
        so callers can introspect codes that aren't fatal in their context (e.g. some
        ``queryDeviceCtrlValue`` calls return non-zero for unsupported params).
        """
        merged = {"action": action, **(params or {})}
        payload = signing.build_authenticated_payload(token, secret, merged)
        url = self._build_url(endpoint, payload)
        body = await self._send(url, action=action)
        if body["err"] == 0:
            return body["dat"]
        if raise_on_error:
            raise errors.from_envelope(body["err"], body.get("desc", ""), action)
        return body
