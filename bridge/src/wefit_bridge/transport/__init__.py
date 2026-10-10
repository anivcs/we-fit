"""Sources of Sample objects. A transport exposes `samples()`, an async iterator."""

from ..config import TRANSPORTS, Config


def make_transport(config: Config):
    if config.transport == "usb":
        from .usb import UsbTransport

        return UsbTransport(port=config.usb_port)
    if config.transport == "ble":
        from .ble import BleTransport

        return BleTransport(name=config.device_name, address=config.device_address)
    if config.transport == "fake":
        from .fake import FakeTransport

        return FakeTransport()
    raise ValueError(f"unknown transport: {config.transport!r} (expected one of {TRANSPORTS})")
