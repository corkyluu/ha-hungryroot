"""Hungryroot binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HungryrootConfigEntry
from .entity import HungryrootEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HungryrootConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HungryrootBoxEditable(entry.runtime_data)])


class HungryrootBoxEditable(HungryrootEntity, BinarySensorEntity):
    """On while the next box can still be changed."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "box_editable")

    @property
    def is_on(self) -> bool | None:
        order = self.next_order
        if not order:
            return None
        if order.get("deadline_exceeded") is True:
            return False
        cutoff = order.get("cutoff")
        if cutoff is None:
            return None
        return dt_util.utcnow() < cutoff
