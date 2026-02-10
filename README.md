# Philips Air+ Home Assistant Integration

[![hacs_badge](https://my.home-assistant.io/badges/hacs_badge.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=autowert66&repository=hass-airplus-cloud&category=integration)

This integration allows you to control Philips Air+ air purifiers through Home Assistant.

## Features
- Power control (On/Off)
- Preset modes (Auto, Low, Medium, High)
- UI-based authentication (OIDC with PKCE)

## Installation
1. Copy the `custom_components/philips_air_plus` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration through the Home Assistant UI.

## Authentication
During setup, you will be provided with a link to log in to your Philips account. After logging in, you will be redirected to a URL starting with `com.philips.air://`. Copy this entire URL and paste it into the Home Assistant configuration dialog.
