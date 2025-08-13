from custom_components.dess_monitor.api.helpers import resolve_param
from custom_components.dess_monitor.api.resolvers.data_resolvers import resolve_pv_power, \
    resolve_battery_discharge_current, resolve_battery_charging_current, resolve_battery_charging_power, resolve_battery_discharge_power

test_data = {
    "last_data": {
        "gts": "2025-05-29 11:47:42",
        "pars": {
            "gd_": [
                {
                    "id": "gd_eybond_read_15",
                    "par": "Grid Voltage",
                    "val": "244.7",
                    "unit": "V"
                },
                {
                    "id": "gd_eybond_read_16",
                    "par": "Grid Frequency",
                    "val": "49.98",
                    "unit": "Hz"
                },
                {
                    "id": "gd_grid_active_power",
                    "par": "Grid Power",
                    "val": "0",
                    "unit": "W"
                },
                {
                    "id": "gd_eybond_read_45",
                    "par": "AC charging current",
                    "val": "0.0",
                    "unit": "A"
                }
            ],
            "sy_": [
                {
                    "id": "sy_eybond_read_14",
                    "par": "Operating mode",
                    "val": "Off-Grid Mode"
                },
                {
                    "id": "sy_eybond_read_38",
                    "par": "DC Module Termperature",
                    "val": "33",
                    "unit": "\u00b0C"
                },
                {
                    "id": "sy_eybond_read_39",
                    "par": "INV Module Termperature",
                    "val": "36",
                    "unit": "\u00b0C"
                },
                {
                    "id": "sy_eybond_read_49",
                    "par": "Output priority",
                    "val": "SBU"
                },
                {
                    "id": "sy_eybond_read_75",
                    "par": "Charger Source Priority",
                    "val": "Only PV charging is allowed"
                }
            ],
            "pv_": [
                {
                    "id": "pv_eybond_read_32",
                    "par": "PV Voltage",
                    "val": "251.1",
                    "unit": "V"
                },
                {
                    "id": "pv_eybond_read_33",
                    "par": "PV Current",
                    "val": "3.1",
                    "unit": "A"
                },
                {
                    "id": "pv_output_power",
                    "par": "PV Power",
                    "val": "798",
                    "unit": "W"
                },
                {
                    "id": "pv_eybond_read_46",
                    "par": "PV charging current",
                    "val": "8.9",
                    "unit": "A"
                }
            ],
            "bt_": [
                {
                    "id": "bt_eybond_read_28",
                    "par": "Battery Voltage",
                    "val": "53.9",
                    "unit": "V"
                },
                {
                    "id": "bt_eybond_read_29",
                    "par": "Battery Current",
                    "val": "8.4",
                    "unit": "A"
                }
            ],
            "bc_": [
                {
                    "id": "bc_eybond_read_23",
                    "par": "Output Voltage",
                    "val": "239.9",
                    "unit": "V"
                },
                {
                    "id": "bc_eybond_read_24",
                    "par": "Output Current",
                    "val": "2.3",
                    "unit": "A"
                },
                {
                    "id": "bc_eybond_read_25",
                    "par": "Output frequency",
                    "val": "49.99",
                    "unit": "HZ"
                },
                {
                    "id": "bc_load_active_power",
                    "par": "Output Active Power",
                    "val": "308",
                    "unit": "W"
                },
                {
                    "id": "bc_eybond_read_27",
                    "par": "Output Apparent Power",
                    "val": "551",
                    "unit": "VA"
                },
                {
                    "id": "bc_eybond_read_37",
                    "par": "Load Percent",
                    "val": "9",
                    "unit": "%"
                }
            ]
        }
    },
    "energy_flow": {
        "brand": 0,
        "status": 0,
        "date": "2025-05-29 18:52:18",
        "bt_status": [
            {
                "par": "bt_battery_capacity",
                "val": "90.0000",
                "unit": "%",
                "status": -1
            },
            {
                "par": "battery_active_power",
                "val": "-0.4150",
                "unit": "kW",
                "status": 1
            }
        ],
        "pv_status": [
            {
                "par": "pv_output_power",
                "val": "0.7980",
                "unit": "kW",
                "status": 1
            }
        ],
        "gd_status": [
            {
                "par": "grid_active_power",
                "val": "0.0000",
                "unit": "kW",
                "status": 2
            }
        ],
        "bc_status": [
            {
                "par": "load_active_power",
                "val": "0.3080",
                "unit": "kW",
                "status": -1
            }
        ],
        "ol_status": [
            {
                "par": "oil_output_power",
                "val": "0",
                "status": 0
            }
        ],
        "we_status": [
            {
                "par": "wind_output_power",
                "val": "0",
                "status": 0
            }
        ],
        "mi_status": [],
        "mt_status": [],
        "wp_status": [],
        "gn_status": [],
        "fd_status": []
    },
    "pars": {
        "parameter": [
            {
                "par": "bt_eybond_read_28",
                "name": "Battery Voltage",
                "val": "53.9000",
                "unit": "V"
            },
            {
                "par": "gd_eybond_read_45",
                "name": "AC charging current",
                "val": "0.0000",
                "unit": "A"
            },
            {
                "par": "pv_eybond_read_32",
                "name": "PV Voltage",
                "val": "251.1000",
                "unit": "V"
            },
            {
                "par": "pv_eybond_read_33",
                "name": "PV Current",
                "val": "3.1000",
                "unit": "A"
            },
            {
                "par": "pv_eybond_read_46",
                "name": "PV charging current",
                "val": "8.9000",
                "unit": "A"
            },
            {
                "par": "pv_output_power",
                "name": "PV Power",
                "val": "0.7980",
                "unit": "kW"
            }
        ]
    },
}
print('resolve_pv_power', resolve_pv_power(test_data, {}))
print('resolve_battery_discharge_current', resolve_battery_discharge_current(test_data, {}))
print('resolve_battery_discharge_power', resolve_battery_discharge_power(test_data, {}))
print('resolve_battery_charging_current', resolve_battery_charging_current(test_data, {}))
print('resolve_battery_charging_power', resolve_battery_charging_power(test_data, {}))
