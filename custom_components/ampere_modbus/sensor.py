from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    EntityCategory,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_MANUFACTURER, DOMAIN
from .hub import AmpereStorageProModbusHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    """Set up Ampere Modbus sensors for one config entry."""
    hub_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    if not hub_data or "hub" not in hub_data:
        _LOGGER.error(
            "Cannot set up sensors for %s entry %s: hub data missing.",
            DOMAIN,
            entry.entry_id,
        )
        return False

    hub: AmpereStorageProModbusHub = hub_data["hub"]
    hub_name = hub_data.get("name") or entry.data.get(CONF_NAME) or entry.title or DOMAIN

    device_info = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities: list[AmpereSensor] = [
        AmpereSensor(
            entry_id=entry.entry_id,
            platform_name=hub_name,
            hub=hub,
            device_info=device_info,
            description=sensor_description,
        )
        for sensor_description in SENSOR_TYPES.values()
    ]

    async_add_entities(entities)
    return True


class AmpereSensor(CoordinatorEntity, SensorEntity):
    """Representation of an Ampere Storage Pro Modbus sensor."""

    entity_description: "AmpereModbusSensorEntityDescription"

    def __init__(
        self,
        entry_id: str,
        platform_name: str,
        hub: AmpereStorageProModbusHub,
        device_info: dict[str, Any],
        description: "AmpereModbusSensorEntityDescription",
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=hub)

        self._entry_id = entry_id
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self.entity_description = description

        self._attr_name = f"{self._platform_name} {self.entity_description.name}"
        self._attr_unique_id = f"{DOMAIN}_{self._entry_id}_{self.entity_description.key}"

    @property
    def available(self) -> bool:
        """Return whether the sensor currently has usable coordinator data."""
        return bool(self.coordinator.last_update_success and self.coordinator.data)

    @property
    def native_value(self):
        """Return the state of the sensor.

        Keep numeric sensors numeric. Invalid or missing values are returned as
        None, which Home Assistant represents safely as unavailable/unknown
        without violating number sensor validation.
        """
        data = self.coordinator.data or {}
        key = self.entity_description.key

        if key not in data:
            return None

        value = data.get(key)

        if value in (None, "", "unknown", "Unknown", "unavailable", "Unavailable"):
            return None

        if self._expects_number:
            try:
                return float(value)
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Ignoring non-numeric value for numeric sensor %s: %r",
                    self.entity_description.key,
                    value,
                )
                return None

        return value

    @property
    def _expects_number(self) -> bool:
        """Return True if HA expects this sensor to expose a numeric value."""
        return bool(
            self.entity_description.native_unit_of_measurement
            or self.entity_description.device_class
            in {
                SensorDeviceClass.BATTERY,
                SensorDeviceClass.CURRENT,
                SensorDeviceClass.ENERGY,
                SensorDeviceClass.FREQUENCY,
                SensorDeviceClass.POWER,
                SensorDeviceClass.TEMPERATURE,
                SensorDeviceClass.VOLTAGE,
            }
            or self.entity_description.state_class
            in {
                SensorStateClass.MEASUREMENT,
                SensorStateClass.TOTAL,
                SensorStateClass.TOTAL_INCREASING,
            }
        )


@dataclass(frozen=True, kw_only=True)
class AmpereModbusSensorEntityDescription(SensorEntityDescription):
    """Description for Ampere Modbus sensor entities."""


