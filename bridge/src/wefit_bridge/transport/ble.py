"""BLE transport: finds the controller, subscribes to samples, reconnects on loss."""

import asyncio
import logging
from collections.abc import AsyncIterator

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from ..protocol import (
    DEVICE_NAME,
    INFO_CHAR_UUID,
    PROTOCOL_VERSION,
    SAMPLE_CHAR_UUID,
    Sample,
    decode_info,
    decode_sample,
)

log = logging.getLogger(__name__)


class BleTransport:
    def __init__(
        self,
        name: str = DEVICE_NAME,
        address: str | None = None,
        scan_timeout_s: float = 10.0,
        retry_delay_s: float = 1.0,
    ):
        self.name = name
        self.address = address
        self.scan_timeout_s = scan_timeout_s
        self.retry_delay_s = retry_delay_s

    async def samples(self) -> AsyncIterator[Sample]:
        while True:
            device = await self._find()
            if device is None:
                log.warning("controller %r not found, scanning again", self.address or self.name)
                continue

            queue: asyncio.Queue[Sample] = asyncio.Queue(maxsize=256)
            disconnected = asyncio.Event()

            def on_notify(_char, data: bytearray) -> None:
                try:
                    queue.put_nowait(decode_sample(bytes(data)))
                except ValueError as e:
                    log.debug("bad sample dropped: %s", e)
                except asyncio.QueueFull:
                    pass  # consumer is behind; newer samples matter more than old ones

            try:
                async with BleakClient(
                    device, disconnected_callback=lambda _client: disconnected.set()
                ) as client:
                    await self._check_version(client)
                    await client.start_notify(SAMPLE_CHAR_UUID, on_notify)
                    log.info("controller connected: %s", device.address)

                    while not disconnected.is_set():
                        try:
                            yield await asyncio.wait_for(queue.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
            except (BleakError, OSError, asyncio.TimeoutError) as e:
                log.warning("BLE error: %s", e)

            log.warning("controller disconnected, reconnecting")
            await asyncio.sleep(self.retry_delay_s)

    async def _find(self):
        if self.address:
            return await BleakScanner.find_device_by_address(
                self.address, timeout=self.scan_timeout_s
            )
        return await BleakScanner.find_device_by_name(self.name, timeout=self.scan_timeout_s)

    async def _check_version(self, client: BleakClient) -> None:
        info = decode_info(bytes(await client.read_gatt_char(INFO_CHAR_UUID)))
        if info.protocol_version != PROTOCOL_VERSION:
            raise BleakError(
                f"protocol version mismatch: firmware {info.protocol_version}, "
                f"bridge {PROTOCOL_VERSION}"
            )
        log.info("firmware v%d, %d Hz", info.fw_version, info.sample_rate_hz)
