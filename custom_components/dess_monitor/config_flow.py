from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .api import auth_user, get_devices
from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)


class WorkMode(str, Enum):
    ALL = "all"
    CLOUD = "cloud"
    DIRECT = "direct"


# Configuration schema for the initial setup form
DATA_SCHEMA = vol.Schema({
    vol.Required("username"): str,
    vol.Required("password"): str,
    vol.Optional("dynamic_settings", default=False): bool,
    vol.Optional("raw_sensors", default=False): bool,
    vol.Optional("direct_request_protocol", default=False): bool,
    vol.Optional("work_mode", default=WorkMode.ALL.value): selector({
        "select": {
            "options": [
                {"value": mode.value, "label": mode.name.title()} for mode in WorkMode
            ]
        }
    }),
})


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    password_hash = hashlib.sha1(data["password"].encode()).hexdigest()
    try:
        auth = await auth_user(data["username"], password_hash)
        return {"title": data["username"], 'auth': auth, 'password_hash': password_hash}
    except Exception:
        raise InvalidAuth


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._devices: list[Any] = []
        self._dynamic_settings = False
        self._direct_request_protocol = False
        self._raw_sensors = False
        self._work_mode = WorkMode.ALL
        self._username: str | None = None
        self._password_hash: str | None = None
        self._info: dict[str, Any] | None = None

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                self._info = info
                self._username = user_input['username']
                self._password_hash = info['password_hash']
                self._dynamic_settings = user_input['dynamic_settings']
                self._raw_sensors = user_input['raw_sensors']
                self._direct_request_protocol = user_input['direct_request_protocol']
                self._work_mode = WorkMode(user_input['work_mode'])

                devices = await get_devices(info['auth']['token'], info['auth']['secret'])
                self._devices = [d for d in devices if d['status'] != 1]
                return await self.async_step_select_devices()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["username"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_select_devices(self, user_input=None):
        if user_input is not None:
            devices = user_input["devices"]
            if devices:
                return self.async_create_entry(
                    title=self._info["title"],
                    data={
                        'username': self._username,
                        'password_hash': self._password_hash,
                        'dynamic_settings': self._dynamic_settings,
                        'raw_sensors': self._raw_sensors,
                        'direct_request_protocol': self._direct_request_protocol,
                        'work_mode': self._work_mode.value,
                        'devices': devices,
                    },
                )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=vol.Schema({
                vol.Required("devices"): selector({
                    "select": {
                        "multiple": True,
                        "options": [
                            {"value": str(d['pn']), "label": f"{d['devalias']}; pn: {d['pn']}; devcode: {d['devcode']}"}
                            for d in self._devices
                        ]
                    }
                })
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry
        self._devices: list[Any] = []

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        username = self._config_entry.data["username"]
        password_hash = self._config_entry.data["password_hash"]
        auth = await auth_user(username, password_hash)
        devices = await get_devices(auth['token'], auth['secret'])
        self._devices = [d for d in devices if d['status'] != 1]

        options_schema = vol.Schema({
            vol.Required(
                "devices",
                default=self._config_entry.options.get('devices', [str(d['pn']) for d in self._devices])
            ): selector({
                "select": {
                    "multiple": True,
                    "options": [
                        {"value": str(d['pn']), "label": f"{d['devalias']}; pn: {d['pn']}; devcode: {d['devcode']}"}
                        for d in self._devices
                    ]
                }
            }),
            vol.Optional(
                "dynamic_settings",
                default=self._config_entry.options.get('dynamic_settings', False)
            ): bool,
            vol.Optional(
                "raw_sensors",
                default=self._config_entry.options.get('raw_sensors', False)
            ): bool,
            vol.Optional(
                "direct_request_protocol",
                default=self._config_entry.options.get('direct_request_protocol', False)
            ): bool,
            vol.Optional(
                "work_mode",
                default=self._config_entry.options.get('work_mode', WorkMode.ALL.value)
            ): selector({
                "select": {
                    "options": [
                        {"value": mode.value, "label": mode.name.title()} for mode in WorkMode
                    ]
                }
            }),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid authentication."""
