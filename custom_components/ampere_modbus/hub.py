"""Ampere Modbus Hub."""

import asyncio
import inspect
import logging
from datetime import timedelta
from typing import Any, Callable, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.client.mixin import ModbusClientMixin
from pymodbus.exceptions import ConnectionException, ModbusIOException
from voluptuous.validators import Number

from .const import (
    BATTERY_DIRECTION,
    DEVICE_STATUSSES,
    FAULT_MESSAGES,
    GRID_DIRECTION,
    PV_DIRECTION,
)

_LOGGER = logging.getLogger(__name__)


class AmpereStorageProModbusHub(DataUpdateCoordinator[dict]):
    """Modbus hub for Ampere / SAJ storage systems.

    Hardening measures implemented:
    - one Modbus transaction at a time
    - conservative chunk size
    - pacing between Modbus requests
    - hard reconnect after I/O errors, timeouts and cancelled transactions
    - partial update cycle: a failed optional block no longer invalidates all data
    - cached last-good values are kept during temporary communication faults
    - clean shutdown support through async_shutdown()/close()
    """

    # SAJ Modbus TCP tends to be more stable with smaller reads than the
    # Modbus theoretical 125-register maximum. 30 keeps payloads small enough
    # to avoid observed transaction mixups on weak TCP/RS485 bridges or busy WRs.
    MAX_REGISTERS_PER_READ = 30

    # Battery / BMS peripheral data.
    # 0xA000..0xA011 contains battery count, capacity, online mask and
    # SOC/SOH/voltage/current/temperature/cycles for the reported battery stack.
    BATTERY_DATA_START_REGISTER = 0xA000
    BATTERY_DATA_REGISTER_COUNT = 0x0012

    # Short delay between requests. Important when KiwiGrid/other clients also
    # access the inverter and when the inverter's Modbus TCP stack is slow.
    READ_PACING_SECONDS = 0.20

    CONNECT_TIMEOUT_SECONDS = 10.0
    READ_TIMEOUT_SECONDS = 15.0
    UPDATE_TIMEOUT_SECONDS = 90.0
    CLOSE_TIMEOUT_SECONDS = 5.0

    INITIAL_FAILURE_COOLDOWN_SECONDS = 120
    MAX_FAILURE_COOLDOWN_SECONDS = 300

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
        self._stopping = False

        # One lock for the connection lifecycle and one for the actual Modbus
        # transaction stream. Do not use threading.Lock in async code.
        self._connection_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()

        self._inverter_data: dict = {}
        self.data: dict = {}
        self._suspend_until: float = 0.0
        self._failure_count: int = 0
        self._last_good_grid_ac_data: dict = {}

    def _create_client(self) -> AsyncModbusTcpClient:
        """Create a new Modbus TCP client instance.

        Pymodbus signatures changed between versions. The optional reconnect
        parameters are therefore set only when supported.
        """
        kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "timeout": self.CONNECT_TIMEOUT_SECONDS,
        }

        try:
            sig = inspect.signature(AsyncModbusTcpClient.__init__)
            if "reconnect_delay" in sig.parameters:
                kwargs["reconnect_delay"] = 0
            if "reconnect_delay_max" in sig.parameters:
                kwargs["reconnect_delay_max"] = 0
        except Exception as e:
            _LOGGER.debug("Could not inspect AsyncModbusTcpClient signature: %s", e)

        client = AsyncModbusTcpClient(**kwargs)
        _LOGGER.debug(
            "Created new Modbus client for %s:%s with kwargs=%s",
            self._host,
            self._port,
            kwargs,
        )
        return client

    async def _safe_close(self) -> bool:
        """Safely close and discard the current Modbus client."""
        client = self._client
        self._client = None

        if not client:
            return True

        try:
            close = getattr(client, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result

            transport = getattr(client, "transport", None)
            if transport:
                transport.close()

            await asyncio.sleep(0.20)
            return not getattr(client, "connected", False)

        except Exception as e:
            _LOGGER.warning("Error during safe Modbus close: %s", e, exc_info=True)
            return False

    async def close(self) -> None:
        """Close the Modbus connection with bounded runtime."""
        if self._closing:
            return

        self._closing = True
        try:
            async with asyncio.timeout(self.CLOSE_TIMEOUT_SECONDS):
                async with self._connection_lock:
                    await self._safe_close()
        except (asyncio.TimeoutError, Exception) as e:
            _LOGGER.warning("Error during Modbus close: %s", e, exc_info=True)
        finally:
            self._closing = False

    async def async_shutdown(self) -> None:
        """Signal shutdown and close the Modbus client.

        Call this from the integration's async_unload_entry if available.
        """
        self._stopping = True
        await self.close()

    def _is_stopping(self) -> bool:
        """Return whether Home Assistant or this hub is stopping."""
        return self._stopping or getattr(self.hass, "is_stopping", False)

    async def ensure_modbus_connection(self) -> None:
        """Ensure that the Modbus TCP connection is established."""
        if self._is_stopping():
            raise ConnectionException(
                "Home Assistant is stopping; Modbus connection skipped."
            )

        async with self._connection_lock:
            if self._client and self._client.connected:
                return

            await self._safe_close()
            self._client = self._create_client()

            try:
                await asyncio.wait_for(
                    self._client.connect(), timeout=self.CONNECT_TIMEOUT_SECONDS
                )
                await asyncio.sleep(0.30)

                if not self._client.connected:
                    raise ConnectionException(
                        "Modbus client did not report connected state."
                    )

                _LOGGER.info(
                    "Successfully connected to Modbus server %s:%s.",
                    self._host,
                    self._port,
                )

            except Exception as e:
                await self._safe_close()
                await asyncio.sleep(0.20)
                _LOGGER.warning(
                    "Error during Modbus connection attempt: %s", e, exc_info=True
                )
                raise ConnectionException("Failed to connect to Modbus server.") from e

    async def _reset_connection_after_error(self) -> None:
        """Close connection after protocol or transport errors."""
        async with self._connection_lock:
            await self._safe_close()

    async def _read_holding_registers_single(
        self,
        unit: int,
        address: int,
        count: int,
        max_retries: int = 1,
        base_delay: float = 0.75,
    ) -> List[int]:
        """Read one Modbus holding-register block.

        Retries are intentionally conservative. A failed transaction closes the
        socket before the next attempt so that stale transaction IDs or buffered
        frames do not contaminate the following read.
        """
        if count <= 0:
            return []

        last_error: Optional[BaseException] = None
        attempts = max(1, max_retries + 1)

        for attempt in range(1, attempts + 1):
            if self._is_stopping():
                raise ConnectionException("Home Assistant is stopping; read cancelled.")

            try:
                await self.ensure_modbus_connection()

                async with self._read_lock:
                    if not self._client or not self._client.connected:
                        raise ConnectionException(
                            "Modbus client is not connected before read."
                        )

                    async with asyncio.timeout(self.READ_TIMEOUT_SECONDS):
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

                await asyncio.sleep(self.READ_PACING_SECONDS)
                return response.registers

            except (
                ModbusIOException,
                ConnectionException,
                AttributeError,
                asyncio.TimeoutError,
                asyncio.CancelledError,
            ) as e:
                last_error = e
                _LOGGER.warning(
                    "Modbus read attempt %s/%s failed at address %s (count %s): %s [%s]",
                    attempt,
                    attempts,
                    hex(address),
                    count,
                    e,
                    type(e).__name__,
                )
                await self._reset_connection_after_error()

                if attempt < attempts and not self._is_stopping():
                    await asyncio.sleep(base_delay * attempt)
                    continue

                break

        raise ConnectionException(
            f"Read operation failed for address {hex(address)}, count {count}"
        ) from last_error

    async def read_holding_registers(
        self,
        unit: int,
        address: int,
        count: int,
        max_retries: int = 1,
        base_delay: float = 0.75,
    ) -> List[int]:
        """Read Modbus holding registers with conservative chunking."""
        if count <= 0:
            return []

        all_registers: List[int] = []
        offset = 0

        while offset < count:
            chunk_address = address + offset
            chunk_count = min(self.MAX_REGISTERS_PER_READ, count - offset)

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

    async def _run_read_block(
        self,
        block_name: str,
        read_func: Callable[[], Any],
        target: dict,
        required: bool = False,
    ) -> bool:
        """Run one read block and merge its data.

        Optional blocks are allowed to fail. Existing/cached values are kept so
        that one bad register block does not invalidate the full Home Assistant
        update cycle.
        """
        try:
            result = await read_func()
            if result:
                target.update(result)
            return True
        except Exception as e:
            log = _LOGGER.error if required else _LOGGER.warning
            log(
                "Modbus read block '%s' failed%s: %s",
                block_name,
                " (required)" if required else "",
                e,
                exc_info=True,
            )
            return False

    async def _async_update_data(self) -> dict:
        """Fetch data for Home Assistant's DataUpdateCoordinator."""
        if self._is_stopping():
            if self.data:
                return dict(self.data)
            raise ConnectionException("Home Assistant is stopping; update skipped.")

        loop_time = asyncio.get_running_loop().time()

        if loop_time < self._suspend_until:
            remaining = self._suspend_until - loop_time
            _LOGGER.debug(
                "Modbus polling suspended for %.1f more seconds after previous failure.",
                remaining,
            )

            await self.close()

            if self.data:
                return dict(self.data)

            raise ConnectionException("Modbus polling temporarily suspended")

        try:
            async with asyncio.timeout(self.UPDATE_TIMEOUT_SECONDS):
                await self.ensure_modbus_connection()

                all_read_data = dict(self.data) if self.data else {}

                if not self._inverter_data:
                    inverter_data: dict = {}
                    inverter_ok = await self._run_read_block(
                        "inverter_data",
                        self.read_modbus_inverter_data,
                        inverter_data,
                        required=False,
                    )
                    if inverter_ok and inverter_data:
                        self._inverter_data = inverter_data

                all_read_data.update(self._inverter_data)

                ok_count = 0
                ok_count += int(
                    await self._run_read_block(
                        "device_data",
                        self.read_modbus_device_data,
                        all_read_data,
                    )
                )
                ok_count += int(
                    await self._run_read_block(
                        "realtime_data",
                        self.read_modbus_realtime_data,
                        all_read_data,
                    )
                )
                ok_count += int(
                    await self._run_read_block(
                        "grid_ac_data",
                        self.read_modbus_grid_ac_data,
                        all_read_data,
                    )
                )
                ok_count += int(
                    await self._run_read_block(
                        "longterm_data",
                        self.read_modbus_longterm_data,
                        all_read_data,
                    )
                )
                ok_count += int(
                    await self._run_read_block(
                        "battery_health_data",
                        self.read_modbus_battery_health_data,
                        all_read_data,
                    )
                )

                if ok_count == 0 and not all_read_data:
                    raise ConnectionException(
                        "All Modbus read blocks failed and no cached data exists."
                    )

                if ok_count == 0:
                    self._failure_count += 1
                    cooldown = min(
                        self.INITIAL_FAILURE_COOLDOWN_SECONDS * self._failure_count,
                        self.MAX_FAILURE_COOLDOWN_SECONDS,
                    )
                    self._suspend_until = asyncio.get_running_loop().time() + cooldown
                    _LOGGER.warning(
                        "All volatile Modbus read blocks failed. Keeping cached data and "
                        "suspending polling for %s seconds after %s consecutive failure(s).",
                        cooldown,
                        self._failure_count,
                    )
                else:
                    self._failure_count = 0
                    self._suspend_until = 0.0

                self.data = all_read_data
                return dict(all_read_data)

        except asyncio.TimeoutError as e:
            self._failure_count += 1
            cooldown = min(
                self.INITIAL_FAILURE_COOLDOWN_SECONDS * self._failure_count,
                self.MAX_FAILURE_COOLDOWN_SECONDS,
            )
            self._suspend_until = asyncio.get_running_loop().time() + cooldown

            _LOGGER.error(
                "Timed out during Modbus update cycle. Suspending polling for %s seconds "
                "after %s consecutive failure(s): %s",
                cooldown,
                self._failure_count,
                e,
                exc_info=True,
            )
            await self._reset_connection_after_error()

            if self.data:
                return dict(self.data)

            raise

        except Exception as e:
            self._failure_count += 1
            cooldown = min(
                self.INITIAL_FAILURE_COOLDOWN_SECONDS * self._failure_count,
                self.MAX_FAILURE_COOLDOWN_SECONDS,
            )
            self._suspend_until = asyncio.get_running_loop().time() + cooldown

            _LOGGER.error(
                "Modbus update cycle failed. Suspending polling for %s seconds after %s "
                "consecutive failure(s): %s",
                cooldown,
                self._failure_count,
                e,
                exc_info=True,
            )
            await self._reset_connection_after_error()

            if self.data:
                return dict(self.data)

            raise

        finally:
            # Keep the original short-lived connection behavior. This avoids long
            # stale sockets in the SAJ/KiwiGrid coexistence scenario. The cost is
            # one reconnect per coordinator update.
            await self.close()

    def _convert_from_registers(self, registers: List[int], datatype: Any) -> Any:
        """Convert registers without relying on an active TCP connection."""
        client = self._client or self._create_client()
        return client.convert_from_registers(registers, datatype)

    def decode_16bit_uint(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._convert_from_registers(
                [register[position]], ModbusClientMixin.DATATYPE.UINT16
            )
        except Exception as e:
            _LOGGER.error("Error decode_16bit_uint at position %s: %s", position, e)

        position += 1
        return value, position

    def decode_16bit_int(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._convert_from_registers(
                [register[position]], ModbusClientMixin.DATATYPE.INT16
            )
        except Exception as e:
            _LOGGER.error("Error decode_16bit_int at position %s: %s", position, e)

        position += 1
        return value, position

    def decode_32bit_uint(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._convert_from_registers(
                [register[position], register[position + 1]],
                ModbusClientMixin.DATATYPE.UINT32,
            )
        except Exception as e:
            _LOGGER.error("Error decode_32bit_uint at position %s: %s", position, e)

        position += 2
        return value, position

    def decode_32bit_int(self, register: List[int], position: int) -> tuple[Any, int]:
        value: Any = 0
        try:
            value = self._convert_from_registers(
                [register[position], register[position + 1]],
                ModbusClientMixin.DATATYPE.INT32,
            )
        except Exception as e:
            _LOGGER.error("Error decode_32bit_int at position %s: %s", position, e)

        position += 2
        return value, position

    def decode_string(
        self, length: int, register: List[int], position: int
    ) -> tuple[str, int]:
        register_of_string: List[int] = []
        for i in range(length):
            register_of_string.append(register[position + i])

        try:
            value = self._convert_from_registers(
                register_of_string, ModbusClientMixin.DATATYPE.STRING
            )
        except Exception as e:
            _LOGGER.error("Error decode_string at position %s: %s", position, e)
            value = ""

        position += length
        return str(value), position

    @staticmethod
    def _is_invalid_register_value(value: Any) -> bool:
        """Return whether a raw register value should be treated as unavailable."""
        return value is None or value in (0xFFFF, 0x7FFF)

    @staticmethod
    def _scale_value(value: Any, factor: float, digits: int) -> Optional[float]:
        """Scale a raw numeric value and return None for invalid values."""
        if AmpereStorageProModbusHub._is_invalid_register_value(value):
            return None

        try:
            return round(float(value) * factor, digits)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _register_value_at(
        register_list: List[int],
        start_address: int,
        address: int,
    ) -> Optional[int]:
        """Return a raw register value by absolute Modbus address."""
        index = address - start_address

        if index < 0 or index >= len(register_list):
            return None

        return register_list[index]

    def _decode_uint16_at(
        self,
        register_list: List[int],
        start_address: int,
        address: int,
    ) -> Optional[int]:
        """Decode one UInt16 register by absolute Modbus address."""
        raw = self._register_value_at(register_list, start_address, address)

        if self._is_invalid_register_value(raw):
            return None

        try:
            value = self._convert_from_registers(
                [raw], ModbusClientMixin.DATATYPE.UINT16
            )
            return int(value)
        except Exception as e:
            _LOGGER.error("Error decoding UInt16 at address %s: %s", hex(address), e)
            return None

    def _decode_int16_at(
        self,
        register_list: List[int],
        start_address: int,
        address: int,
    ) -> Optional[int]:
        """Decode one Int16 register by absolute Modbus address."""
        raw = self._register_value_at(register_list, start_address, address)

        if self._is_invalid_register_value(raw):
            return None

        try:
            value = self._convert_from_registers(
                [raw], ModbusClientMixin.DATATYPE.INT16
            )
            return int(value)
        except Exception as e:
            _LOGGER.error("Error decoding Int16 at address %s: %s", hex(address), e)
            return None

    async def read_modbus_battery_health_data(self) -> dict:
        """Read battery / BMS health data from peripheral device register block.

        Register range:
        - 0xA000: battery module / stack count
        - 0xA001: battery capacity [Ah]
        - 0xA00A: available battery capacity
        - 0xA00B: battery online mask
        - 0xA00C..0xA011: SOC, SOH, voltage, current, temperature, cycles
          for the reported battery stack.
        """
        start_address = self.BATTERY_DATA_START_REGISTER

        register_list = await self.read_holding_registers(
            self._unit,
            start_address,
            self.BATTERY_DATA_REGISTER_COUNT,
        )

        data: dict = {}

        battery_module_count = self._decode_uint16_at(
            register_list, start_address, 0xA000
        )
        battery_capacity_ah = self._decode_uint16_at(
            register_list, start_address, 0xA001
        )
        battery_available_capacity = self._decode_uint16_at(
            register_list, start_address, 0xA00A
        )
        battery_online_mask = self._decode_uint16_at(
            register_list, start_address, 0xA00B
        )

        data["battery_module_count"] = battery_module_count
        data["battery_capacity_ah"] = battery_capacity_ah
        data["battery_available_capacity"] = battery_available_capacity
        data["battery_online_mask"] = battery_online_mask

        soc_raw = self._decode_uint16_at(register_list, start_address, 0xA00C)
        soh_raw = self._decode_uint16_at(register_list, start_address, 0xA00D)
        voltage_raw = self._decode_uint16_at(register_list, start_address, 0xA00E)
        current_raw = self._decode_int16_at(register_list, start_address, 0xA00F)
        temperature_raw = self._decode_int16_at(register_list, start_address, 0xA010)
        cycles_raw = self._decode_uint16_at(register_list, start_address, 0xA011)

        data["battery_1_soc"] = self._scale_value(soc_raw, 0.01, 2)
        data["battery_1_soh"] = self._scale_value(soh_raw, 0.01, 2)
        data["battery_1_voltage"] = self._scale_value(voltage_raw, 0.1, 1)
        data["battery_1_current"] = self._scale_value(current_raw, 0.01, 2)
        data["battery_1_temperature"] = self._scale_value(temperature_raw, 0.1, 1)
        data["battery_1_cycles"] = cycles_raw

        return data

    async def read_modbus_inverter_data(self) -> dict:
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

    async def read_modbus_device_data(self) -> dict:
        register_list = await self.read_holding_registers(self._unit, 0x4004, 7)
        position = 0
        data = {}

        value, position = self.decode_16bit_uint(register_list, position)
        data["devicestatus_raw"] = value
        data["devicestatus"] = DEVICE_STATUSSES.get(value, "Unknown")
        data["island_mode"] = value == 3
        data["grid_mode"] = value == 4

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

    async def read_modbus_realtime_data(self) -> dict:
        """Read realtime battery, PV and power-flow data.

        The realtime register area contains model-dependent gaps/reserved
        addresses. Reading one large contiguous block from 0x4069 to 0x40A4 can
        fail on some SAJ H2 devices, especially around 0x4087. Therefore this
        method reads two smaller stable blocks:
        - 0x4069..0x4079: battery and PV values
        - 0x4095..0x40A7: flow directions and power values
        """
        data = {}

        # ------------------------------------------------------------------
        # Block 1: Battery and PV values
        # 0x4069..0x4079
        # ------------------------------------------------------------------
        battery_pv_registers = await self.read_holding_registers(
            self._unit,
            0x4069,
            17,
        )

        position = 0

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["batteryvoltage"] = round(value * 0.1, 1)

        value, position = self.decode_16bit_int(battery_pv_registers, position)
        data["batterycurrent"] = round(value * 0.01, 2)

        # 0x406B BatCurr1, 0x406C BatCurr2
        position += 2

        value, position = self.decode_16bit_int(battery_pv_registers, position)
        data["batterypower"] = round(value * 1, 0)

        value, position = self.decode_16bit_int(battery_pv_registers, position)
        data["batterytemperature"] = round(value * 0.1, 0)

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["batterypercent"] = round(value * 0.01, 0)

        # 0x4070 reserved
        position += 1

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv1volt"] = round(value * 0.1, 1)

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv1curr"] = round(value * 0.01, 2)

        pv1power, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv1power"] = round(pv1power * 1, 0)

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv2volt"] = round(value * 0.1, 1)

        value, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv2curr"] = round(value * 0.01, 2)

        pv2power, position = self.decode_16bit_uint(battery_pv_registers, position)
        data["pv2power"] = round(pv2power * 1, 0)

        # Keep existing behavior: total PV power is calculated from PV1 + PV2.
        data["totalpvpower"] = round(pv1power * 1, 0) + round(pv2power * 1, 0)

        # ------------------------------------------------------------------
        # Block 2: Flow directions and CT / total power values
        # 0x4095..0x40A7
        # ------------------------------------------------------------------
        flow_registers = await self.read_holding_registers(
            self._unit,
            0x4095,
            19,
        )

        position = 0

        value, position = self.decode_16bit_int(flow_registers, position)
        data["pvflow"] = value
        data["pvflowtext"] = PV_DIRECTION.get(value, "Unknown")

        value, position = self.decode_16bit_int(flow_registers, position)
        data["batteryflow"] = value
        data["batteryflowtext"] = BATTERY_DIRECTION.get(value, "Unknown")

        value, position = self.decode_16bit_int(flow_registers, position)
        data["gridflow"] = value
        data["gridflowtext"] = GRID_DIRECTION.get(value, "Unknown")

        # 0x4098 Output_direction
        # 0x4099..0x409F reserved / model-dependent
        # 0x40A0 SysTotalLoadWatt
        position += 9

        value, position = self.decode_16bit_int(flow_registers, position)
        data["gridpower"] = value

        return data

    async def read_modbus_longterm_data(self) -> dict:
        register_list = await self.read_holding_registers(self._unit, 0x40BF, 184)
        position = 0
        data = {}

        value, position = self.decode_32bit_uint(register_list, position)
        data["dailypvgeneration"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["monthpvgeneration"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["yearpvgeneration"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["totalpvgeneration"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["dailychargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["monthchargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["yearchargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["totalchargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["dailydischargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["monthdischargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["yeardischargebattery"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["totaldischargebattery"] = round(value * 0.01, 2)

        target_offset = 0x4167 - 0x40BF
        if position < target_offset:
            position = target_offset

        value, position = self.decode_32bit_uint(register_list, position)
        data["dailygridimportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["monthgridimportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["yeargridimportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["totalgridimportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["dailygridexportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["monthgridexportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["yeargridexportenergy"] = round(value * 0.01, 2)

        value, position = self.decode_32bit_uint(register_list, position)
        data["totalgridexportenergy"] = round(value * 0.01, 2)

        return data

    async def read_modbus_grid_ac_data(self) -> dict:
        """Read AC grid data and suppress short invalid zero/implausible readings."""
        try:
            register_list = await self.read_holding_registers(self._unit, 0x4031, 15)

            r_v_raw = register_list[0]
            r_f_raw = register_list[2]
            s_v_raw = register_list[7]
            t_v_raw = register_list[14]

            grid_voltage_l1 = round(r_v_raw * 0.1, 1)
            grid_voltage_l2 = round(s_v_raw * 0.1, 1)
            grid_voltage_l3 = round(t_v_raw * 0.1, 1)
            grid_frequency = round(r_f_raw * 0.01, 2)

            freq_valid = 45.0 <= grid_frequency <= 55.0
            v1_valid = 100.0 <= grid_voltage_l1 <= 300.0
            v2_valid = 100.0 <= grid_voltage_l2 <= 300.0
            v3_valid = 100.0 <= grid_voltage_l3 <= 300.0

            all_zero = (
                grid_frequency == 0.0
                and grid_voltage_l1 == 0.0
                and grid_voltage_l2 == 0.0
                and grid_voltage_l3 == 0.0
            )

            all_valid = freq_valid and v1_valid and v2_valid and v3_valid

            if all_valid:
                data = {
                    "grid_voltage_l1": grid_voltage_l1,
                    "grid_voltage_l2": grid_voltage_l2,
                    "grid_voltage_l3": grid_voltage_l3,
                    "grid_frequency": grid_frequency,
                }
                self._last_good_grid_ac_data = dict(data)
                return data

            if self._last_good_grid_ac_data:
                if all_zero:
                    _LOGGER.warning(
                        "Ignoring temporary zero grid AC reading from inverter. "
                        "Keeping last valid values."
                    )
                else:
                    _LOGGER.warning(
                        "Ignoring implausible grid AC reading: L1=%s V, L2=%s V, "
                        "L3=%s V, f=%s Hz. Keeping last valid values.",
                        grid_voltage_l1,
                        grid_voltage_l2,
                        grid_voltage_l3,
                        grid_frequency,
                    )
                return dict(self._last_good_grid_ac_data)

            _LOGGER.warning(
                "Grid AC reading invalid and no cached valid values available: "
                "L1=%s V, L2=%s V, L3=%s V, f=%s Hz",
                grid_voltage_l1,
                grid_voltage_l2,
                grid_voltage_l3,
                grid_frequency,
            )
            return {}

        except Exception as e:
            _LOGGER.warning("Error reading AC grid data: %s", e, exc_info=True)
            if self._last_good_grid_ac_data:
                return dict(self._last_good_grid_ac_data)
            raise
