"""Config flow for Philips Air+ integration."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, parse_qs

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
        query_string = "&".join([f"{k}={v}" for k, v in auth_params.items()])
        auth_link = f"{AUTH_URL}?{query_string}"

        errors = {}
        if user_input is not None:
            redirect_url = user_input.get(CONF_REDIRECT_URL)
            try:
                parsed_url = urlparse(redirect_url)
                # The redirect URL might be in the form com.philips.air://loginredirect?code=...
                # or it might have been pasted as a full URL.
                query = parse_qs(parsed_url.query)
                code = query.get("code")
                if not code:
                    # Try to handle cases where the scheme might cause issues with urlparse
                    if "code=" in redirect_url:
                        code = [redirect_url.split("code=")[1].split("&")[0]]
                
                if code:
                    session = async_get_clientsession(self.hass)
                    api = PhilipsAirPlusAPI(session)
                    tokens = await api.get_tokens_from_code(code[0], self._verifier)
                    user_id = await api.get_user_id()
                    devices = await api.get_devices()
                    
                    if not devices:
                        errors["base"] = "no_devices"
                    else:
                        # For simplicity, we'll take the first device
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
                    errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Error during auth")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_REDIRECT_URL): str,
            }),
            description_placeholders={"auth_url": auth_link},
            errors=errors,
        )
