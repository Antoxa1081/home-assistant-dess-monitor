"""Tests for ``custom_components.dess_monitor.config_flow``."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dess_monitor.config_flow import InvalidAuth, validate_input
from custom_components.dess_monitor.const import (
    CONF_DIRECT_PROTOCOL,
    DEFAULT_DIRECT_PROTOCOL,
    DIRECT_PROTOCOL_PI18,
    DOMAIN,
)

CLIENT_SYMBOL = "custom_components.dess_monitor.config_flow.DessmonitorClient"


def _device(pn="PN1", status=0, **extra):
    base = {
        "pn": pn,
        "sn": f"SN_{pn}",
        "devcode": 2376,
        "devaddr": 1,
        "status": status,
        "uid": "u1",
        "devalias": f"Inv {pn}",
    }
    base.update(extra)
    return base


def _fake_client(devices):
    """Return a MagicMock standing in for DessmonitorClient with async resources."""
    client = MagicMock()
    client.auth.login = AsyncMock(return_value=None)
    client.devices.list = AsyncMock(return_value=devices)
    return client


def _user_input(username="tester", password="secret", **extra):
    data = {
        "username": username,
        "password": password,
        "dynamic_settings": False,
        "raw_sensors": False,
        "direct_request_protocol": False,
        CONF_DIRECT_PROTOCOL: DEFAULT_DIRECT_PROTOCOL,
    }
    data.update(extra)
    return data


# --- validate_input ----------------------------------------------------------


class TestValidateInput:
    async def test_returns_title_hash_and_devices(self, hass) -> None:
        devices = [_device("PN1"), _device("PN2")]
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await validate_input(hass, {"username": "tester", "password": "secret"})

        assert result["title"] == "tester"
        assert result["password_hash"] == hashlib.sha1(b"secret").hexdigest()
        assert result["devices"] == devices

    async def test_login_failure_raises_invalid_auth(self, hass) -> None:
        client = _fake_client([])
        client.auth.login = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(CLIENT_SYMBOL, return_value=client):
            with pytest.raises(InvalidAuth):
                await validate_input(hass, {"username": "x", "password": "y"})

    async def test_devices_list_failure_raises_invalid_auth(self, hass) -> None:
        client = _fake_client([])
        client.devices.list = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(CLIENT_SYMBOL, return_value=client):
            with pytest.raises(InvalidAuth):
                await validate_input(hass, {"username": "x", "password": "y"})


# --- ConfigFlow --------------------------------------------------------------


class TestConfigFlow:
    async def test_user_step_shows_form(self, hass) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    async def test_invalid_auth_sets_username_error(self, hass) -> None:
        client = _fake_client([])
        client.auth.login = AsyncMock(side_effect=RuntimeError("nope"))
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch(CLIENT_SYMBOL, return_value=client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _user_input()
            )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"username": "invalid_auth"}

    async def test_valid_input_advances_to_select_devices(self, hass) -> None:
        devices = [_device("PN1"), _device("PN2")]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _user_input()
            )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_devices"

    async def test_inactive_devices_filtered_out(self, hass) -> None:
        # status == 1 means inactive and is excluded; the select form should
        # only offer PN_ACTIVE.
        devices = [_device("PN_ACTIVE", status=0), _device("PN_INACTIVE", status=1)]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _user_input()
            )
        # Drill into the select selector options to confirm filtering.
        schema = result["data_schema"].schema
        selector_cfg = next(iter(schema.values()))
        options = selector_cfg.config["options"]
        values = {opt["value"] for opt in options}
        assert values == {"PN_ACTIVE"}

    async def test_select_devices_creates_entry(self, hass) -> None:
        devices = [_device("PN1"), _device("PN2")]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                _user_input(dynamic_settings=True, raw_sensors=True,
                            direct_request_protocol=True,
                            **{CONF_DIRECT_PROTOCOL: DIRECT_PROTOCOL_PI18}),
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"devices": ["PN1"]}
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "tester"
        data = result["data"]
        assert data["username"] == "tester"
        assert data["password_hash"] == hashlib.sha1(b"secret").hexdigest()
        assert data["devices"] == ["PN1"]
        assert data["dynamic_settings"] is True
        assert data["raw_sensors"] is True
        assert data["direct_request_protocol"] is True
        assert data[CONF_DIRECT_PROTOCOL] == DIRECT_PROTOCOL_PI18

    async def test_select_devices_empty_reshows_form(self, hass) -> None:
        devices = [_device("PN1")]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _user_input()
            )
            # Empty selection -> no entry created, form re-shown.
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"devices": []}
            )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_devices"


# --- OptionsFlow -------------------------------------------------------------


class TestOptionsFlow:
    def _entry(self, hass, options=None):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "tester", "password_hash": "0" * 40},
            options=options or {},
            title="tester",
        )
        entry.add_to_hass(hass)
        return entry

    async def test_init_shows_form_with_devices(self, hass) -> None:
        entry = self._entry(hass)
        devices = [_device("PN1"), _device("PN2", status=1)]
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"
        schema = result["data_schema"].schema
        selector_cfg = next(iter(schema.values()))
        options = selector_cfg.config["options"]
        values = {opt["value"] for opt in options}
        # status == 1 filtered out.
        assert values == {"PN1"}

    async def test_submitting_options_creates_entry(self, hass) -> None:
        entry = self._entry(hass)
        devices = [_device("PN1")]
        with patch(CLIENT_SYMBOL, return_value=_fake_client(devices)):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {
                    "devices": ["PN1"],
                    "dynamic_settings": True,
                    "raw_sensors": False,
                    "direct_request_protocol": False,
                    CONF_DIRECT_PROTOCOL: DEFAULT_DIRECT_PROTOCOL,
                    "main_update_interval": 60,
                    "direct_update_interval": 10,
                    "dynamic_settings_interval": 300,
                    "enable_websocket": False,
                    "battery_virtual_enabled": False,
                    "enable_last_at_sensors": False,
                },
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["devices"] == ["PN1"]
        assert result["data"]["dynamic_settings"] is True
