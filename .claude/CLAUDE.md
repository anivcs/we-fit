# we-fit — motion controller branch

Motion-controlled Subway Surfers clone. This branch (`motion-controller`) owns the
**controller pipeline only**: ESP32 + IMU firmware, and a Python bridge that receives
IMU data from several controllers at once and publishes it to the game server.

The game server / frontend is a **black box owned by someone else** (see
`origin/infra/backend`, author Anish). Do not build game logic, sessions, or
leaderboards here. Our output boundary is the bridge's `Publisher` interface.

Detailed context lives next to this file:

- [docs/architecture.md](docs/architecture.md) — components, data flow, repo layout
- [docs/protocol.md](docs/protocol.md) — ESP32 → bridge wire format (source of truth)
- [docs/build-plan.md](docs/build-plan.md) — milestones, open questions

## Current state of the repo (as of 2026-10-10)

Only these exist. Everything else in the docs is **planned, not yet created**.

- `README.md` — two lines.
- `firstiterationsubwaysurfers/firstiterationsubwaysurfers.ino` — working Arduino IDE
  prototype: ESP32 + BNO055 over I2C, prints linear acceleration and
  `>>> UP/LEFT/RIGHT <<<` to serial at 115200 baud. No networking. Treat as the
  reference for known-good hardware settings and gesture thresholds.
- `.venv/` — empty Python 3.11.0 venv (pip + setuptools only), gitignored.
- PlatformIO is **not installed** (`pio` is not on PATH).

## Known-good hardware facts (from the prototype)

- Board: ESP32 dev board, I2C on SDA=21, SCL=22, bus clock 100 kHz.
- IMU: Bosch BNO055 via `Adafruit_BNO055`, address 0x28 or 0x29 (probe both).
- Mode: `OPERATION_MODE_IMUPLUS` (accel + gyro fusion, no magnetometer, relative heading).
- Gestures: linear accel, dominant-axis test, side threshold 2.0 m/s², up threshold
  2.5 m/s², 1000 ms cooldown, 50 Hz loop. Prototype has up/left/right only;
  **down is new** and is planned as the mirror of up (negative Z beyond a threshold,
  dominant axis). Its threshold needs tuning on hardware.

## Planned layout

```
firmware/   PlatformIO project (Arduino framework, ESP32) — one binary for all controllers
bridge/     Python package `wefit_bridge` — UDP receiver, registry, gestures, publishers
tools/      fake_controller.py — simulates N controllers without hardware
legacy/     the original .ino, kept for reference
```

## Design decisions (defaults chosen; revisit only with a reason)

0. **Output contract: four boolean arrow keys.** The game sees only `up`, `down`,
   `left`, `right`, each on/off. At most ONE key is on at a time per controller; no
   diagonals, no combos. Full rules in [docs/architecture.md](docs/architecture.md#output-contract-arrow-keys).
1. **Transport: UDP over a phone's mobile-data Wi-Fi hotspot.** Bridge host and all
   ESP32s join the same hotspot. Broadcast discovery first, with a static
   `bridge_host` (IP) in the firmware config as the fallback, because some phone
   hotspots drop broadcast traffic.
2. **Controller identity = Wi-Fi MAC**, carried in every packet. Same firmware on
   every unit; no per-device flashing or config.
3. **Firmware is a dumb sensor streamer.** Gesture detection runs in the bridge so
   thresholds can be tuned without reflashing.
4. **Binary fixed-size packets**, little-endian, versioned. `firmware/lib/protocol/protocol.h`
   and `bridge/src/wefit_bridge/protocol.py` must change together with `docs/protocol.md`.
5. **Publisher is pluggable.** Console publisher first; the real one is written when
   the game server interface is known.
7. **Drift is reset per round by the game, not solved by us.** The bridge exposes a
   `reset` command (per player or all) that re-zeroes the reference orientation and
   clears gesture state. Gestures use sensor-frame linear acceleration, so they do not
   depend on heading drift in the first place. No drift compensation code beyond this.
6. **Bridge is self-contained in `bridge/`** with its own `pyproject.toml`
   (Python >= 3.11, stdlib-only core) so it does not collide with the root
   `pyproject.toml` on `origin/infra/backend` (which requires Python >= 3.13, uses uv).

## Commands (once scaffolded)

```
# firmware
pip install platformio                 # into .venv; pio is not installed yet
pio run -d firmware                    # build
pio run -d firmware -t upload          # flash
pio device monitor -d firmware -b 115200

# bridge
pip install -e "bridge[dev]"
python -m wefit_bridge --config bridge/config.toml
python tools/fake_controller.py --count 4   # no hardware needed
pytest bridge
```

## Conventions

- Wi-Fi credentials go in `firmware/include/secrets.h` (gitignored); commit only
  `secrets.h.example`.
- Never block the firmware loop on the network; a missing bridge must not stall sampling.
- Bridge code is asyncio; one event loop, no threads.
- An IMU cannot give absolute position. The game-facing output is arrow-key state
  only; orientation, acceleration and angular velocity stay inside the bridge (and
  in an optional debug stream).
- Gesture names are exactly `up`, `down`, `left`, `right`. Use these strings
  everywhere (code, config, events, tests); no synonyms.
