"""Cover platform for Curtain Control integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_DEVICE_ADDRESS,
    DATA_COORDINATOR,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .coordinator import CurtainTCPCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_DEVICE_ADDRESS): cv.positive_int,
})


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the curtain control platform."""
    host = config[CONF_HOST]
    port = config[CONF_PORT]
    name = config[CONF_NAME]
    device_address = config.get(CONF_DEVICE_ADDRESS, 0x06FE)

    # Create coordinator if it doesn't exist
    coordinator_key = f"{host}:{port}"
    if coordinator_key not in hass.data.setdefault(DATA_COORDINATOR, {}):
        coordinator = CurtainTCPCoordinator(hass, host, port)
        await coordinator.async_setup()
        hass.data[DATA_COORDINATOR][coordinator_key] = coordinator

    coordinator = hass.data[DATA_COORDINATOR][coordinator_key]
    async_add_entities([CurtainControl(coordinator, device_address, name)])


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up curtain control from a config entry."""
    coordinator = hass.data[DATA_COORDINATOR][entry.entry_id]

    # Get devices from entry data
    devices = entry.data.get("devices", [])
    entities = []

    for device_config in devices:
        device_address = device_config["device_address"]
        name = device_config["name"]
        entities.append(CurtainControl(coordinator, device_address, name))

    async_add_entities(entities)


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    coordinator = hass.data[DATA_COORDINATOR].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()
        del hass.data[DATA_COORDINATOR][entry.entry_id]

    _LOGGER.info("Unloaded curtain control config entry")
    return True


class CurtainControl(CoverEntity):
    """Representation of a curtain control using coordinator."""

    def __init__(self, coordinator: CurtainTCPCoordinator, device_address: int, name: str):
        """Initialize the curtain control."""
        self._coordinator = coordinator
        self._device_address = device_address
        self._name = name
        self._position: int | None = None
        self._attr_is_closed: bool | None = None

        # Register with coordinator
        self._coordinator.register_device(self._device_address, self)

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the cover."""
        return f"curtain_{self._coordinator.host}_{self._coordinator.port}_{self._device_address:04x}"

    @property
    def name(self) -> str:
        """Return the name of the cover."""
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this curtain controller."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._coordinator.host}_{self._coordinator.port}")},
            name="Duya窗帘控制器",
            manufacturer="Duya",
            model="智能窗帘控制器",
            sw_version="1.0",
            connections={("tcp", f"{self._coordinator.host}:{self._coordinator.port}")},
        )

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Flag supported features."""
        return (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        return self._position

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        if self._position is None:
            return None
        return self._position == 0

    @property
    def device_class(self) -> str:
        """Return the device class of the cover."""
        return "curtain"

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        if self._position is None:
            return "mdi:curtains"
        if self._position == 0:
            return "mdi:curtains-closed"           # 完全关闭
        if self._position == 100:
            return "mdi:curtains"                  # 完全打开
        if self._position < 25:
            return "mdi:curtains-closed"           # 大部分关闭
        if self._position < 75:
            return "mdi:curtains"                  # 中等位置，部分打开
        return "mdi:curtains"                      # 大部分打开

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "position_percentage": self._position,
            "status": self._get_status_text(),
            "device_address": f"0x{self._device_address:04X}",
            "coordinator_status": "已连接" if self._coordinator.is_connected else "未连接",
            "protocol": "TCP"
        }

    def _get_status_text(self) -> str:
        """Get human readable status text."""
        if self._position is None:
            return "状态未知"
        if self._position == 0:
            return "完全关闭"
        if self._position == 100:
            return "完全打开"
        return f"开启 {self._position}%"

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        _LOGGER.info("窗帘控制实体已添加: %s (0x%04X)", self._name, self._device_address)

        # Get initial position from coordinator
        self._position = self._coordinator.get_device_position(self._device_address)
        if self._position is not None:
            self._attr_is_closed = self._position == 0

    async def async_will_remove_from_hass(self) -> None:
        """Call when entity will be removed from hass."""
        _LOGGER.info("窗帘控制实体即将移除: %s (0x%04X)", self._name, self._device_address)
        self._coordinator.unregister_device(self._device_address)

    async def async_update_position(self, position: int) -> None:
        """Update position from coordinator callback."""
        old_position = self._position
        self._position = position
        self._attr_is_closed = position == 0

        _LOGGER.debug("位置更新: %s (0x%04X) %s -> %d%%",
                     self._name, self._device_address, old_position, position)

        # Notify Home Assistant of state change
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs) -> None:
        """Open the cover."""
        _LOGGER.info("打开窗帘: %s (0x%04X)", self._name, self._device_address)

        success = await self._coordinator.send_command(
            self._device_address, 0x03, 0x04, 0x64  # 100% position
        )

        if success:
            # Optimistically update state
            self._position = 100
            self._attr_is_closed = False
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to send open command to %s", self._name)

    async def async_close_cover(self, **kwargs) -> None:
        """Close the cover."""
        _LOGGER.info("关闭窗帘: %s (0x%04X)", self._name, self._device_address)

        success = await self._coordinator.send_command(
            self._device_address, 0x03, 0x04, 0x00  # 0% position
        )

        if success:
            # Optimistically update state
            self._position = 0
            self._attr_is_closed = True
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to send close command to %s", self._name)

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop the cover."""
        _LOGGER.info("停止窗帘: %s (0x%04X)", self._name, self._device_address)

        success = await self._coordinator.send_command(
            self._device_address, 0x03, 0x04, 0x50  # 80% position (stop)
        )

        if not success:
            _LOGGER.error("Failed to send stop command to %s", self._name)

    async def async_set_cover_position(self, **kwargs) -> None:
        """Move the cover to a specific position."""
        position = kwargs.get("position")
        if position is None:
            return

        _LOGGER.info("设置窗帘位置: %s (0x%04X) -> %d%%",
                    self._name, self._device_address, position)

        success = await self._coordinator.send_command(
            self._device_address, 0x03, 0x04, position
        )

        if success:
            # Optimistically update state
            self._position = position
            self._attr_is_closed = position == 0
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to send position command to %s", self._name)
