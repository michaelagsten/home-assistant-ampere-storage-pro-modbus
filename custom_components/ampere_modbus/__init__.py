"""The Ampere Storage Pro Modbus Integration."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_UNIT,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT,
    DOMAIN,
)
from .hub import AmpereStorageProModbusHub

_LOGGER = logging.getLogger(__name__)

AMPERE_MODBUS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Required(CONF_UNIT, default=DEFAULT_UNIT): cv.positive_int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: AMPERE_MODBUS_SCHEMA})}, extra=vol.ALLOW_EXTRA
)

PLATFORMS: list[str] = ["sensor", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Ampere Storage Pro Modbus component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an Ampere Storage Pro Modbus config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    port = entry.data[CONF_PORT]
    unit = entry.data.get(CONF_UNIT, DEFAULT_UNIT)
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    _LOGGER.debug(
        "Setting up %s entry '%s' (%s:%s, unit=%s, scan_interval=%ss) with platforms: %s",
        DOMAIN,
        name,
        host,
        port,
        unit,
        scan_interval,
        PLATFORMS,
    )

    hub = AmpereStorageProModbusHub(hass, name, host, port, unit, scan_interval)

    # Store by entry_id, not by name. Names are user-visible and may collide or be changed.
    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "name": name,
    }

    try:
        await hub.async_config_entry_first_refresh()
    except Exception as err:
        await _async_shutdown_hub(hub)
        _remove_entry_data(hass, entry)

        _LOGGER.warning(
            "Initial refresh failed for %s entry '%s' at %s:%s. Entry will be retried.",
            DOMAIN,
            name,
            host,
            port,
            exc_info=True,
        )
        raise ConfigEntryNotReady(
            f"Initial Modbus refresh failed for {name} at {host}:{port}"
        ) from err

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await _async_shutdown_hub(hub)
        _remove_entry_data(hass, entry)

        _LOGGER.exception(
            "Failed to set up platforms for %s entry '%s'.", DOMAIN, name
        )
        raise

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry update.

    Reload the entry so changed options/data are applied consistently.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Ampere Storage Pro Modbus config entry."""
    hub = _get_hub(hass, entry)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if not unload_ok:
        _LOGGER.warning(
            "Could not unload all platforms for %s entry '%s'. Keeping hub data.",
            DOMAIN,
            entry.title or entry.data.get(CONF_NAME, DEFAULT_NAME),
        )
        return False

    if hub:
        await _async_shutdown_hub(hub)

    _remove_entry_data(hass, entry)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an Ampere Storage Pro Modbus config entry.

    This is called when the config entry is removed from Home Assistant.
    It makes sure that the Modbus hub is shut down and stale runtime data is
    removed from hass.data.
    """
    hub = _get_hub(hass, entry)

    if hub:
        await _async_shutdown_hub(hub)

    _remove_entry_data(hass, entry)

    _LOGGER.debug(
        "Removed %s config entry '%s'.",
        DOMAIN,
        entry.title or entry.data.get(CONF_NAME, DEFAULT_NAME),
    )


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow Home Assistant to remove stale devices for this config entry.

    This integration creates devices from entity device_info. If an older device
    remains in the device registry after device_info changes or sensor
    consolidation, Home Assistant asks this hook whether the device may be
    removed. Returning True allows removal from the UI.
    """
    _LOGGER.debug(
        "Allowing removal of device '%s' for %s entry '%s'.",
        device_entry.name_by_user or device_entry.name or device_entry.id,
        DOMAIN,
        entry.title or entry.data.get(CONF_NAME, DEFAULT_NAME),
    )
    return True


def _get_hub(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> AmpereStorageProModbusHub | None:
    """Return the hub for a config entry, if available."""
    hub_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    if not hub_data:
        return None

    hub = hub_data.get("hub")

    if isinstance(hub, AmpereStorageProModbusHub):
        return hub

    return None


def _remove_entry_data(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove runtime data for one config entry and clean empty domain data."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)


async def _async_shutdown_hub(hub: AmpereStorageProModbusHub) -> None:
    """Shutdown the hub safely during setup failure, unload or removal."""
    try:
        shutdown = getattr(hub, "async_shutdown", None)
        if shutdown:
            await shutdown()
        else:
            await hub.close()
    except Exception:
        _LOGGER.warning("Error while shutting down Ampere Modbus hub.", exc_info=True)
