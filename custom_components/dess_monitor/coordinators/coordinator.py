import logging
from datetime import timedelta

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)

from custom_components.dess_monitor.api import *
from custom_components.dess_monitor.api.helpers import *

_LOGGER = logging.getLogger(__name__)


async def safe_call(coro, default=None):
    try:
        return await coro
    except Exception as e:
        print(f"Error during {coro}: {e}")
        return default


class MainCoordinator(DataUpdateCoordinator):
    devices = []
    auth = None
    auth_issued_at = None

    def __init__(self, hass: HomeAssistant, config_entry):
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Main coordinator",
            config_entry=config_entry,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=60),
            # Set always_update to `False` if the data returned from the
            # api can be compared via `__eq__` to avoid duplicate updates
            # being dispatched to listeners
            always_update=False

        )
        # self.my_api = my_api
        # self._device: MyDevice | None = None

    async def _async_setup(self):
        """Set up the coordinator

        This is the place to set up your coordinator,
        or to load data, that only needs to be loaded once.

        This method will be called automatically during
        coordinator.async_config_entry_first_refresh.
        """
        await self.create_auth()

        self.devices = await self.get_active_devices()
        print('coordinator setup devices count: ', len(self.devices))

        # token = self.auth['token']
        # secret = self.auth['secret']
        # query_device_ctrl_fields = [get_device_ctrl_fields(token, secret, device) for device in self.devices]
        # query_device_ctrl_fields_results = await asyncio.gather(*query_device_ctrl_fields)
        # for i, device_field_data in enumerate(query_device_ctrl_fields_results):
        #     for k, field_data in device_field_data['field']:
        #         async_add_entities(InverterDynamicSettingSelect())
        # await self.async_refresh()
        # await self._async_update_data()

    async def create_auth(self):
        username = self.config_entry.data["username"]
        password_hash = self.config_entry.data["password_hash"]
        auth = await auth_user(username, password_hash)
        auth_issued_at = int(datetime.now().timestamp())

        self.auth = auth
        self.auth_issued_at = auth_issued_at

    async def check_auth(self):
        now = int(datetime.now().timestamp())
        # print(self.auth)
        if self.auth_issued_at is None or (now - (self.auth_issued_at + (self.auth['expire'])) <= 3600):
            await self.create_auth()

    async def get_active_devices(self):
        devices = await get_devices(self.auth['token'], self.auth['secret'])
        active_devices = [device for device in devices if device['status'] != 1]
        selected_devices = [device for device in active_devices if
                            str(device['pn']) in self.config_entry.options["devices"] or str(device['uid']) in
                            self.config_entry.options["devices"]] if (
                "devices" in self.config_entry.options and len(
            self.config_entry.options["devices"]) > 0) else active_devices
        return selected_devices

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            async with async_timeout.timeout(120):
                print('coordinator update data devices')

                await self.check_auth()
                self.devices = await self.get_active_devices()

                token = self.auth['token']
                secret = self.auth['secret']

                async def build_device_data(device):
                    pn = device['pn']
                    last_data = await safe_call(get_device_last_data(token, secret, device), default={})
                    energy_flow = await safe_call(get_device_energy_flow(token, secret, device), default={})
                    pars = await safe_call(get_device_pars(token, secret, device), default={})
                    ctrl_fields = await safe_call(get_device_ctrl_fields(token, secret, device), default={'field': []})
                    output_priority = await safe_call(get_inverter_output_priority(token, secret, ctrl_fields, device), default={})

                    return pn, {
                        'last_data': last_data,
                        'energy_flow': energy_flow,
                        'pars': pars,
                        'device': device,
                        'ctrl_fields': ctrl_fields.get('field', []),
                        'device_extra': {
                            'output_priority': output_priority,
                        }
                    }

                tasks = [build_device_data(device) for device in self.devices]

                device_data = await asyncio.gather(*tasks)

                data_map = {pn: data for pn, data in device_data}

                return data_map
                # return
        except TimeoutError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise err
        except AuthInvalidateError:
            await self.create_auth()
            # raise ConfigEntryAuthFailed from err
        # except ApiError as err:
