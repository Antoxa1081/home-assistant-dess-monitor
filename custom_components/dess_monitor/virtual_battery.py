"""Coulomb-counting State-of-Charge estimator for inverters without a BMS.

Some firmwares don't expose a battery percentage at all, or expose only a
load-percent value mislabelled as SOC. When the user knows their bank's
nominal capacity (Ah) and full-charge voltage, we can integrate the signed
battery current over time to track SOC accurately enough for energy-flow
visualisation.

Algorithm — per device, per coordinator update:

1. Take signed battery current ``I`` (positive = charging, negative =
   discharging) and battery terminal voltage ``V``.
2. Coulomb integration: ``ΔAh = I · Δt``; ``ΔSOC% = ΔAh / capacity_Ah · 100``.
   Apply to the running SOC, clamped to ``[0, 100]``.
3. Voltage-based rebase at full: when ``V`` is at-or-above the configured
   full-charge voltage AND ``|I|`` falls below ``BATTERY_FULL_TAIL_CURRENT_RATIO``
   of the bank capacity (i.e. we're in the absorption tail), pin SOC = 100%.
   This is the only "anchor" we have without an empty-rebase event, so it's
   essential for long-term drift correction.
4. Persist SOC + last-update timestamp through HA restarts so a brief restart
   doesn't reset the estimate to None.

Caveats and intentional simplifications:

- No empty-rebase: discharge cutoff is firmware-controlled, so by the time
  we'd "see" empty the inverter has typically already shut down.
- No temperature compensation: most users don't expose battery temperature.
- Chemistry argument is recorded for forward compatibility but currently has
  no effect on the math — voltage rebase uses only the user-provided
  ``voltage_full``, which already encodes the chemistry-specific absorb
  level.
- First-ever boot: SOC starts at None until at least one coulomb tick can
  compute a delta against a saved or seeded value. We don't try to seed
  from voltage alone — the resting OCV curve is too device-specific and a
  bad seed would be worse than ``Unknown`` until the user takes the bank
  through one full charge.
"""
from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.dess_monitor.const import (
    BATTERY_FULL_TAIL_CURRENT_RATIO,
    BATTERY_FULL_VOLTAGE_BAND,
)

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1


