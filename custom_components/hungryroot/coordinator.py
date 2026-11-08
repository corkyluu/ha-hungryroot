"""Fetches and parses Hungryroot data on a timer."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    HungryrootApiChanged,
    HungryrootAuthError,
    HungryrootClient,
    HungryrootError,
)
from .const import CONF_COOKIE, CONF_SCAN_HOURS, DEFAULT_SCAN_HOURS, DOMAIN, HISTORY_LIMIT

_LOGGER = logging.getLogger(__name__)

ISSUE_API_CHANGED = "api_changed"


def _first(d: dict[str, Any] | None, *keys: str) -> Any:
    """Return the first non-empty value among several possible field names."""
    if not isinstance(d, dict):
        return None
    for key in keys:
        val = d.get(key)
        if val not in (None, "", [], {}):
            return val
    return None


def _money(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, dict):
        val = _first(val, "amount", "value", "total")
    try:
        num = float(str(val).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    # Some APIs send cents as integers.
    return round(num / 100, 2) if isinstance(val, int) and num > 1000 else round(num, 2)


def _as_date(val: Any) -> date | None:
    if not val:
        return None
    parsed = dt_util.parse_date(str(val)[:10])
    return parsed


def _as_datetime(val: Any) -> datetime | None:
    if not val:
        return None
    parsed = dt_util.parse_datetime(str(val))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed


def _name(obj: Any) -> str | None:
    if isinstance(obj, str):
        return obj
    return _first(obj, "name", "display_name", "title", "short_name")


# Order status codes from hungryroot.com's own code.
STATUS_NAMES = {
    0: "None",
    10: "Cart",
    20: "Scheduled",  # Hungryroot calls this "Recurring": planned, still editable
    25: "Charging",
    30: "Submitted",
    35: "Released",
    40: "Processing",
    60: "Pre-transit",
    70: "In transit",
    80: "Out for delivery",
    100: "Delivered",
    -20: "Skipped",
    -30: "Held",
    -40: "Canceled",
    -60: "Undelivered",
    -80: "Invalidated",
    -90: "Voided",
    -100: "Error",
}


def _status(order: dict[str, Any]) -> str | None:
    code = order.get("status")
    if isinstance(code, int) and code in STATUS_NAMES:
        return STATUS_NAMES[code]
    return _first(order, "status_label") or (str(code) if code is not None else None)


def parse_order(order: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull the fields we show out of one order, whatever shape it comes in."""
    if not isinstance(order, dict):
        return None

    items: list[dict[str, Any]] = []
    for prod in order.get("products") or []:
        inner = prod.get("product") if isinstance(prod.get("product"), dict) else prod
        name = _name(inner)
        if name:
            items.append(
                {
                    "name": name,
                    "quantity": _first(prod, "quantity", "container_quantity") or 1,
                    "category": _first(inner, "primary_category_name") or "Other",
                    "brand": _first(inner, "brand_name"),
                    "image": _first(inner, "small_image_url", "card_image_url"),
                }
            )

    recipes: list[str] = []
    recipe_details: list[dict[str, Any]] = []
    for bundle in order.get("bundles") or []:
        pairing = bundle.get("pairing") if isinstance(bundle, dict) else None
        name = _name(pairing) or _first(bundle, "pairing_name")
        if not name or name in recipes:
            continue
        recipes.append(name)
        pairing = pairing if isinstance(pairing, dict) else {}
        dish_type = pairing.get("dish_type")
        recipe_details.append(
            {
                "name": name,
                "image": _first(pairing, "featured_img_url", "featured_img_transparent_url"),
                "minutes": pairing.get("cooking_time"),
                "calories": pairing.get("calories"),
                "servings": pairing.get("servings"),
                "dish_type": _name(dish_type) if isinstance(dish_type, dict) else dish_type,
                "url": (
                    f"https://www.hungryroot.com/recipes/{pairing['slug']}/"
                    if pairing.get("slug")
                    else None
                ),
            }
        )

    return {
        "id": order.get("id"),
        "status": _status(order),
        "delivery_date": _as_date(
            _first(order, "delivery_date", "preferred_date", "scheduled_delivery_date")
        ),
        "cutoff": _as_datetime(_first(order, "cutoff_datetime", "cutoff", "edit_deadline")),
        "deadline_exceeded": order.get("deadline_exceeded"),
        "is_editable": order.get("is_editable"),
        "days_left_to_customize": order.get("days_left_to_customize"),
        "tracking_url": order.get("tracking_url") or None,
        "total": _money(
            _first(order, "total", "total_price", "grand_total", "order_total", "price")
        ),
        "shipping_cost": _money(order.get("shipping_cost")),
        "items": items,
        "recipes": recipes,
        "recipe_details": recipe_details,
    }


