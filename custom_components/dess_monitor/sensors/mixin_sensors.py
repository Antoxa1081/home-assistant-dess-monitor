from datetime import datetime, timezone

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event


class EntityStateSubscriberMixin:
    """
    Подписка на изменение состояния внешней number-сущности и хранение её float-значения.
    """

    def __init__(self, hass, entity_id: str, attr_name: str):
        self._hass = hass
        self._entity_id = entity_id
        self._subscribed_attr = attr_name
        setattr(self, attr_name, None)
        async_track_state_change_event(hass, [entity_id], self._handle_entity_change)

    @callback
    def _handle_entity_change(self, event):
        state = event.data.get("new_state")
        try:
            value = float(state.state)
            if value <= 0:
                value = None
        except (ValueError, TypeError, AttributeError):
            value = None
        setattr(self, self._subscribed_attr, value)
        self._on_subscribed_value_update()

    def _on_subscribed_value_update(self):
        """Хук: вызывается после обновления значения subscribed entity."""
        pass


class VoltageEntityMixin(EntityStateSubscriberMixin):
    """
    Миксин для работы с единственным voltage entity как bulk и float.
    """

    def get_bulk_charging_voltage(self) -> float | None:
        return getattr(self, self._subscribed_attr)

    def get_floating_charging_voltage(self) -> float | None:
        return getattr(self, self._subscribed_attr)


class SectionReaderMixin:
    """
    Безопасное чтение float-значений из секции data[section_name].
    """

    def __init__(self, data_section: str):
        self._data_section = data_section

    def get_section_float(self, key: str) -> float | None:
        try:
            raw = self.data.get(self._data_section, {}).get(key)
            value = float(raw)
            return value if value > 0 else None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None


class SocCalculatorMixin:
    """
    Накопление энергии и расчёт SOC в процентах.
    """

    def __init__(self):
        self._accumulated_energy_wh = 0.0
        self._prev_power = 0.0
        self._prev_ts = None
        self._has_prev = False

    def reset_accumulator(self, capacity_wh: float, soc_percent: float):
        # Инициализация накопленной энергии по SOC
        self._accumulated_energy_wh = capacity_wh * soc_percent / 100.0
        now = datetime.now(timezone.utc)
        self._prev_ts = now
        self._prev_power = 0.0
        self._has_prev = True

    def _accumulate(self, current_power: float):
        now = datetime.now(timezone.utc)
        if not self._has_prev:
            self._prev_ts = now
            self._prev_power = current_power
            self._has_prev = True
            return
        hours = (now - self._prev_ts).total_seconds() / 3600
        self._accumulated_energy_wh += (self._prev_power + current_power) / 2 * hours
        self._prev_power = current_power
        self._prev_ts = now

    def calculate_soc(
            self,
            capacity_wh: float,
            bulk_v: float,
            float_v: float,
            current_power: float,
            current_voltage: float,
    ) -> float:
        self._accumulate(current_power)
        # Если заряд на уровне bulk или удерживается float при малом токе
        if current_voltage >= bulk_v or (
                current_voltage >= float_v and 0 < current_power <= 2 * bulk_v
        ):
            self._accumulated_energy_wh = capacity_wh
        self._accumulated_energy_wh = min(
            max(self._accumulated_energy_wh, 0.0), capacity_wh
        )
        return (self._accumulated_energy_wh / capacity_wh) * 100
