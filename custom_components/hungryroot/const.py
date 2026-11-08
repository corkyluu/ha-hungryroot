"""Constants for the Hungryroot integration."""

from datetime import timedelta

DOMAIN = "hungryroot"

API_BASE = "https://api.hungryroot.com"
WEB_ORIGIN = "https://www.hungryroot.com"

# Public client key the Hungryroot website sends on every API call.
# It is baked into their public JavaScript; it is not a secret or a user credential.
CLIENT_KEY = "c61de580-e48d-41d2-a8d1-6cd1429987a1"

CONF_COOKIE = "cookie"
CONF_SCAN_HOURS = "scan_interval_hours"

DEFAULT_SCAN_HOURS = 6
MIN_SCAN_HOURS = 1
MAX_SCAN_HOURS = 24

HISTORY_LIMIT = 10

DEFAULT_SCAN_INTERVAL = timedelta(hours=DEFAULT_SCAN_HOURS)