SENSOR_TYPES: dict[str, AmpereModbusSensorEntityDescription] = {
    "DeviceType": AmpereModbusSensorEntityDescription(
        name="Device Type",
        key="devicetype",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "SubType": AmpereModbusSensorEntityDescription(
        name="Sub Type",
        key="subtype",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "CommVer": AmpereModbusSensorEntityDescription(
        name="Comms Protocol Version",
        key="commver",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "SerialNumber": AmpereModbusSensorEntityDescription(
        name="Serial Number",
        key="serialnumber",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "ProductCode": AmpereModbusSensorEntityDescription(
        name="Product Code",
        key="productcode",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "DV": AmpereModbusSensorEntityDescription(
        name="Display Software Version",
        key="dv",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "MCV": AmpereModbusSensorEntityDescription(
        name="Master Ctrl Software Version",
        key="mcv",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "SCV": AmpereModbusSensorEntityDescription(
        name="Slave Ctrl Software Version",
        key="scv",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "DispHWVersion": AmpereModbusSensorEntityDescription(
        name="Display Board Hardware Version",
        key="disphwversion",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "CtrlHWVersion": AmpereModbusSensorEntityDescription(
        name="Control Board Hardware Version",
        key="ctrlhwversion",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "PowerHWVersion": AmpereModbusSensorEntityDescription(
        name="Power Board Hardware Version",
        key="powerhwversion",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "BatteryVoltage": AmpereModbusSensorEntityDescription(
        name="Battery Voltage",
        key="batteryvoltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "BatteryCurr": AmpereModbusSensorEntityDescription(
        name="Battery Current",
        key="batterycurrent",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "BatteryPower": AmpereModbusSensorEntityDescription(
        name="Battery Power",
        key="batterypower",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "BatteryTemperature": AmpereModbusSensorEntityDescription(
        name="Battery Temperature",
        key="batterytemperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "BatteryPercent": AmpereModbusSensorEntityDescription(
        name="Battery Percent",
        key="batterypercent",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    # ---------------------------------------------------------------------
    # Battery / BMS health raw values from peripheral block 0xA000..0xA023
    # ---------------------------------------------------------------------
    "BatteryModuleCount": AmpereModbusSensorEntityDescription(
        name="Battery Module Count",
        key="battery_module_count",
        icon="mdi:battery-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "BatteryCapacityAh": AmpereModbusSensorEntityDescription(
        name="Battery Capacity Ah",
        key="battery_capacity_ah",
        native_unit_of_measurement="Ah",
        icon="mdi:battery-high",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "BatteryAvailableCapacity": AmpereModbusSensorEntityDescription(
        name="Battery Available Capacity",
        key="battery_available_capacity",
        native_unit_of_measurement="Ah",
        icon="mdi:battery-check",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "BatteryOnlineMask": AmpereModbusSensorEntityDescription(
        name="Battery Online Mask",
        key="battery_online_mask",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    "Battery1Soc": AmpereModbusSensorEntityDescription(
        name="Battery 1 SOC",
        key="battery_1_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery1Soh": AmpereModbusSensorEntityDescription(
        name="Battery 1 SOH",
        key="battery_1_soh",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery1Voltage": AmpereModbusSensorEntityDescription(
        name="Battery 1 Voltage",
        key="battery_1_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery1Current": AmpereModbusSensorEntityDescription(
        name="Battery 1 Current",
        key="battery_1_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery1Temperature": AmpereModbusSensorEntityDescription(
        name="Battery 1 Temperature",
        key="battery_1_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery1Cycles": AmpereModbusSensorEntityDescription(
        name="Battery 1 Cycles",
        key="battery_1_cycles",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    "Battery2Soc": AmpereModbusSensorEntityDescription(
        name="Battery 2 SOC",
        key="battery_2_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery2Soh": AmpereModbusSensorEntityDescription(
        name="Battery 2 SOH",
        key="battery_2_soh",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery2Voltage": AmpereModbusSensorEntityDescription(
        name="Battery 2 Voltage",
        key="battery_2_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery2Current": AmpereModbusSensorEntityDescription(
        name="Battery 2 Current",
        key="battery_2_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery2Temperature": AmpereModbusSensorEntityDescription(
        name="Battery 2 Temperature",
        key="battery_2_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery2Cycles": AmpereModbusSensorEntityDescription(
        name="Battery 2 Cycles",
        key="battery_2_cycles",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    "Battery3Soc": AmpereModbusSensorEntityDescription(
        name="Battery 3 SOC",
        key="battery_3_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery3Soh": AmpereModbusSensorEntityDescription(
        name="Battery 3 SOH",
        key="battery_3_soh",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery3Voltage": AmpereModbusSensorEntityDescription(
        name="Battery 3 Voltage",
        key="battery_3_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery3Current": AmpereModbusSensorEntityDescription(
        name="Battery 3 Current",
        key="battery_3_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery3Temperature": AmpereModbusSensorEntityDescription(
        name="Battery 3 Temperature",
        key="battery_3_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery3Cycles": AmpereModbusSensorEntityDescription(
        name="Battery 3 Cycles",
        key="battery_3_cycles",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    "Battery4Soc": AmpereModbusSensorEntityDescription(
        name="Battery 4 SOC",
        key="battery_4_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery4Soh": AmpereModbusSensorEntityDescription(
        name="Battery 4 SOH",
        key="battery_4_soh",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery4Voltage": AmpereModbusSensorEntityDescription(
        name="Battery 4 Voltage",
        key="battery_4_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery4Current": AmpereModbusSensorEntityDescription(
        name="Battery 4 Current",
        key="battery_4_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery4Temperature": AmpereModbusSensorEntityDescription(
        name="Battery 4 Temperature",
        key="battery_4_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "Battery4Cycles": AmpereModbusSensorEntityDescription(
        name="Battery 4 Cycles",
        key="battery_4_cycles",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    "PV1Volt": AmpereModbusSensorEntityDescription(
        name="PV1 Voltage",
        key="pv1volt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "PV1Curr": AmpereModbusSensorEntityDescription(
        name="PV1 Current",
        key="pv1curr",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "PV1Power": AmpereModbusSensorEntityDescription(
        name="PV1 Power",
        key="pv1power",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "PV2Volt": AmpereModbusSensorEntityDescription(
        name="PV2 Voltage",
        key="pv2volt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "PV2Curr": AmpereModbusSensorEntityDescription(
        name="PV2 Current",
        key="pv2curr",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    "PV2Power": AmpereModbusSensorEntityDescription(
        name="PV2 Power",
        key="pv2power",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "TotalPvPower": AmpereModbusSensorEntityDescription(
        name="Total PV Power",
        key="totalpvpower",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "GridPower": AmpereModbusSensorEntityDescription(
        name="Grid Power",
        key="gridpower",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "DailyPvGeneration": AmpereModbusSensorEntityDescription(
        name="Daily PV Generation",
        key="dailypvgeneration",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "MonthPvGeneration": AmpereModbusSensorEntityDescription(
        name="Month PV Generation",
        key="monthpvgeneration",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "YearPvGeneration": AmpereModbusSensorEntityDescription(
        name="Year PV Generation",
        key="yearpvgeneration",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "TotalPvGeneration": AmpereModbusSensorEntityDescription(
        name="Total PV Generation",
        key="totalpvgeneration",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "DailyChargeBattery": AmpereModbusSensorEntityDescription(
        name="Daily Charge Battery",
        key="dailychargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "MonthChargeBattery": AmpereModbusSensorEntityDescription(
        name="Month Charge Battery",
        key="monthchargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "YearChargeBattery": AmpereModbusSensorEntityDescription(
        name="Year Charge Battery",
        key="yearchargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "TotalChargeBattery": AmpereModbusSensorEntityDescription(
        name="Total Charge Battery",
        key="totalchargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "DailyDischargeBattery": AmpereModbusSensorEntityDescription(
        name="Daily Discharge Battery",
        key="dailydischargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "MonthDischargeBattery": AmpereModbusSensorEntityDescription(
        name="Month Discharge Battery",
        key="monthdischargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "YearDischargeBattery": AmpereModbusSensorEntityDescription(
        name="Year Discharge Battery",
        key="yeardischargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "TotalDischargeBattery": AmpereModbusSensorEntityDescription(
        name="Total Discharge Battery",
        key="totaldischargebattery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "PvFlowText": AmpereModbusSensorEntityDescription(
        name="PV Flow Text",
        key="pvflowtext",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "PvFlow": AmpereModbusSensorEntityDescription(
        name="PV Flow",
        key="pvflow",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "BatteryFlowText": AmpereModbusSensorEntityDescription(
        name="Battery Flow Text",
        key="batteryflowtext",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "BatteryFlow": AmpereModbusSensorEntityDescription(
        name="Battery Flow",
        key="batteryflow",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "GridFlowText": AmpereModbusSensorEntityDescription(
        name="Grid Flow Text",
        key="gridflowtext",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "GridFlow": AmpereModbusSensorEntityDescription(
        name="Grid Flow",
        key="gridflow",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    "DeviceStatus": AmpereModbusSensorEntityDescription(
        name="Device Status",
        key="devicestatus",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "DeviceStatusRaw": AmpereModbusSensorEntityDescription(
        name="Device Status Raw",
        key="devicestatus_raw",
        icon="mdi:counter",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "DeviceError": AmpereModbusSensorEntityDescription(
        name="Device Error",
        key="deviceerror",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "GridVoltageL1": AmpereModbusSensorEntityDescription(
        name="Grid Voltage L1",
        key="grid_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    "GridVoltageL2": AmpereModbusSensorEntityDescription(
        name="Grid Voltage L2",
        key="grid_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    "GridVoltageL3": AmpereModbusSensorEntityDescription(
        name="Grid Voltage L3",
        key="grid_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    "GridFrequency": AmpereModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    "DailyGridImportEnergy": AmpereModbusSensorEntityDescription(
        name="Daily Grid Import Energy",
        key="dailygridimportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "MonthGridImportEnergy": AmpereModbusSensorEntityDescription(
        name="Month Grid Import Energy",
        key="monthgridimportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "YearGridImportEnergy": AmpereModbusSensorEntityDescription(
        name="Year Grid Import Energy",
        key="yeargridimportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "TotalGridImportEnergy": AmpereModbusSensorEntityDescription(
        name="Total Grid Import Energy",
        key="totalgridimportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "DailyGridExportEnergy": AmpereModbusSensorEntityDescription(
        name="Daily Grid Export Energy",
        key="dailygridexportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "MonthGridExportEnergy": AmpereModbusSensorEntityDescription(
        name="Month Grid Export Energy",
        key="monthgridexportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "YearGridExportEnergy": AmpereModbusSensorEntityDescription(
        name="Year Grid Export Energy",
        key="yeargridexportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "TotalGridExportEnergy": AmpereModbusSensorEntityDescription(
        name="Total Grid Export Energy",
        key="totalgridexportenergy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
}
