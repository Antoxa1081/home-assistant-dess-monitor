"""Unit tests for the mapping seed catalog (``mapping/seed.py``).

Pure logic — no Home Assistant. Asserts structural invariants of the
``CANONICAL_METRICS`` catalog and the behaviour of the frozen
``ProviderKeyCandidate`` dataclass.
"""
from __future__ import annotations

import dataclasses

import pytest

from custom_components.dess_monitor.mapping import (
    CANONICAL_METRICS,
    MATCH_FIELD_ID,
    MATCH_FIELD_PAR,
    SIGN_NEGATIVE,
    SIGN_POSITIVE,
    ProviderKeyCandidate,
)
from custom_components.dess_monitor.mapping.seed import (
    _CHARGE_PRIORITY_MAP,
    _MAINS_STATUS_MAP,
    _OUTPUT_PRIORITY_MAP,
)


class TestModuleConstants:
    def test_match_field_values(self):
        assert MATCH_FIELD_ID == "id"
        assert MATCH_FIELD_PAR == "par"

    def test_sign_values(self):
        assert SIGN_POSITIVE == "+"
        assert SIGN_NEGATIVE == "-"


class TestProviderKeyCandidate:
    def test_defaults(self):
        cand = ProviderKeyCandidate("foo", MATCH_FIELD_ID)
        assert cand.provider_key == "foo"
        assert cand.match_field == "id"
        assert cand.scale == 1.0
        assert cand.offset == 0.0
        assert cand.unit_hint is None
        assert cand.value_map is None
        assert cand.sign is None

    def test_frozen_is_immutable(self):
        cand = ProviderKeyCandidate("foo", MATCH_FIELD_ID)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cand.scale = 2.0  # type: ignore[misc]

    def test_is_hashable(self):
        # frozen dataclasses are hashable; the catalog/cache relies on this.
        cand = ProviderKeyCandidate("foo", MATCH_FIELD_ID)
        assert isinstance(hash(cand), int)
        assert {cand: 1}[cand] == 1

    def test_equality(self):
        a = ProviderKeyCandidate("foo", MATCH_FIELD_ID, scale=2.0)
        b = ProviderKeyCandidate("foo", MATCH_FIELD_ID, scale=2.0)
        c = ProviderKeyCandidate("foo", MATCH_FIELD_PAR, scale=2.0)
        assert a == b
        assert a != c

    def test_all_fields_supplied(self):
        vm = {"x": "Y"}
        cand = ProviderKeyCandidate(
            "k", MATCH_FIELD_PAR, scale=0.1, offset=-1.0,
            unit_hint="V", value_map=vm, sign=SIGN_POSITIVE,
        )
        assert cand.scale == pytest.approx(0.1)
        assert cand.offset == pytest.approx(-1.0)
        assert cand.unit_hint == "V"
        assert cand.value_map is vm
        assert cand.sign == "+"


def _all_candidates():
    for canonical, cands in CANONICAL_METRICS.items():
        for cand in cands:
            yield canonical, cand


class TestCatalogStructure:
    def test_catalog_is_nonempty_dict(self):
        assert isinstance(CANONICAL_METRICS, dict)
        assert len(CANONICAL_METRICS) > 0

    def test_canonical_names_are_strings(self):
        for name in CANONICAL_METRICS:
            assert isinstance(name, str)
            assert name  # non-empty

    def test_every_value_is_nonempty_list(self):
        for name, cands in CANONICAL_METRICS.items():
            assert isinstance(cands, list), name
            assert len(cands) > 0, name

    def test_all_entries_are_candidates(self):
        for name, cand in _all_candidates():
            assert isinstance(cand, ProviderKeyCandidate), name

    def test_match_field_is_valid(self):
        for name, cand in _all_candidates():
            assert cand.match_field in (MATCH_FIELD_ID, MATCH_FIELD_PAR), (
                name, cand.provider_key
            )

    def test_provider_key_nonempty_string(self):
        for _name, cand in _all_candidates():
            assert isinstance(cand.provider_key, str)
            assert cand.provider_key

    def test_scale_is_positive_finite(self):
        for name, cand in _all_candidates():
            assert isinstance(cand.scale, (int, float))
            assert cand.scale > 0, (name, cand.provider_key)

    def test_offset_is_finite_number(self):
        for _name, cand in _all_candidates():
            assert isinstance(cand.offset, (int, float))

    def test_sign_is_valid(self):
        for name, cand in _all_candidates():
            assert cand.sign in (None, SIGN_POSITIVE, SIGN_NEGATIVE), (
                name, cand.provider_key
            )

    def test_value_map_is_mapping_str_to_str(self):
        for name, cand in _all_candidates():
            if cand.value_map is None:
                continue
            for k, v in cand.value_map.items():
                assert isinstance(k, str), (name, k)
                assert isinstance(v, str), (name, v)

    def test_no_duplicate_candidates_within_a_metric(self):
        """A (provider_key, match_field, sign) triple shouldn't repeat —
        a duplicate would be dead weight in the resolve loop."""
        for name, cands in CANONICAL_METRICS.items():
            seen = set()
            for c in cands:
                key = (c.provider_key, c.match_field, c.sign)
                assert key not in seen, (name, key)
                seen.add(key)


