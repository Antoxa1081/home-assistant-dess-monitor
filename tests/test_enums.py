"""Tests for the protocol enumerations."""
from __future__ import annotations

from enum import Enum

import pytest

from custom_components.dess_monitor.api.protocols import enums

READBACK_ENUMS = [
    enums.BatteryType,
    enums.ACInputVoltageRange,
    enums.OutputSourcePriority,
    enums.ChargerSourcePriority,
    enums.ParallelMode,
    enums.OperatingMode,
]

SETTING_ENUMS = [
    enums.BatteryTypeSetting,
    enums.OutputSourcePrioritySetting,
    enums.ChargeSourcePrioritySetting,
]

ALL_ENUMS = READBACK_ENUMS + SETTING_ENUMS


class TestEnumInvariants:
    @pytest.mark.parametrize("enum_cls", ALL_ENUMS)
    def test_is_enum_subclass(self, enum_cls):
        assert issubclass(enum_cls, Enum)

    @pytest.mark.parametrize("enum_cls", ALL_ENUMS)
    def test_values_are_strings(self, enum_cls):
        for member in enum_cls:
            assert isinstance(member.value, str)

    @pytest.mark.parametrize("enum_cls", ALL_ENUMS)
    def test_values_are_unique(self, enum_cls):
        values = [m.value for m in enum_cls]
        assert len(values) == len(set(values))

    @pytest.mark.parametrize("enum_cls", ALL_ENUMS)
    def test_lookup_by_value_round_trips(self, enum_cls):
        for member in enum_cls:
            assert enum_cls(member.value) is member


class TestReadbackEnumValues:
    @pytest.mark.parametrize("enum_cls", READBACK_ENUMS[:-1])
    def test_readback_values_are_digit_codes(self, enum_cls):
        # All numeric readback enums use single-digit string codes.
        for member in enum_cls:
            assert member.value.isdigit()

    def test_battery_type_codes(self):
        assert enums.BatteryType.AGM.value == "0"
        assert enums.BatteryType.LIB.value == "3"
        assert enums.BatteryType("2") is enums.BatteryType.UserDefined

    def test_output_source_priority_codes(self):
        assert enums.OutputSourcePriority.UtilityFirst.value == "0"
        assert enums.OutputSourcePriority.SBU.value == "2"
        assert enums.OutputSourcePriority.BatteryOnly.value == "4"
        assert enums.OutputSourcePriority.Smart.value == "7"

    def test_charger_source_priority_codes(self):
        assert enums.ChargerSourcePriority.UtilityFirst.value == "0"
        assert enums.ChargerSourcePriority.OnlySolar.value == "3"

    def test_operating_mode_letters(self):
        assert enums.OperatingMode.PowerOn.value == "P"
        assert enums.OperatingMode.Line.value == "L"
        assert enums.OperatingMode.Battery.value == "B"
        assert enums.OperatingMode("F") is enums.OperatingMode.Fault

    def test_ac_input_voltage_range(self):
        assert enums.ACInputVoltageRange.Appliance.value == "0"
        assert enums.ACInputVoltageRange.UPS.value == "1"

    def test_parallel_mode(self):
        assert enums.ParallelMode.Master.value == "0"
        assert enums.ParallelMode.PARALLEL_3_PHASE.value == "4"


class TestSettingEnumValues:
    @pytest.mark.parametrize("enum_cls,prefix", [
        (enums.BatteryTypeSetting, "PBT"),
        (enums.OutputSourcePrioritySetting, "POP"),
        (enums.ChargeSourcePrioritySetting, "PCP"),
    ])
    def test_setting_command_prefixes(self, enum_cls, prefix):
        for member in enum_cls:
            assert member.value.startswith(prefix)

    def test_battery_type_setting_codes(self):
        assert enums.BatteryTypeSetting.AGM.value == "PBT00"
        assert enums.BatteryTypeSetting.LiFePO4.value == "PBT03"

    def test_output_source_priority_setting_codes(self):
        assert enums.OutputSourcePrioritySetting.UtilityFirst.value == "POP00"
        assert enums.OutputSourcePrioritySetting.SBU.value == "POP01"
        assert enums.OutputSourcePrioritySetting.SolarFirst.value == "POP02"

    def test_charge_source_priority_setting_codes(self):
        assert enums.ChargeSourcePrioritySetting.UtilityFirst.value == "PCP00"
        assert enums.ChargeSourcePrioritySetting.SolarFirst.value == "PCP01"
        assert enums.ChargeSourcePrioritySetting.SolarAndUtility.value == "PCP02"

    def test_setting_and_readback_enums_are_distinct(self):
        # The readback "0"/"1"/"2" codes must never equal the POPxx settings.
        readback = {m.value for m in enums.OutputSourcePriority}
        settings = {m.value for m in enums.OutputSourcePrioritySetting}
        assert readback.isdisjoint(settings)
