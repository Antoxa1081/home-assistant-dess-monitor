"""Enumerations shared across inverter protocols.

These mirror the enum values used by Voltronic Axpert/PI30 firmware. Newer
protocols (e.g. PI18) reuse most of them directly, even when raw codes differ —
the parser maps codes to ``.name`` strings so downstream sensors stay stable.
"""
from __future__ import annotations

from enum import Enum


class BatteryType(Enum):
    AGM = "0"
    Flooded = "1"
    UserDefined = "2"
    LIB = "3"
    LIC = "4"
    RESERVED = "5"
    RESERVED_1 = "6"
    RESERVED_2 = "7"


class ACInputVoltageRange(Enum):
    Appliance = "0"
    UPS = "1"


class OutputSourcePriority(Enum):
    UtilityFirst = "0"
    SolarFirst = "1"
    SBU = "2"
    BatteryOnly = "4"
    UtilityOnly = "5"
    SolarAndUtility = "6"
    Smart = "7"


class ChargerSourcePriority(Enum):
    UtilityFirst = "0"
    SolarFirst = "1"
    SolarAndUtility = "2"
    OnlySolar = "3"


class ParallelMode(Enum):
    Master = "0"
    Slave = "1"
    Standalone = "2"
    PARALLEL_1_PHASE = "3"
    PARALLEL_3_PHASE = "4"


class OperatingMode(Enum):
    PowerOn = "P"
    Standby = "S"
    Line = "L"
    Battery = "B"
    ShutdownApproaching = "D"
    Fault = "F"


# ---------------------------------------------------------------------------
# Settings — values used by the *write* path (PB Txx, POPxx, PCPxx ...).
# These are intentionally NOT the same enums as the readback codes above:
# QPIRI returns "0"/"1"/"2" for output_source_priority, while the matching
# command is "POP00"/"POP01"/"POP02". Keep them distinct so the wire codes
# can never accidentally cross-pollinate.
# ---------------------------------------------------------------------------


class BatteryTypeSetting(Enum):
    AGM = "PBT00"
    Flooded = "PBT01"
    UserDefined = "PBT02"
    LiFePO4 = "PBT03"


class OutputSourcePrioritySetting(Enum):
    UtilityFirst = "POP00"
    SBU = "POP01"
    SolarFirst = "POP02"


class ChargeSourcePrioritySetting(Enum):
    UtilityFirst = "PCP00"
    SolarFirst = "PCP01"
    SolarAndUtility = "PCP02"
