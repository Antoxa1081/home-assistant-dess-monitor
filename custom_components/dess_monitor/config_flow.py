from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .api import auth_user, get_devices
from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

# This is the schema that used to display the UI to the user. This simple
# schema has a single required host field, but it could include a number of fields
# such as username, password etc. See other components in the HA core code for
# further examples.
# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations
# At the time of writing I found the translations created by the scaffold didn't
# quite work as documented and always gave me the "Lokalise key references" string
# (in square brackets), rather than the actual translated value. I did not attempt to
# figure this out or look further into it.


DATA_SCHEMA = vol.Schema({
    vol.Required("username"): str,
    vol.Required("password"): str,
    vol.Optional("dynamic_settings", default=False): bool,
    vol.Optional("raw_sensors", default=False): bool,
    vol.Optional("direct_request_protocol", default=False): bool,
})


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.
    # if len(data["username"]) < 3:
    #     raise InvalidHost

    # hub = Hub(hass, data["username"])
    # The dummy hub provides a `test_connection` method to ensure it's working
    # as expected

    # result = await hub.init()
    password_hash = hashlib.sha1(data["password"].encode()).hexdigest()
    try:
        auth = await auth_user(data["username"], password_hash)
        return {"title": data["username"], 'auth': auth, 'password_hash': password_hash}
    except Exception as e:
        raise InvalidAuth
    # if not result:
    #     # If there is an error, raise an exception to notify HA that there was a
    #     # problem. The UI will also show there was a problem
    #     raise CannotConnect

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this hub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._devices = []
        self._dynamic_settings = False
        self._direct_request_protocol = False
        self._raw_sensors = False
        self._username = None
        self._password_hash = None
        self._info = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                self._info = info
                self._username = user_input['username']
                self._password_hash = info['password_hash']
                self._dynamic_settings = user_input['dynamic_settings']
                self._direct_request_protocol = user_input['direct_request_protocol']
                self._raw_sensors = user_input['raw_sensors']
                devices = await get_devices(info['auth']['token'], info['auth']['secret'])
                active_devices = [device for device in devices if device['status'] != 1]
                self._devices = active_devices
                return await self.async_step_select_devices()
                # return self.async_create_entry(title=info["title"], data={
                #     'username': user_input['username'],
                #     'password_hash': info['password_hash'],
                #     'dynamic_settings': user_input['dynamic_settings'],
                #     # 'raw_sensors': user_input['raw_sensors'],
                # })
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                # The error string is set here, and should be translated.
                # This example does not currently cover translations, see the
                # comments on `DATA_SCHEMA` for further details.
                # Set the error on the `host` field, not the entire form.
                errors["username"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_select_devices(self, user_input=None):
        if user_input is not None:
            devices = user_input["devices"]  # List of selected device IDs
            # print("devices_selected", devices)
            if len(devices) > 0:
                return self.async_create_entry(title=self._info["title"], data={
                    'username': self._username,
                    'password_hash': self._password_hash,
                    'dynamic_settings': self._dynamic_settings,
                    'direct_request_protocol': self._direct_request_protocol,
                    'devices': devices,
                    'raw_sensors': self._raw_sensors,
                })

        return self.async_show_form(
            step_id="select_devices",
            data_schema=vol.Schema({
                vol.Required("devices"): selector({
                    "select": {
                        "multiple": True,
                        "options": [
                            {
                                "value": str(device['pn']),
                                "label": f'{device['devalias']}; pn: {device['pn']}; devcode: {device['devcode']}'
                            }
                            for device in self._devices
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
        self._devices = []  # All available devices

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # print('user_input', user_input)
            return self.async_create_entry(data=user_input)

        # Get login data from the config entry
        username = self._config_entry.data["username"]
        password_hash = self._config_entry.data["password_hash"]
        auth = await auth_user(username, password_hash)
        devices = await get_devices(auth['token'], auth['secret'])
        active_devices = [device for device in devices if device['status'] != 1]
        self._devices = active_devices

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "devices",
                    default=self._config_entry.options.get('devices',
                                                           list(map(lambda x: str(x['pn']), active_devices)))
                ): selector({
                    "select": {
                        "multiple": True,
                        "options": [
                            {"value": str(device['pn']),
                             "label": f'{device['devalias']}; pn: {device['pn']}; devcode: {device['devcode']}'}
                            for device in self._devices
                        ]
                    }
                }),
                vol.Optional("dynamic_settings",
                             default=self._config_entry.options.get('dynamic_settings', False)): bool,
                vol.Optional("raw_sensors",
                             default=self._config_entry.options.get('raw_sensors', False)): bool,
                vol.Optional("direct_request_protocol",
                             default=self._config_entry.options.get('direct_request_protocol', False)): bool,
            })
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""
