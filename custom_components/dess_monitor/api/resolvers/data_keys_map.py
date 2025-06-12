from typing import Dict

SENSOR_KEYS_MAP: Dict[str, list[str]] = {
    "battery_charging_current": [
        "bt_eybond_read_29",
        "bt_battery_charging_current",
        "Battery charging current",
        "eybond_read_25",
        "Battery Current",
    ],
    "battery_charging_voltage": [
        "bt_vulk_charging_voltage",
        "Battery charging voltage",
    ],
    "battery_discharge_current": [
        "bt_eybond_read_29",
        "bt_battery_discharge_current",
        "bt_discharge_current",
        "Battery discharge current",
    ],
    "battery_voltage": [
        "bt_battery_voltage",
        "Battery Voltage",
        "eybond_read_24",
    ],
    "battery_active_power": [
        "battery_active_power",
    ],
    "active_load_power": [
        "load_active_power",
        "output_power",
        "bc_load_active_power",
        "Output Active Power",
        "bt_load_active_power_sole",
        "AC Output Active Power",
    ],
    "active_load_percentage": [
        "bt_output_load_percent",
        "Output Load Percent",
    ],
    "output_priority": [
        "bc_output_source_priority",
        "Output priority",
    ],
    "output_priority_option": [
        'bse_eybond_ctrl_49',
        'Output priority',
        'los_output_source_priority',
        'bse_output_source_priority',
        'Output source priority rating'
    ],
    "charge_priority": [
        "bt_charger_source_priority",
    ],
    "grid_in_power": [
        "gd_grid_active_power",
        "grid_active_power",
        "Grid Power",
    ],
    "battery_capacity": [
        "bt_battery_capacity",
    ],
    "grid_frequency": [
        "gd_grid_frequency",
        "gd_ac_input_frequency",
        "Grid frequency",
        "bt_grid_frequency",
        "Grid Frequency",
        "bt_grid_AC_frequency",
        "AC Output Frequency",
    ],
    "pv_power": [
        "pv_output_power",
        "Total PV Power",
        "bt_input_power",
        "PV1 Charging Power",
    ],
    "pv_voltage": [
        "pv_input_voltage",
        "pv_voltage",
        "PV Voltage",
        "PV Input Voltage",
        "eybond_read_43",
        "PV1 Voltage",
        "bt_voltage_1",
        "PV1 Input Voltage",
    ],
    "pv_input_current": [
        "pv_input_current",
        "PV1 Input Current",
    ],
    "pv2_power": [
        "bt_input_power_1",
        "PV2 Charging power",
    ],
    "pv2_voltage": [
        "bt_voltage_2",
        "PV2 Input voltage",
    ],
    "pv2_input_current": [
        "pv_input_current2",
        "PV2 Input current",
    ],
    "grid_input_voltage": [
        "gd_ac_input_voltage",
        "gd_grid_voltage",
        "Grid Voltage",
        "bt_grid_voltage",
    ],
    "grid_output_voltage": [
        "bc_output_voltage",
        "Output Voltage",
        "bt_ac_output_voltage",
        "AC Output Voltage",
    ],
    "dc_module_temperature": [
        "DC Module Termperature",
    ],
    "inv_temperature": [
        "INV Module Termperature",
    ],
    "bt_utility_charge": [
        "bt_utility_charge",
    ],
    "bt_total_charge_current": [
        "bt_total_charge_current",
    ],
    "bt_cutoff_voltage": [
        "bt_battery_cut_off_voltage",
    ],
    "sy_nominal_out_power": [
        "sy_nonimal_output_active_power",
    ],
    "sy_rated_battery_voltage": [
        "sy_rated_battery_voltage",
    ],
    "bt_comeback_utility_voltage": [
        "bt_comeback_utility_iode",
    ],
    "bt_comeback_battery_voltage": [
        "bt_battery_mode_voltage",
    ],
    "apparent_load_power": [
        "bt_ac_output_apparent_power",
        "AC Output Apparent Power",
    ]
}
