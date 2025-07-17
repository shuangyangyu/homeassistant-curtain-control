"""Device Discovery Service for Curtain Control integration."""

import asyncio
import logging
from typing import NamedTuple

from .coordinator import CurtainTCPCoordinator

_LOGGER = logging.getLogger(__name__)


class DiscoveredDevice(NamedTuple):
    """Represents a discovered curtain device."""
    address: int
    name: str
    last_position: int
    last_seen: float


class DeviceDiscovery:
    """Service for discovering curtain control devices."""

    def __init__(self, coordinator: CurtainTCPCoordinator, use_mapping: bool = True):
        """Initialize device discovery service."""
        self._coordinator = coordinator
        self._devices: dict[int, DiscoveredDevice] = {}
        self._discovery_active = False
        self._use_mapping = use_mapping

    @property
    def discovered_devices(self) -> list[DiscoveredDevice]:
        """Return list of discovered devices."""
        return list(self._devices.values())

    def get_device_name(self, address: int, use_mapping: bool = True) -> str:
        """Generate a friendly name for a device."""
        if not use_mapping:
            # 不使用映射表，直接返回设备地址
            return f"窗帘 0x{address:04X}"

        # 真实设备地址映射表
        device_names = {
            0x06FE: "主卧室_纱帘",
            0x05FE: "主卧室_布帘",
            0x04FE: "客厅_纱帘",
            0x07FE: "儿童房_布帘",
            0x08FE: "儿童房_纱帘",
            0x0AFE: "书房_纱帘",
            0x09FE: "书房_布帘",
            0x02FE: "老人房_纱帘",
            0x01FE: "老人房_布帘",
            0x03FE: "客厅_布帘",
        }

        return device_names.get(address, f"窗帘 0x{address:04X}")

    async def scan_for_devices(self, timeout: int = 30) -> list[DiscoveredDevice]:
        """Scan for devices for a specified time."""
        _LOGGER.info("🔍 Starting device discovery scan for %d seconds", timeout)

        # Clear previous discoveries
        self._devices.clear()
        self._discovery_active = True

        # Add callback to capture discovered devices
        def on_device_discovered(address: int):
            if self._discovery_active:
                position = self._coordinator.get_device_position(address) or 0
                device = DiscoveredDevice(
                    address=address,
                    name=self.get_device_name(address, self._use_mapping),
                    last_position=position,
                    last_seen=asyncio.get_event_loop().time()
                )
                self._devices[address] = device
                _LOGGER.info("✅ Found device: %s (0x%04X) at position %d%%",
                           device.name, address, position)

        # Register discovery callback
        self._coordinator.add_discovery_callback(on_device_discovered)

        try:
            # Wait for discovery period
            await asyncio.sleep(timeout)

            # Also get any devices that were already known
            for address in self._coordinator.discovered_devices:
                if address not in self._devices:
                    position = self._coordinator.get_device_position(address) or 0
                    device = DiscoveredDevice(
                        address=address,
                        name=self.get_device_name(address, self._use_mapping),
                        last_position=position,
                        last_seen=asyncio.get_event_loop().time()
                    )
                    self._devices[address] = device

        finally:
            self._discovery_active = False
            self._coordinator.remove_discovery_callback(on_device_discovered)

        discovered = list(self._devices.values())
        _LOGGER.info("🎯 Discovery complete! Found %d devices: %s",
                   len(discovered),
                   ", ".join([f"{d.name}(0x{d.address:04X})" for d in discovered]))

        return discovered

    async def test_device_communication(self, address: int) -> bool:
        """Test communication with a specific device."""
        _LOGGER.info("Testing communication with device 0x%04X", address)

        # Try to send a query command
        try:
            success = await self._coordinator.send_command(address, 0x01, 0x01, 0x00)
        except (TimeoutError, OSError, ConnectionError) as e:
            _LOGGER.error("Error testing device 0x%04X: %s", address, e)
            return False

        if success:
            _LOGGER.info("✅ Device 0x%04X communication test passed", address)
            return True
        _LOGGER.warning("❌ Device 0x%04X communication test failed", address)
        return False

    def get_device_by_address(self, address: int) -> DiscoveredDevice:
        """Get device info by address."""
        return self._devices.get(address)

    def create_device_config(self, device: DiscoveredDevice) -> dict:
        """Create device configuration for Home Assistant."""
        return {
            "device_address": device.address,
            "name": device.name,
            "last_position": device.last_position,
            "unique_id": f"curtain_{device.address:04x}",
        }

    async def validate_device_addresses(self, addresses: list[int]) -> list[int]:
        """Validate that specified device addresses are reachable."""
        valid_addresses = []

        for address in addresses:
            if await self.test_device_communication(address):
                valid_addresses.append(address)
            else:
                _LOGGER.warning("Device 0x%04X is not responding", address)

        return valid_addresses

    def get_device_statistics(self) -> dict:
        """Get statistics about discovered devices."""
        if not self._devices:
            return {"total": 0, "responding": 0}

        total = len(self._devices)
        positions = [d.last_position for d in self._devices.values() if d.last_position is not None]

        return {
            "total": total,
            "responding": len(positions),
            "average_position": sum(positions) / len(positions) if positions else 0,
            "devices": [
                {
                    "address": f"0x{d.address:04X}",
                    "name": d.name,
                    "position": d.last_position
                }
                for d in self._devices.values()
            ]
        }
