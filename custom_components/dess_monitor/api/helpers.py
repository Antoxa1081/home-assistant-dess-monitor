from typing import Any, Dict, Optional

from custom_components.dess_monitor.api import set_ctrl_device_param, get_device_ctrl_value, send_device_direct_command
from custom_components.dess_monitor.api.commands.direct_commands import decode_direct_response, get_command_hex
from custom_components.dess_monitor.api.resolvers.data_keys_map import SENSOR_KEYS_MAP


def resolve_param(data, where, case_insensitive=False, find_all=False, default=None, root_keys=None):
    """
    Recursively searches for elements in a nested structure that satisfy 'where'.

    Args:
      data: The input data (dict, list, etc.).
      where: A dict of conditions (AND mode) or a list of dicts (OR mode).
      case_insensitive: Compare strings in lower-case if True.
      find_all: Return all matching elements if True; otherwise, first match.
      default: Value to return if no match is found.
      root_keys: List of keys at root to start the search; if None, search full structure.

    Returns:
      A matching element (or list of elements) or default if not found.
    """
    found = []

    def _matches_conditions(item):
        # OR mode if where is a list; AND mode if dict.
        if isinstance(where, list):
            for condition in where:
                if not isinstance(condition, dict):
                    continue
                match = True
                for key, value in condition.items():
                    if key not in item:
                        match = False
                        break
                    item_val = item[key]
                    if case_insensitive and isinstance(item_val, str) and isinstance(value, str):
                        if item_val.lower() != value.lower():
                            match = False
                            break
                    else:
                        if item_val != value:
                            match = False
                            break
                if match:
                    return True
            return False
        elif isinstance(where, dict):
            for key, value in where.items():
                if key not in item:
                    return False
                item_val = item[key]
                if case_insensitive and isinstance(item_val, str) and isinstance(value, str):
                    if item_val.lower() != value.lower():
                        return False
                else:
                    if item_val != value:
                        return False
            return True
        return False

    def _search(current):
        nonlocal found
        if isinstance(current, dict):
            if _matches_conditions(current):
                found.append(current)
                if not find_all:
                    return True
            for v in current.values():
                if isinstance(v, (dict, list)):
                    if _search(v) and not find_all:
                        return True
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    if _search(item) and not find_all:
                        return True
        return False

    if root_keys is not None and isinstance(data, dict):
        for key in root_keys:
            if key in data:
                _search(data[key])
    else:
        _search(data)

    if find_all:
        return found if found else default
    else:
        return found[0] if found else default


def safe_float(val: Optional[str], default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_sensor_value_simple(
        name: str,
        data: Dict[str, Any],
        device_data: Dict[str, Any]
) -> Optional[str]:
    keys = SENSOR_KEYS_MAP.get(name, [])

    for key in keys:
        res = resolve_param(data, {"id": key}, case_insensitive=True)
        if res:
            return res.get("val")
        res = resolve_param(data, {"par": key}, case_insensitive=True)
        if res:
            if res.get("status") != 0:
                return res.get("val")
    return None


def get_sensor_value_simple_entry(
        name: str,
        data: Dict[str, Any],
        device_data: Dict[str, Any]
) -> tuple[str, Any, Any] | None:
    """
    Ищет значение сенсора по ключам из SENSOR_KEYS_MAP[name].
    Возвращает кортеж (имя_поля, значение), где имя_поля — "id" или "par".
    """
    keys = SENSOR_KEYS_MAP.get(name, [])
    for key in keys:
        res = resolve_param(data, {"id": key}, case_insensitive=True)
        if res:
            return res.get("id"), res.get("val"), res.get("unit", None)
        res = resolve_param(data, {"par": key}, case_insensitive=True)
        if res:
            if res.get("status") == 0:
                return None
            return res.get("par"), res.get("val"), res.get("unit", None)
    return None


async def set_inverter_output_priority(token: str, secret: str, device_data, value: str):
    match device_data['devcode']:
        case 2341:
            map_param_value = {
                'Utility': '0',
                'Solar': '1',
                'SBU': '2',
            }
            param_value = map_param_value[value]

            param_id = 'los_output_source_priority'
        case 2428:
            map_param_value = {
                'Utility': '12336',
                'Solar': '12337',
                'SBU': '12338',
                'SUB': '12339',
            }
            param_value = map_param_value[value]

            param_id = 'bse_output_source_priority'
        case 2376:
            map_param_value = {
                'Utility': '0',
                'Solar': '1',
                'SBU': '2',
                'SUB': '3'  
            }
            param_value = map_param_value[value]

            param_id = 'bse_eybond_ctrl_49'

        case _:
            return
    return await set_ctrl_device_param(token, secret, device_data, param_id, param_value)


async def get_inverter_output_priority(token: str, secret: str, ctrl_fields, device_data):
    map_param_value = {
        'UTILITY FIRST': 'Utility',
        'UTILITY': 'Utility',
        'SOLAR FIRST': 'Solar',
        'SOLAR': 'Solar',
        'SOL': 'Solar',
        'SBU': 'SBU',
        'SBU FIRST': 'SBU',
        'UTI': 'Utility',
        'SUB': 'SUB',
        'SUB FIRST': 'SUB',
        None: None
    }

    entry = get_sensor_value_simple_entry('output_priority_option', ctrl_fields, device_data)

    if entry is None:
        return None
    param_id, _, _ = entry
    result = await get_device_ctrl_value(token, secret, device_data, param_id)
    if result['val'].upper() not in map_param_value:
        return None
    return map_param_value[result['val'].upper()]


async def get_direct_data(token: str, secret: str, device_data, cmd_name):
    result = await send_device_direct_command(token, secret, device_data, get_command_hex(cmd_name))
    return decode_direct_response(cmd_name, result['dat'])
