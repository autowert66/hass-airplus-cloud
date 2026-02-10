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
    DOMAIN, CONF_THING_NAME, CONF_ACCESS_TOKEN, CONF_SIGNATURE,
    WS_URL, PRESET_MODES, MODE_TO_VALUE, VALUE_TO_MODE
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
        """Main MQTT connection loop with reconnection logic."""
        retry_delay = 5
        while self._should_reconnect:
            try:
                _LOGGER.debug("Refreshing tokens and fetching signature for %s", self._thing_name)
                
                # Refresh tokens and get fresh signature before connecting
                signature = await self._api.get_signature()
                
                client_id = f"{self._api.user_id}_{uuid.uuid4().hex[:8]}"
                # Using CallbackAPIVersion.VERSION2 for paho-mqtt 2.x compatibility
                try:
                    self._mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, transport="websockets")
                except AttributeError:
                    # Fallback for older paho-mqtt versions
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
                
                _LOGGER.info("Connecting to Philips Air+ MQTT at %s", "ats.prod.eu-da.iot.versuni.com")
                
                # Connect
                self._mqtt_client.connect("ats.prod.eu-da.iot.versuni.com", 443, keepalive=30)
                
                # Start loop
                self._mqtt_client.loop_start()
                
                # Wait for connection or timeout
                conn_timeout = 20
                start_time = time.time()
                while not self._mqtt_client.is_connected() and time.time() - start_time < conn_timeout:
                    await asyncio.sleep(0.5)
                
                if not self._mqtt_client.is_connected():
                    _LOGGER.error("MQTT connection timed out after %ds", conn_timeout)
                    self._mqtt_client.loop_stop()
                    self._mqtt_client.disconnect()
                else:
                    # Monitor connection
                    while self._mqtt_client.is_connected():
                        await asyncio.sleep(1)
                    _LOGGER.warning("MQTT connection lost")
                    retry_delay = 5 # Reset delay on successful connection
                
            except Exception:
                _LOGGER.exception("Unexpected error in MQTT loop")
            
            if self._should_reconnect:
                _LOGGER.info("Retrying MQTT connection in %ds...", retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300) # Exponential backoff up to 5 mins

    def _on_log(self, client, userdata, level, buf):
        """Log MQTT client messages."""
        _LOGGER.debug("MQTT Log: %s", buf)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Handle connection result."""
        # Note: rc is a ReasonCode object in VERSION2
        code = getattr(rc, "value", rc)
        if code == 0:
            _LOGGER.info("Successfully connected to Philips Air+ MQTT")
            client.subscribe(f"{self._shadow_topic}/accepted")
        else:
            _LOGGER.error("Failed to connect to Philips Air+ MQTT, reason code: %s", str(rc))

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        """Handle disconnection."""
        _LOGGER.warning("Disconnected from Philips Air+ MQTT, reason: %s", str(rc))

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = json.loads(msg.payload)
            _LOGGER.debug("Received MQTT message on %s: %s", msg.topic, payload)
            state = payload.get("state", {}).get("reported", {})
            if "powerOn" in state:
                self._is_on = state["powerOn"]
            
            # Update UI
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
        """Turn on the fan."""
        payload = {"state": {"desired": {"powerOn": True}}}
        if self._mqtt_client and self._mqtt_client.is_connected():
            _LOGGER.debug("Sending turn_on command")
            self._mqtt_client.publish(self._shadow_topic, json.dumps(payload))
            self._is_on = True
            
            if preset_mode:
                await self.async_set_preset_mode(preset_mode)
            
            self.async_write_ha_state()
        else:
            _LOGGER.error("Cannot turn on: MQTT client not connected")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        payload = {"state": {"desired": {"powerOn": False}}}
        if self._mqtt_client and self._mqtt_client.is_connected():
            _LOGGER.debug("Sending turn_off command")
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
            "data": {
                "portName": "Control",
                "properties": {
                    "D0310C": value
                }
            }
        }
        if self._mqtt_client and self._mqtt_client.is_connected():
            _LOGGER.debug("Sending set_preset_mode command: %s", preset_mode)
            self._mqtt_client.publish(self._ncp_topic, json.dumps(payload))
            self._preset_mode = preset_mode
            self.async_write_ha_state()
        else:
            _LOGGER.error("Cannot set preset mode: MQTT client not connected")

    async def async_will_remove_from_hass(self) -> None:
        """Handle being removed from Home Assistant."""
        self._should_reconnect = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
