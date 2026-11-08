"""Shared base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HungryrootCoordinator


class HungryrootEntity(CoordinatorEntity[HungryrootCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = "Data from hungryroot.com (unofficial)"

    def __init__(self, coordinator: HungryrootCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name="Hungryroot",
            manufacturer="Hungryroot",
            model="Grocery subscription",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.hungryroot.com/account/",
        )

    @property
    def next_order(self) -> dict | None:
        return (self.coordinator.data or {}).get("next_order")