def _results(payload: Any) -> list[dict[str, Any]]:
    """Find the list of orders.

    The orders list comes back as {"count", "next", "results": {"order": [...], "tags": [...]}};
    a single order as {"order": [...], "tags": [...]}.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "orders", "order", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for inner in ("order", "orders", "results"):
                    if isinstance(val.get(inner), list):
                        return val[inner]
    raise HungryrootApiChanged(f"Orders list has an unexpected shape ({_shape(payload)})")


def _shape(payload: Any) -> str:
    """Describe a response's layout (field names only, never values) for error messages."""
    if isinstance(payload, dict):
        parts = []
        for key, val in list(payload.items())[:12]:
            if isinstance(val, dict):
                parts.append(f"{key}{{{', '.join(list(val)[:8])}}}")
            else:
                parts.append(f"{key}:{type(val).__name__}")
        return ", ".join(parts)
    return type(payload).__name__


class HungryrootCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps one account's Hungryroot data fresh."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HungryrootClient) -> None:
        hours = entry.options.get(CONF_SCAN_HOURS, DEFAULT_SCAN_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
        )
        self.client = client
        self.raw: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            customer = await self.client.get_customer()
            upcoming_raw = await self.client.get_orders("upcoming", 3)
            past_raw = await self.client.get_orders("past", HISTORY_LIMIT)

            upcoming = _results(upcoming_raw)
            next_detail = None
            if upcoming and upcoming[0].get("id") is not None:
                detail_raw = await self.client.get_order(upcoming[0]["id"])
                detail_list = _results(detail_raw) if not detail_raw.get("id") else [detail_raw]
                next_detail = detail_list[0] if detail_list else upcoming[0]
        except HungryrootAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HungryrootApiChanged as err:
            self._flag_api_changed(str(err))
            raise UpdateFailed(f"Hungryroot changed their site: {err}") from err
        except HungryrootError as err:
            raise UpdateFailed(str(err)) from err

        self.raw = {
            "customer": customer,
            "upcoming": upcoming_raw,
            "past": past_raw,
            "next_order_detail": next_detail,
        }
        self._save_cookie()

        next_order = parse_order(next_detail)
        if next_order is not None and next_order["delivery_date"] is None:
            self._flag_api_changed("Next order has no delivery date field")
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_API_CHANGED)

        history = [p for p in (parse_order(o) for o in _results(past_raw)) if p]
        return {
            "customer_id": _first(customer, "id", "customer_id"),
            "next_order": next_order,
            "upcoming_count": len(upcoming),
            "history": history,
            # The box you have now: the most recent delivered / arriving box.
            "current_box": history[0] if history else None,
        }

    def _save_cookie(self) -> None:
        """Hungryroot may rotate the session cookie; keep the newest copy."""
        cookie = self.client.cookie
        if cookie and cookie != self.config_entry.data.get(CONF_COOKIE):
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_COOKIE: cookie}
            )

    def _flag_api_changed(self, detail: str) -> None:
        _LOGGER.warning("Hungryroot API looks different than expected: %s", detail)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_API_CHANGED,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_API_CHANGED,
            translation_placeholders={"detail": detail},
        )
