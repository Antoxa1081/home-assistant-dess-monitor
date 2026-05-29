"""Unit tests for ``virtual_battery.VirtualBatteryEstimator``.

The estimator persists through an HA ``Store`` (needs the ``hass`` fixture) and
integrates current over wall-clock time (we drive ``time.time`` via a fake clock
so ticks are deterministic). Constants used by the math, from ``const.py``:

* ``BATTERY_FULL_TAIL_CURRENT_RATIO = 0.02``  → tail = capacity_ah * 0.02
* ``BATTERY_FULL_VOLTAGE_BAND = 0.005``        → full_low = voltage_full * 0.995
"""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.dess_monitor import virtual_battery as vb_mod
from custom_components.dess_monitor.virtual_battery import VirtualBatteryEstimator


class FakeClock:
    """Monotonic-ish fake for ``time.time`` driven by explicit advances."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    c = FakeClock()
    monkeypatch.setattr(vb_mod.time, "time", c.time)
    return c


@pytest.fixture
def estimator(hass) -> VirtualBatteryEstimator:
    return VirtualBatteryEstimator(hass, "entry1", "inv1")


def _configure(est: VirtualBatteryEstimator, capacity=100.0, voltage_full=56.0):
    est.set_capacity_ah(capacity)
    est.set_voltage_full(voltage_full)


class TestConfiguration:
    def test_starts_unconfigured(self, estimator):
        assert estimator.configured is False
        assert estimator.soc is None

    def test_configured_requires_both_values(self, estimator):
        estimator.set_capacity_ah(100)
        assert estimator.configured is False
        estimator.set_voltage_full(56.0)
        assert estimator.configured is True

    def test_set_capacity_clamps_and_coerces(self, estimator):
        estimator.set_capacity_ah(-5)
        assert estimator.capacity_ah == 0.0
        estimator.set_capacity_ah("120")
        assert estimator.capacity_ah == 120.0
        estimator.set_capacity_ah("garbage")
        assert estimator.capacity_ah == 0.0

    def test_set_voltage_full_clamps_and_coerces(self, estimator):
        estimator.set_voltage_full(-1)
        assert estimator.voltage_full == 0.0
        estimator.set_voltage_full("56.4")
        assert estimator.voltage_full == pytest.approx(56.4)
        estimator.set_voltage_full(None)
        assert estimator.voltage_full == 0.0

    def test_set_chemistry(self, estimator):
        assert estimator.chemistry == "lifepo4"
        estimator.set_chemistry("lead_acid")
        assert estimator.chemistry == "lead_acid"
        estimator.set_chemistry("")  # ignored
        assert estimator.chemistry == "lead_acid"
        estimator.set_chemistry(123)  # ignored
        assert estimator.chemistry == "lead_acid"


class TestUpdateGuards:
    def test_noop_when_unconfigured(self, estimator, clock):
        estimator.update(50.0, 10.0)
        assert estimator.soc is None
        assert estimator.last_update_at is None
        assert estimator.is_dirty is False

    def test_missing_data_only_bookmarks_time(self, estimator, clock):
        _configure(estimator)
        estimator.update(None, 10.0)
        assert estimator.last_update_at == clock.now
        assert estimator.soc is None  # configured but not primed
        # the dirty flag is not set on a missing-data tick
        assert estimator.is_dirty is False


class TestVoltageRebase:
    def test_rebase_to_full_in_absorption_tail(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        # V at full, current within tail (tail = 100 * 0.02 = 2 A)
        estimator.update(56.0, 1.0)
        assert estimator.soc == 100.0
        assert estimator.is_dirty is True

    def test_no_rebase_when_voltage_below_band(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        # full_low = 56 * 0.995 = 55.72; 55.0 is below it
        estimator.update(55.0, 1.0)
        assert estimator.soc is None

    def test_no_rebase_when_current_above_tail(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        # tail = 2 A; 5 A exceeds it (still bulk charging)
        estimator.update(56.0, 5.0)
        assert estimator.soc is None

    def test_no_rebase_when_discharging(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        estimator.update(56.0, -1.0)
        assert estimator.soc is None


class TestCoulombIntegration:
    def test_discharge_decrements_soc(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        # Prime to 100% via a full-rebase tick.
        estimator.update(56.0, 1.0)
        assert estimator.soc == 100.0
        # Discharge 50 A for 1 hour → ΔAh = -50 → ΔSOC = -50%.
        clock.advance(3600)
        estimator.update(52.0, -50.0)
        assert estimator.soc == pytest.approx(50.0)

    def test_charge_increments_soc(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        estimator.update(56.0, 1.0)  # prime 100
        # Force a known lower SOC by discharging first.
        clock.advance(3600)
        estimator.update(52.0, -40.0)  # → 60%
        assert estimator.soc == pytest.approx(60.0)
        # Charge 20 A for 0.5 h → +10 Ah → +10% → 70%. Keep V below band so no rebase.
        clock.advance(1800)
        estimator.update(52.0, 20.0)
        assert estimator.soc == pytest.approx(70.0)

    def test_soc_clamped_to_zero(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        estimator.update(56.0, 1.0)  # prime 100
        clock.advance(3600)
        estimator.update(48.0, -500.0)  # would be -500% → clamp 0
        assert estimator.soc == 0.0

    def test_single_tick_capped_at_one_hour(self, estimator, clock):
        _configure(estimator, capacity=100.0, voltage_full=56.0)
        estimator.update(56.0, 1.0)  # prime 100
        # Advance 10 hours but only 1 h should be counted.
        clock.advance(36000)
        estimator.update(52.0, -10.0)  # -10 A * 1 h = -10 Ah = -10%
        assert estimator.soc == pytest.approx(90.0)


class TestPersistence:
    async def test_save_then_load_roundtrip(self, hass, clock):
        est = VirtualBatteryEstimator(hass, "entryP", "invP")
        _configure(est)
        est.update(56.0, 1.0)  # soc -> 100, dirty
        assert est.is_dirty is True
        await est.async_save()
        assert est.is_dirty is False

        # Fresh estimator over the same store keys restores the SOC.
        est2 = VirtualBatteryEstimator(hass, "entryP", "invP")
        _configure(est2)
        await est2.async_load()
        assert est2.soc == 100.0

    async def test_load_is_idempotent(self, hass):
        est = VirtualBatteryEstimator(hass, "entryI", "invI")
        await est.async_load()
        await est.async_load()  # no error on second load

    async def test_save_skips_when_not_dirty(self, hass, clock):
        est = VirtualBatteryEstimator(hass, "entryN", "invN")
        _configure(est)
        # Never updated → not dirty → save is a no-op (and load finds nothing).
        await est.async_save()
        est2 = VirtualBatteryEstimator(hass, "entryN", "invN")
        _configure(est2)
        await est2.async_load()
        assert est2.soc is None

    async def test_clear_resets_state(self, hass, clock):
        est = VirtualBatteryEstimator(hass, "entryC", "invC")
        _configure(est)
        est.update(56.0, 1.0)
        await est.async_save()
        await est.async_clear()
        assert est.soc is None
        assert est.last_update_at is None
        # A fresh estimator finds nothing persisted.
        est2 = VirtualBatteryEstimator(hass, "entryC", "invC")
        _configure(est2)
        await est2.async_load()
        assert est2.soc is None
