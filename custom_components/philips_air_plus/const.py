"""Constants for the Philips Air+ integration."""

DOMAIN = "philips_air_plus"

CONF_REDIRECT_URL = "redirect_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ID_TOKEN = "id_token"
CONF_EXPIRES_AT = "expires_at"
CONF_USER_ID = "user_id"
CONF_THING_NAME = "thing_name"
CONF_SIGNATURE = "signature"

# OAuth2 Secret Obfuscation
# def make_mj(s, key=0x55):
#     return [ord(c) ^ key for c in s]
def _mj(data):
    return "".join(chr(x ^ 0x55) for x in data)

_CID_mj = [120, 13, 38, 30, 98, 26, 99, 60, 16, 62, 25, 56, 57, 98, 98, 44, 17, 18, 17, 0, 60, 101, 62, 32]
_CSC_mj = [3, 102, 97, 23, 57, 20, 61, 32, 60, 57, 28, 49, 26, 45, 101, 28, 56, 58, 100, 99, 39, 18, 4, 103]

# OAuth2 Configuration
CLIENT_ID = _mj(_CID_mj)
CLIENT_SECRET = _mj(_CSC_mj)
REDIRECT_URI = "com.philips.air://loginredirect"
SCOPE = "openid email profile address DI.Account.read DI.AccountProfile.read DI.AccountProfile.write DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write DI.GeneralConsent.read subscriptions profile_extended consents DI.AccountSubscription.read DI.AccountSubscription.write"
AUTH_URL = "https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/authorize"
TOKEN_URL = "https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/oauth/token"
API_BASE = "https://prod.eu-da.iot.versuni.com/api/da"
USER_AGENT = "Air (com.philips.ph.homecare; build:3.16.1; locale:en_US; Android:12 Sdk:2.2.0) okhttp/4.12.0"

# MQTT Configuration
WS_URL = "wss://ats.prod.eu-da.iot.versuni.com/mqtt"

# Modes mapping
# 0: Auto, 1: Medium, 17: Low, 18: High
MODE_AUTO = 0
MODE_MEDIUM = 1
MODE_LOW = 17
MODE_HIGH = 18

PRESET_MODES = ["Auto", "Low", "Medium", "High"]
MODE_TO_VALUE = {
    "Auto": MODE_AUTO,
    "Low": MODE_LOW,
    "Medium": MODE_MEDIUM,
    "High": MODE_HIGH,
}
VALUE_TO_MODE = {v: k for k, v in MODE_TO_VALUE.items()}
