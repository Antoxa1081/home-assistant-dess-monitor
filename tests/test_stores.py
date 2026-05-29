"""Tests for the HA-backed storage adapters.

Covers ``HomeAssistantTokenStorage`` (auth_store.py) and
``HomeAssistantMappingStorage`` (mapping_store.py). Both wrap an HA ``Store``;
we use the real ``hass`` fixture so the roundtrips exercise actual storage.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.dess_monitor.auth_store import HomeAssistantTokenStorage
from custom_components.dess_monitor.mapping_store import HomeAssistantMappingStorage
from custom_components.dess_monitor.sdk import Auth


def _make_auth() -> Auth:
    return Auth(
        token="tok-abc",
        secret="sec-xyz",
        expire=3600,
        uid="uid-1",
        usr="user@example.com",
        issued_at=1_700_000_000,
    )


# --------------------------------------------------------------------------- #
# HomeAssistantTokenStorage
# --------------------------------------------------------------------------- #


async def test_token_load_empty_returns_none(hass):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    assert await store.load() is None


async def test_token_save_then_load_roundtrip(hass):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    auth = _make_auth()
    await store.save(auth)

    loaded = await store.load()
    assert loaded == auth


async def test_token_fresh_instance_reads_persisted_data(hass):
    auth = _make_auth()
    await HomeAssistantTokenStorage(hass, "entry1", "user@example.com").save(auth)

    # A brand-new wrapper over the same entry/username must see the data.
    fresh = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    assert await fresh.load() == auth


async def test_token_username_mismatch_invalidates(hass):
    await HomeAssistantTokenStorage(hass, "entry1", "old@example.com").save(_make_auth())

    # Same entry, different username -> cached token must be rejected.
    other = HomeAssistantTokenStorage(hass, "entry1", "new@example.com")
    assert await other.load() is None


async def test_token_clear_removes_data(hass):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    await store.save(_make_auth())
    assert await store.load() is not None

    await store.clear()
    # HA's Store keeps an in-memory cache on the same instance even after
    # async_remove deletes the backing file; verify persistence is gone by
    # reading through a fresh wrapper.
    fresh = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    assert await fresh.load() is None


async def test_token_malformed_auth_shape_discarded(hass):
    """If the stored auth dict is missing fields, load() returns None."""
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    # Write a structurally-valid wrapper with a broken inner auth dict.
    await store._store.async_save(
        {"username": "user@example.com", "auth": {"token": "t"}}
    )
    assert await store.load() is None


async def test_token_non_dict_auth_field_returns_none(hass):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    await store._store.async_save({"username": "user@example.com", "auth": "notadict"})
    assert await store.load() is None


async def test_token_non_dict_root_returns_none(hass):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    await store._store.async_save(["not", "a", "dict"])
    assert await store.load() is None


async def test_token_coerces_int_fields(hass):
    """expire / issued_at are passed through int(); string ints must coerce."""
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")
    raw = asdict(_make_auth())
    raw["expire"] = "7200"
    raw["issued_at"] = "1700000001"
    await store._store.async_save({"username": "user@example.com", "auth": raw})

    loaded = await store.load()
    assert loaded is not None
    assert loaded.expire == 7200
    assert loaded.issued_at == 1700000001


async def test_token_load_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")

    async def boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(store._store, "async_load", boom)
    assert await store.load() is None


async def test_token_save_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")

    async def boom(_data):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store._store, "async_save", boom)
    # Must not raise.
    await store.save(_make_auth())


async def test_token_clear_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantTokenStorage(hass, "entry1", "user@example.com")

    async def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(store._store, "async_remove", boom)
    await store.clear()


# --------------------------------------------------------------------------- #
# HomeAssistantMappingStorage
# --------------------------------------------------------------------------- #


async def test_mapping_load_empty_returns_none(hass):
    store = HomeAssistantMappingStorage(hass, "entry1")
    assert await store.load() is None


async def test_mapping_save_then_load_roundtrip(hass):
    store = HomeAssistantMappingStorage(hass, "entry1")
    data = {"version": 1, "keys": {"a": "b"}}
    await store.save(data)
    assert await store.load() == data


async def test_mapping_fresh_instance_reads_persisted_data(hass):
    data = {"version": 2, "keys": {"x": "y"}}
    await HomeAssistantMappingStorage(hass, "entry1").save(data)

    fresh = HomeAssistantMappingStorage(hass, "entry1")
    assert await fresh.load() == data


async def test_mapping_clear_removes_data(hass):
    store = HomeAssistantMappingStorage(hass, "entry1")
    await store.save({"version": 1})
    assert await store.load() is not None

    await store.clear()
    # Same Store in-memory caching caveat as the token store; check via a
    # fresh wrapper that the persisted data is gone.
    fresh = HomeAssistantMappingStorage(hass, "entry1")
    assert await fresh.load() is None


async def test_mapping_non_dict_stored_returns_none(hass):
    store = HomeAssistantMappingStorage(hass, "entry1")
    await store._store.async_save([1, 2, 3])
    assert await store.load() is None


async def test_mapping_scoped_by_entry(hass):
    await HomeAssistantMappingStorage(hass, "entryA").save({"version": 1, "who": "A"})
    await HomeAssistantMappingStorage(hass, "entryB").save({"version": 1, "who": "B"})

    assert (await HomeAssistantMappingStorage(hass, "entryA").load())["who"] == "A"
    assert (await HomeAssistantMappingStorage(hass, "entryB").load())["who"] == "B"


async def test_mapping_load_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantMappingStorage(hass, "entry1")

    async def boom():
        raise RuntimeError("read fail")

    monkeypatch.setattr(store._store, "async_load", boom)
    assert await store.load() is None


async def test_mapping_save_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantMappingStorage(hass, "entry1")

    async def boom(_data):
        raise RuntimeError("write fail")

    monkeypatch.setattr(store._store, "async_save", boom)
    await store.save({"version": 1})


async def test_mapping_clear_swallows_store_errors(hass, monkeypatch):
    store = HomeAssistantMappingStorage(hass, "entry1")

    async def boom():
        raise RuntimeError("remove fail")

    monkeypatch.setattr(store._store, "async_remove", boom)
    await store.clear()
