"""Seed catalog of canonical metrics and their provider-key aliases.

Each canonical sensor (``battery_voltage``, ``pv_power``, …) lists ordered
provider-key candidates: a raw key from the upstream API plus enough metadata
to normalize the extracted value (``match_field``, ``scale``, ``unit_hint``,
``value_map``, ``sign``).

The :class:`MappingDiscovery` walks this list once per device, resolves the
first candidate that matches the live data shape, and pins it for subsequent
ticks. Adding support for a new device firmware = appending candidates here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

# --- Public types ------------------------------------------------------------

MATCH_FIELD_ID = "id"      # last_data shape: items have id/val/unit
MATCH_FIELD_PAR = "par"    # pars shape:     items have par/val/unit/status

SIGN_POSITIVE = "+"        # value if value > 0 else 0.0
SIGN_NEGATIVE = "-"        # abs(value) if value < 0 else 0.0


@dataclass(frozen=True)
class ProviderKeyCandidate:
    """One alias for a canonical metric.

    ``provider_key`` is the raw key as it appears in the upstream payload;
    ``match_field`` declares which payload shape it lives in.
    """
    provider_key: str
    match_field: str  # MATCH_FIELD_ID | MATCH_FIELD_PAR
    scale: float = 1.0
    offset: float = 0.0
    unit_hint: Optional[str] = None
    value_map: Optional[Mapping[str, str]] = None
    sign: Optional[str] = None  # SIGN_POSITIVE | SIGN_NEGATIVE | None


# --- Value maps reused across canonical names --------------------------------

_OUTPUT_PRIORITY_MAP: Mapping[str, str] = {
    "uti": "Utility", "utility": "Utility", "utility first": "Utility",
    "sbu": "SBU", "sbu first": "SBU",
    "sol": "Solar", "solar": "Solar", "solar first": "Solar",
    # Anenji 11kw (devcode 6544) ctrl_fields publish three-letter codes
    # without an explanatory mapping; pass them through as-is so the sensor
    # never goes Unknown when the device picks one we haven't tagged.
    "sub": "SUB", "sub first": "SUB",
    "suf": "SUF",
    "off": "OFF",
}

_CHARGE_PRIORITY_MAP: Mapping[str, str] = {
    "solar priority": "SOLAR_PRIORITY",
    "pv first": "SOLAR_PRIORITY",
    "sof": "SOLAR_PRIORITY",   # Anenji 11kw devcode 6544 (Solar First)
    "solar and mains": "SOLAR_AND_UTILITY",
    "pv is at the same level as mains": "SOLAR_AND_UTILITY",
    "pv is at the same level as utility": "SOLAR_AND_UTILITY",
    "snu": "SOLAR_AND_UTILITY",  # Solar a-N-d Utility
    "solar only": "SOLAR_ONLY",
    "only pv": "SOLAR_ONLY",
    "oso": "SOLAR_ONLY",         # Only SOlar
    "utility first": "UTILITY",
    "sor": "UTILITY",            # Solar OR utility — closest existing value
    "n/a": "NONE",
    "off": "NONE",
}

_MAINS_STATUS_MAP: Mapping[str, str] = {
    # Operating mode the inverter reports — collapses many cloud labels into
    # a small enum a HA automation can switch on. Includes Chinese variants
    # because some firmwares stream WS payloads in zh-CN regardless of UI
    # locale.
    "battery mode": "BATTERY",
    "battery": "BATTERY",
    "discharge": "BATTERY",
    "off-grid mode": "BATTERY",
    "off grid mode": "BATTERY",
    "off-grid": "BATTERY",
    "invert mode": "BATTERY",
    "\u7535\u6c60\u6a21\u5f0f": "BATTERY",       # 电池模式
    "\u7535\u6c60\u4f9b\u7535": "BATTERY",       # 电池供电
    "\u5e02\u7535\u672a\u63a5\u5165\u7cfb\u7edf": "BATTERY",  # 市电未接入系统
    "mains mode": "GRID",
    "mains": "GRID",
    "mains ok": "GRID",
    "grid": "GRID",
    "utility": "GRID",
    "line mode": "GRID",
    "bypass": "GRID",
    "ac mode": "GRID",
    "\u5e02\u7535\u6a21\u5f0f": "GRID",          # 市电模式
    "\u5e02\u7535\u5df2\u63a5\u5165\u7cfb\u7edf": "GRID",  # 市电已接入系统
    "hybrid": "HYBRID",
    "solar mode": "SOLAR",
    "solar": "SOLAR",
    "pv": "SOLAR",
    "\u5149\u4f0f\u6a21\u5f0f": "SOLAR",         # 光伏模式
    "standby": "STANDBY",
    "\u5f85\u673a": "STANDBY",                   # 待机
    "fault": "FAULT",
    "\u6545\u969c": "FAULT",                     # 故障
    "off": "OFF",
}


# --- Catalog -----------------------------------------------------------------

CANONICAL_METRICS: dict[str, list[ProviderKeyCandidate]] = {
    "battery_voltage": [
        ProviderKeyCandidate("bt_battery_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Battery Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("eybond_read_24", MATCH_FIELD_ID),
        # Anenji 11kw (devcode 6544) — eybond_read_43xxx parameter family.
        ProviderKeyCandidate("eybond_read_43951", MATCH_FIELD_PAR),
        # Anenji-style eybond firmwares (devcode 2376 et al) — id form.
        ProviderKeyCandidate("bt_eybond_read_28", MATCH_FIELD_ID),
    ],
    "battery_charging_voltage": [
        ProviderKeyCandidate("bt_vulk_charging_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Battery charging voltage", MATCH_FIELD_ID),
    ],
    "battery_charging_current": [
        ProviderKeyCandidate("bt_eybond_read_29", MATCH_FIELD_PAR, sign=SIGN_POSITIVE),
        # Anenji-style eybond (devcode 2376) — same id key as PAR variant above,
        # signed: positive = charging.
        ProviderKeyCandidate("bt_eybond_read_29", MATCH_FIELD_ID, sign=SIGN_POSITIVE),
        ProviderKeyCandidate("bt_battery_charging_current", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Battery charging current", MATCH_FIELD_ID),
        ProviderKeyCandidate("eybond_read_25", MATCH_FIELD_ID),
        ProviderKeyCandidate("Battery Current", MATCH_FIELD_ID, sign=SIGN_POSITIVE),
        # Stevo Hybrid Monster (devcode 6467) — bt_input_current is the charging leg.
        ProviderKeyCandidate("bt_input_current", MATCH_FIELD_ID),
        # Devcode 2428 — short machine name (bt_charging_current, not bt_battery_*).
        ProviderKeyCandidate("bt_charging_current", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_charging_current", MATCH_FIELD_PAR),
    ],
    "battery_discharge_current": [
        ProviderKeyCandidate("bt_eybond_read_29", MATCH_FIELD_PAR, sign=SIGN_NEGATIVE),
        # Anenji-style eybond (devcode 2376) — id form, sign-filtered for negatives.
        ProviderKeyCandidate("bt_eybond_read_29", MATCH_FIELD_ID, sign=SIGN_NEGATIVE),
        ProviderKeyCandidate("bt_battery_discharge_current", MATCH_FIELD_PAR),
        ProviderKeyCandidate("bt_discharge_current", MATCH_FIELD_PAR),
        # Devcode 2428 — same key in id form (last_data shape).
        ProviderKeyCandidate("bt_discharge_current", MATCH_FIELD_ID),
        ProviderKeyCandidate("Battery discharge current", MATCH_FIELD_ID),
        ProviderKeyCandidate("Battery Current", MATCH_FIELD_ID, sign=SIGN_NEGATIVE),
        # Stevo Hybrid Monster (devcode 6467) — bt_battery_current carries the
        # discharge magnitude (positive when discharging) on this firmware.
        ProviderKeyCandidate("bt_battery_current", MATCH_FIELD_ID),
    ],
    "battery_active_power": [
        ProviderKeyCandidate("battery_active_power", MATCH_FIELD_PAR),
    ],
    # Signed battery power: positive when charging, negative when discharging.
    # Same key as ``battery_active_power`` (no sign filter — value already
    # carries direction). The resolver layer falls back to charge−discharge
    # arithmetic when no provider key is present.
    "battery_power": [
        ProviderKeyCandidate("battery_active_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("battery_active_power", MATCH_FIELD_ID),
        ProviderKeyCandidate("Battery Power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Battery Power", MATCH_FIELD_ID),
    ],
    # Same key as battery_active_power, sign-filtered for charging vs discharging.
    "battery_charging_power": [
        ProviderKeyCandidate("battery_active_power", MATCH_FIELD_PAR, sign=SIGN_POSITIVE),
    ],
    "battery_discharge_power": [
        ProviderKeyCandidate("battery_active_power", MATCH_FIELD_PAR, sign=SIGN_NEGATIVE),
    ],
    "battery_capacity": [
        ProviderKeyCandidate("bt_battery_capacity", MATCH_FIELD_PAR),
    ],
    "active_load_power": [
        ProviderKeyCandidate("load_active_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("output_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("bc_load_active_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Output Active Power", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_load_active_power_sole", MATCH_FIELD_PAR),
        ProviderKeyCandidate("AC Output Active Power", MATCH_FIELD_ID),
        # Anenji 11kw (devcode 6544) — eybond per-phase active power.
        ProviderKeyCandidate("eybond_read_43967", MATCH_FIELD_PAR),
    ],
    "active_load_percentage": [
        ProviderKeyCandidate("bt_output_load_percent", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Output Load Percent", MATCH_FIELD_ID),
        # Stevo Hybrid Monster (devcode 6467).
        ProviderKeyCandidate("bc_load_percent", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("bc_eybond_read_37", MATCH_FIELD_ID),
        ProviderKeyCandidate("Load Percent", MATCH_FIELD_PAR),
    ],
    "apparent_load_power": [
        ProviderKeyCandidate("bt_ac_output_apparent_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("AC Output Apparent Power", MATCH_FIELD_ID),
        # Stevo Hybrid Monster (devcode 6467) — name says "op load power" but
        # the unit is VA, so this is apparent (not active) power.
        ProviderKeyCandidate("bc_op_load_power", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("bc_eybond_read_27", MATCH_FIELD_ID),
        ProviderKeyCandidate("Output Apparent Power", MATCH_FIELD_PAR),
        # Devcode 2341 — last_data id form.
        ProviderKeyCandidate("bc_output_apparent_power", MATCH_FIELD_ID),
        ProviderKeyCandidate("bc_output_apparent_power", MATCH_FIELD_PAR),
    ],
    "output_priority": [
        ProviderKeyCandidate("bc_output_source_priority", MATCH_FIELD_PAR, value_map=_OUTPUT_PRIORITY_MAP),
        ProviderKeyCandidate("Output priority", MATCH_FIELD_ID, value_map=_OUTPUT_PRIORITY_MAP),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("sy_eybond_read_49", MATCH_FIELD_ID, value_map=_OUTPUT_PRIORITY_MAP),
        ProviderKeyCandidate("Output priority", MATCH_FIELD_PAR, value_map=_OUTPUT_PRIORITY_MAP),
    ],
    "charge_priority": [
        ProviderKeyCandidate("bt_charger_source_priority", MATCH_FIELD_PAR, value_map=_CHARGE_PRIORITY_MAP),
        # Anenji-style eybond (devcode 2376) — id with verbose human label in val.
        ProviderKeyCandidate("sy_eybond_read_75", MATCH_FIELD_ID, value_map=_CHARGE_PRIORITY_MAP),
        ProviderKeyCandidate("Charger Source Priority", MATCH_FIELD_PAR, value_map=_CHARGE_PRIORITY_MAP),
    ],
    "mains_status": [
        # Stevo Hybrid Monster (devcode 6467) carries it as id="gd_mains_status";
        # other firmwares may expose it via different keys — extend as we see them.
        ProviderKeyCandidate("gd_mains_status", MATCH_FIELD_ID, value_map=_MAINS_STATUS_MAP),
        # Devcode 2341 — par="Mains Status", id="gd_mains_status" (handled above).
        ProviderKeyCandidate("Mains Status", MATCH_FIELD_PAR, value_map=_MAINS_STATUS_MAP),
        ProviderKeyCandidate("Mains Status", MATCH_FIELD_ID, value_map=_MAINS_STATUS_MAP),
        ProviderKeyCandidate("bt_mains_status", MATCH_FIELD_PAR, value_map=_MAINS_STATUS_MAP),
        ProviderKeyCandidate("bc_work_state", MATCH_FIELD_PAR, value_map=_MAINS_STATUS_MAP),
        # Anenji-style eybond (devcode 2376) — par="Operating mode", val="Mains Mode" / "Off-Grid Mode".
        ProviderKeyCandidate("sy_eybond_read_14", MATCH_FIELD_ID, value_map=_MAINS_STATUS_MAP),
        ProviderKeyCandidate("Operating mode", MATCH_FIELD_PAR, value_map=_MAINS_STATUS_MAP),
        # Devcode 2341 fallback — sy_status gives "Invert Mode" / "Mains Mode".
        ProviderKeyCandidate("sy_status", MATCH_FIELD_ID, value_map=_MAINS_STATUS_MAP),
        ProviderKeyCandidate("Working State", MATCH_FIELD_PAR, value_map=_MAINS_STATUS_MAP),
    ],
    "grid_in_power": [
        ProviderKeyCandidate("gd_grid_active_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("grid_active_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Grid Power", MATCH_FIELD_ID),
    ],
    "grid_frequency": [
        ProviderKeyCandidate("gd_grid_frequency", MATCH_FIELD_PAR),
        ProviderKeyCandidate("gd_ac_input_frequency", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Grid frequency", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_grid_frequency", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Grid Frequency", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_grid_AC_frequency", MATCH_FIELD_PAR),
        ProviderKeyCandidate("AC Output Frequency", MATCH_FIELD_ID),
        # Stevo Hybrid Monster (devcode 6467) — misleading name: this id has
        # unit=Hz and value ~50, i.e. it's the grid frequency, not voltage.
        ProviderKeyCandidate("gd_phase_a_mains_voltage", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("gd_eybond_read_16", MATCH_FIELD_ID),
        ProviderKeyCandidate("Grid Frequency", MATCH_FIELD_PAR),
    ],
    "pv_power": [
        # PV1-specific keys go first so dual-MPPT firmwares (devcode 6416, etc.)
        # report the PV1 leg here, not the total. Single-MPPT devices that only
        # publish a "total" key fall through to ``pv_output_power`` below.
        ProviderKeyCandidate("pv_power", MATCH_FIELD_PAR),  # MiC 6.2 (devcode 6416) — PV1 Input Power
        ProviderKeyCandidate("pv_power", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV1 Charging Power", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV1 Input Power", MATCH_FIELD_PAR),
        # Anenji 11kw (devcode 6544) — eybond explicit PV1 power.
        ProviderKeyCandidate("eybond_read_43972", MATCH_FIELD_PAR),
        ProviderKeyCandidate("bt_input_power", MATCH_FIELD_PAR),
        # Single-MPPT fallback — total ≈ PV1 when no PV2 leg exists.
        ProviderKeyCandidate("pv_output_power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Total PV Power", MATCH_FIELD_ID),
    ],
    "pv_voltage": [
        ProviderKeyCandidate("pv_input_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("pv_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV Input Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("eybond_read_43", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV1 Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_voltage_1", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV1 Input Voltage", MATCH_FIELD_ID),
        # Anenji 11kw (devcode 6544).
        ProviderKeyCandidate("eybond_read_43970", MATCH_FIELD_PAR),
        # Stevo Hybrid Monster (devcode 6467) — pv_voltage as id is PV1.
        ProviderKeyCandidate("pv_voltage", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("pv_eybond_read_32", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV Voltage", MATCH_FIELD_PAR),
    ],
    "pv_input_current": [
        ProviderKeyCandidate("pv_input_current", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV1 Input Current", MATCH_FIELD_ID),
        # Stevo Hybrid Monster (devcode 6467).
        ProviderKeyCandidate("pv_input_current", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("pv_eybond_read_33", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV Current", MATCH_FIELD_PAR),
    ],
    "pv2_power": [
        ProviderKeyCandidate("bt_input_power_1", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV2 Charging power", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 input power", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV2 Charging Power", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Input Power", MATCH_FIELD_PAR),
        # Anenji 11kw (devcode 6544) — eybond explicit PV2 power.
        ProviderKeyCandidate("eybond_read_43975", MATCH_FIELD_PAR),
        # MiC 6.2 (devcode 6416) — PV2 input power lives under a generic
        # "eybond_read_2" alias on this firmware.
        ProviderKeyCandidate("eybond_read_2", MATCH_FIELD_PAR),
    ],
    "pv2_voltage": [
        ProviderKeyCandidate("bt_voltage_2", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV2 Input voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Input Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Input Voltage", MATCH_FIELD_PAR),
        # Anenji 11kw (devcode 6544).
        ProviderKeyCandidate("eybond_read_43973", MATCH_FIELD_PAR),
        # Stevo Hybrid Monster (devcode 6467) — counterintuitive: id
        # `pv_voltage_1` is the PV2 string.
        ProviderKeyCandidate("pv_voltage_1", MATCH_FIELD_ID),
    ],
    "pv2_input_current": [
        ProviderKeyCandidate("pv_input_current2", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV2 Input current", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Input Current", MATCH_FIELD_ID),
        ProviderKeyCandidate("PV2 Input Current", MATCH_FIELD_PAR),
        ProviderKeyCandidate("PV2 Current", MATCH_FIELD_PAR),
        # Stevo Hybrid Monster (devcode 6467).
        ProviderKeyCandidate("pv_input_current_2", MATCH_FIELD_ID),
    ],
    "grid_input_voltage": [
        ProviderKeyCandidate("gd_ac_input_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("gd_grid_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Grid Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_grid_voltage", MATCH_FIELD_PAR),
        # Anenji 11kw (devcode 6544).
        ProviderKeyCandidate("eybond_read_43960", MATCH_FIELD_PAR),
        # Stevo Hybrid Monster (devcode 6467).
        ProviderKeyCandidate("gd_bse_input_voltage", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("gd_eybond_read_15", MATCH_FIELD_ID),
        ProviderKeyCandidate("Grid Voltage", MATCH_FIELD_PAR),
    ],
    "grid_output_voltage": [
        ProviderKeyCandidate("bc_output_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("Output Voltage", MATCH_FIELD_ID),
        ProviderKeyCandidate("bt_ac_output_voltage", MATCH_FIELD_PAR),
        ProviderKeyCandidate("AC Output Voltage", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("bc_eybond_read_23", MATCH_FIELD_ID),
        ProviderKeyCandidate("Output Voltage", MATCH_FIELD_PAR),
    ],
    "dc_module_temperature": [
        ProviderKeyCandidate("DC Module Termperature", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376) — same human label, lives in par too.
        ProviderKeyCandidate("DC Module Termperature", MATCH_FIELD_PAR),
        ProviderKeyCandidate("sy_eybond_read_38", MATCH_FIELD_ID),
    ],
    "inv_temperature": [
        ProviderKeyCandidate("INV Module Termperature", MATCH_FIELD_ID),
        # Anenji-style eybond (devcode 2376).
        ProviderKeyCandidate("INV Module Termperature", MATCH_FIELD_PAR),
        ProviderKeyCandidate("sy_eybond_read_39", MATCH_FIELD_ID),
    ],
    "bt_utility_charge": [
        ProviderKeyCandidate("bt_utility_charge", MATCH_FIELD_PAR),
    ],
    "bt_total_charge_current": [
        ProviderKeyCandidate("bt_total_charge_current", MATCH_FIELD_PAR),
    ],
    "bt_cutoff_voltage": [
        ProviderKeyCandidate("bt_battery_cut_off_voltage", MATCH_FIELD_PAR),
    ],
    "sy_nominal_out_power": [
        ProviderKeyCandidate("sy_nonimal_output_active_power", MATCH_FIELD_PAR),
    ],
    "sy_rated_battery_voltage": [
        ProviderKeyCandidate("sy_rated_battery_voltage", MATCH_FIELD_PAR),
    ],
    "bt_comeback_utility_voltage": [
        ProviderKeyCandidate("bt_comeback_utility_iode", MATCH_FIELD_PAR),
    ],
    "bt_comeback_battery_voltage": [
        ProviderKeyCandidate("bt_battery_mode_voltage", MATCH_FIELD_PAR),
    ],
}
