# Wire protocol v2 — ESP32 <-> bridge (BLE and USB)

Source of truth. `firmware/include/protocol.h` and
`bridge/src/wefit_bridge/protocol.py` must match this file. Any layout change bumps
`PROTOCOL_VERSION`; the bridge refuses to use a controller reporting another version.

The board sends sensor data only. Gestures, key state and reset live in the bridge.
The bridge sends one thing: which fusion mode to run.

v2 (2026-10-11) added the status packet, the mode command and `flags` bit 0. The
sample layout did not change.

## GATT layout

| Item | Value |
| --- | --- |
| Advertised name | `WeFit` |
| Service | `7e3f0001-6b1c-4f6a-9d2e-5a1c0f3b9a10` |
| Sample characteristic (notify) | `7e3f0002-6b1c-4f6a-9d2e-5a1c0f3b9a10` |
| Info characteristic (read) | `7e3f0003-6b1c-4f6a-9d2e-5a1c0f3b9a10` |
| Status characteristic (notify) | `7e3f0004-6b1c-4f6a-9d2e-5a1c0f3b9a10` |
| Command characteristic (write) | `7e3f0005-6b1c-4f6a-9d2e-5a1c0f3b9a10` |

No pairing, bonding or encryption. All multi-byte fields are little-endian; structs
are packed.

## Sample (20 bytes, notified at 50 Hz while a host is connected)

| Offset | Size | Type | Field | Notes |
| --- | --- | --- | --- | --- |
| 0 | 2 | u16 | seq | increments per sample, wraps |
| 2 | 2 | u16 | t_ms | device `millis()` taken just before the sensor read, truncated, wraps every ~65 s |
| 4 | 6 | i16[3] | accel | linear acceleration x, y, z; value = raw / 100 m/s² |
| 10 | 8 | i16[4] | quat | orientation w, x, y, z; value = raw / 16384 |
| 18 | 1 | u8 | calib | BNO055 calibration: sys<<6, gyro<<4, accel<<2, mag |
| 19 | 1 | u8 | flags | bit 0 = 1 in NDOF mode; other bits 0 |

Python: `struct.Struct("<HH3h4hBB")`

The scale factors are the BNO055's native units, so nothing is lost in transit.
Acceleration has gravity removed and is expressed in the sensor frame.

## Info (5 bytes, read once after connecting)

| Offset | Size | Type | Field |
| --- | --- | --- | --- |
| 0 | 1 | u8 | protocol_version (`2`) |
| 1 | 2 | u16 | fw_version |
| 3 | 2 | u16 | sample_rate_hz |

Python: `struct.Struct("<BHH")`

## Status (11 bytes, notified at 5 Hz: once per 10 samples)

| Offset | Size | Type | Field | Notes |
| --- | --- | --- | --- | --- |
| 0 | 4 | u32 | uptime_ms | device `millis()`, not truncated |
| 4 | 6 | i16[3] | mag | magnetic field x, y, z; value = raw / 16 µT. Zeros in IMU mode, where the magnetometer is off |
| 10 | 1 | u8 | mode | fusion mode, below |

Python: `struct.Struct("<I3hB")`

## Fusion mode and the command

| Mode | Value (the BNO055's `OPR_MODE`) |
| --- | --- |
| IMU (accelerometer + gyroscope) | `0x08` |
| NDOF (plus magnetometer) | `0x0C` |

- The board boots in IMU mode.
- BLE: the bridge writes one byte, the mode, to the command characteristic on every
  connect. A BLE connect does not reboot the board, so the mode from the last session
  would otherwise persist.
- USB: the bridge sends the line `M,<mode>` (decimal, e.g. `M,12`). The board ignores
  input while it boots, so the bridge sends it once samples flow and repeats it every
  0.5 s until a status line shows that mode.
- Any other value is ignored. The switch goes through the chip's config mode and stalls
  sampling for about 60 ms.
- The bridge confirms the mode from `status.mode`, on both transports.

## USB serial (115200 baud, 8N1)

The firmware prints every sample as one text line on its USB serial port, whether or
not a BLE host is connected (`SERIAL_STREAM` in `firmware/include/config.h`):

```
S,<seq>,<t_ms>,<ax>,<ay>,<az>,<qw>,<qx>,<qy>,<qz>,<calib>
```

- Fields are the same raw integers as the BLE sample, in the same order and scale.
  `flags` is omitted.
- A status packet is the line `T,<uptime_ms>,<mx>,<my>,<mz>,<mode>`, raw integers as
  in the BLE packet.
- Other lines are firmware log messages; the bridge ignores them.
  A log line can occasionally interleave with a sample line; the damaged line fails
  to parse and is dropped.
- There is no version field on this path. A layout change shows up as lines that
  fail to parse. Firmware older than v2 sends no `T,` lines: the bridge then assumes
  IMU mode with a warning, and refuses to start in NDOF mode.
- Opening the port toggles DTR/RTS and resets most ESP32 dev boards. Expect about
  3-5 s before the first sample.

Python: `parse_sample_line()`, `parse_status_line()` and `command_line()` in `protocol.py`.

## Rules

- 20 bytes is the largest payload that fits the default ATT MTU of 23. Keep the
  sample at or under that unless MTU negotiation is added on both sides.
- The bridge drops any notification that is not exactly 20 bytes.
- The bridge stamps each sample on arrival with its own clock (`clock.now`, in
  `Sample.rx`). `seq` and `t_ms` feed the latency log (loss, jitter, delay; see
  `latency-tracking.md`) and are not used by gesture detection.
- Nothing sets the ESP32's clock. The bridge fits the device-to-host clock mapping from
  the samples, so no time sync message exists on either transport.
- The firmware sends no BLE notifications when no host is connected and restarts
  advertising on disconnect. The bridge rescans and reconnects on its own.
