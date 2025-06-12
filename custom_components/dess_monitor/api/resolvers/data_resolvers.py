from custom_components.dess_monitor.api.helpers import get_sensor_value_simple, safe_float, \
    get_sensor_value_simple_entry


def resolve_battery_charging_current(data, device_data):
    raw = get_sensor_value_simple("battery_charging_current", data, device_data)
    return max(safe_float(raw), 0.0)


def resolve_battery_charging_voltage(data, device_data):
    return safe_float(get_sensor_value_simple("battery_charging_voltage", data, device_data))


def resolve_battery_discharge_current(
        data,
        device_data,
) -> float:
    """
    Для поля bt_eybond_read_29 — возвращает ABS только для отрицательных значений,
    иначе 0.0.
    Для всех остальных полей — возвращает значение как есть (может быть +
    или −).
    Если ничего не найдено — 0.0.
    """
    found = get_sensor_value_simple_entry("battery_discharge_current", data, device_data)
    if not found:
        return 0.0

    key, raw_val, unit = found
    value = safe_float(raw_val)

    if key == "bt_eybond_read_29" or key == "Battery Current":
        # Только отрицательный ток разряда, положительный — в 0
        return abs(value) if value < 0 else 0.0
    else:
        # Для прочих сенсоров возвращаем значение напрямую
        return value


def resolve_battery_voltage(data, device_data):
    return safe_float(get_sensor_value_simple("battery_voltage", data, device_data))


def resolve_battery_charging_power(data, device_data):
    found = get_sensor_value_simple_entry("battery_active_power", data, device_data)
    if found:
        key, raw_val, unit = found
        value = safe_float(raw_val)
        if unit == 'kW':
            value *= 1000
        if value > 0:
            return value
        else:
            return 0.0
    current = resolve_battery_charging_current(data, device_data)
    voltage = resolve_battery_charging_voltage(data, device_data) or resolve_battery_voltage(data, device_data)
    return current * voltage


def resolve_battery_discharge_power(data, device_data):
    found = get_sensor_value_simple_entry("battery_active_power", data, device_data)
    if found:
        key, raw_val, unit = found
        value = safe_float(raw_val)
        if unit == 'kW':
            value *= 1000
        if value < 0:
            return abs(value)
        else:
            return 0.0
    return resolve_battery_discharge_current(data, device_data) * resolve_battery_voltage(data, device_data)


def resolve_active_load_power(data, device_data):
    return safe_float(get_sensor_value_simple("active_load_power", data, device_data)) * 1000


def resolve_active_load_percentage(data, device_data):
    return safe_float(get_sensor_value_simple("active_load_percentage", data, device_data))


def resolve_output_priority(data, device_data):
    return data['device_extra']['output_priority']


def resolve_charge_priority(data, device_data):
    mapper = {
        'solar priority': 'SOLAR_PRIORITY',
        'solar and mains': 'SOLAR_AND_UTILITY',
        'solar only': 'SOLAR_ONLY',
        'n/a': 'NONE',
    }
    raw = get_sensor_value_simple("charge_priority", data, device_data)
    if raw is None:
        return None
    return mapper.get(raw.lower(), None)


def resolve_grid_in_power(data, device_data):
    return safe_float(get_sensor_value_simple("grid_in_power", data, device_data))


def resolve_battery_capacity(data, device_data):
    return safe_float(get_sensor_value_simple("battery_capacity", data, device_data))


def resolve_grid_frequency(data, device_data):
    return get_sensor_value_simple("grid_frequency", data, device_data)


def resolve_pv_power(data, device_data):
    found = (get_sensor_value_simple_entry("pv_power", data, device_data))

    if not found:
        return None

    key, raw_val, unit = found
    val = safe_float(raw_val)
    if unit == 'kW':
        val *= 1000

    return val


def resolve_pv2_power(data, device_data):
    found = (get_sensor_value_simple_entry("pv2_power", data, device_data))

    if not found:
        return None

    key, raw_val, unit = found
    val = safe_float(raw_val)
    if unit == 'kW':
        val *= 1000

    return val


def resolve_pv_voltage(data, device_data):
    return get_sensor_value_simple("pv_voltage", data, device_data)


def resolve_pv2_voltage(data, device_data):
    return get_sensor_value_simple("pv2_voltage", data, device_data)


def resolve_grid_input_voltage(data, device_data):
    return get_sensor_value_simple("grid_input_voltage", data, device_data)


def resolve_grid_output_voltage(data, device_data):
    return get_sensor_value_simple("grid_output_voltage", data, device_data)


def resolve_dc_module_temperature(data, device_data):
    return get_sensor_value_simple("dc_module_temperature", data, device_data)


def resolve_inv_temperature(data, device_data):
    return get_sensor_value_simple("inv_temperature", data, device_data)


def resolve_bt_utility_charge(data, device_data):
    return get_sensor_value_simple("bt_utility_charge", data, device_data)


def resolve_bt_total_charge_current(data, device_data):
    return get_sensor_value_simple("bt_total_charge_current", data, device_data)


def resolve_bt_cutoff_voltage(data, device_data):
    return get_sensor_value_simple("bt_cutoff_voltage", data, device_data)


def resolve_sy_nominal_out_power(data, device_data):
    return get_sensor_value_simple("sy_nominal_out_power", data, device_data)


def resolve_sy_rated_battery_voltage(data, device_data):
    return get_sensor_value_simple("sy_rated_battery_voltage", data, device_data)


def resolve_bt_comeback_utility_voltage(data, device_data):
    return get_sensor_value_simple("bt_comeback_utility_voltage", data, device_data)


def resolve_bt_comeback_battery_voltage(data, device_data):
    return get_sensor_value_simple("bt_comeback_battery_voltage", data, device_data)
