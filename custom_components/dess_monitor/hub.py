from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.dess_monitor.coordinators.coordinator import MainCoordinator
from custom_components.dess_monitor.coordinators.direct_coordinator import DirectCoordinator
from custom_components.dess_monitor.mapping import MappingDiscovery
from custom_components.dess_monitor.sdk import DessmonitorClient
from custom_components.dess_monitor.virtual_battery import VirtualBatteryEstimator


class Hub:
    manufacturer = "DESS Monitor"

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        client: DessmonitorClient,
        coordinator: MainCoordinator,
        direct_coordinator: DirectCoordinator,
        mapping: MappingDiscovery,
    ) -> None:
        self._username = username
        self._hass = hass
        self._name = username
        self._client = client
        self.coordinator = coordinator
        self.direct_coordinator = direct_coordinator
        self._mapping = mapping
        self._id = username.lower()
        self.items: list[InverterDevice] = []

    @property
    def hub_id(self) -> str:
        return self._id

    @property
    def client(self) -> DessmonitorClient:
        return self._client

    @property
    def mapping(self) -> MappingDiscovery:
        return self._mapping

    @property
    def online(self) -> bool:
        return bool(self.coordinator and self.coordinator.last_update_success)

    async def init(self) -> None:
        for device in self.coordinator.devices:
            self.items.append(
                InverterDevice(f"{device['pn']}", f"{device['devalias']}", device, self)
            )


class InverterDevice:

    def __init__(self, inverter_pn: str, name: str, device_data: dict[str, Any], hub: Hub) -> None:
        self._id = inverter_pn
        self.hub = hub
        self.device_data = device_data
        self.name = name
        self.firmware_version = "0.0.1"
        self.model = "DESS Device"
        self.virtual_battery: VirtualBatteryEstimator | None = None

    @property
    def inverter_id(self) -> str:
        return self._id

    @property
    def online(self) -> bool:
        data = self.hub.coordinator.data
        if data is None or self.inverter_id not in data:
            return False
        return True

    def resolve(self, canonical_name: str, data: dict[str, Any]) -> float | str | None:
        """Look up a canonical metric in this device's tick data."""
        return self.hub.mapping.resolve(self._id, canonical_name, data)
