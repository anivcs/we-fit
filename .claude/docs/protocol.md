# Wire protocol v1 — ESP32 <-> bridge

Source of truth. `firmware/lib/protocol/protocol.h` and
`bridge/src/wefit_bridge/protocol.py` must match this file. Any layout change bumps
`version`; the bridge drops packets with an unknown version.

- Transport: UDP, bridge listens on port **4210**.
- Byte order: little-endian. Structs are packed (`__attribute__((packed))` on the
  ESP32, `<` prefix in Python `struct`).
- One message per datagram. No fragmentation, no retransmission.

## Common header (10 bytes)

| Offset | Size | Type | Field | Notes |
| --- | --- | --- | --- | --- |
| 0 | 2 | char[2] | magic | ASCII `WF` |
| 2 | 1 | u8 | version | `1` |
| 3 | 1 | u8 | msg_type | see below |
| 4 | 6 | u8[6] | device_id | ESP32 station MAC |

Python: `HEADER = struct.Struct("<2sBB6s")`

| msg_type | Name | Direction | Total size |
| --- | --- | --- | --- |
| 1 | HELLO | device -> broadcast | 14 |
| 2 | ACK | bridge -> device | 10 |
| 3 | SAMPLE | device -> bridge | 60 |

## HELLO (14 bytes)

Sent to the subnet broadcast address once per second while the device has no bridge.

| Offset | Size | Type | Field |
| --- | --- | --- | --- |
| 10 | 2 | u16 | fw_version |
| 12 | 2 | u16 | sample_rate_hz |

Python: `struct.Struct("<2sBB6sHH")`

## ACK (10 bytes)

Header only; `device_id` echoes the device being addressed. Sent in reply to `HELLO`
and then once per second as a heartbeat. The device takes the bridge address from the
datagram source, and returns to `HELLO` after 3 s without an `ACK`.

## SAMPLE (60 bytes)

| Offset | Size | Type | Field | Units / notes |
| --- | --- | --- | --- | --- |
| 10 | 4 | u32 | seq | increments per sample, wraps |
| 14 | 4 | u32 | t_ms | device `millis()` at sample time |
| 18 | 16 | f32[4] | quat | w, x, y, z — unit quaternion |
| 34 | 12 | f32[3] | lin_accel | x, y, z in m/s², gravity removed |
| 46 | 12 | f32[3] | gyro | x, y, z in rad/s |
| 58 | 1 | u8 | calib | BNO055 calibration: sys<<6, gyro<<4, accel<<2, mag |
| 59 | 1 | u8 | flags | bit 0 = button pressed (reserved, 0 for now) |

Python: `struct.Struct("<2sBB6sII10fBB")` — size 60.

## Scope note

This protocol carries sensor data only. Gesture detection, arrow-key state, and drift
reset all live in the bridge, so none of them changed the wire format. Version stays
`1`. Discovery uses broadcast, or is skipped when the firmware has a configured
`BRIDGE_HOST`; in that case the device sends `HELLO` unicast to that address.

## Rules

- Bridge ignores datagrams whose length does not match the msg_type, or whose magic
  or version is wrong.
- Bridge identifies a controller by `device_id` only. Source IP and port can change.
- `seq` going backwards by a small amount means a reordered packet: drop it.
  `seq` dropping to near zero means the device rebooted: reset that controller's state.
- Default sample rate is 50 Hz (matches the prototype loop). The BNO055 fusion output
  tops out at 100 Hz.
