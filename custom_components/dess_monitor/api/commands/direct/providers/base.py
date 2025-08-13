# providers/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol, runtime_checkable
from enum import Enum

class InverterOperatingMode(str, Enum):
    POWER_ON = "PowerOn"
    STANDBY = "Standby"
    LINE = "Line"
    BATTERY = "Battery"
    FAULT = "Fault"
    UNKNOWN = "Unknown"

@dataclass
class CanonicalSnapshot:
    # Унифицированные поля (минимальный MVP)
    ts: float                               # time.monotonic() или time.time()
    model: Optional[str] = None
    serial: Optional[str] = None
    fw: Optional[str] = None

    grid_voltage_v: Optional[float] = None
    grid_freq_hz: Optional[float] = None

    ac_out_voltage_v: Optional[float] = None
    ac_out_freq_hz: Optional[float] = None
    out_active_power_w: Optional[float] = None
    out_apparent_power_va: Optional[float] = None
    load_percent: Optional[float] = None

    battery_voltage_v: Optional[float] = None
    battery_current_a: Optional[float] = None   # +заряд / –разряд (или наоборот — главное зафиксировать правило)
    battery_soc_percent: Optional[float] = None
    inverter_temp_c: Optional[float] = None

    pv_voltage_v: Optional[float] = None
    pv_current_a: Optional[float] = None
    pv_power_w: Optional[float] = None

    operating_mode: InverterOperatingMode = InverterOperatingMode.UNKNOWN
    # Дополнительно: оценка сетевого ввода (твоя resolve_grid_input_power)
    grid_input_power_w: Optional[float] = None

    # «Сырые» источники — чтобы текущие сенсоры продолжили работать
    raw: Dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class InverterProvider(Protocol):
    """Единый интерфейс провайдера для любых инверторов."""
    name: str

    async def probe(self) -> bool:
        """Проверка соединения/готовности. Необязательные быстрые команды."""
        ...

    async def read_snapshot(self) -> CanonicalSnapshot:
        """Снимает и нормализует текущие телеметрические данные; возвращает CanonicalSnapshot."""
        ...
