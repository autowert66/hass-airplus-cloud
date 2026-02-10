"""Config flow for Philips Air+ integration."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PhilipsAirPlusAPI
from .const import (
    DOMAIN, AUTH_URL, CLIENT_ID, REDIRECT_URI, SCOPE,
    CONF_REDIRECT_URL, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN,
    CONF_ID_TOKEN, CONF_EXPIRES_AT, CONF_USER_ID, CONF_THING_NAME
)

_LOGGER = logging.getLogger(__name__)

class PhilipsAirPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Philips Air+."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._verifier: str | None = None
        self._challenge: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Ensure PKCE values are generated once and stored in the flow instance
        if self._verifier is None:
            self._verifier, self._challenge = PhilipsAirPlusAPI.generate_pkce()

        auth_params = {
            "client_id": CLIENT_ID,
            "code_challenge": self._challenge,
            "code_challenge_method": "S256",
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "ui_locales": "en-US",
            "scope": SCOPE,
        }
        # Use urlencode to properly escape parameters
        query_string = urlencode(auth_params)
        auth_link = f"{AUTH_URL}?{query_string}"

        errors = {}
        if user_input is not None:
            redirect_url = user_input.get(CONF_REDIRECT_URL)
            try:
                # Robust code extraction
                code = None
                if "code=" in redirect_url:
                    # Split by code= and then by the next & or end of string
                    parts = redirect_url.split("code=")
                    if len(parts) > 1:
                        code = parts[1].split("&")[0]
                
                if code:
                    _LOGGER.debug("Extracted code, attempting token exchange with verifier: %s", self._verifier)
                    session = async_get_clientsession(self.hass)
                    api = PhilipsAirPlusAPI(session)
                    
                    # This call now includes the fixed expires_at calculation
                    tokens = await api.get_tokens_from_code(code, self._verifier)
                    user_id = await api.get_user_id()
                    devices = await api.get_devices()
                    
                    if not devices:
                        errors["base"] = "no_devices"
                    else:
                        device = devices[0]
                        return self.async_create_entry(
                            title=device.get("friendlyName", "Philips Air Purifier"),
                            data={
                                CONF_ACCESS_TOKEN: tokens["access_token"],
                                CONF_REFRESH_TOKEN: tokens["refresh_token"],
                                CONF_ID_TOKEN: tokens["id_token"],
                                CONF_EXPIRES_AT: tokens["expires_at"],
                                CONF_USER_ID: user_id,
                                CONF_THING_NAME: device["thingName"],
                            },
                        )
                else:
                    _LOGGER.error("Could not extract code from redirect URL: %s", redirect_url)
                    errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception("Error during auth: %s", str(e))
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_REDIRECT_URL): str,
            }),
            description_placeholders={"auth_url": auth_link},
            errors=errors,
        )
