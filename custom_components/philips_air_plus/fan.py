"""Fan platform for Philips Air+ integration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN, CONF_THING_NAME, PRESET_MODES, MODE_TO_VALUE
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Philips Air+ fan platform."""
    api = hass.data[DOMAIN][config_entry.entry_id]
    thing_name = config_entry.data[CONF_THING_NAME]
    
    fan = PhilipsAirPlusFan(api, thing_name, config_entry.title)
    async_add_entities([fan])

class PhilipsAirPlusFan(FanEntity):
    """Philips Air+ Fan Entity."""

    _attr_has_entity_name = True
    _attr_supported_features = FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    _attr_preset_modes = PRESET_MODES

    def __init__(self, api, thing_name, name):
        self._api = api
        self._thing_name = thing_name
        self._attr_name = name
        self._attr_unique_id = f"{thing_name}_fan"
        
        self._mqtt_client = None
        self._is_on = False
        self._preset_mode = None
        
        self._shadow_topic = f"$aws/things/{thing_name}/shadow/update"
        self._ncp_topic = f"da_ctrl/{thing_name}/to_ncp"
        self._reconnect_task = None
        self._should_reconnect = True

    async def async_added_to_hass(self) -> None:
        """Handle being added to Home Assistant."""
        self._should_reconnect = True
        self._reconnect_task = asyncio.create_task(self._mqtt_loop())

    async def _mqtt_loop(self):
        """Main MQTT connection loop with clean-slate reconnection logic."""
        retry_delay = 5
        while self._should_reconnect:
            try:
                # Cleanup previous client if it exists
                if self._mqtt_client:
                    try:
                        self._mqtt_client.loop_stop()
                        self._mqtt_client.disconnect()
                    except Exception:
                        pass
                    self._mqtt_client = None

                _LOGGER.debug("Starting fresh connection attempt for %s", self._thing_name)
                
                # Force token refresh if close to expiry and get fresh signature
                # This ensures we don't start a connection with a signature that's about to die
                signature = await self._api.get_signature()
                
                client_id = f"{self._api.user_id}_{uuid.uuid4().hex[:8]}"
                
                # Initialize new client for every attempt to avoid internal state issues
                try:
                    self._mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, transport="websockets")
                except AttributeError:
                    self._mqtt_client = mqtt.Client(client_id=client_id, transport="websockets")
                
                self._mqtt_client.ws_set_options(headers={
                    'token-header': f"Bearer {self._api.access_token}",
                    'x-amz-customauthorizer-signature': signature,
                    'x-amz-customauthorizer-name': 'CustomAuthorizer',
                    'tenant': 'da'
                })
                self._mqtt_client.tls_set()
                
                self._mqtt_client.on_connect = self._on_connect
                self._mqtt_client.on_message = self._on_message
                self._mqtt_client.on_disconnect = self._on_disconnect
                self._mqtt_client.on_log = self._on_log
                
                _LOGGER.info("Connecting to Philips Air+ MQTT...")
                self._mqtt_client.connect("ats.prod.eu-da.iot.versuni.com", 443, keepalive=30)
                self._mqtt_client.loop_start()
                
                # Monitor the connection
                conn_timeout = 20
                start_time = time.time()
                while self._should_reconnect:
                    if self._mqtt_client.is_connected():
                        retry_delay = 5 # Reset delay on success
                        await asyncio.sleep(5) # Check status every 5 seconds
                    elif time.time() - start_time < conn_timeout:
                        await asyncio.sleep(0.5) # Waiting for initial connection
                    else:
                        _LOGGER.warning("MQTT connection lost or timed out, initiating fresh reconnect")
                        break
                
            except Exception:
                _LOGGER.exception("Unexpected error in MQTT loop")
            
            if self._should_reconnect:
                _LOGGER.info("Retrying MQTT connection in %ds...", retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)

    def _on_log(self, client, userdata, level, buf):
        _LOGGER.debug("MQTT Log: %s", buf)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        code = getattr(rc, "value", rc)
        if code == 0:
            _LOGGER.info("Successfully connected to Philips Air+ MQTT")
            client.subscribe(f"{self._shadow_topic}/accepted")
        else:
            _LOGGER.error("Failed to connect to Philips Air+ MQTT, reason code: %s", str(rc))

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        _LOGGER.warning("Disconnected from Philips Air+ MQTT, reason: %s", str(rc))

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            state = payload.get("state", {}).get("reported", {})
            if "powerOn" in state:
                self._is_on = state["powerOn"]
            self.hass.add_job(self.async_write_ha_state)
        except Exception:
            _LOGGER.exception("Error handling MQTT message")

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def preset_mode(self) -> str | None:
        return self._preset_mode

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        payload = {"state": {"desired": {"powerOn": True}}}
        if self._mqtt_client and self._mqtt_client.is_connected():
            self._mqtt_client.publish(self._shadow_topic, json.dumps(payload))
            self._is_on = True
            if preset_mode:
                await self.async_set_preset_mode(preset_mode)
            self.async_write_ha_state()
        else:
            _LOGGER.error("Cannot turn on: MQTT client not connected")

    async def async_turn_off(self, **kwargs: Any) -> None:
        payload = {"state": {"desired": {"powerOn": False}}}
        if self._mqtt_client and self._mqtt_client.is_connected():
            self._mqtt_client.publish(self._shadow_topic, json.dumps(payload))
            self._is_on = False
            self.async_write_ha_state()
        else:
            _LOGGER.error("Cannot turn off: MQTT client not connected")

    async def async_set_preset_mode(self, preset_mode: str):
        if preset_mode not in MODE_TO_VALUE:
            return
        value = MODE_TO_VALUE[preset_mode]
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        payload = {
            "cid": uuid.uuid4().hex[:8],
            "time": timestamp,
            "type": "command",
            "cn": "setPort",
            "ct": "mobile",
            "data": {"portName": "Control", "properties": {"D0310C": value}}
        }
        if self._mqtt_client and self._mqtt_client.is_connected():
            self._mqtt_client.publish(self._ncp_topic, json.dumps(payload))
            self._preset_mode = preset_mode
            self.async_write_ha_state()
        else:
            _LOGGER.error("Cannot set preset mode: MQTT client not connected")

    async def async_will_remove_from_hass(self) -> None:
        self._should_reconnect = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
