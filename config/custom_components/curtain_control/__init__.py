"""Curtain Control Integration for Home Assistant."""

import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass, config):
    """Set up the curtain control component."""
    _LOGGER.info("Setting up curtain control component")
    return True

async def async_setup_entry(hass, entry):
    """Set up curtain control from a config entry."""
    _LOGGER.info("Setting up curtain control from config entry")
    await hass.config_entries.async_forward_entry_setups(entry, ["cover"])
    return True

async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    _LOGGER.info("Unloading curtain control config entry")
    return await hass.config_entries.async_forward_entry_unload(entry, "cover") 