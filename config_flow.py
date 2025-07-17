"""Config flow for Curtain Control integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_AUTO_DISCOVERY,
    CONF_DEVICES,
    CONF_DISCOVERY_TIMEOUT,
    CONF_USE_DEVICE_MAPPING,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_PORT,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_NO_DEVICES_FOUND,
    STEP_DEVICE_SELECTION,
    STEP_DISCOVERY,
)
from .coordinator import CurtainTCPCoordinator
from .device_discovery import DeviceDiscovery, DiscoveredDevice

_LOGGER = logging.getLogger(__name__)


@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return {
        f"{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
        for entry in hass.config_entries.async_entries(DOMAIN)
    }


class CurtainControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Curtain Control."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize config flow."""
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._coordinator: CurtainTCPCoordinator = None
        self._discovery: DeviceDiscovery = None
        self._discovered_devices: list[DiscoveredDevice] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            instance_key = f"{host}:{port}"

            if instance_key in configured_instances(self.hass):
                errors["base"] = "already_configured"
            else:
                # Test connection
                try:
                    coordinator = CurtainTCPCoordinator(self.hass, host, port)

                    # Try to establish connection
                    if await coordinator.test_connection():
                        await coordinator.disconnect()

                        # Store connection info
                        self._host = host
                        self._port = port

                        # Proceed to discovery
                        return await self.async_step_discovery()
                    errors["base"] = ERROR_CANNOT_CONNECT

                except (OSError, ConnectionError) as e:
                    _LOGGER.error("Error testing connection: %s", e)
                    errors["base"] = ERROR_CANNOT_CONNECT

        data_schema = vol.Schema({
            vol.Required(CONF_HOST): cv.string,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "default_port": str(DEFAULT_PORT)
            }
        )

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None):
        """Handle device discovery step."""
        errors = {}

        if user_input is not None:
            auto_discovery = user_input.get(CONF_AUTO_DISCOVERY, True)
            discovery_timeout = user_input.get(CONF_DISCOVERY_TIMEOUT, DEFAULT_DISCOVERY_TIMEOUT)
            use_device_mapping = user_input.get(CONF_USE_DEVICE_MAPPING, True)

            # Store the mapping setting for later use
            self._use_device_mapping = use_device_mapping

            if auto_discovery:
                # Perform device discovery
                try:
                    # Create coordinator for discovery
                    self._coordinator = CurtainTCPCoordinator(self.hass, self._host, self._port)
                    await self._coordinator.async_setup()

                    # Create discovery service with mapping setting
                    self._discovery = DeviceDiscovery(self._coordinator, use_device_mapping)

                    # Scan for devices
                    _LOGGER.info("Starting device discovery for %d seconds...", discovery_timeout)
                    self._discovered_devices = await self._discovery.scan_for_devices(discovery_timeout)

                    await self._coordinator.async_shutdown()

                    if self._discovered_devices:
                        return await self.async_step_device_selection()
                    errors["base"] = ERROR_NO_DEVICES_FOUND

                except (OSError, ConnectionError) as e:
                    _LOGGER.error("Error during device discovery: %s", e)
                    errors["base"] = ERROR_CANNOT_CONNECT
                    if self._coordinator:
                        await self._coordinator.async_shutdown()
            else:
                # Skip discovery, create entry without devices
                return self.async_create_entry(
                    title=f"窗帘控制器 ({self._host}:{self._port})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_DEVICES: [],
                        CONF_USE_DEVICE_MAPPING: use_device_mapping,
                    }
                )

        data_schema = vol.Schema({
            vol.Optional(CONF_AUTO_DISCOVERY, default=True): cv.boolean,
            vol.Optional(CONF_USE_DEVICE_MAPPING, default=True): cv.boolean,
            vol.Optional(CONF_DISCOVERY_TIMEOUT, default=DEFAULT_DISCOVERY_TIMEOUT): vol.All(
                cv.positive_int, vol.Range(min=10, max=120)
            ),
        })

        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "host": self._host,
                "port": str(self._port),
                "default_timeout": str(DEFAULT_DISCOVERY_TIMEOUT)
            }
        )

    async def async_step_device_selection(self, user_input: dict[str, Any] | None = None):
        """Handle device selection step."""
        if user_input is not None:
            selected_devices = user_input.get("selected_devices", [])

            if not selected_devices:
                return self.async_show_form(
                    step_id=STEP_DEVICE_SELECTION,
                    data_schema=self._get_device_selection_schema(),
                    errors={"base": "no_devices_selected"},
                    description_placeholders={
                        "device_count": str(len(self._discovered_devices))
                    }
                )

            # Prepare device configurations
            devices = []
            for device_addr_str in selected_devices:
                device_addr = int(device_addr_str, 16)
                device = next(
                    (d for d in self._discovered_devices if d.address == device_addr),
                    None
                )
                if device:
                    devices.append(self._discovery.create_device_config(device))

            # Create config entry
            return self.async_create_entry(
                title=f"窗帘控制器 ({self._host}:{self._port}) - {len(devices)}个设备",
                data={
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    CONF_DEVICES: devices,
                    CONF_USE_DEVICE_MAPPING: getattr(self, '_use_device_mapping', True),
                }
            )

        return self.async_show_form(
            step_id=STEP_DEVICE_SELECTION,
            data_schema=self._get_device_selection_schema(),
            description_placeholders={
                "device_count": str(len(self._discovered_devices))
            }
        )

    def _get_device_selection_schema(self):
        """Get device selection schema."""
        if not self._discovered_devices:
            return vol.Schema({})

        # Create options for device selection
        device_options = {}
        for device in self._discovered_devices:
            key = f"{device.address:04X}"
            label = f"{device.name} (0x{device.address:04X}) - 位置: {device.last_position}%"
            device_options[key] = label

        return vol.Schema({
            vol.Optional("selected_devices", default=list(device_options.keys())): cv.multi_select(device_options),
        })

    async def async_step_import(self, import_config: dict[str, Any]):
        """Handle import from configuration.yaml."""
        host = import_config[CONF_HOST]
        port = import_config.get(CONF_PORT, DEFAULT_PORT)

        # Check if already configured
        instance_key = f"{host}:{port}"
        if instance_key in configured_instances(self.hass):
            return self.async_abort(reason="already_configured")

        # Create basic entry without discovery
        return self.async_create_entry(
            title=f"窗帘控制器 ({host}:{port})",
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_DEVICES: [],
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return CurtainControlOptionsFlow(config_entry)


class CurtainControlOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Curtain Control."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self._coordinator: CurtainTCPCoordinator = None
        self._discovery: DeviceDiscovery = None
        self._discovered_devices: list[DiscoveredDevice] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Handle options flow start."""
        if user_input is not None:
            action = user_input.get("action")

            if action == "rediscover":
                return await self.async_step_rediscover()
            if action == "manage_devices":
                return await self.async_step_manage_devices()

        schema = vol.Schema({
            vol.Required("action"): vol.In({
                "rediscover": "重新发现设备",
                "manage_devices": "管理现有设备",
            }),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )

    async def async_step_rediscover(self, user_input: dict[str, Any] | None = None):
        """Handle device rediscovery."""
        if user_input is not None:
            timeout = user_input.get("timeout", DEFAULT_DISCOVERY_TIMEOUT)

            try:
                host = self.config_entry.data[CONF_HOST]
                port = self.config_entry.data[CONF_PORT]

                # Create coordinator for discovery
                self._coordinator = CurtainTCPCoordinator(self.hass, host, port)
                await self._coordinator.async_setup()

                # Create discovery service with mapping setting from config
                use_device_mapping = self.config_entry.data.get(CONF_USE_DEVICE_MAPPING, True)
                self._discovery = DeviceDiscovery(self._coordinator, use_device_mapping)

                # Scan for devices
                self._discovered_devices = await self._discovery.scan_for_devices(timeout)

                await self._coordinator.async_shutdown()

                if self._discovered_devices:
                    return await self.async_step_select_new_devices()
                return self.async_show_form(
                    step_id="rediscover",
                    data_schema=self._get_rediscover_schema(),
                    errors={"base": ERROR_NO_DEVICES_FOUND}
                )

            except (OSError, ConnectionError) as e:
                _LOGGER.error("Error during rediscovery: %s", e)
                if self._coordinator:
                    await self._coordinator.async_shutdown()
                return self.async_show_form(
                    step_id="rediscover",
                    data_schema=self._get_rediscover_schema(),
                    errors={"base": ERROR_CANNOT_CONNECT}
                )

        return self.async_show_form(
            step_id="rediscover",
            data_schema=self._get_rediscover_schema(),
        )

    def _get_rediscover_schema(self):
        """Get rediscovery schema."""
        return vol.Schema({
            vol.Optional("timeout", default=DEFAULT_DISCOVERY_TIMEOUT): vol.All(
                cv.positive_int, vol.Range(min=10, max=120)
            ),
        })

    async def async_step_select_new_devices(self, user_input: dict[str, Any] | None = None):
        """Handle selection of newly discovered devices."""
        if user_input is not None:
            selected_devices = user_input.get("selected_devices", [])

            if selected_devices:
                # Get existing devices
                existing_devices = list(self.config_entry.data.get(CONF_DEVICES, []))
                existing_addresses = {d["device_address"] for d in existing_devices}

                # Add new devices
                for device_addr_str in selected_devices:
                    device_addr = int(device_addr_str, 16)
                    if device_addr not in existing_addresses:
                        device = next(
                            (d for d in self._discovered_devices if d.address == device_addr),
                            None
                        )
                        if device:
                            existing_devices.append(self._discovery.create_device_config(device))

                # Update config entry
                new_data = {**self.config_entry.data, CONF_DEVICES: existing_devices}
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

                return self.async_create_entry(title="", data={})

        # Filter out already configured devices
        existing_addresses = {
            d["device_address"] for d in self.config_entry.data.get(CONF_DEVICES, [])
        }
        new_devices = [
            d for d in self._discovered_devices
            if d.address not in existing_addresses
        ]

        if not new_devices:
            return self.async_show_form(
                step_id="select_new_devices",
                data_schema=vol.Schema({}),
                errors={"base": "no_new_devices_found"}
            )

        # Create options for new devices only
        device_options = {}
        for device in new_devices:
            key = f"{device.address:04X}"
            label = f"{device.name} (0x{device.address:04X}) - 位置: {device.last_position}%"
            device_options[key] = label

        schema = vol.Schema({
            vol.Optional("selected_devices", default=list(device_options.keys())): cv.multi_select(device_options),
        })

        return self.async_show_form(
            step_id="select_new_devices",
            data_schema=schema,
        )

    async def async_step_manage_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device management."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        # Show current devices
        devices = self.config_entry.data.get(CONF_DEVICES, [])
        device_info = "\n".join([
            f"• {d['name']} (0x{d['device_address']:04X})"
            for d in devices
        ])

        return self.async_show_form(
            step_id="manage_devices",
            data_schema=vol.Schema({}),
            description_placeholders={
                "device_info": device_info or "无已配置设备"
            }
        )
