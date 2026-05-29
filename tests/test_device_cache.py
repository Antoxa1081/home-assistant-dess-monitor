"""Unit tests for ``device_cache.DeviceCache`` and its TTL helpers.

The cache layers an in-memory TTL over an HA ``Store`` (needs the ``hass``
fixture). We drive the clock by monkeypatching the module-level ``_now`` so TTL
expiry is deterministic, and use simple counting fetchers to assert that a fresh
entry skips the fetch.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.dess_monitor import device_cache as dc_mod
from custom_components.dess_monitor.device_cache import (
    CTRL_FIELDS_TTL,
    DEVICES_TTL,
    DeviceCache,
    _is_fresh,
)
from custom_components.dess_monitor.sdk import ApiError


class Clock:
    def __init__(self, start: int = 1_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(dc_mod, "_now", c)
    return c


class Counter:
    """Async fetcher that records how many times it was awaited."""

    def __init__(self, value) -> None:
        self.value = value
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return self.value


# --- _is_fresh ----------------------------------------------------------------

class TestIsFresh:
    def test_none_entry_not_fresh(self, clock):
        assert _is_fresh(None, 100) is False

    def test_missing_timestamp_not_fresh(self, clock):
        assert _is_fresh({"data": 1}, 100) is False

    def test_non_numeric_timestamp_not_fresh(self, clock):
        assert _is_fresh({"fetched_at": "soon"}, 100) is False

    def test_within_ttl_is_fresh(self, clock):
        entry = {"fetched_at": clock.now}
        clock.advance(50)
        assert _is_fresh(entry, 100) is True

    def test_exactly_at_ttl_is_stale(self, clock):
        entry = {"fetched_at": clock.now}
        clock.advance(100)
        assert _is_fresh(entry, 100) is False

    def test_beyond_ttl_is_stale(self, clock):
        entry = {"fetched_at": clock.now}
        clock.advance(101)
        assert _is_fresh(entry, 100) is False


# --- devices ------------------------------------------------------------------

class TestDevices:
    async def test_fetches_on_cold_cache(self, hass, clock):
        cache = DeviceCache(hass, "e1")
        fetcher = Counter([{"pn": "A"}])
        result = await cache.async_get_devices(fetcher)
        assert result == [{"pn": "A"}]
        assert fetcher.calls == 1

    async def test_serves_fresh_without_refetch(self, hass, clock):
        cache = DeviceCache(hass, "e1")
        fetcher = Counter([{"pn": "A"}])
        await cache.async_get_devices(fetcher)
        clock.advance(DEVICES_TTL - 1)
        await cache.async_get_devices(fetcher)
        assert fetcher.calls == 1  # still fresh

    async def test_refetches_after_ttl(self, hass, clock):
        cache = DeviceCache(hass, "e1")
        fetcher = Counter([{"pn": "A"}])
        await cache.async_get_devices(fetcher)
        clock.advance(DEVICES_TTL + 1)
        await cache.async_get_devices(fetcher)
        assert fetcher.calls == 2

    async def test_invalidate_forces_refetch(self, hass, clock):
        cache = DeviceCache(hass, "e1")
        fetcher = Counter([{"pn": "A"}])
        await cache.async_get_devices(fetcher)
        await cache.async_invalidate_devices()
        await cache.async_get_devices(fetcher)
        assert fetcher.calls == 2

    async def test_persists_across_instances(self, hass, clock):
        cache = DeviceCache(hass, "persist")
        await cache.async_get_devices(Counter([{"pn": "X"}]))
        # New instance over the same entry id loads the persisted devices.
        cache2 = DeviceCache(hass, "persist")
        fetcher2 = Counter([{"pn": "Y"}])
        result = await cache2.async_get_devices(fetcher2)
        assert result == [{"pn": "X"}]
        assert fetcher2.calls == 0  # served from persisted cache


# --- ctrl_fields --------------------------------------------------------------

class TestCtrlFields:
    async def test_fetches_and_caches_per_pn(self, hass, clock):
        cache = DeviceCache(hass, "e2")
        f_a = Counter({"field": ["a"]})
        f_b = Counter({"field": ["b"]})
        assert await cache.async_get_ctrl_fields("PNA", f_a) == {"field": ["a"]}
        assert await cache.async_get_ctrl_fields("PNB", f_b) == {"field": ["b"]}
        # Re-fetch within TTL serves cache.
        await cache.async_get_ctrl_fields("PNA", f_a)
        assert f_a.calls == 1
        assert f_b.calls == 1

    async def test_refetch_after_ttl(self, hass, clock):
        cache = DeviceCache(hass, "e2")
        f = Counter({"field": ["a"]})
        await cache.async_get_ctrl_fields("PN", f)
        clock.advance(CTRL_FIELDS_TTL + 1)
        await cache.async_get_ctrl_fields("PN", f)
        assert f.calls == 2

    async def test_no_record_error_cached_as_empty(self, hass, clock):
        cache = DeviceCache(hass, "e2")

        async def fetcher():
            raise ApiError("no record", code=12)

        result = await cache.async_get_ctrl_fields("PNX", fetcher)
        assert result == {"field": []}
        # Cached empty: a second call within TTL does not re-raise/re-fetch.
        result2 = await cache.async_get_ctrl_fields("PNX", fetcher)
        assert result2 == {"field": []}

    async def test_other_api_error_propagates(self, hass, clock):
        cache = DeviceCache(hass, "e2")

        async def fetcher():
            raise ApiError("boom", code=5)

        with pytest.raises(ApiError):
            await cache.async_get_ctrl_fields("PNZ", fetcher)

    async def test_invalidate_single_pn(self, hass, clock):
        cache = DeviceCache(hass, "e2")
        f = Counter({"field": ["a"]})
        await cache.async_get_ctrl_fields("PN", f)
        await cache.async_invalidate_ctrl_fields("PN")
        await cache.async_get_ctrl_fields("PN", f)
        assert f.calls == 2

    async def test_invalidate_all(self, hass, clock):
        cache = DeviceCache(hass, "e2")
        fa = Counter({"field": ["a"]})
        fb = Counter({"field": ["b"]})
        await cache.async_get_ctrl_fields("A", fa)
        await cache.async_get_ctrl_fields("B", fb)
        await cache.async_invalidate_ctrl_fields()  # pn=None clears all
        await cache.async_get_ctrl_fields("A", fa)
        await cache.async_get_ctrl_fields("B", fb)
        assert fa.calls == 2
        assert fb.calls == 2


# --- output_priority (in-memory only) -----------------------------------------

class TestOutputPriority:
    async def test_fetch_and_cache(self, hass, clock):
        cache = DeviceCache(hass, "e3")
        f = Counter("SBU")
        assert await cache.async_get_output_priority("PN", f) == "SBU"
        await cache.async_get_output_priority("PN", f)
        assert f.calls == 1

    async def test_refetch_after_ttl(self, hass, clock):
        cache = DeviceCache(hass, "e3")
        f = Counter("SBU")
        await cache.async_get_output_priority("PN", f)
        clock.advance(301)
        await cache.async_get_output_priority("PN", f)
        assert f.calls == 2

    async def test_invalidate(self, hass, clock):
        cache = DeviceCache(hass, "e3")
        f = Counter("SBU")
        await cache.async_get_output_priority("PN", f)
        cache.invalidate_output_priority("PN")
        await cache.async_get_output_priority("PN", f)
        assert f.calls == 2

    async def test_not_persisted(self, hass, clock):
        # output_priority is in-memory only; a new instance must re-fetch.
        cache = DeviceCache(hass, "e3mem")
        await cache.async_get_output_priority("PN", Counter("SBU"))
        cache2 = DeviceCache(hass, "e3mem")
        f2 = Counter("Solar")
        assert await cache2.async_get_output_priority("PN", f2) == "Solar"
        assert f2.calls == 1


class TestClear:
    async def test_clear_wipes_all_tiers(self, hass, clock):
        cache = DeviceCache(hass, "eC")
        await cache.async_get_devices(Counter([{"pn": "A"}]))
        await cache.async_get_ctrl_fields("PN", Counter({"field": ["a"]}))
        await cache.async_clear()
        # After clear, devices re-fetch.
        f = Counter([{"pn": "B"}])
        assert await cache.async_get_devices(f) == [{"pn": "B"}]
        assert f.calls == 1
