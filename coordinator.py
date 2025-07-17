"""TCP Coordinator for Curtain Control integration."""

import asyncio
from collections.abc import Callable
import contextlib
import logging
import struct
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def calculate_crc(command: bytes) -> int:
    """Calculate CRC for the command."""
    crc = 0xFFFF
    for byte in command:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def bytes_to_hex(byte_string: bytes) -> str:
    """Convert bytes to hex string."""
    return ' '.join([f'{b:02X}' for b in byte_string])


def correct_position(position: int) -> int:
    """修正位置数据，处理硬件限位器不精确的问题.

    Args:
        position: 原始位置值 (0-100)

    Returns:
        修正后的位置值
    """
    if 97 <= position <= 100:
        return 100
    if 0 <= position <= 3:
        return 0
    return position


def generate_command(device_address: int, function_code: int, data_address: int, data: int) -> bytes:
    """Generate command for the curtain control."""
    command = struct.pack('>BHB', 0x55, device_address, function_code) + struct.pack('>B', data_address) + struct.pack('>B', data)
    crc = calculate_crc(command)
    return command + struct.pack('<H', crc)


class CurtainTCPCoordinator(DataUpdateCoordinator):
    """Coordinator for managing TCP connection and device communication."""

    def __init__(self, hass: HomeAssistant, host: str, port: int):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # We handle updates via TCP stream
        )

        self._host = host
        self._port = port

        # Device management
        self._devices: dict[int, Any] = {}  # device_address -> entity
        self._device_positions: dict[int, int | None] = {}  # device_address -> position

        # TCP connection
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listen_task: asyncio.Task | None = None
        self._command_lock = asyncio.Lock()

        # Discovery
        self._discovered_devices: list[int] = []
        self._discovery_callbacks: list[Callable] = []

    @property
    def host(self) -> str:
        """Return the host."""
        return self._host

    @property
    def port(self) -> int:
        """Return the port."""
        return self._port

    @property
    def discovered_devices(self) -> list[int]:
        """Return list of discovered device addresses."""
        return self._discovered_devices.copy()

    @property
    def is_connected(self) -> bool:
        """Return if coordinator is connected."""
        return self._writer is not None

    async def test_connection(self) -> bool:
        """Test if connection can be established."""
        return await self._async_connect()

    async def disconnect(self) -> None:
        """Disconnect from TCP server."""
        await self._async_disconnect()

    async def async_setup(self) -> bool:
        """Set up the coordinator."""
        _LOGGER.info("Setting up curtain TCP coordinator for %s:%d", self._host, self._port)

        # Start the TCP listening task
        self._listen_task = asyncio.create_task(self._async_listen_loop())
        return True

    async def async_shutdown(self):
        """Shutdown the coordinator."""
        _LOGGER.info("Shutting down curtain TCP coordinator")

        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

        await self._async_disconnect()

    async def _async_connect(self) -> bool:
        """Establish TCP connection."""
        try:
            _LOGGER.info("Connecting to TCP server %s:%d", self._host, self._port)
            self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
            _LOGGER.info("✅ Successfully connected to TCP server")
        except (OSError, ConnectionError) as e:
            _LOGGER.error("Failed to connect to TCP server: %s", e)
            return False
        else:
            return True

    async def _async_disconnect(self):
        """Disconnect from TCP server."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None
            _LOGGER.info("Disconnected from TCP server")

    async def _async_listen_loop(self):
        """Main listening loop for TCP data."""
        _LOGGER.info("Starting TCP listening loop")

        while True:
            try:
                # Ensure connection
                if not self._reader or not self._writer:
                    if not await self._async_connect():
                        _LOGGER.info("Waiting 5 seconds before retry...")
                        await asyncio.sleep(5)
                        continue

                # Read data
                data = await self._reader.read(1024)
                if not data:
                    _LOGGER.warning("TCP connection closed, reconnecting...")
                    await self._async_disconnect()
                    continue

                _LOGGER.debug("Received TCP data: %s", bytes_to_hex(data))

                # Parse multiple packets
                self._parse_multiple_packets(data)

            except asyncio.CancelledError:
                _LOGGER.info("TCP listening loop cancelled")
                break
            except (OSError, ConnectionError, struct.error, ValueError) as e:
                _LOGGER.error("Error in TCP listening loop: %s", e)
                await self._async_disconnect()
                await asyncio.sleep(5)

    def _parse_multiple_packets(self, data: bytes):
        """Parse multiple packets from TCP stream."""
        offset = 0
        while offset < len(data):
            # Find packet start marker 0x55
            start_idx = data.find(0x55, offset)
            if start_idx == -1:
                break

            # Check if we have enough data for a complete packet
            if start_idx + 8 > len(data):
                _LOGGER.debug("Incomplete packet, waiting for more data")
                break

            # Extract single packet (8 bytes)
            packet = data[start_idx:start_idx + 8]
            _LOGGER.debug("Processing packet: %s", bytes_to_hex(packet))
            self._parse_status_packet(packet)

            offset = start_idx + 8

    def _parse_status_packet(self, data: bytes):
        """Parse status packet and update device state."""
        if len(data) < 8:
            return
        if data[0] != 0x55:
            return

        # Parse device address (bytes 1-2, big endian)
        device_address = struct.unpack('>H', data[1:3])[0]
        function_code = data[3]
        data_address = data[4]
        position = data[5]

        _LOGGER.debug("Parsed packet: device=0x%04X, func=0x%02X, addr=0x%02X, pos=%d",
                     device_address, function_code, data_address, position)

        # Verify CRC
        crc_received = struct.unpack('<H', data[6:8])[0]
        crc_calculated = calculate_crc(data[:6])

        if crc_received != crc_calculated:
            _LOGGER.error("CRC mismatch for device 0x%04X", device_address)
            return

        # Update device discovery
        if device_address not in self._discovered_devices:
            self._discovered_devices.append(device_address)
            _LOGGER.info("🔍 Discovered new device: 0x%04X", device_address)

            # Notify discovery callbacks
            for callback in self._discovery_callbacks:
                try:
                    callback(device_address)
                except (TypeError, ValueError, AttributeError) as e:
                    _LOGGER.error("Error in discovery callback: %s", e)

        # Update device position if this is a status response
        if function_code == 0x01 and data_address == 0x01:
            old_position = self._device_positions.get(device_address)

            # 修正位置数据，处理硬件限位器不精确的问题
            raw_position = position
            corrected_position = correct_position(position)

            self._device_positions[device_address] = corrected_position

            if raw_position != corrected_position:
                _LOGGER.info("📍 Device 0x%04X position update: %s -> %d (raw: %d, corrected: %d)",
                            device_address, old_position, corrected_position, raw_position, corrected_position)
            else:
                _LOGGER.info("📍 Device 0x%04X position update: %s -> %d",
                            device_address, old_position, corrected_position)

            # Notify registered device entity
            if device_address in self._devices:
                entity = self._devices[device_address]
                if hasattr(entity, 'async_update_position'):
                    self.hass.async_create_task(
                        entity.async_update_position(corrected_position)
                    )

    async def send_command(self, device_address: int, function_code: int, data_address: int, data: int) -> bool:
        """Send command to specific device."""
        command = generate_command(device_address, function_code, data_address, data)
        return await self._send_raw_command(command)

    async def _send_raw_command(self, command: bytes) -> bool:
        """Send raw command bytes."""
        async with self._command_lock:
            try:
                # Ensure connection
                if not self._writer:
                    if not await self._async_connect():
                        return False

                # Send command
                self._writer.write(command)
                await self._writer.drain()

                _LOGGER.info("📤 Sent command: %s", bytes_to_hex(command))

            except (OSError, ConnectionError) as e:
                _LOGGER.error("Failed to send command: %s", e)
                await self._async_disconnect()
                return False
            else:
                return True

    def register_device(self, device_address: int, entity):
        """Register a device entity with the coordinator."""
        self._devices[device_address] = entity
        _LOGGER.info("Registered device 0x%04X with coordinator", device_address)

    def unregister_device(self, device_address: int):
        """Unregister a device entity."""
        if device_address in self._devices:
            del self._devices[device_address]
            _LOGGER.info("Unregistered device 0x%04X", device_address)

    def get_device_position(self, device_address: int) -> int | None:
        """Get current position for a device."""
        return self._device_positions.get(device_address)

    def add_discovery_callback(self, callback: Callable[[int], None]):
        """Add a callback for device discovery."""
        self._discovery_callbacks.append(callback)

    def remove_discovery_callback(self, callback: Callable[[int], None]):
        """Remove a discovery callback."""
        if callback in self._discovery_callbacks:
            self._discovery_callbacks.remove(callback)

    async def async_discover_devices(self, timeout: int = 30) -> list[int]:
        """Discover devices by listening for a specified time."""
        _LOGGER.info("Starting device discovery for %d seconds...", timeout)

        initial_devices = set(self._discovered_devices)
        await asyncio.sleep(timeout)
        new_devices = set(self._discovered_devices) - initial_devices

        _LOGGER.info("Discovery complete. Found %d new devices: %s",
                    len(new_devices),
                    [f"0x{addr:04X}" for addr in new_devices])

        return self._discovered_devices.copy()
