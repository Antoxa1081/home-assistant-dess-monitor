from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from custom_components.dess_monitor.api.direct_service import DirectService
from custom_components.dess_monitor.api.protocols import Pi18Protocol, Smg2ModbusProtocol
from custom_components.dess_monitor.api.protocols.base import ProtocolBinding
from custom_components.dess_monitor.api.transports import CloudHexTransport
from custom_components.dess_monitor.const import (
    CONF_DIRECT_PROTOCOL,
    CONF_DIRECT_UPDATE_INTERVAL,
    DEFAULT_DIRECT_PROTOCOL,
    DEFAULT_DIRECT_UPDATE_INTERVAL,
    DIRECT_PROTOCOL_PI18,
    DIRECT_PROTOCOL_SMG2,
    MAX_DIRECT_UPDATE_INTERVAL,
    MIN_DIRECT_UPDATE_INTERVAL,
)
from custom_components.dess_monitor.coordinators.coordinator import _clamp
from custom_components.dess_monitor.device_cache import DeviceCache
from custom_components.dess_monitor.sdk import AuthError, DessmonitorClient, TransportError

_LOGGER = logging.getLogger(__name__)


# Poll plans per protocol. Sensors read by *section name* (``qpigs``/``qpiri``/
# ``qpigs2``), insulated from which underlying command produced the data.
_AXPERT_BINDING = ProtocolBinding(
    protocol_name="axpert",
    sections={
        "qpigs": "QPIGS",
        "qpigs2": "QPIGS2",
        "qpiri": "QPIRI",
    },
)

# SMG-II Modbus has no QPIGS2 register block; skipping it keeps the polling
# loop quick rather than wasting a transaction on an "unsupported" reply.
_SMG2_BINDING = ProtocolBinding(
    protocol_name="smg2_modbus",
    sections={
        "qpigs": "QPIGS",
        "qpiri": "QPIRI",
    },
)

# PI18 packs PV1+PV2 into a single GS reply. Both sections point at the
# same logical command — the coordinator deduplicates the round-trip and
# the protocol decoder returns a multi-section dict (``qpigs`` + ``qpigs2``).
_PI18_BINDING = ProtocolBinding(
    protocol_name="pi18",
    sections={
        "qpigs": "QPIGS",
        "qpigs2": "QPIGS",
        "qpiri": "QPIRI",
    },
)


class DirectCoordinator(DataUpdateCoordinator):
    """Polls inverter direct-protocol commands described by a ProtocolBinding."""
    devices: list[dict[str, Any]] = []

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Any,
        client: DessmonitorClient,
        device_cache: DeviceCache,
        *,
        service: DirectService | None = None,
        binding: ProtocolBinding | None = None,
    ) -> None:
        interval_seconds = _clamp(
            config_entry.options.get(CONF_DIRECT_UPDATE_INTERVAL, DEFAULT_DIRECT_UPDATE_INTERVAL),
            MIN_DIRECT_UPDATE_INTERVAL,
            MAX_DIRECT_UPDATE_INTERVAL,
        )
        super().__init__(
            hass,
            _LOGGER,
            name="Direct request sensor",
            config_entry=config_entry,
            update_interval=timedelta(seconds=interval_seconds),
            always_update=False,
        )
        self._update_timeout = max(interval_seconds, 30)
        self._client = client
        self._device_cache = device_cache

        protocol_name = config_entry.options.get(
            CONF_DIRECT_PROTOCOL, DEFAULT_DIRECT_PROTOCOL
        )

        # Always cloud transport; only the codec on top differs. The DESS
        # relay forwards opaque bytes to the inverter's serial line, so
        # whether we ship Voltronic ASCII or a Modbus RTU frame is purely
        # a protocol-side concern.
        if service is None:
            transport = CloudHexTransport(client)
            if protocol_name == DIRECT_PROTOCOL_SMG2:
                service = DirectService(transport, protocol=Smg2ModbusProtocol())
                default_binding = _SMG2_BINDING
            elif protocol_name == DIRECT_PROTOCOL_PI18:
                service = DirectService(transport, protocol=Pi18Protocol())
                default_binding = _PI18_BINDING
            else:
                service = DirectService(transport)
                default_binding = _AXPERT_BINDING
        else:
            if protocol_name == DIRECT_PROTOCOL_SMG2:
                default_binding = _SMG2_BINDING
            elif protocol_name == DIRECT_PROTOCOL_PI18:
                default_binding = _PI18_BINDING
            else:
                default_binding = _AXPERT_BINDING

        self._service = service
        self._binding = binding or default_binding
        self._protocol_name = protocol_name

    @property
    def client(self) -> DessmonitorClient:
        return self._client

    async def _async_setup(self) -> None:
        if self.config_entry.options.get('direct_request_protocol', False) is not True:
            return
        async with async_timeout.timeout(30):
            await self._client.session.get_auth()
            self.devices = await self.get_active_devices()
            _LOGGER.debug("direct coordinator setup devices count: %s", len(self.devices))

    async def get_active_devices(self) -> list[dict[str, Any]]:
        devices = await self._device_cache.async_get_devices(
            lambda: self._client.devices.list()
        )
        active_devices = [device for device in devices if device['status'] != 1]
        devices_filter = self.config_entry.options.get("devices", [])
        if devices_filter:
            return [
                device for device in active_devices
                if str(device.get("pn")) in devices_filter
            ]
        return active_devices

    async def _async_update_data(self) -> dict[str, dict[str, Any]] | None:
        try:
            async with async_timeout.timeout(self._update_timeout):
                if self.config_entry.options.get('direct_request_protocol', False) is not True:
                    return None
                _LOGGER.debug("direct coordinator update data devices")

                self.devices = await self.get_active_devices()

                async def fetch_device_data(device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                    # Group sections by command so a protocol like PI18 — where
                    # one GS reply carries both qpigs and qpigs2 data — only
                    # makes one cloud round-trip. When several sections share a
                    # command we expect the decoder to return a *multi-section*
                    # dict ``{section: {...}, section: {...}}``; for a single
                    # section the decoder's flat dict IS that section.
                    cmd_to_sections: dict[str, list[str]] = {}
                    for section, command in self._binding.sections.items():
                        cmd_to_sections.setdefault(command, []).append(section)

                    sections: dict[str, Any] = {}
                    for command, target_sections in cmd_to_sections.items():
                        result = await self._service.query(device, command)
                        if len(target_sections) == 1:
                            sections[target_sections[0]] = result
                            continue
                        for section in target_sections:
                            value = result.get(section) if isinstance(result, dict) else None
                            sections[section] = value if isinstance(value, dict) else {}
                    return device['pn'], sections

                results = await asyncio.gather(*map(fetch_device_data, self.devices))
                return dict(results)
        except TimeoutError:
            raise
        except AuthError as err:
            await self._client.session.invalidate()
            raise UpdateFailed("auth token invalidated, will re-issue next tick") from err
        except TransportError as err:
            # Wrap as UpdateFailed so HA logs a single WARNING line instead
            # of the full aiohttp + SDK traceback every time the cloud blips.
            raise UpdateFailed(f"DESS cloud transient: {err}") from err
