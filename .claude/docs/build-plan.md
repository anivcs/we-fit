# Build plan

Each milestone is independently demoable. M1 needs no hardware, so firmware and
bridge work can proceed in parallel after it.

## M0 — Scaffold

- `pip install platformio` into `.venv`.
- Create `firmware/` with `platformio.ini` (`board = esp32dev`, `framework = arduino`,
  `monitor_speed = 115200`, `lib_deps = adafruit/Adafruit BNO055`,
  `adafruit/Adafruit Unified Sensor`).
- Port the `.ino` to `firmware/src/main.cpp` unchanged in behaviour; move the original
  to `legacy/`.
- Extend `.gitignore`: `.pio/`, `firmware/include/secrets.h`, `__pycache__/`,
  `*.egg-info/`, `bridge/config.toml`.
- Done when: `pio run -d firmware` builds and the board prints the same serial output
  as the prototype.

## M1 — Protocol, bridge skeleton, fake controller

- `bridge/` package: `protocol.py`, `transport.py`, `registry.py`, console publisher.
- `tools/fake_controller.py --count N` sending HELLO then SAMPLE at 50 Hz.
- Tests: pack/unpack round-trip, wrong magic/version/length rejected.
- Done when: bridge prints samples from 4 fake controllers with distinct player numbers.

## M2 — Firmware networking

- `lib/net`: Wi-Fi connect with background reconnect, HELLO/ACK discovery, UDP send.
- `lib/protocol/protocol.h`: packed structs with `static_assert` on sizes (10/14/60).
- `lib/imu`: read quaternion, linear accel, gyro, calibration status.
- Loop scheduled with `millis()`; no `delay()` in the steady state.
- Done when: one real controller shows up in the bridge and survives the bridge
  being restarted and the Wi-Fi being dropped.

## M3 — Multiple controllers

- Player map in `config.toml`, join-order fallback, disconnect timeout, status events.
- Loss/reorder counters per device, printed periodically.
- Done when: 2+ real controllers run together, one can be power-cycled and returns
  to the same player number.

## M4 — Gestures and arrow keys in the bridge

- Port the prototype's thresholds and cooldown to `gestures.py`, per controller.
- Add `down` as the mirror of `up` (negative Z); tune its threshold on hardware.
- `keys.py`: press on gesture, auto-release after `key_hold_ms`, one key at a time,
  release-before-press on overlap, forced release on disconnect.
- `control.py`: `reset` command (per player or all) that re-zeros the reference
  quaternion, clears detectors and releases keys.
- Record raw samples to a file for replay-based tests and threshold tuning.
- Tests: no two keys ever down at once (property test over random gesture streams),
  no stuck key after disconnect or reset, reset mid-hold releases the key.
- Done when: `up/down/left/right` key events match the intended motions on a real
  controller, and a reset between rounds leaves no stale state.

## M5 — Real publisher

- Blocked on the game server interface. Implement one `Publisher` subclass for it.
- Done when: the game reacts to a physical controller.

## Open questions

| # | Question | Default assumed | Who decides |
| --- | --- | --- | --- |
| 1 | How does the game server want data: transport and schema? | Console JSON lines for now | Game/backend team |
| 2 | ~~Raw samples, gestures, or both?~~ Decided: boolean arrow keys only; raw samples are debug-only | Resolved | Us |
| 3 | ~~Demo network~~ Decided: phone mobile-data Wi-Fi hotspot, 2.4 GHz. Check client cap and broadcast behaviour on the actual phone | Resolved, needs a hardware check | Us |
| 9 | How does the game trigger the per-round `reset`? | UDP control channel on port 4211, or in-process call | Game/backend team |
| 10 | Does "one key at a time" apply per controller or across all players? | Per controller | Product |
| 11 | Key semantics: tap with auto-release, or held while the gesture lasts? | Tap, 120 ms hold | Game/backend team |
| 4 | Exact ESP32 board model? | `esp32dev` (pins 21/22 match a DevKit) | Us |
| 5 | BNO055 vs the MPU6050 in the backend diagram | BNO055, as in the working prototype | Us, tell the backend team |
| 6 | How many controllers at once? | Designed for 2-8 | Product |
| 7 | How is a controller bound to a player/session? | Static map in bridge config | Game/backend team |
| 8 | Battery power and enclosure | Out of scope for now | Us |

## Hotspot checklist (before M2)

- Hotspot set to 2.4 GHz (iPhone: "Maximize Compatibility").
- Confirm the phone allows at least N controllers + the bridge host as clients.
- Test whether a broadcast `HELLO` reaches the bridge host; if not, set `BRIDGE_HOST`.
- Disable Wi-Fi power save on the ESP32 and measure round-trip jitter.

## Fallbacks if Wi-Fi is not viable

- **ESP-NOW** to a receiver ESP32 plugged into the host over USB. No access point
  needed. Costs one extra board and a serial transport in the bridge.
- **USB serial** per controller. Tethered, but useful for bench debugging.

The bridge's transport is one module, so either can be added without touching the
registry, gestures, or publishers.
