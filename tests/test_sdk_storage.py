"""Unit tests for ``sdk.storage`` — the TokenStorage protocol + in-memory impl."""
from __future__ import annotations

from custom_components.dess_monitor.sdk.models import Auth
from custom_components.dess_monitor.sdk.storage import InMemoryTokenStorage, TokenStorage


def _auth(token: str = "tok") -> Auth:
    return Auth(token=token, secret="sec", expire=86400, uid="u", usr="user", issued_at=1000)


class TestInMemoryTokenStorage:
    async def test_load_empty_is_none(self) -> None:
        storage = InMemoryTokenStorage()
        assert await storage.load() is None

    async def test_save_then_load_roundtrip(self) -> None:
        storage = InMemoryTokenStorage()
        auth = _auth()
        await storage.save(auth)
        assert await storage.load() is auth

    async def test_save_overwrites(self) -> None:
        storage = InMemoryTokenStorage()
        await storage.save(_auth("a"))
        await storage.save(_auth("b"))
        loaded = await storage.load()
        assert loaded is not None
        assert loaded.token == "b"

    async def test_clear_resets_to_none(self) -> None:
        storage = InMemoryTokenStorage()
        await storage.save(_auth())
        await storage.clear()
        assert await storage.load() is None

    def test_satisfies_protocol(self) -> None:
        storage = InMemoryTokenStorage()
        assert isinstance(storage, TokenStorage)

    def test_protocol_runtime_checkable_rejects_non_conforming(self) -> None:
        class Incomplete:
            async def load(self) -> None:  # missing save/clear
                return None

        assert not isinstance(Incomplete(), TokenStorage)
