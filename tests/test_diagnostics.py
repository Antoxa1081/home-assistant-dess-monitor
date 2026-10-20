"""Tests for ``custom_components.dess_monitor.diagnostics``."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dess_monitor.const import DOMAIN
from custom_components.dess_monitor.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

REDACTED = "**REDACTED**"


class TestConfigEntryDiagnostics:
    async def test_redacts_sensitive_fields(self, hass) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="My Inverter",
            data={
                "username": "tester",
                "password_hash": "0" * 40,
                "email": "a@b.c",
                "title": "secret-title",
                "dynamic_settings": True,
            },
            options={"devices": ["PN1"]},
        )
        entry.add_to_hass(hass)

        result = await async_get_config_entry_diagnostics(hass, entry)

        ce = result["config_entry"]
        assert ce["title"] == "My Inverter"
        data = ce["data"]
        assert data["username"] == REDACTED
        assert data["password_hash"] == REDACTED
        assert data["email"] == REDACTED
        assert data["title"] == REDACTED
        # Non-sensitive field passes through untouched.
        assert data["dynamic_settings"] is True
        assert ce["options"] == {"devices": ["PN1"]}


class TestDeviceDiagnostics:
    async def test_returns_redacted_device_data_and_direct_data(self, hass) -> None:
        device_model = "PN1"
        coordinator_data = {
            device_model: {
                "devalias": "Inv 1",
                "pn": "PN1",
                "sn": "SN1",
                "collalias": "coll",
                "usr": "user",
                "voltage": 230,
            }
        }
        direct_data = {device_model: {"raw": "ascii-stuff"}}

        entry = SimpleNamespace(
            runtime_data=SimpleNamespace(
                coordinator=SimpleNamespace(data=coordinator_data),
                direct_coordinator=SimpleNamespace(data=direct_data),
            )
        )
        device = SimpleNamespace(hw_version=2376, model=device_model)

        result = await async_get_device_diagnostics(hass, entry, device)

        dev = result["device"]
        assert dev["devcode"] == 2376
        data = dev["data"]
        for redacted_key in ("devalias", "pn", "sn", "collalias", "usr"):
            assert data[redacted_key] == REDACTED
        assert data["voltage"] == 230
        assert dev["direct_data"] == {"raw": "ascii-stuff"}

    async def test_direct_data_none_yields_empty(self, hass) -> None:
        device_model = "PN1"
        entry = SimpleNamespace(
            runtime_data=SimpleNamespace(
                coordinator=SimpleNamespace(data={device_model: {"voltage": 1}}),
                direct_coordinator=SimpleNamespace(data=None),
            )
        )
        device = SimpleNamespace(hw_version=1, model=device_model)

        result = await async_get_device_diagnostics(hass, entry, device)
        assert result["device"]["direct_data"] == {}

    async def test_direct_data_missing_model_yields_empty(self, hass) -> None:
        device_model = "PN1"
        entry = SimpleNamespace(
            runtime_data=SimpleNamespace(
                coordinator=SimpleNamespace(data={device_model: {"voltage": 1}}),
                direct_coordinator=SimpleNamespace(data={"OTHER": {"x": 1}}),
            )
        )
        device = SimpleNamespace(hw_version=1, model=device_model)

        result = await async_get_device_diagnostics(hass, entry, device)
        assert result["device"]["direct_data"] == {}
