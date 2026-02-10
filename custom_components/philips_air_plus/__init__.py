"""The Philips Air+ integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PhilipsAirPlusAPI
from .const import (
    DOMAIN, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_ID_TOKEN,
    CONF_EXPIRES_AT, CONF_USER_ID
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.FAN]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Philips Air+ from a config entry."""
    session = async_get_clientsession(hass)
    api = PhilipsAirPlusAPI(session)
    
    api.access_token = entry.data.get(CONF_ACCESS_TOKEN)
    api.refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    api.id_token = entry.data.get(CONF_ID_TOKEN)
    api.expires_at = entry.data.get(CONF_EXPIRES_AT)
    api.user_id = entry.data.get(CONF_USER_ID)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
