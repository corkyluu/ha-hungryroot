"""Hungryroot integration (read-only)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import HungryrootClient
from .const import CONF_COOKIE
from .coordinator import HungryrootCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type HungryrootConfigEntry = ConfigEntry[HungryrootCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HungryrootConfigEntry) -> bool:
    # Own HTTP session so Hungryroot cookies never mix with other integrations.
    client = HungryrootClient(async_create_clientsession(hass), entry.data[CONF_COOKIE])
    coordinator = HungryrootCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options_change))
    return True


async def _reload_on_options_change(hass: HomeAssistant, entry: HungryrootConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HungryrootConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
