# <img src="/assets/icon.png" style="width:1em;height:1em;"> Philips Air+ Home Assistant Integration

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=autowert66&repository=hass-airplus-cloud)

Home Assistant integration for Philips Air+ air purifiers like the AC0651
that DO NOT support local control (e.g. [1], [2]).

## Features
- Power control (On/Off)
- Preset modes (Auto, Low, Medium, High)
- UI-based authentication

## Supported Devices
- AC0651
- _possibly more, untested_

## Limitations 
- Not tested with any other devices
- Not tested with multiple devices
- Relies on permanent cloud MQTT connection
- Seems to break simultaneous control using the official app
- No sensor reading support _yet_

## Installation
1. Press the HACS Badge or copy the `custom_components/philips_air_plus` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Add the integration through the Home Assistant UI

## Authentication
During setup, you will be provided with a link to log in to your Philips account. After logging in, you will be redirected to a URL starting with `com.philips.air://`. Use the Browser DevTools to see and copy this entire URL and paste it into the Home Assistant configuration dialog.

Detailed Instruction (for Chrome, should be similar for other browsers):
- Copy the URL from the integration setup UI
- In a new tab, open DevTools (right-click → inspect)
- Select the `Network`-Tab
- Press the Filter-icon to reveal a search bar
- Paste this into the search bar: `loginredirect`
- Open the URL in the current tab and complete the login
- In the list of requests, a new line should appear (color red), select it
- Verify it starts with: `com.philips.air://loginredirect?code=...`
- Right-click the request to copy the URL

<img width="660" height="240" alt="image" src="/assets/devtools-intercept.jpeg" />

## See Also
- [kongo09/philips-airpurifier-coap][1]: local implementation using CoAP
- [ruaan-deysel/ha-philips-airpurifier][2]: local implementation using encrypted CoAP
- [cmgrayb/hass-dyson][3]: unrelated integration using a similar AWS IOT MQTT endpoint, see [here][3-1]

[1]: https://github.com/kongo09/philips-airpurifier-coap
[2]: https://github.com/ruaan-deysel/ha-philips-airpurifier
[3]: https://github.com/cmgrayb/hass-dyson/
[3-1]: https://github.com/cmgrayb/hass-dyson/blob/ca382150da3343da19eab0fa3847537cdbd476da/custom_components/hass_dyson/device.py#L697

