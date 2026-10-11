# we-fit — motion controller branch

Motion-controlled Subway Surfers clone. This branch (`motion-controller`) owns the
**input pipeline only**: one ESP32 + IMU controller that talks to a Python bridge
over USB serial or Bluetooth LE. The bridge turns motion into arrow-key inputs for a
**single-player** game.

The game itself is owned by someone else (see `origin/infra/backend`, author Anish).
Do not build game logic here. Our output boundary is the bridge's sinks and the
`Controller` class.

Detailed context lives next to this file:

- [docs/architecture.md](docs/architecture.md) — components, data flow, repo layout
- [docs/protocol.md](docs/protocol.md) — BLE and USB wire formats (source of truth)
- [docs/build-plan.md](docs/build-plan.md) — milestones, open questions
- [docs/latency-tracking.md](docs/latency-tracking.md) — latency logging, metrics, report; phases 1-2 planned

User-facing setup instructions are in the root `README.md`. Keep it in step with the
commands below.

## Scope

- **One controller, one player.** No player numbers, no device registry, no Wi-Fi.
- **Output is four boolean arrow keys**: `up`, `down`, `left`, `right`. At most one is
  on at a time. No diagonals. Use exactly these strings everywhere.
- **Two transports, one firmware.** USB serial is the simple path for bench testing;
  BLE is the untethered path. The firmware always does both.

## Where the logic lives (decided)

**The gesture logic is recreated in Python. The `.ino` is not used directly.**

- Firmware streams raw sensor values (linear acceleration + quaternion) and makes no
  decisions.
- The bridge applies thresholds, return-to-rest gating, cooldown and the one-key rule
  in `bridge/src/wefit_bridge/gestures.py`, a port of the sketch.
- Why: thresholds are tuned in a TOML file instead of by reflashing, and motion can
  be replayed in tests.
- **All tuning is in `tuning.toml` at the repo root**, read on every start (no flag):
  `[orientation]` (which sensor axis is right/up) and one profile per transport,
  `[usb]` and `[ble]`, each with a `threshold`/`rest_ms`/`cooldown_ms` row per
  direction. `tuning.py` loads it into `GestureConfig`; `fake` ignores the file.
  `bridge/config.toml` no longer has a `[gestures]` table.
- No IMU maths library is needed in Python. The BNO055 does sensor fusion on-chip.
- **The teammates keep tuning `firstiterationsubwaysurfers/*.ino` on hardware**
  (author "Spiritqurse"). When that file changes, re-port its constants and logic
  into `gestures.py`, `tuning.toml`, the tests and the README.

## Current state (as of 2026-10-10)

| Path | State |
| --- | --- |
| Bridge core (protocol, gestures, keys, pipeline) | Working. Logic tests pass. |
| `transport/fake.py` | Working; used by tests and demos. |
| `transport/usb.py`, `transport/ble.py` | Written. **Never run against a real board.** |
| `firmware/` | **Compiles** (`pio run`, 87.6% of flash). **Never flashed or run.** |
| `bridge/tests/test_setup.py` | Hardware checks. Verified only in their failing state (no board attached), plus "Bluetooth is enabled" passing. |
| `latency/` (log, stats, `report.py`) | Working against `fake`. **Never run against a real board**, including the clock checks. |
| `firstiterationsubwaysurfers/*.ino` | Teammates' Arduino IDE prototype; source of the gesture logic. |

`.venv` is Python 3.11.0 with everything from `requirements.txt` installed.

## Known-good hardware facts (from the prototype sketch)

- Board: ESP32 dev board, I2C on SDA=21, SCL=22, bus clock 100 kHz.
- IMU: Bosch BNO055 via `Adafruit_BNO055`, address 0x28 or 0x29 (probe both).
- Mode: `OPERATION_MODE_IMUPLUS` (accel + gyro fusion, no magnetometer).
- Gestures (sketch at commit 04c71fc): dominant-axis test on linear acceleration.
  Up = +Z > 7.0, down = −Z > 4.0, right = +X > 4.0, left = −X > 4.0 (m/s²).
  Re-arm after all axes stay under 1.0 for 150 ms. Cooldown 500 ms. 50 Hz.

## Commands

```
pip install -r requirements.txt              # from the repo root

python check.py                              # all checks
python check.py logic | usb | bluetooth      # one group

python -m wefit_bridge --transport usb       # wired (default transport)
python -m wefit_bridge --transport ble       # Bluetooth
python -m wefit_bridge --transport fake      # scripted gestures, no hardware
python -m wefit_bridge --scan                # list USB ports and WeFit BLE devices
python -m wefit_bridge --transport usb --sink keyboard   # press real arrow keys
python examples/game_stub.py usb|ble|fake
python -m wefit_bridge --transport usb --no-latency-log  # skip logs/raw/ and the exit summary
python report.py [usb|ble|fake|<file>]       # latency report -> logs/reports/

pio run -d firmware                          # build
pio run -d firmware -t upload                # flash
pio device monitor -d firmware -b 115200
```

In this environment `pio` is not on PATH unless the venv is activated; use
`.venv/Scripts/python.exe -m platformio ...`.

## Conventions

- `firmware/include/protocol.h`, `bridge/src/wefit_bridge/protocol.py` and
  `docs/protocol.md` change together. Bump `PROTOCOL_VERSION` on any layout change.
- `requirements.txt` lists top-level packages only and must stay UTF-8. Do not
  replace it with `pip freeze` output (PowerShell's `>` writes UTF-16, and a freeze
  pins the editable install to a git URL).
- Tests are deliberately simple. Logic tests need no hardware. Hardware checks are
  marked `usb` or `bluetooth`, fail when the hardware is absent, and print one
  sentence saying what to do (`pytest.fail(..., pytrace=False)`).
- Firmware loop is scheduled with `millis()`; no `delay()` in the steady state.
- All bridge timing uses `clock.now` (`time.perf_counter`). Do not use `time.monotonic`:
  it ticks every 15.6 ms on Windows before Python 3.13.
- Latency logs: `logs/raw/` is git-ignored, `logs/reports/` is committed. Metric names
  live in `latency/metrics.py` (`METRICS`, `Summary`); reuse them, do not redefine.
- Bridge core (`gestures`, `keys`, `Pipeline`) is synchronous and takes `now` as an
  argument. Bridge I/O is asyncio. `Controller` runs that loop on one background
  thread so a blocking game loop can poll it.
- Drift is not compensated. The game calls `Controller.reset()` at the start of each
  round. Gestures use sensor-frame linear acceleration, which heading drift does not
  affect.
- The bridge keeps its own `bridge/pyproject.toml` (Python >= 3.11) so it does not
  collide with the root `pyproject.toml` on `origin/infra/backend` (Python >= 3.13, uv).
