from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.coordinators.direct_coordinator import DirectCoordinator


class Hub:
    manufacturer = "DESS Monitor"

    def __init__(self, hass: HomeAssistant, username: str, coordinator: MainCoordinator = None,
                 direct_coordinator1: DirectCoordinator = None) -> None:
        self.auth = None
        self._username = username
        self._hass = hass
        self._name = username
        self.coordinator = coordinator
        self.direct_coordinator = direct_coordinator1
        self._id = username.lower()
        print('init hub', username)
        self.items = []
        self.online = True

    @property
    def hub_id(self) -> str:
        return self._id

    async def init(self):
        devices = self.coordinator.devices
        for device in devices:
            # print(device)
            inverter_device = InverterDevice(f"{device['pn']}", f"{device['devalias']}", device, self)
            self.items.append(inverter_device)


class InverterDevice:

    def __init__(self, inverter_pn: str, name: str, device_data, hub: Hub) -> None:
        self._id = inverter_pn
        self.hub = hub
        self.device_data = device_data
        self.name = name
        self.firmware_version = f"0.0.1"
        self.model = "DESS Device"

    @property
    def inverter_id(self) -> str:
        return self._id

    @property
    def online(self) -> float:
        if self.hub.coordinator.data is not None and self.inverter_id not in self.hub.coordinator.data:
            return False
        return True
