"""Unit tests for ``mapping/storage.py``.

Covers the ``MappingStorage`` runtime-checkable Protocol and the
``InMemoryMappingStorage`` default implementation.
"""
from __future__ import annotations

from custom_components.dess_monitor.mapping import (
    InMemoryMappingStorage,
    MappingStorage,
)


class TestInMemoryMappingStorage:
    async def test_load_empty_returns_none(self):
        storage = InMemoryMappingStorage()
        assert await storage.load() is None

    async def test_save_then_load_roundtrip(self):
        storage = InMemoryMappingStorage()
        payload = {"version": 2, "devices": {"PN1": {"battery_voltage": {}}}}
        await storage.save(payload)
        assert await storage.load() == payload

    async def test_load_returns_same_object(self):
        storage = InMemoryMappingStorage()
        payload = {"a": 1}
        await storage.save(payload)
        assert await storage.load() is payload

    async def test_save_overwrites(self):
        storage = InMemoryMappingStorage()
        await storage.save({"first": True})
        await storage.save({"second": True})
        assert await storage.load() == {"second": True}

    async def test_clear_resets_to_none(self):
        storage = InMemoryMappingStorage()
        await storage.save({"x": 1})
        await storage.clear()
        assert await storage.load() is None

    async def test_clear_on_empty_is_noop(self):
        storage = InMemoryMappingStorage()
        await storage.clear()
        assert await storage.load() is None

    async def test_instances_are_isolated(self):
        a = InMemoryMappingStorage()
        b = InMemoryMappingStorage()
        await a.save({"only": "a"})
        assert await a.load() == {"only": "a"}
        assert await b.load() is None


class TestMappingStorageProtocol:
    def test_inmemory_satisfies_protocol(self):
        assert isinstance(InMemoryMappingStorage(), MappingStorage)

    def test_object_missing_methods_does_not_satisfy(self):
        class Incomplete:
            async def load(self):
                return None

        assert not isinstance(Incomplete(), MappingStorage)

    def test_duck_typed_class_satisfies(self):
        class Custom:
            async def load(self):
                return None

            async def save(self, data):
                pass

            async def clear(self):
                pass

        assert isinstance(Custom(), MappingStorage)
