"""Unit tests for ``mapping/discovery.py`` (the resolver core).

Covers resolve() discovery + pinning, value extraction (scale/offset/unit/
sign/value_map), the WS > live > cached haystack priority (issue #88),
dirty-flag bookkeeping, snapshot/restore, and persistence interaction.

Data-shape recap (see _iter_haystacks / _search_haystack):
  * ``ws_data``        -> highest priority haystack
  * everything except ws_data/pars -> "live" haystack
  * ``pars``           -> lowest priority (cached) haystack
  An item is a dict carrying ``val`` and optionally ``unit``/``status``.
  ``id``-keyed items live in last_data shape; ``par``-keyed in pars shape.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.dess_monitor.mapping import (
    MATCH_FIELD_ID,
    MATCH_FIELD_PAR,
    InMemoryMappingStorage,
    MappingDiscovery,
    ProviderKeyCandidate,
)
from custom_components.dess_monitor.mapping.discovery import _SNAPSHOT_VERSION

PN = "W0030000000000"


def disc(storage=None) -> MappingDiscovery:
    return MappingDiscovery(storage or InMemoryMappingStorage())


def id_item(provider_key, val, unit=None):
    item = {"id": provider_key, "val": val}
    if unit is not None:
        item["unit"] = unit
    return item


def par_item(provider_key, val, unit=None, status=None):
    item = {"par": provider_key, "val": val}
    if unit is not None:
        item["unit"] = unit
    if status is not None:
        item["status"] = status
    return item


# --------------------------------------------------------------------------- #
# Basic discovery + extraction
# --------------------------------------------------------------------------- #
class TestResolveDiscovery:
    def test_resolve_simple_id_match(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}}
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(53.2)

    def test_resolve_unknown_canonical_returns_none(self):
        d = disc()
        assert d.resolve(PN, "does_not_exist", {"x": {}}) is None

    def test_resolve_missing_key_returns_none(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("unrelated", "1")]}}
        assert d.resolve(PN, "battery_voltage", data) is None

    def test_resolve_non_dict_data_returns_none(self):
        d = disc()
        assert d.resolve(PN, "battery_voltage", None) is None
        assert d.resolve(PN, "battery_voltage", ["not", "a", "dict"]) is None

    def test_resolve_val_none_returns_none(self):
        d = disc()
        data = {"last_data": {"pars": [{"id": "bt_battery_voltage", "val": None}]}}
        assert d.resolve(PN, "battery_voltage", data) is None

    def test_resolve_unparseable_val_returns_none(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_battery_voltage", "----")]}}
        assert d.resolve(PN, "battery_voltage", data) is None

    def test_pins_candidate_after_first_resolve(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}}
        d.resolve(PN, "battery_voltage", data)
        pinned = d.discovered_provider_key(PN, "battery_voltage")
        assert pinned is not None
        assert pinned.provider_key == "bt_battery_voltage"
        assert pinned.match_field == MATCH_FIELD_ID

    def test_resolve_picks_first_matching_in_seed_order(self):
        # battery_voltage seed order: bt_battery_voltage(id) first, then par.
        d = disc()
        data = {
            "last_data": {"pars": [id_item("Battery Voltage", "12.0")]},
        }
        # bt_battery_voltage absent -> falls to "Battery Voltage" id candidate.
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(12.0)
        assert d.discovered_provider_key(PN, "battery_voltage").provider_key == "Battery Voltage"


class TestExtraction:
    def test_kw_unit_scales_to_watts(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("battery_active_power", "1.5", unit="kW")]}}
        assert d.resolve(PN, "battery_power", data) == pytest.approx(1500.0)

    def test_w_unit_unchanged(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("battery_active_power", "1500", unit="W")]}}
        assert d.resolve(PN, "battery_power", data) == pytest.approx(1500.0)

    def test_scale_and_offset_applied(self):
        cand = ProviderKeyCandidate("k", MATCH_FIELD_ID, scale=0.1, offset=2.0)
        item = id_item("k", "100")
        # 100 * 0.1 + 2.0 = 12.0
        assert MappingDiscovery._extract(cand, {"live": [item]}) == pytest.approx(12.0)

    def test_sign_positive_keeps_positive(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_eybond_read_29", "8.0")]}}
        assert d.resolve(PN, "battery_charging_current", data) == pytest.approx(8.0)

    def test_sign_positive_zeros_negative(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_eybond_read_29", "-8.0")]}}
        assert d.resolve(PN, "battery_charging_current", data) == pytest.approx(0.0)

    def test_sign_negative_returns_abs_of_negative(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_eybond_read_29", "-8.0")]}}
        assert d.resolve(PN, "battery_discharge_current", data) == pytest.approx(8.0)

    def test_sign_negative_zeros_positive(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_eybond_read_29", "8.0")]}}
        assert d.resolve(PN, "battery_discharge_current", data) == pytest.approx(0.0)

    def test_value_map_lookup_lowercased(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bc_output_source_priority", "SBU")]}}
        assert d.resolve(PN, "output_priority", data) == "SBU"

    def test_value_map_unknown_value_returns_none(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bc_output_source_priority", "weird")]}}
        # value_map.get(...) -> None; resolve continues, no other candidate, None.
        assert d.resolve(PN, "output_priority", data) is None

    def test_value_map_non_string_val_coerced(self):
        # raw_val coerced to str before lowercasing; "off" -> "OFF".
        d = disc()
        data = {"last_data": {"pars": [id_item("bc_output_source_priority", "Utility")]}}
        assert d.resolve(PN, "output_priority", data) == "Utility"

    def test_mains_status_chinese(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("gd_mains_status", "电池模式")]}}
        assert d.resolve(PN, "mains_status", data) == "BATTERY"


# --------------------------------------------------------------------------- #
# Haystack priority (issue #88)
# --------------------------------------------------------------------------- #
class TestHaystackPriority:
    def test_ws_data_wins_over_live(self):
        d = disc()
        data = {
            "ws_data": {"pars": [id_item("bt_battery_voltage", "60.0")]},
            "last_data": {"pars": [id_item("bt_battery_voltage", "50.0")]},
        }
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(60.0)

    def test_live_wins_over_cached_pars(self):
        # Same snake_case key present as id in live and par in cached pars.
        d = disc()
        data = {
            "last_data": {"pars": [id_item("bt_battery_charging_current", "12.0")]},
            "pars": {"parameter": [par_item("bt_battery_charging_current", "3.0")]},
        }
        assert d.resolve(PN, "battery_charging_current", data) == pytest.approx(12.0)

    def test_cached_pars_used_when_live_absent(self):
        d = disc()
        data = {
            "pars": {"parameter": [par_item("bt_battery_voltage", "48.0")]},
        }
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(48.0)

    def test_opposite_field_fallback_within_haystack(self):
        # candidate declares id, but only a par item exists in the live block.
        d = disc()
        data = {"last_data": {"pars": [par_item("bt_battery_voltage", "44.0")]}}
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(44.0)

    def test_par_status_zero_is_skipped(self):
        # primary par item offline (status 0) -> not returned.
        cand = ProviderKeyCandidate("bt_battery_voltage", MATCH_FIELD_PAR)
        haystack = {"parameter": [par_item("bt_battery_voltage", "44.0", status=0)]}
        assert MappingDiscovery._search_haystack(cand, haystack) is None

    def test_par_status_nonzero_returned(self):
        cand = ProviderKeyCandidate("bt_battery_voltage", MATCH_FIELD_PAR)
        haystack = {"parameter": [par_item("bt_battery_voltage", "44.0", status=1)]}
        item = MappingDiscovery._search_haystack(cand, haystack)
        assert item is not None and item["val"] == "44.0"

    def test_opposite_par_status_zero_blocks_fallback(self):
        # id candidate, only an offline par item exists -> None.
        cand = ProviderKeyCandidate("bt_battery_voltage", MATCH_FIELD_ID)
        haystack = {"parameter": [par_item("bt_battery_voltage", "44.0", status=0)]}
        assert MappingDiscovery._search_haystack(cand, haystack) is None

    def test_case_insensitive_key_match(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("BT_BATTERY_VOLTAGE", "53.0")]}}
        assert d.resolve(PN, "battery_voltage", data) == pytest.approx(53.0)


# --------------------------------------------------------------------------- #
# Pinning + re-discovery + dirty flag
# --------------------------------------------------------------------------- #
class TestPinningAndDirty:
    def test_fresh_instance_not_dirty(self):
        assert disc().is_dirty is False

    def test_dirty_set_after_discovery(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}}
        d.resolve(PN, "battery_voltage", data)
        assert d.is_dirty is True

    def test_pinned_shortcircuits_subsequent_resolve(self):
        d = disc()
        data = {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}}
        d.resolve(PN, "battery_voltage", data)
        # New tick, same pinned candidate, new value.
        data2 = {"last_data": {"pars": [id_item("bt_battery_voltage", "54.9")]}}
        assert d.resolve(PN, "battery_voltage", data2) == pytest.approx(54.9)

    def test_pin_falls_through_when_pinned_key_disappears(self):
        d = disc()
        # First pin to "Battery Voltage" (id) because bt_battery_voltage absent.
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("Battery Voltage", "12.0")]}})
        assert d.discovered_provider_key(PN, "battery_voltage").provider_key == "Battery Voltage"
        # Now "Battery Voltage" gone, bt_battery_voltage present -> re-discover.
        val = d.resolve(PN, "battery_voltage",
                        {"last_data": {"pars": [id_item("bt_battery_voltage", "48.0")]}})
        assert val == pytest.approx(48.0)
        assert d.discovered_provider_key(PN, "battery_voltage").provider_key == "bt_battery_voltage"

    def test_pin_disappears_entirely_returns_none(self):
        d = disc()
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "48.0")]}})
        # Key gone, nothing else matches.
        assert d.resolve(PN, "battery_voltage",
                         {"last_data": {"pars": [id_item("nope", "1")]}}) is None
        # Pin removed, dirty set.
        assert d.discovered_provider_key(PN, "battery_voltage") is None
        assert d.is_dirty is True

    def test_per_device_isolation(self):
        d = disc()
        d.resolve("PN_A", "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "10.0")]}})
        d.resolve("PN_B", "battery_voltage",
                  {"last_data": {"pars": [id_item("Battery Voltage", "20.0")]}})
        assert d.discovered_provider_key("PN_A", "battery_voltage").provider_key == "bt_battery_voltage"
        assert d.discovered_provider_key("PN_B", "battery_voltage").provider_key == "Battery Voltage"

    def test_discovered_provider_key_none_when_unresolved(self):
        assert disc().discovered_provider_key(PN, "battery_voltage") is None


# --------------------------------------------------------------------------- #
# Persistence lifecycle
# --------------------------------------------------------------------------- #
class TestPersistence:
    async def test_async_save_noop_when_not_dirty(self):
        storage = AsyncMock()
        d = MappingDiscovery(storage)
        await d.async_save()
        storage.save.assert_not_awaited()

    async def test_async_save_persists_snapshot_and_clears_dirty(self):
        storage = AsyncMock()
        d = MappingDiscovery(storage)
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}})
        assert d.is_dirty
        await d.async_save()
        storage.save.assert_awaited_once()
        snapshot = storage.save.await_args.args[0]
        assert snapshot["version"] == _SNAPSHOT_VERSION
        assert snapshot["devices"][PN]["battery_voltage"] == {
            "provider_key": "bt_battery_voltage",
            "match_field": "id",
        }
        assert d.is_dirty is False

    async def test_async_save_failure_keeps_dirty(self):
        storage = AsyncMock()
        storage.save.side_effect = RuntimeError("boom")
        d = MappingDiscovery(storage)
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}})
        await d.async_save()
        assert d.is_dirty is True

    async def test_roundtrip_save_then_load_restores_pins(self):
        storage = InMemoryMappingStorage()
        d1 = MappingDiscovery(storage)
        d1.resolve(PN, "battery_voltage",
                   {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}})
        await d1.async_save()

        d2 = MappingDiscovery(storage)
        await d2.async_load()
        pinned = d2.discovered_provider_key(PN, "battery_voltage")
        assert pinned is not None
        assert pinned.provider_key == "bt_battery_voltage"
        assert pinned.match_field == "id"
        # restored pin is not dirty
        assert d2.is_dirty is False

    async def test_load_empty_storage_noop(self):
        d = MappingDiscovery(InMemoryMappingStorage())
        await d.async_load()
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_load_is_idempotent(self):
        storage = AsyncMock()
        storage.load.return_value = None
        d = MappingDiscovery(storage)
        await d.async_load()
        await d.async_load()
        storage.load.assert_awaited_once()

    async def test_load_wrong_version_ignored(self):
        storage = InMemoryMappingStorage()
        await storage.save({
            "version": 1,
            "devices": {PN: {"battery_voltage": {
                "provider_key": "bt_battery_voltage", "match_field": "id"}}},
        })
        d = MappingDiscovery(storage)
        await d.async_load()
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_load_non_dict_ignored(self):
        storage = AsyncMock()
        storage.load.return_value = ["not", "a", "dict"]
        d = MappingDiscovery(storage)
        await d.async_load()  # must not raise
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_load_unknown_provider_key_skipped(self):
        storage = InMemoryMappingStorage()
        await storage.save({
            "version": _SNAPSHOT_VERSION,
            "devices": {PN: {"battery_voltage": {
                "provider_key": "ghost_key", "match_field": "id"}}},
        })
        d = MappingDiscovery(storage)
        await d.async_load()
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_load_bad_match_field_skipped(self):
        storage = InMemoryMappingStorage()
        await storage.save({
            "version": _SNAPSHOT_VERSION,
            "devices": {PN: {"battery_voltage": {
                "provider_key": "bt_battery_voltage", "match_field": "bogus"}}},
        })
        d = MappingDiscovery(storage)
        await d.async_load()
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_load_storage_exception_swallowed(self):
        storage = AsyncMock()
        storage.load.side_effect = RuntimeError("io error")
        d = MappingDiscovery(storage)
        await d.async_load()  # must not raise
        assert d.discovered_provider_key(PN, "battery_voltage") is None

    async def test_async_clear_resets_state_and_storage(self):
        storage = InMemoryMappingStorage()
        d = MappingDiscovery(storage)
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}})
        await d.async_save()
        await d.async_clear()
        assert d.discovered_provider_key(PN, "battery_voltage") is None
        assert d.is_dirty is False
        assert await storage.load() is None

    async def test_async_clear_storage_exception_swallowed(self):
        storage = AsyncMock()
        storage.clear.side_effect = RuntimeError("io error")
        d = MappingDiscovery(storage)
        d.resolve(PN, "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "53.2")]}})
        await d.async_clear()  # must not raise
        assert d.discovered_provider_key(PN, "battery_voltage") is None


# --------------------------------------------------------------------------- #
# Snapshot helper
# --------------------------------------------------------------------------- #
class TestSnapshot:
    def test_snapshot_groups_by_device(self):
        d = disc()
        d.resolve("PN_A", "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "10")]}})
        d.resolve("PN_A", "pv_power",
                  {"last_data": {"pars": [id_item("pv_power", "100")]}})
        d.resolve("PN_B", "battery_voltage",
                  {"last_data": {"pars": [id_item("bt_battery_voltage", "20")]}})
        snap = d._snapshot_locked()
        assert snap["version"] == _SNAPSHOT_VERSION
        assert set(snap["devices"]) == {"PN_A", "PN_B"}
        assert set(snap["devices"]["PN_A"]) == {"battery_voltage", "pv_power"}

    def test_empty_snapshot(self):
        snap = disc()._snapshot_locked()
        assert snap == {"version": _SNAPSHOT_VERSION, "devices": {}}
