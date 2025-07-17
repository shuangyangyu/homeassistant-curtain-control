"""Curtain Control Integration for Home Assistant."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_DEVICES, DATA_COORDINATOR, DOMAIN
from .coordinator import CurtainTCPCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the curtain control component."""
    _LOGGER.info("Setting up curtain control component")

    # Initialize data storage
    hass.data.setdefault(DOMAIN, {})
    hass.data.setdefault(DATA_COORDINATOR, {})

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up curtain control from a config entry."""
    _LOGGER.info("Setting up curtain control from config entry: %s", entry.title)

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    devices = entry.data.get(CONF_DEVICES, [])

    # Create coordinator
    coordinator = CurtainTCPCoordinator(hass, host, port)

    # Setup coordinator
    if not await coordinator.async_setup():
        _LOGGER.error("Failed to setup coordinator for %s:%d", host, port)
        return False

    # Store coordinator
    hass.data[DATA_COORDINATOR][entry.entry_id] = coordinator

    # Register device in device registry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{host}_{port}")},
        name="Duya窗帘控制器",
        manufacturer="Duya",
        model="智能窗帘控制器",
        sw_version="1.0",
        connections={("tcp", f"{host}:{port}")},
    )

    _LOGGER.info("✅ Coordinator created for %s:%d with %d devices",
                host, port, len(devices))

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Log device information
    if devices:
        device_info = ", ".join([
            f"{d['name']}(0x{d['device_address']:04X})"
            for d in devices
        ])
        _LOGGER.info("Configured devices: %s", device_info)
    else:
        _LOGGER.info("No devices configured - add devices through integration options")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading curtain control config entry: %s", entry.title)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Shutdown and remove coordinator
    coordinator = hass.data[DATA_COORDINATOR].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()
        del hass.data[DATA_COORDINATOR][entry.entry_id]
        _LOGGER.info("Coordinator shutdown completed")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("Reloading curtain control config entry: %s", entry.title)
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
