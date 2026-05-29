"""Tests for util.resolve_number_with_unit."""
from __future__ import annotations

import pytest

from custom_components.dess_monitor.util import resolve_number_with_unit


class TestResolveNumberWithUnit:
    @pytest.mark.parametrize("value,expected", [
        ("230.5 V", 230.5),
        ("50Hz", 50.0),
        ("27.00", 27.0),
        ("100%", 100.0),
        ("-12.3 A", -12.3),
        ("1500W", 1500.0),
    ])
    def test_strips_unit_and_returns_float(self, value, expected):
        assert resolve_number_with_unit(value) == pytest.approx(expected)

    def test_keeps_digits_dot_and_minus_only(self):
        # Letters are stripped; '.' and '-' kept.
        assert resolve_number_with_unit("V-12.5kW") == pytest.approx(-12.5)

    def test_non_numeric_returns_original_string(self):
        # Stripping leaves "" which float() rejects -> original returned.
        assert resolve_number_with_unit("abc") == "abc"

    def test_empty_string_returns_original(self):
        assert resolve_number_with_unit("") == ""

    def test_only_unit_returns_original(self):
        assert resolve_number_with_unit("kWh") == "kWh"

    def test_multiple_dots_falls_back_to_original(self):
        # "1.2.3 V" -> "1.2.3" which float() rejects -> original returned.
        assert resolve_number_with_unit("1.2.3 V") == "1.2.3 V"

    def test_integer_string(self):
        result = resolve_number_with_unit("42")
        assert result == pytest.approx(42.0)
        assert isinstance(result, float)
