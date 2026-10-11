"""Sources of Sample objects. A transport exposes `samples()`, an async iterator."""

from ..config import TRANSPORTS, Config
from ..protocol import MODES


def make_transport(config: Config):
    """Call after build_pipeline(), which settles config.fusion_mode."""
    mode = MODES[config.fusion_mode or "imu"]
    if config.transport == "usb":
        from .usb import UsbTransport

        return UsbTransport(port=config.usb_port, mode=mode)
    if config.transport == "ble":
        from .ble import BleTransport

        return BleTransport(name=config.device_name, address=config.device_address, mode=mode)
    if config.transport == "fake":
        from .fake import FakeTransport

        return FakeTransport(mode=mode, reference_at_s=4.0 if config.gravity else None)
    raise ValueError(f"unknown transport: {config.transport!r} (expected one of {TRANSPORTS})")
