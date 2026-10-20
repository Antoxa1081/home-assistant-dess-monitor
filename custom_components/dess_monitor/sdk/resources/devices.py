from __future__ import annotations

from typing import cast

from ..models import (
    DeviceDict,
    DeviceIdentity,
    EnergyFlowResponse,
    FieldsResponse,
    HistoricalDataResponse,
    LastDataResponse,
    ParsResponse,
)
from ..session import Session

_DEFAULT_LIST_PARAMS: dict[str, str] = {
    "i18n": "en_US",
    "source": "1",
    "page": "0",
    "pagesize": "15",
}


class DevicesResource:
    """Device-scoped queries: listing, snapshots, parameters, history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def list(self, **overrides: object) -> list[DeviceDict]:
        params = {**_DEFAULT_LIST_PARAMS, **overrides}
        dat = await self._session.request("webQueryDeviceEs", params)
        return cast(list[DeviceDict], dat["device"])

    async def energy_flow(self, identity: DeviceIdentity) -> EnergyFlowResponse:
        return cast(
            EnergyFlowResponse,
            await self._session.request(
                "webQueryDeviceEnergyFlowEs",
                {"i18n": "en_US", "source": "1", **identity.as_params()},
            ),
        )

    async def last_data(self, identity: DeviceIdentity) -> LastDataResponse:
        return cast(
            LastDataResponse,
            await self._session.request(
                "querySPDeviceLastData",
                {"i18n": "en_US", "source": "1", **identity.as_params()},
            ),
        )

    async def pars(self, identity: DeviceIdentity) -> ParsResponse:
        return cast(
            ParsResponse,
            await self._session.request(
                "queryDeviceParsEs",
                {"i18n": "en_US", "source": "1", **identity.as_params()},
            ),
        )

    async def fields(self, identity: DeviceIdentity) -> FieldsResponse:
        return cast(
            FieldsResponse,
            await self._session.request(
                "queryDeviceFields",
                {"i18n": "en_US", "source": "1", **identity.as_params()},
            ),
        )

    async def historical_data(
        self,
        identity: DeviceIdentity,
        date: str,
        *,
        page: int = 0,
        pagesize: int = 15,
    ) -> HistoricalDataResponse:
        """One-day paged history. ``date`` is ``YYYY-MM-DD`` in plant-local time."""
        return cast(
            HistoricalDataResponse,
            await self._session.request(
                "queryDeviceDataOneDayPaging",
                {
                    "i18n": "en_US",
                    "source": "1",
                    "page": str(page),
                    "pagesize": str(pagesize),
                    "date": date,
                    **identity.as_params(),
                },
            ),
        )
