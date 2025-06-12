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


class DirectCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""
    devices = []
    auth = None
    auth_issued_at = None

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Direct request sensor",
            config_entry=config_entry,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=10),
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
        print('direct coordinator setup devices count: ', len(self.devices))

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
        devices_filter = self.config_entry.options.get("devices", [])

        if devices_filter:
            selected_devices = [
                device for device in active_devices
                if str(device.get("pn")) in devices_filter
            ]
        else:
            selected_devices = active_devices
        return selected_devices

    async def _async_update_data(self):
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(30):
                if self.config_entry.options.get('direct_request_protocol', False) is not True:
                    return None
                print('direct coordinator update data devices')

                await self.check_auth()
                self.devices = await self.get_active_devices()

                token = self.auth['token']
                secret = self.auth['secret']

                async def fetch_device_data(device):
                    qpigs = await get_direct_data(token, secret, device, 'QPIGS')
                    qpigs2 = await get_direct_data(token, secret, device, 'QPIGS2')
                    qpiri = await get_direct_data(token, secret, device, 'QPIRI')
                    return device['pn'], {
                        'qpigs': qpigs,
                        'qpigs2': qpigs2,
                        'qpiri': qpiri
                    }

                data_map = dict(await asyncio.gather(*map(fetch_device_data, self.devices)))
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
