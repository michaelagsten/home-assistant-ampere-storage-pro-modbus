"""The Ampere Storage Pro Modbus Integration."""

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from .const import (
    CONF_UNIT,
    DEFAULT_NAME,
    DEFAULT_UNIT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .hub import AmpereStorageProModbusHub

_LOGGER = logging.getLogger(__name__)

AMPERE_MODBUS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.string,
        vol.Required(CONF_UNIT, default=DEFAULT_UNIT): cv.positive_int,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): cv.positive_int,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: AMPERE_MODBUS_SCHEMA})}, extra=vol.ALLOW_EXTRA
)

PLATFORMS: list[str] = ["sensor", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config):
    """Set up the Ampere Storage Pro Modbus component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up an Ampere Storage Pro Modbus entry."""
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    port = entry.data[CONF_PORT]
    unit = entry.data[CONF_UNIT]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]

    _LOGGER.debug("Setup %s.%s with platforms: %s", DOMAIN, name, PLATFORMS)

    hub = AmpereStorageProModbusHub(hass, name, host, port, unit, scan_interval)

    try:
        await hub.async_config_entry_first_refresh()
    except Exception:
        await hub.close()
        _LOGGER.exception("Initial refresh failed for %s.%s", DOMAIN, name)
        raise

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][name] = {"hub": hub}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload Ampere Storage Pro Modbus entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        name = entry.data[CONF_NAME]
        hub_data = hass.data.get(DOMAIN, {}).get(name)

        if hub_data and "hub" in hub_data:
            await hub_data["hub"].close()

        hass.data.get(DOMAIN, {}).pop(name, None)

    return unloaded
