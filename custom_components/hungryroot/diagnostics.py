"""Download diagnostics: the raw Hungryroot answers, with personal info removed.

When Hungryroot changes their site, this file is what's needed to fix the parser.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant

from . import HungryrootConfigEntry
from .const import CONF_COOKIE

REDACT = {
    CONF_COOKIE,
    CONF_EMAIL,
    "email",
    "first_name",
    "last_name",
    "name_on_card",
    "phone",
    "phone_number",
    "address",
    "address1",
    "address2",
    "street",
    "street_address",
    "line1",
    "line2",
    "zip",
    "zip_code",
    "postal_code",
    "latitude",
    "longitude",
    "card",
    "last4",
    "stripe_customer_id",
    "referral_code",
    "referral_link",
    "token",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HungryrootConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "last_update_success": coordinator.last_update_success,
        "raw": async_redact_data(coordinator.raw, REDACT),
    }
