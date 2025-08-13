# providers/registry.py
from typing import Callable, Dict

from .aneji_modbus_provider import AnejiModbusProvider
from .base import InverterProvider
from .qpigs_provider import QpigsProvider

ProviderFactory = Callable[..., InverterProvider]

REGISTRY: Dict[str, ProviderFactory] = {
    "direct": QpigsProvider,
    "anern_modbus": AnejiModbusProvider,
}


def create_provider(kind: str, **kwargs) -> InverterProvider:
    if kind not in REGISTRY:
        raise ValueError(f"Unknown provider kind: {kind}")
    return REGISTRY[kind](**kwargs)