class TestOrderingInvariant:
    """Doc invariant: when the same *snake_case* provider_key has both id and
    par variants in a metric, the id variant comes first (prefer live data).

    The rule is explicitly scoped to snake_case keys in seed.py's module
    docstring. Human-label keys (e.g. "Mains Status") are ordered case by
    case per firmware and are intentionally excluded.
    """

    @staticmethod
    def _is_snake_case(key: str) -> bool:
        return key == key.lower() and " " not in key

    def test_id_before_par_for_same_snake_case_key(self):
        checked = 0
        for name, cands in CANONICAL_METRICS.items():
            first_id: dict[str, int] = {}
            first_par: dict[str, int] = {}
            for idx, c in enumerate(cands):
                if not self._is_snake_case(c.provider_key):
                    continue
                if c.match_field == MATCH_FIELD_ID:
                    first_id.setdefault(c.provider_key, idx)
                else:
                    first_par.setdefault(c.provider_key, idx)
            for key, par_idx in first_par.items():
                if key in first_id:
                    checked += 1
                    assert first_id[key] < par_idx, (name, key)
        assert checked > 0  # the invariant actually exercised something


class TestValueMaps:
    @pytest.mark.parametrize("vmap", [
        _OUTPUT_PRIORITY_MAP, _CHARGE_PRIORITY_MAP, _MAINS_STATUS_MAP,
    ])
    def test_keys_are_lowercase(self, vmap):
        # _extract lowercases the raw value before lookup, so keys must be
        # lowercase or they can never match.
        for k in vmap:
            assert k == k.lower(), k

    @pytest.mark.parametrize("vmap", [
        _OUTPUT_PRIORITY_MAP, _CHARGE_PRIORITY_MAP, _MAINS_STATUS_MAP,
    ])
    def test_values_nonempty_strings(self, vmap):
        for v in vmap.values():
            assert isinstance(v, str) and v

    def test_output_priority_known_entries(self):
        assert _OUTPUT_PRIORITY_MAP["uti"] == "Utility"
        assert _OUTPUT_PRIORITY_MAP["sbu"] == "SBU"
        assert _OUTPUT_PRIORITY_MAP["solar first"] == "Solar"

    def test_charge_priority_known_entries(self):
        assert _CHARGE_PRIORITY_MAP["solar priority"] == "SOLAR_PRIORITY"
        assert _CHARGE_PRIORITY_MAP["only pv"] == "SOLAR_ONLY"
        assert _CHARGE_PRIORITY_MAP["off"] == "NONE"

    def test_mains_status_known_entries(self):
        assert _MAINS_STATUS_MAP["battery mode"] == "BATTERY"
        assert _MAINS_STATUS_MAP["grid"] == "GRID"
        assert _MAINS_STATUS_MAP["fault"] == "FAULT"

    def test_mains_status_chinese_variants_present(self):
        # 电池模式 -> BATTERY
        assert _MAINS_STATUS_MAP["电池模式"] == "BATTERY"


class TestSpecificMetricExpectations:
    def test_battery_charging_current_has_sign_positive_first(self):
        first = CANONICAL_METRICS["battery_charging_current"][0]
        assert first.sign == SIGN_POSITIVE

    def test_battery_discharge_current_has_sign_negative_first(self):
        first = CANONICAL_METRICS["battery_discharge_current"][0]
        assert first.sign == SIGN_NEGATIVE

    def test_priority_metrics_carry_value_maps(self):
        for c in CANONICAL_METRICS["output_priority"]:
            assert c.value_map is _OUTPUT_PRIORITY_MAP
        for c in CANONICAL_METRICS["charge_priority"]:
            assert c.value_map is _CHARGE_PRIORITY_MAP
        for c in CANONICAL_METRICS["mains_status"]:
            assert c.value_map is _MAINS_STATUS_MAP

    def test_numeric_metrics_have_no_value_map(self):
        for c in CANONICAL_METRICS["battery_voltage"]:
            assert c.value_map is None
