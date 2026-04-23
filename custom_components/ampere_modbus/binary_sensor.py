from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
    BinarySensorDeviceClass,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_MANUFACTURER, DOMAIN
from .hub import AmpereStorageProModbusHub


async def async_setup_entry(hass, entry, async_add_entities):
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities = []
    for description in BINARY_SENSOR_TYPES.values():
        entities.append(
            AmpereBinarySensor(
                hub_name,
                hub,
                device_info,
                description,
            )
        )

    async_add_entities(entities)
    return True


class AmpereBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an Ampere Storage Pro Modbus binary sensor."""

    def __init__(
        self,
        platform_name: str,
        hub: AmpereStorageProModbusHub,
        device_info,
        description: AmpereModbusBinarySensorEntityDescription,
    ):
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self.entity_description = description

        super().__init__(coordinator=hub)

    @property
    def name(self) -> str:
        return f"{self._platform_name} {self.entity_description.name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self.entity_description.key}"

    @property
    def is_on(self) -> Optional[bool]:
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return bool(value)


@dataclass
class AmpereModbusBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Description for Ampere Modbus binary sensor entities."""


BINARY_SENSOR_TYPES: dict[str, AmpereModbusBinarySensorEntityDescription] = {
    "IslandMode": AmpereModbusBinarySensorEntityDescription(
        name="Island Mode",
        key="island_mode",
        icon="mdi:transmission-tower-off",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "GridMode": AmpereModbusBinarySensorEntityDescription(
        name="Grid Mode",
        key="grid_mode",
        icon="mdi:transmission-tower",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}
