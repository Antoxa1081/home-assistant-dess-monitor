from __future__ import annotations

from typing import cast

from ..models import CollectorListResponse
from ..session import Session

_DEFAULT_LIST_PARAMS: dict[str, str] = {
    "source": "1",
    "devtype": "2304",
    "page": "0",
    "pagesize": "15",
}


class CollectorsResource:
    """Data-collector (datalogger) queries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def list(self, **overrides: object) -> CollectorListResponse:
        params = {**_DEFAULT_LIST_PARAMS, **overrides}
        return cast(
            CollectorListResponse,
            await self._session.request("webQueryCollectorsEs", params),
        )
