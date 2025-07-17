"""Constants for Curtain Control integration."""

DOMAIN = "curtain_control"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_DEVICE_ADDRESS = "device_address"
CONF_DEVICES = "devices"
CONF_AUTO_DISCOVERY = "auto_discovery"
CONF_DISCOVERY_TIMEOUT = "discovery_timeout"
CONF_USE_DEVICE_MAPPING = "use_device_mapping"
CONF_ENABLE_POLLING = "enable_polling"
CONF_POLLING_INTERVAL = "polling_interval"

# Default values
DEFAULT_NAME = "Curtain"
DEFAULT_PORT = 32
DEFAULT_DISCOVERY_TIMEOUT = 30
DEFAULT_POLLING_INTERVAL = 5

# Data keys
DATA_COORDINATOR = "coordinator"
DATA_DISCOVERY = "discovery"

# Discovery steps
STEP_DISCOVERY = "discovery"
STEP_DEVICE_SELECTION = "device_selection"

# Error codes
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_NO_DEVICES_FOUND = "no_devices_found"
ERROR_DEVICE_NOT_RESPONDING = "device_not_responding"
