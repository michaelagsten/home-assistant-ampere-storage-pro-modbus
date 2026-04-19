"""Ampere Modbus Hub"""

import asyncio
import logging
from datetime import timedelta
from typing import Any, List, Optional
import inspect
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from voluptuous.validators import Number
import threading
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.client.mixin import ModbusClientMixin
from pymodbus.exceptions import ConnectionException, ModbusIOException

from .const import (
    DEVICE_STATUSSES,
    PV_DIRECTION,
    BATTERY_DIRECTION,
    GRID_DIRECTION,
    FAULT_MESSAGES,
)

_LOGGER = logging.getLogger(__name__)


class AmpereStorageProModbusHub(DataUpdateCoordinator[dict]):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        host: str,
        port: Number,
        unit: Number,
        scan_interval: Number,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=scan_interval),
            update_method=self._async_update_data,
        )
        self._host = host
        self._port = port
        self._unit = unit
        self._client: Optional[AsyncModbusTcpClient] = None
        self._closing = False
        self._read_lock = asyncio.Lock()
        self._connection_lock = asyncio.Lock()
        self._lock = threading.Lock()

        self._inverter_data: dict = {}
        self.data: dict = {}

    def _create_client(self) -> AsyncModbusTcpClient:
        """Create a new client instance."""
        client = AsyncModbusTcpClient(
            host=self._host,
            port=self._port,
            timeout=10,
        )
        _LOGGER.debug(
            "Created new Modbus client: AsyncModbusTcpClient %s:%s",
            self._host,
            self._port,
        )
        return client

    async def _safe_close(self) -> bool:
        """Safely closes the Modbus connection."""
        if not self._client:
            return True

        try:
            if self._client.connected:
                close = getattr(self._client, "close", None)
                if close:
                    await close() if inspect.iscoroutinefunction(close) else close()
                transport = getattr(self._client, "transport", None)
                if transport:
                    transport.close()
                await asyncio.sleep(0.2)
                return not self._client.connected
            return True
        except Exception as e:
            _LOGGER.warning("Error during safe close: %s", e, exc_info=True)
            return False
        finally:
            self._client = None

    async def close(self) -> None:
        """Closes the Modbus connection with improved resource management."""
        if self._closing:
            return

        self._closing = True
        try:
            async with asyncio.timeout(5.0):
                async with self._connection_lock:
                    await self._safe_close()
        except (asyncio.TimeoutError, Exception) as e:
            _LOGGER.warning("Error during close: %s", e, exc_info=True)
        finally:
            self._closing = False

    async def ensure_modbus_connection(self) -> None:
        """Ensure the Modbus connection is established and stable."""
        if self._client and self._client.connected:
            return

        self._client = self._client or self._create_client()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=10)
            _LOGGER.info("Successfully connected to Modbus server.")
        except Exception as e:
            _LOGGER.warning("Error during connection attempt: %s", e, exc_info=True)
            raise ConnectionException("Failed to connect to Modbus server.") from e

    async def _read_holding_registers_single(
        self,
        unit: int,
        address: int,
        count: int,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ) -> List[int]:
        """Read one Modbus holding-register block with error handling."""
        if count <= 0:
            return []

        for attempt in range(max_retries):
            try:
                await self.ensure_modbus_connection()

                async with self._read_lock:
                    response = await self._client.read_holding_registers(
                        address=address,
                        count=count,
                        device_id=unit,
                    )

                if not response or response.isError():
                    raise ModbusIOException(
                        f"Invalid Modbus response from address {hex(address)}, count {count}"
                    )

                if not hasattr(response, "registers") or response.registers is None:
                    raise ModbusIOException(
                        f"No registers returned from address {hex(address)}, count {count}"
                    )

                if len(response.registers) != count:
                    raise ModbusIOException(
                        f"Register length mismatch at address {hex(address)}: "
                        f"expected {count}, got {len(response.registers)}"
                    )

                return response.registers

            except (ModbusIOException, ConnectionException, AttributeError) as e:
                _LOGGER.error(
                    "Read attempt %s failed at address %s (count %s): %s",
                    attempt + 1,
                    hex(address),
                    count,
                    e,
                )

                if attempt < max_retries - 1:
                    delay = min(base_delay * (2**attempt), 10.0)
                    await asyncio.sleep(delay)

                    if not await self._safe_close():
                        _LOGGER.warning("Failed to safely close the Modbus client.")

                    try:
                        await self.ensure_modbus_connection()
                    except ConnectionException:
                        _LOGGER.error("Failed to reconnect Modbus client.")
                        continue
                    else:
                        _LOGGER.info("Reconnected Modbus client successfully.")

        _LOGGER.error(
            "Failed to read registers from unit %s, address %s, count %s after %s attempts",
            unit,
            hex(address),
            count,
            max_retries,
        )
        raise ConnectionException(
            f"Read operation failed for address {hex(address)}, count {count} "
            f"after {max_retries} attempts"
        )

    async def read_holding_registers(
        self,
        unit: int,
        address: int,
        count: int,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ) -> List[int]:
        """
        Read Modbus holding registers with automatic chunking.

        Modbus allows max. 125 registers per request.
        We use 120 as a conservative chunk size.
        """
        if count <= 0:
            return []

        max_chunk_size = 120
        all_registers: List[int] = []

        offset = 0
        while offset < count:
            chunk_address = address + offset
            chunk_count = min(max_chunk_size, count - offset)

            chunk = await self._read_holding_registers_single(
                unit=unit,
                address=chunk_address,
                count=chunk_count,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            all_registers.extend(chunk)
            offset += chunk_count

        return all_registers

    async def _async_update_data(self) -> dict:
        try:
            await self.ensure_modbus_connection()

            if not self._inverter_data:
                self._inverter_data.update(await self.read_modbus_inverter_data())

            all_read_data = {**self._inverter_data}
            all_read_data.update(await self.read_modbus_device_data())
            all_read_data.update(await self.read_modbus_realtime_data())
            all_read_data.update(await self.read_modbus_grid_ac_data())
            all_read_data.update(await self.read_modbus_longterm_data())

            return all_read_data
        finally:
            await self.close()

    def decode_16bit_uint(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._client.convert_from_registers(
                [register[position]], ModbusClientMixin.DATATYPE.UINT16
            )
        except Exception as e:
            _LOGGER.error("Error decode_16bit_uint: %s", e)

        position += 1
        return value, position

    def decode_16bit_int(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._client.convert_from_registers(
                [register[position]], ModbusClientMixin.DATATYPE.INT16
            )
        except Exception as e:
            _LOGGER.error("Error decode_16bit_int: %s", e)

        position += 1
        return value, position

    def decode_32bit_uint(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._client.convert_from_registers(
                [register[position], register[position + 1]],
                ModbusClientMixin.DATATYPE.UINT32,
            )
        except Exception as e:
            _LOGGER.error("Error decode_32bit_uint: %s", e)

        position += 2
        return value, position

    def decode_32bit_int(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._client.convert_from_registers(
                [register[position], register[position + 1]],
                ModbusClientMixin.DATATYPE.INT32,
            )
        except Exception as e:
            _LOGGER.error("Error decode_32bit_int: %s", e)

        position += 2
        return value, position

    def decode_string(
        self, length: int, register: List[int], position: int
    ) -> tuple[str, int]:
        register_of_string: List[int] = []
        for i in range(length):
            register_of_string.append(register[position + i])

        try:
            value = self._client.convert_from_registers(
                register_of_string, ModbusClientMixin.DATATYPE.STRING
            )
        except Exception as e:
            _LOGGER.error("Error decode_string: %s", e)
            value = ""

        position += length
        return str(value), position

    async def read_modbus_inverter_data(self) -> dict:
        try:
            register_list = await self.read_holding_registers(self._unit, 0x8F00, 29)
            position = 0
            data = {}

            value, position = self.decode_16bit_uint(register_list, position)
            data["devicetype"] = value

            value, position = self.decode_16bit_uint(register_list, position)
            data["subtype"] = value

            value, position = self.decode_16bit_uint(register_list, position)
            data["commver"] = round(value * 0.001, 3)

            value, position = self.decode_string(10, register_list, position)
            data["serialnumber"] = str(value)

            value, position = self.decode_string(10, register_list, position)
            data["productcode"] = str(value)

            value, position = self.decode_16bit_uint(register_list, position)
            data["dv"] = round(value * 0.001, 3)
            value, position = self.decode_16bit_uint(register_list, position)
            data["mcv"] = round(value * 0.001, 3)
            value, position = self.decode_16bit_uint(register_list, position)
            data["scv"] = round(value * 0.001, 3)
            value, position = self.decode_16bit_uint(register_list, position)
            data["disphwversion"] = round(value * 0.001, 3)
            value, position = self.decode_16bit_uint(register_list, position)
            data["ctrlhwversion"] = round(value * 0.001, 3)
            value, position = self.decode_16bit_uint(register_list, position)
            data["powerhwversion"] = round(value * 0.001, 3)

            return data
        except Exception as e:
            _LOGGER.error("Error reading inverter data: %s", e)
            return {}

    async def read_modbus_device_data(self) -> dict:
        try:
            register_list = await self.read_holding_registers(self._unit, 0x4004, 7)
            position = 0
            data = {}

            value, position = self.decode_16bit_uint(register_list, position)
            data["devicestatus"] = DEVICE_STATUSSES.get(value, "Unknown")

            fault1, position = self.decode_32bit_uint(register_list, position)
            fault2, position = self.decode_32bit_uint(register_list, position)
            fault3, position = self.decode_32bit_uint(register_list, position)

            error_messages = []
            error_messages.extend(
                msg for code, msg in FAULT_MESSAGES[0].items() if fault1 & code
            )
            error_messages.extend(
                msg for code, msg in FAULT_MESSAGES[1].items() if fault2 & code
            )
            error_messages.extend(
                msg for code, msg in FAULT_MESSAGES[2].items() if fault3 & code
            )
            data["deviceerror"] = ", ".join(error_messages).strip()[:254]

            return data
        except Exception as e:
            _LOGGER.error("Error reading inverter data: %s", e)
            return {}

    async def read_modbus_realtime_data(self) -> dict:
        try:
            register_list = await self.read_holding_registers(self._unit, 0x4069, 60)
            position = 0
            data = {}

            value, position = self.decode_16bit_uint(register_list, position)
            data["batteryvoltage"] = round(value * 0.1, 1)

            value, position = self.decode_16bit_int(register_list, position)
            data["batterycurrent"] = round(value * 0.01, 2)

            position += 2  # skip 4 bytes

            value, position = self.decode_16bit_int(register_list, position)
            data["batterypower"] = round(value * 1, 0)
            value, position = self.decode_16bit_int(register_list, position)
            data["batterytemperature"] = round(value * 0.1, 0)
            value, position = self.decode_16bit_uint(register_list, position)
            data["batterypercent"] = round(value * 0.01, 0)

            position += 1  # skip 2 bytes

            value, position = self.decode_16bit_uint(register_list, position)
            data["pv1volt"] = round(value * 0.1, 1)
            value, position = self.decode_16bit_uint(register_list, position)
            data["pv1curr"] = round(value * 0.01, 2)
            pv1power, position = self.decode_16bit_uint(register_list, position)
            data["pv1power"] = round(pv1power * 1, 0)

            value, position = self.decode_16bit_uint(register_list, position)
            data["pv2volt"] = round(value * 0.1, 1)
            value, position = self.decode_16bit_uint(register_list, position)
            data["pv2curr"] = round(value * 0.01, 2)
            pv2power, position = self.decode_16bit_uint(register_list, position)
            data["pv2power"] = round(pv2power * 1, 0)

            data["totalpvpower"] = round(pv1power * 1, 0) + round(pv2power * 1, 0)

            position += 6   # skip pv3 & pv4 = 12 bytes
            position += 16  # skip unknown = 32 bytes

            position += 1  # V Volt (R)
            position += 1  # A Current (R)
            position += 1  # Hz Frequenz (R)
            position += 1  # W Power L1 (R)
            position += 1  # A Current L2 (S)
            position += 1  # W Power L2 (S)
            position += 1  # A Current L3 (T)
            position += 1  # W Power L3 (T)

            value, position = self.decode_16bit_int(register_list, position)
            data["pvflow"] = value
            data["pvflowtext"] = PV_DIRECTION.get(value, "Unknown")

            value, position = self.decode_16bit_int(register_list, position)
            data["batteryflow"] = value
            data["batteryflowtext"] = BATTERY_DIRECTION.get(value, "Unknown")

            value, position = self.decode_16bit_int(register_list, position)
            data["gridflow"] = value
            data["gridflowtext"] = GRID_DIRECTION.get(value, "Unknown")

            position += 1  # flow load
            position += 7  # reserved

            position += 1  # total system load consumes power
            value, position = self.decode_16bit_int(register_list, position)
            data["gridpower"] = value
            position += 1  # CT Apparent power of the grid
            position += 1  # CT PV real power
            position += 1  # CT PV Apparent power

            return data

        except Exception as e:
            _LOGGER.error("Error reading inverter data: %s", e)
            return {}

    async def read_modbus_longterm_data(self) -> dict:
        try:
            # 0x40BF .. 0x4176 exclusive => 184 registers
            register_list = await self.read_holding_registers(self._unit, 0x40BF, 184)
            position = 0
            data = {}

            # --- PV ---
            value, position = self.decode_32bit_uint(register_list, position)
            data["dailypvgeneration"] = round(value * 0.01, 2)       # 0x40BF
            value, position = self.decode_32bit_uint(register_list, position)
            data["monthpvgeneration"] = round(value * 0.01, 2)       # 0x40C1
            value, position = self.decode_32bit_uint(register_list, position)
            data["yearpvgeneration"] = round(value * 0.01, 2)        # 0x40C3
            value, position = self.decode_32bit_uint(register_list, position)
            data["totalpvgeneration"] = round(value * 0.01, 2)       # 0x40C5

            # --- Battery charge ---
            value, position = self.decode_32bit_uint(register_list, position)
            data["dailychargebattery"] = round(value * 0.01, 2)      # 0x40C7
            value, position = self.decode_32bit_uint(register_list, position)
            data["monthchargebattery"] = round(value * 0.01, 2)      # 0x40C9
            value, position = self.decode_32bit_uint(register_list, position)
            data["yearchargebattery"] = round(value * 0.01, 2)       # 0x40CB
            value, position = self.decode_32bit_uint(register_list, position)
            data["totalchargebattery"] = round(value * 0.01, 2)      # 0x40CD

            # --- Battery discharge ---
            value, position = self.decode_32bit_uint(register_list, position)
            data["dailydischargebattery"] = round(value * 0.01, 2)   # 0x40CF
            value, position = self.decode_32bit_uint(register_list, position)
            data["monthdischargebattery"] = round(value * 0.01, 2)   # 0x40D1
            value, position = self.decode_32bit_uint(register_list, position)
            data["yeardischargebattery"] = round(value * 0.01, 2)    # 0x40D3
            value, position = self.decode_32bit_uint(register_list, position)
            data["totaldischargebattery"] = round(value * 0.01, 2)   # 0x40D5

            # Direktsprung auf 0x4167
            target_offset = 0x4167 - 0x40BF  # 168 Register
            if position < target_offset:
                position = target_offset

            # --- Sum FeedIn = Netzbezug / Import ---
            value, position = self.decode_32bit_uint(register_list, position)
            data["dailygridimportenergy"] = round(value * 0.01, 2)   # 0x4167
            value, position = self.decode_32bit_uint(register_list, position)
            data["monthgridimportenergy"] = round(value * 0.01, 2)   # 0x4169
            value, position = self.decode_32bit_uint(register_list, position)
            data["yeargridimportenergy"] = round(value * 0.01, 2)    # 0x416B
            value, position = self.decode_32bit_uint(register_list, position)
            data["totalgridimportenergy"] = round(value * 0.01, 2)   # 0x416D

            # --- Sum Sell = Netzeinspeisung / Export ---
            value, position = self.decode_32bit_uint(register_list, position)
            data["dailygridexportenergy"] = round(value * 0.01, 2)   # 0x416F
            value, position = self.decode_32bit_uint(register_list, position)
            data["monthgridexportenergy"] = round(value * 0.01, 2)   # 0x4171
            value, position = self.decode_32bit_uint(register_list, position)
            data["yeargridexportenergy"] = round(value * 0.01, 2)    # 0x4173
            value, position = self.decode_32bit_uint(register_list, position)
            data["totalgridexportenergy"] = round(value * 0.01, 2)   # 0x4175

            return data

        except Exception as e:
            _LOGGER.error("Error reading inverter data: %s", e)
            return {}

    async def read_modbus_grid_ac_data(self) -> dict:
        """
        Reads AC grid data.

        Register block: 0x4031 .. 0x403F (15 registers)
        - 0x4031: RGridVolt, scale 0.1 V
        - 0x4033: RGridFreq, scale 0.01 Hz
        - 0x4038: SGridVolt, scale 0.1 V
        - 0x403F: TGridVolt, scale 0.1 V
        """
        try:
            register_list = await self.read_holding_registers(self._unit, 0x4031, 15)

            data = {}

            r_v_raw = register_list[0]
            r_f_raw = register_list[2]
            s_v_raw = register_list[7]
            t_v_raw = register_list[14]

            data["grid_voltage_l1"] = round(r_v_raw * 0.1, 1)
            data["grid_voltage_l2"] = round(s_v_raw * 0.1, 1)
            data["grid_voltage_l3"] = round(t_v_raw * 0.1, 1)
            data["grid_frequency"] = round(r_f_raw * 0.01, 2)

            return data

        except Exception as e:
            _LOGGER.error("Error reading AC grid data: %s", e)
            return {}
