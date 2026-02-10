"""Fan platform for Philips Air+ integration."""
from __future__ import annotations

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
    
    # Get fresh signature
    signature = await api.get_signature()
    
    fan = PhilipsAirPlusFan(api, thing_name, signature, config_entry.title)
    async_add_entities([fan])

class PhilipsAirPlusFan(FanEntity):
    """Philips Air+ Fan Entity."""

    _attr_has_entity_name = True
    _attr_supported_features = FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    _attr_preset_modes = PRESET_MODES

    def __init__(self, api, thing_name, signature, name):
        self._api = api
        self._thing_name = thing_name
        self._signature = signature
        self._attr_name = name
        self._attr_unique_id = f"{thing_name}_fan"
        
        self._mqtt_client = None
        self._is_on = False
        self._preset_mode = None
        
        self._shadow_topic = f"$aws/things/{thing_name}/shadow/update"
        self._ncp_topic = f"da_ctrl/{thing_name}/to_ncp"

    async def async_added_to_hass(self) -> None:
        """Handle being added to Home Assistant."""
        await self._connect_mqtt()

    async def _connect_mqtt(self):
        client_id = f"{self._api.user_id}_{uuid.uuid4()}"
        
        self._mqtt_client = mqtt.Client(client_id=client_id, transport="websockets")
        self._mqtt_client.ws_set_options(headers={
            'token-header': f"Bearer {self._api.access_token}",
            'x-amz-customauthorizer-signature': self._signature,
            'x-amz-customauthorizer-name': 'CustomAuthorizer',
            'tenant': 'da'
        })
        self._mqtt_client.tls_set()
        
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        
        # Connect in a separate thread to not block HA
        self._mqtt_client.connect_async("ats.prod.eu-da.iot.versuni.com", 443, keepalive=30)
        self._mqtt_client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info("Connected to Philips Air+ MQTT")
            client.subscribe(f"{self._shadow_topic}/accepted")
        else:
            _LOGGER.error("Failed to connect to Philips Air+ MQTT, rc: %d", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            state = payload.get("state", {}).get("reported", {})
            if "powerOn" in state:
                self._is_on = state["powerOn"]
            
            # Note: The CLI uses D0310C for mode, we might need to find where it's reported
            # For now, we update the UI based on what we know
            self.async_write_ha_state()
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
        self._mqtt_client.publish(self._shadow_topic, json.dumps(payload))
        self._is_on = True
        
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
        
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        payload = {"state": {"desired": {"powerOn": False}}}
        self._mqtt_client.publish(self._shadow_topic, json.dumps(payload))
        self._is_on = False
        self.async_write_ha_state()

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
        self._mqtt_client.publish(self._ncp_topic, json.dumps(payload))
        self._preset_mode = preset_mode
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle being removed from Home Assistant."""
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
