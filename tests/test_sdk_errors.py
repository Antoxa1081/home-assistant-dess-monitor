"""Unit tests for ``sdk.errors`` — envelope-code → exception mapping."""
from __future__ import annotations

import pytest

from custom_components.dess_monitor.sdk import errors


class TestDessmonitorError:
    def test_stores_code_and_action(self) -> None:
        err = errors.DessmonitorError("boom", code=5, action="webQueryDeviceEs")
        assert str(err) == "boom"
        assert err.code == 5
        assert err.action == "webQueryDeviceEs"

    def test_defaults(self) -> None:
        err = errors.DessmonitorError("boom")
        assert err.code is None
        assert err.action is None

    def test_repr_includes_fields(self) -> None:
        err = errors.DessmonitorError("boom", code=5, action="act")
        r = repr(err)
        assert "DessmonitorError" in r
        assert "code=5" in r
        assert "action='act'" in r
        assert "boom" in r


class TestExceptionHierarchy:
    def test_subclassing(self) -> None:
        assert issubclass(errors.TransportError, errors.DessmonitorError)
        assert issubclass(errors.ApiError, errors.DessmonitorError)
        assert issubclass(errors.AuthError, errors.ApiError)
        assert issubclass(errors.RateLimitError, errors.ApiError)

    def test_caught_as_base(self) -> None:
        with pytest.raises(errors.DessmonitorError):
            raise errors.AuthError("x", code=10)


class TestFromEnvelope:
    def test_auth_error_for_code_10(self) -> None:
        err = errors.from_envelope(10, "token expired", "webQueryDeviceEs")
        assert isinstance(err, errors.AuthError)
        assert err.code == 10
        assert err.action == "webQueryDeviceEs"

    @pytest.mark.parametrize("code", [3, 9])
    def test_rate_limit_codes(self, code: int) -> None:
        err = errors.from_envelope(code, "slow down", "act")
        assert isinstance(err, errors.RateLimitError)
        # RateLimitError is a subclass of ApiError but NOT AuthError
        assert not isinstance(err, errors.AuthError)
        assert err.code == code

    @pytest.mark.parametrize("code", [1, 2, 6000, 500])
    def test_generic_api_error_for_other_codes(self, code: int) -> None:
        err = errors.from_envelope(code, "generic", "act")
        assert type(err) is errors.ApiError
        assert not isinstance(err, (errors.AuthError, errors.RateLimitError))

    def test_message_contains_context(self) -> None:
        err = errors.from_envelope(7, "bad request", "queryDeviceParsEs")
        assert "bad request" in str(err)
        assert "err=7" in str(err)
        assert "queryDeviceParsEs" in str(err)

    def test_action_may_be_none(self) -> None:
        err = errors.from_envelope(1, "desc", None)
        assert err.action is None
