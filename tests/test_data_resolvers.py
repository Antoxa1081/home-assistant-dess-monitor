"""Unit tests for ``api.resolvers.data_resolvers``.

The ``resolve_*`` functions are thin wrappers over
``InverterDevice.resolve(canonical, data)``; we drive them with a fake device
so the focus stays on the resolver-specific logic (clamping, V·A fallbacks,
the layered battery-power resolution, PV2 difference + single-MPPT suppression)
and on the free-form timestamp parsing in ``resolve_last_sample_time``.

These tests touch only ``homeassistant.util.dt`` (no event loop / Store), so
they run as plain synchronous unit tests without the ``hass`` fixture.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.util import dt as dt_util

from custom_components.dess_monitor.api.resolvers import data_resolvers as dr


class FakeCandidate:
    def __init__(self, provider_key: str, match_field: str = "id") -> None:
        self.provider_key = provider_key
        self.match_field = match_field


class FakeMapping:
    def __init__(self, discovered: dict[str, FakeCandidate] | None = None) -> None:
        self._discovered = discovered or {}

    def discovered_provider_key(self, inverter_id, canonical):
        return self._discovered.get(canonical)


class FakeDevice:
    """Minimal stand-in for ``InverterDevice``."""

    def __init__(self, values=None, device_data=None, mapping=None) -> None:
        self._values = values or {}
        self.device_data = device_data if device_data is not None else {"pn": "PN1"}
        self.inverter_id = "inv1"
        self.hub = SimpleNamespace(mapping=mapping)

    def resolve(self, canonical, data):
        return self._values.get(canonical)


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """``resolve_last_sample_time`` memoises per-pn TZ offset + diag flags."""
    dr._LAST_SAMPLE_TIME_DIAG_LOGGED.clear()
    dr._LAST_SAMPLE_TIME_TZ_OFFSET_HOURS.clear()
    yield
    dr._LAST_SAMPLE_TIME_DIAG_LOGGED.clear()
    dr._LAST_SAMPLE_TIME_TZ_OFFSET_HOURS.clear()


# --- simple pass-through resolvers --------------------------------------------

class TestPassThroughResolvers:
    @pytest.mark.parametrize(
        "func,canonical",
        [
            (dr.resolve_battery_voltage, "battery_voltage"),
            (dr.resolve_battery_charging_voltage, "battery_charging_voltage"),
            (dr.resolve_battery_discharge_current, "battery_discharge_current"),
            (dr.resolve_active_load_power, "active_load_power"),
            (dr.resolve_active_load_percentage, "active_load_percentage"),
            (dr.resolve_output_priority, "output_priority"),
            (dr.resolve_charge_priority, "charge_priority"),
            (dr.resolve_mains_status, "mains_status"),
            (dr.resolve_grid_in_power, "grid_in_power"),
            (dr.resolve_battery_capacity, "battery_capacity"),
            (dr.resolve_grid_frequency, "grid_frequency"),
            (dr.resolve_pv_power, "pv_power"),
            (dr.resolve_pv_voltage, "pv_voltage"),
            (dr.resolve_pv2_voltage, "pv2_voltage"),
            (dr.resolve_grid_input_voltage, "grid_input_voltage"),
            (dr.resolve_grid_output_voltage, "grid_output_voltage"),
            (dr.resolve_dc_module_temperature, "dc_module_temperature"),
            (dr.resolve_inv_temperature, "inv_temperature"),
            (dr.resolve_bt_utility_charge, "bt_utility_charge"),
            (dr.resolve_bt_total_charge_current, "bt_total_charge_current"),
            (dr.resolve_bt_cutoff_voltage, "bt_cutoff_voltage"),
            (dr.resolve_sy_nominal_out_power, "sy_nominal_out_power"),
            (dr.resolve_sy_rated_battery_voltage, "sy_rated_battery_voltage"),
            (dr.resolve_bt_comeback_utility_voltage, "bt_comeback_utility_voltage"),
            (dr.resolve_bt_comeback_battery_voltage, "bt_comeback_battery_voltage"),
        ],
    )
    def test_passes_value_through(self, func, canonical):
        device = FakeDevice({canonical: 42.5})
        assert func({}, device) == 42.5

    @pytest.mark.parametrize(
        "func,canonical",
        [
            (dr.resolve_battery_voltage, "battery_voltage"),
            (dr.resolve_pv_power, "pv_power"),
            (dr.resolve_grid_frequency, "grid_frequency"),
        ],
    )
    def test_returns_none_when_unresolved(self, func, canonical):
        assert func({}, FakeDevice({})) is None


class TestBatteryChargingCurrent:
    def test_clamps_negative_to_zero(self):
        device = FakeDevice({"battery_charging_current": -5.0})
        assert dr.resolve_battery_charging_current({}, device) == 0.0

    def test_passes_positive(self):
        device = FakeDevice({"battery_charging_current": 12.3})
        assert dr.resolve_battery_charging_current({}, device) == 12.3

    def test_none_stays_none(self):
        assert dr.resolve_battery_charging_current({}, FakeDevice({})) is None

    def test_zero_stays_zero(self):
        device = FakeDevice({"battery_charging_current": 0.0})
        assert dr.resolve_battery_charging_current({}, device) == 0.0


class TestBatteryChargingPower:
    def test_prefers_direct_value(self):
        device = FakeDevice({
            "battery_charging_power": 500.0,
            "battery_charging_current": 10.0,
            "battery_voltage": 50.0,
        })
        assert dr.resolve_battery_charging_power({}, device) == 500.0

    def test_falls_back_to_current_times_charge_voltage(self):
        device = FakeDevice({
            "battery_charging_current": 10.0,
            "battery_charging_voltage": 55.0,
            "battery_voltage": 50.0,
        })
        # charge_voltage wins over battery_voltage in the fallback
        assert dr.resolve_battery_charging_power({}, device) == pytest.approx(550.0)

    def test_falls_back_to_battery_voltage_when_no_charge_voltage(self):
        device = FakeDevice({
            "battery_charging_current": 10.0,
            "battery_voltage": 48.0,
        })
        assert dr.resolve_battery_charging_power({}, device) == pytest.approx(480.0)

    def test_none_when_current_missing(self):
        device = FakeDevice({"battery_voltage": 48.0})
        assert dr.resolve_battery_charging_power({}, device) is None


class TestBatteryDischargePower:
    def test_prefers_direct(self):
        device = FakeDevice({"battery_discharge_power": 300.0})
        assert dr.resolve_battery_discharge_power({}, device) == 300.0

    def test_fallback_va(self):
        device = FakeDevice({
            "battery_discharge_current": 5.0,
            "battery_voltage": 50.0,
        })
        assert dr.resolve_battery_discharge_power({}, device) == pytest.approx(250.0)

    def test_none_when_incomplete(self):
        device = FakeDevice({"battery_discharge_current": 5.0})
        assert dr.resolve_battery_discharge_power({}, device) is None


class TestBatteryPower:
    def test_layer1_direct(self):
        device = FakeDevice({"battery_power": -120.0})
        assert dr.resolve_battery_power({}, device) == -120.0

    def test_layer2_charge_minus_discharge(self):
        device = FakeDevice({
            "battery_charging_power": 400.0,
            "battery_discharge_power": 0.0,
        })
        assert dr.resolve_battery_power({}, device) == 400.0

    def test_layer2_discharge_only(self):
        device = FakeDevice({"battery_discharge_power": 250.0})
        assert dr.resolve_battery_power({}, device) == -250.0

    def test_layer3_net_current_times_voltage(self):
        device = FakeDevice({
            "battery_voltage": 50.0,
            "battery_charging_current": 10.0,
            "battery_discharge_current": 2.0,
        })
        # net = (10 - 2) * 50 = 400
        assert dr.resolve_battery_power({}, device) == pytest.approx(400.0)

    def test_layer3_discharge_dominant(self):
        device = FakeDevice({
            "battery_voltage": 50.0,
            "battery_discharge_current": 4.0,
        })
        assert dr.resolve_battery_power({}, device) == pytest.approx(-200.0)

    def test_none_when_nothing(self):
        assert dr.resolve_battery_power({}, FakeDevice({})) is None

    def test_none_when_only_voltage(self):
        device = FakeDevice({"battery_voltage": 50.0})
        assert dr.resolve_battery_power({}, device) is None


class TestPv2Power:
    def test_prefers_direct(self):
        device = FakeDevice({"pv2_power": 800.0})
        assert dr.resolve_pv2_power({}, device) == 800.0

    def test_difference_total_minus_pv1(self):
        device = FakeDevice(
            {"pv_total_power": 1000.0, "pv_power": 600.0},
            mapping=FakeMapping({
                "pv_power": FakeCandidate("pv1key"),
                "pv_total_power": FakeCandidate("totalkey"),
            }),
        )
        assert dr.resolve_pv2_power({}, device) == pytest.approx(400.0)

    def test_difference_clamped_at_zero(self):
        device = FakeDevice(
            {"pv_total_power": 500.0, "pv_power": 600.0},
            mapping=FakeMapping({
                "pv_power": FakeCandidate("pv1key"),
                "pv_total_power": FakeCandidate("totalkey"),
            }),
        )
        assert dr.resolve_pv2_power({}, device) == 0.0

    def test_single_mppt_suppressed(self):
        # pv_power and pv_total_power discovered the SAME provider key+field.
        same = FakeCandidate("shared", "id")
        device = FakeDevice(
            {"pv_total_power": 1000.0, "pv_power": 1000.0},
            mapping=FakeMapping({"pv_power": same, "pv_total_power": same}),
        )
        assert dr.resolve_pv2_power({}, device) is None

    def test_none_when_total_or_pv1_missing(self):
        device = FakeDevice({"pv_power": 600.0}, mapping=FakeMapping())
        assert dr.resolve_pv2_power({}, device) is None

    def test_mapping_attribute_error_falls_through_to_diff(self):
        # hub.mapping is None -> AttributeError caught -> still computes diff.
        device = FakeDevice({"pv_total_power": 1000.0, "pv_power": 600.0}, mapping=None)
        assert dr.resolve_pv2_power({}, device) == pytest.approx(400.0)


class TestWsLastFrameAt:
    def test_returns_utc_datetime(self):
        device = FakeDevice()
        out = dr.resolve_ws_last_frame_at({"ws_received_at": 1700000000}, device)
        assert out == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_none_when_missing(self):
        assert dr.resolve_ws_last_frame_at({}, FakeDevice()) is None

    def test_none_when_not_numeric(self):
        assert dr.resolve_ws_last_frame_at({"ws_received_at": "soon"}, FakeDevice()) is None

    def test_none_when_data_not_dict(self):
        assert dr.resolve_ws_last_frame_at("nope", FakeDevice()) is None


class TestLastSampleTime:
    def _device(self, pn="PN1"):
        return FakeDevice(device_data={"pn": pn} if pn else {})

    def test_none_when_last_data_missing(self):
        assert dr.resolve_last_sample_time({}, self._device()) is None

    def test_none_when_last_data_not_dict(self):
        assert dr.resolve_last_sample_time({"last_data": "x"}, self._device()) is None

    def test_none_when_no_timestamp_key(self):
        assert dr.resolve_last_sample_time({"last_data": {}}, self._device()) is None

    def test_epoch_seconds(self):
        # pn=None disables the per-device TZ offset calibration.
        out = dr.resolve_last_sample_time(
            {"last_data": {"gts": 1700000000}}, self._device(pn=None)
        )
        assert out == datetime.fromtimestamp(1700000000, tz=dt_util.UTC)

    def test_epoch_milliseconds(self):
        out = dr.resolve_last_sample_time(
            {"last_data": {"gts": 1700000000000}}, self._device(pn=None)
        )
        assert out == datetime.fromtimestamp(1700000000, tz=dt_util.UTC)

    def test_numeric_string_epoch(self):
        out = dr.resolve_last_sample_time(
            {"last_data": {"gts": " 1700000000 "}}, self._device(pn=None)
        )
        assert out == datetime.fromtimestamp(1700000000, tz=dt_util.UTC)

    @pytest.mark.parametrize("text", [
        "2024-01-02 03:04:05",
        "2024-01-02T03:04:05",
        "2024/01/02 03:04:05",
    ])
    def test_datetime_string_formats(self, text):
        out = dr.resolve_last_sample_time(
            {"last_data": {"gts": text}}, self._device(pn=None)
        )
        assert out is not None
        assert (out.year, out.month, out.day) == (2024, 1, 2)
        assert (out.hour, out.minute, out.second) == (3, 4, 5)
        # naive parse gets the HA default timezone attached
        assert out.tzinfo is not None

    def test_unparseable_returns_none(self):
        out = dr.resolve_last_sample_time(
            {"last_data": {"gts": "not-a-date"}}, self._device(pn=None)
        )
        assert out is None

    def test_falls_back_to_ts_then_time_key(self):
        out = dr.resolve_last_sample_time(
            {"last_data": {"ts": 1700000000}}, self._device(pn=None)
        )
        assert out == datetime.fromtimestamp(1700000000, tz=dt_util.UTC)

    def test_tz_offset_calibrated_and_cached(self):
        # A gts equal to "now" (UTC epoch) calibrates offset ~0 and caches it.
        now_epoch = int(dt_util.utcnow().timestamp())
        device = self._device(pn="PNX")
        out = dr.resolve_last_sample_time({"last_data": {"gts": now_epoch}}, device)
        assert out is not None
        assert "PNX" in dr._LAST_SAMPLE_TIME_TZ_OFFSET_HOURS
        # Second call reuses the cached offset (no exception, consistent result).
        out2 = dr.resolve_last_sample_time({"last_data": {"gts": now_epoch}}, device)
        assert out2 == out
