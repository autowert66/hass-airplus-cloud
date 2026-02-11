import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import aiohttp
from .const import (
    API_BASE, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE, 
    TOKEN_URL, USER_AGENT, WS_URL
)

_LOGGER = logging.getLogger(__name__)

def base64_url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').replace('=', '')

class PhilipsAirPlusAPI:
    def __init__(self, session: aiohttp.ClientSession, on_token_update: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.session = session
        self.access_token = None
        self.refresh_token = None
        self.id_token = None
        self.expires_at = 0
        self.user_id = None
        self._on_token_update = on_token_update

    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        verifier = base64_url_encode(secrets.token_bytes(32))
        challenge = base64_url_encode(hashlib.sha256(verifier.encode('utf-8')).digest())
        return verifier, challenge

    async def ensure_valid_token(self):
        """Ensure the access token is valid, refreshing if necessary."""
        # Refresh if token is expired or expiring within 5 minutes to be safe
        if time.time() >= self.expires_at - 300:
            _LOGGER.debug("Token expired or expiring soon, refreshing...")
            await self.refresh_tokens()

    async def get_tokens_from_code(self, code: str, verifier: str) -> Dict[str, Any]:
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
        async with self.session.post(TOKEN_URL, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error("Failed to get tokens: %s", text)
                raise Exception(f"Token error: {resp.status} - {text}")
            tokens = await resp.json()
            tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
            self._update_tokens(tokens)
            return tokens

    async def refresh_tokens(self) -> Dict[str, Any]:
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        async with self.session.post(TOKEN_URL, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error("Failed to refresh tokens: %s", text)
                raise Exception(f"Refresh error: {resp.status} - {text}")
            tokens = await resp.json()
            tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
            self._update_tokens(tokens)
            return tokens

    def _update_tokens(self, tokens: Dict[str, Any]):
        self.access_token = tokens.get("access_token")
        self.refresh_token = tokens.get("refresh_token")
        self.id_token = tokens.get("id_token")
        self.expires_at = tokens.get("expires_at")
        if self._on_token_update:
            self._on_token_update(tokens)

    async def get_user_id(self) -> str:
        await self.ensure_valid_token()
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        payload = {"idToken": self.id_token}
        async with self.session.post(f"{API_BASE}/user/self/get-id", headers=headers, json=payload) as resp:
            data = await resp.json()
            self.user_id = data.get("userId")
            return self.user_id

    async def get_devices(self) -> List[Dict[str, Any]]:
        await self.ensure_valid_token()
        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self.access_token}"
        }
        async with self.session.get(f"{API_BASE}/user/self/device", headers=headers) as resp:
            return await resp.json()

    async def get_signature(self) -> str:
        # Crucial: Always ensure token is valid before fetching signature
        await self.ensure_valid_token()
        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self.access_token}"
        }
        async with self.session.get(f"{API_BASE}/user/self/signature", headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error("Failed to get signature: %s", text)
                raise Exception(f"Signature error: {resp.status}")
            data = await resp.json()
            return data.get("signature")
