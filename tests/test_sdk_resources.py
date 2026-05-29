"""Unit tests for ``sdk.resources.*`` — endpoint wrappers over Session.

Each resource takes a Session and builds request params / parses responses.
We mock Session.request (and get_auth/invalidate for AuthResource) and assert
the action name, params, and return shaping.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.dess_monitor.sdk.models import Auth, DeviceIdentity
from custom_components.dess_monitor.sdk.resources import (
    AuthResource,
    CollectorsResource,
    ControlResource,
    DevicesResource,
)


def _identity() -> DeviceIdentity:
    return DeviceIdentity(devaddr=1, devcode=2376, pn="PN1", sn="SN1")


def _session(return_value: Any = None) -> MagicMock:
    sess = MagicMock()
    sess.request = AsyncMock(return_value=return_value)
    return sess


class TestAuthResource:
    async def test_current_calls_get_auth(self) -> None:
        sess = MagicMock()
        auth = Auth(token="t", secret="s", expire=1, uid="u", usr="b", issued_at=0)
        sess.get_auth = AsyncMock(return_value=auth)
        res = AuthResource(sess)
        result = await res.current()
        assert result is auth
        sess.get_auth.assert_awaited_once_with()

    async def test_login_forces_refresh(self) -> None:
        sess = MagicMock()
        sess.get_auth = AsyncMock(return_value="auth")
        res = AuthResource(sess)
        await res.login()
        sess.get_auth.assert_awaited_once_with(force_refresh=True)

    async def test_logout_invalidates(self) -> None:
        sess = MagicMock()
        sess.invalidate = AsyncMock()
        res = AuthResource(sess)
        await res.logout()
        sess.invalidate.assert_awaited_once_with()


class TestDevicesResource:
    async def test_list_default_params_and_unwraps_device(self) -> None:
        sess = _session({"device": [{"pn": "P"}]})
        res = DevicesResource(sess)
        out = await res.list()
        assert out == [{"pn": "P"}]
        args = sess.request.call_args.args
        assert args[0] == "webQueryDeviceEs"
        params = args[1]
        assert params == {"i18n": "en_US", "source": "1", "page": "0", "pagesize": "15"}

    async def test_list_overrides_merge(self) -> None:
        sess = _session({"device": []})
        res = DevicesResource(sess)
        await res.list(page="2", pagesize="50")
        params = sess.request.call_args.args[1]
        assert params["page"] == "2"
        assert params["pagesize"] == "50"

    async def test_energy_flow_params(self) -> None:
        sess = _session({"bt_status": []})
        res = DevicesResource(sess)
        out = await res.energy_flow(_identity())
        assert out == {"bt_status": []}
        args = sess.request.call_args.args
        assert args[0] == "webQueryDeviceEnergyFlowEs"
        params = args[1]
        assert params["i18n"] == "en_US"
        assert params["source"] == "1"
        assert params["pn"] == "PN1"
        assert params["devaddr"] == "1"
        assert params["devcode"] == "2376"
        assert params["sn"] == "SN1"

    async def test_last_data_action(self) -> None:
        sess = _session({"pars": {}})
        res = DevicesResource(sess)
        await res.last_data(_identity())
        assert sess.request.call_args.args[0] == "querySPDeviceLastData"

    async def test_pars_action(self) -> None:
        sess = _session({"pars": {}})
        res = DevicesResource(sess)
        await res.pars(_identity())
        assert sess.request.call_args.args[0] == "queryDeviceParsEs"

    async def test_fields_action(self) -> None:
        sess = _session({"field": []})
        res = DevicesResource(sess)
        await res.fields(_identity())
        assert sess.request.call_args.args[0] == "queryDeviceFields"

    async def test_historical_data_params(self) -> None:
        sess = _session({"rows": []})
        res = DevicesResource(sess)
        await res.historical_data(_identity(), "2026-05-29", page=3, pagesize=20)
        args = sess.request.call_args.args
        assert args[0] == "queryDeviceDataOneDayPaging"
        params = args[1]
        assert params["date"] == "2026-05-29"
        assert params["page"] == "3"
        assert params["pagesize"] == "20"
        assert params["pn"] == "PN1"

    async def test_historical_data_defaults(self) -> None:
        sess = _session({"rows": []})
        res = DevicesResource(sess)
        await res.historical_data(_identity(), "2026-01-01")
        params = sess.request.call_args.args[1]
        assert params["page"] == "0"
        assert params["pagesize"] == "15"


class TestControlResource:
    async def test_get_value_uses_raise_on_error_false(self) -> None:
        sess = _session({"val": "12"})
        res = ControlResource(sess)
        out = await res.get_value(_identity(), "param1")
        assert out == {"val": "12"}
        args = sess.request.call_args.args
        kwargs = sess.request.call_args.kwargs
        assert args[0] == "queryDeviceCtrlValue"
        assert args[1]["id"] == "param1"
        assert kwargs["raise_on_error"] is False

    async def test_get_fields_action(self) -> None:
        sess = _session({"field": []})
        res = ControlResource(sess)
        await res.get_fields(_identity())
        assert sess.request.call_args.args[0] == "queryDeviceCtrlField"

    async def test_set_param_builds_id_and_val(self) -> None:
        sess = _session({"err": 0})
        res = ControlResource(sess)
        await res.set_param(_identity(), "pid", "5")
        args = sess.request.call_args.args
        assert args[0] == "ctrlDevice"
        assert args[1]["id"] == "pid"
        assert args[1]["val"] == "5"

    async def test_send_direct_command_no_i18n(self) -> None:
        sess = _session({"dat": "ABCD"})
        res = ControlResource(sess)
        out = await res.send_direct_command(_identity(), "FFEE")
        assert out == {"dat": "ABCD"}
        args = sess.request.call_args.args
        assert args[0] == "sendCmdToDevice"
        params = args[1]
        assert params["cmd"] == "FFEE"
        assert params["source"] == "1"
        assert "i18n" not in params


class TestCollectorsResource:
    async def test_list_default_params(self) -> None:
        sess = _session({"collector": [{"pn": "C"}]})
        res = CollectorsResource(sess)
        out = await res.list()
        assert out == {"collector": [{"pn": "C"}]}
        args = sess.request.call_args.args
        assert args[0] == "webQueryCollectorsEs"
        assert args[1] == {
            "source": "1",
            "devtype": "2304",
            "page": "0",
            "pagesize": "15",
        }

    async def test_list_overrides(self) -> None:
        sess = _session({"collector": []})
        res = CollectorsResource(sess)
        await res.list(devtype="9999")
        assert sess.request.call_args.args[1]["devtype"] == "9999"