class VirtualBatteryEstimator:
    """Per-device Coulomb-counting SOC estimator."""

    def __init__(
            self,
            hass: HomeAssistant,
            entry_id: str,
            inverter_id: str,
    ) -> None:
        self._hass = hass
        self._inverter_id = inverter_id
        # Settings mutated at runtime by the device's CONFIG-category
        # Number/Select entities. Until both ``capacity_ah`` and
        # ``voltage_full`` are non-zero the estimator stays dormant.
        self._capacity_ah: float = 0.0
        self._voltage_full: float = 0.0
        self._chemistry: str = "lifepo4"
        self._soc_pct: float | None = None
        self._last_update_at: float | None = None
        self._loaded = False
        self._dirty = False
        self._save_lock = asyncio.Lock()
        self._store: Store = Store(
            hass, _STORAGE_VERSION,
            f"dess_monitor.battery.{entry_id}.{inverter_id}",
        )

    # --- runtime configuration (driven by per-device entities) -----------

    @property
    def capacity_ah(self) -> float:
        return self._capacity_ah

    @property
    def voltage_full(self) -> float:
        return self._voltage_full

    @property
    def chemistry(self) -> str:
        return self._chemistry

    @property
    def configured(self) -> bool:
        """True when the user has provided enough info to run the integrator."""
        return self._capacity_ah > 0 and self._voltage_full > 0

    def set_capacity_ah(self, value) -> None:
        try:
            self._capacity_ah = max(0.0, float(value))
        except (TypeError, ValueError):
            self._capacity_ah = 0.0

    def set_voltage_full(self, value) -> None:
        try:
            self._voltage_full = max(0.0, float(value))
        except (TypeError, ValueError):
            self._voltage_full = 0.0

    def set_chemistry(self, value) -> None:
        if isinstance(value, str) and value:
            self._chemistry = value

    @property
    def soc(self) -> float | None:
        """Current SOC %; ``None`` while not configured or not yet primed."""
        if not self.configured:
            return None
        return self._soc_pct

    @property
    def last_update_at(self) -> float | None:
        return self._last_update_at

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    async def async_load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            stored = await self._store.async_load()
        except Exception:
            _LOGGER.exception("Failed to load virtual battery state for %s", self._inverter_id)
            return
        if not isinstance(stored, dict):
            return
        soc = stored.get("soc")
        if isinstance(soc, (int, float)) and 0 <= float(soc) <= 100:
            self._soc_pct = float(soc)
        ts = stored.get("last_update_at")
        if isinstance(ts, (int, float)):
            self._last_update_at = float(ts)
        _LOGGER.debug(
            "Restored virtual battery for %s: soc=%s, last_at=%s",
            self._inverter_id, self._soc_pct, self._last_update_at,
        )

    async def async_save(self) -> None:
        async with self._save_lock:
            if not self._dirty:
                return
            snapshot = {
                "soc": self._soc_pct,
                "last_update_at": self._last_update_at,
            }
            self._dirty = False
        try:
            await self._store.async_save(snapshot)
        except Exception:
            _LOGGER.exception("Failed to save virtual battery state for %s", self._inverter_id)
            self._dirty = True  # retry next round

    async def async_clear(self) -> None:
        self._soc_pct = None
        self._last_update_at = None
        self._dirty = False
        try:
            await self._store.async_remove()
        except Exception:
            _LOGGER.exception("Failed to remove virtual battery state for %s", self._inverter_id)

    def update(self, voltage: float | None, signed_current_a: float | None) -> None:
        """Tick the estimator with the latest battery readings.

        ``signed_current_a``: positive = charging, negative = discharging.
        Either argument may be ``None`` (data missing for this tick) — we
        bookmark the timestamp without touching SOC so the next valid tick
        sees a small ``Δt`` gap rather than the entire outage.
        """
        if not self.configured:
            # Capacity/voltage_full not set by the user yet — silently no-op.
            return

        now = time.time()

        if voltage is None or signed_current_a is None:
            self._last_update_at = now
            return

        if self._last_update_at is not None and self._soc_pct is not None:
            dt_seconds = max(0.0, now - self._last_update_at)
            # Cap a single tick at 1 hour to avoid huge step-changes after
            # long outages — we'd rather under-count than diverge wildly.
            dt_seconds = min(dt_seconds, 3600.0)
            dt_hours = dt_seconds / 3600.0
            delta_ah = signed_current_a * dt_hours
            delta_pct = (delta_ah / self._capacity_ah) * 100.0
            self._soc_pct = max(0.0, min(100.0, self._soc_pct + delta_pct))

        # Voltage rebase at full: when the bank is sitting at-or-above the
        # configured absorb voltage AND barely accepting any charging current
        # (absorption tail), it's full. Pin to 100% — this is the anchor that
        # corrects any cumulative drift from the integration.
        full_low = self._voltage_full * (1.0 - BATTERY_FULL_VOLTAGE_BAND)
        if voltage >= full_low:
            tail_threshold = self._capacity_ah * BATTERY_FULL_TAIL_CURRENT_RATIO
            if 0.0 <= signed_current_a <= tail_threshold:
                if self._soc_pct != 100.0:
                    _LOGGER.debug(
                        "Virtual battery %s: full-rebase (V=%.2f >= %.2f, I=%.2fA <= %.2fA)",
                        self._inverter_id, voltage, full_low,
                        signed_current_a, tail_threshold,
                    )
                self._soc_pct = 100.0

        # Bootstrap: if we've never recorded SOC at all, we wait for the
        # first full-rebase event. Until then SOC stays None and the sensor
        # shows Unknown — better than guessing.
        if self._soc_pct is None and self._last_update_at is None:
            self._last_update_at = now
            return

        self._last_update_at = now
        self._dirty = True
