"""Hungryroot sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HungryrootConfigEntry
from .entity import HungryrootEntity


def _next(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("next_order") or {}


def _history(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.get("history") or []


def _history_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "delivery_date": o["delivery_date"].isoformat() if o.get("delivery_date") else None,
            "status": o.get("status"),
            "total": o.get("total"),
            "items": len(o.get("items") or []),
            "recipes": o.get("recipes") or [],
        }
        for o in _history(data)
    ]


def _spend(data: dict[str, Any]) -> float | None:
    totals = [o["total"] for o in _history(data) if o.get("total") is not None]
    return round(sum(totals), 2) if totals else None


@dataclass(frozen=True, kw_only=True)
class HungryrootSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[HungryrootSensorDescription, ...] = (
    HungryrootSensorDescription(
        key="next_delivery",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _next(d).get("delivery_date"),
        attrs_fn=lambda d: {
            "status": _next(d).get("status"),
            "order_id": _next(d).get("id"),
            "upcoming_orders": d.get("upcoming_count"),
        },
    ),
    HungryrootSensorDescription(
        key="edit_cutoff",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _next(d).get("cutoff"),
    ),
    HungryrootSensorDescription(
        key="box_items",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(_next(d).get("items") or []) if _next(d) else None,
        attrs_fn=lambda d: {"items": _next(d).get("items") or []},
    ),
    HungryrootSensorDescription(
        key="recipes",
        native_unit_of_measurement="recipes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(_next(d).get("recipes") or []) if _next(d) else None,
        attrs_fn=lambda d: {
            "recipes": _next(d).get("recipes") or [],
            "recipe_details": _next(d).get("recipe_details") or [],
        },
    ),
    HungryrootSensorDescription(
        key="next_box_total",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        value_fn=lambda d: _next(d).get("total"),
        attrs_fn=lambda d: {"shipping_cost": _next(d).get("shipping_cost")},
    ),
    HungryrootSensorDescription(
        key="recent_spend",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        value_fn=_spend,
        attrs_fn=lambda d: {"orders": _history_rows(d)},
    ),
    HungryrootSensorDescription(
        key="last_delivery",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: (_history(d)[0].get("delivery_date") if _history(d) else None),
        attrs_fn=lambda d: (
            {
                "status": _history(d)[0].get("status"),
                "total": _history(d)[0].get("total"),
                "tracking_url": _history(d)[0].get("tracking_url"),
            }
            if _history(d)
            else {}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HungryrootConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HungryrootSensor(coordinator, desc) for desc in SENSORS)


class HungryrootSensor(HungryrootEntity, SensorEntity):
    entity_description: HungryrootSensorDescription
    # Big lists: shown live, but not copied into the history database every refresh.
    _unrecorded_attributes = frozenset({"items", "recipes", "recipe_details", "orders"})

    def __init__(self, coordinator, description: HungryrootSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or {})
