# Proposal: ground-referenced gestures (`--gravity`)

```yaml
id: gravity
status: built 2026-10-11    # see "As built" below; never run on a real board
branch: gravity
date: 2026-10-11
datasheet: .claude/docs/bst-bno055-ds000.pdf   # BST-BNO055-DS000-18, rev 1.8, Oct 2021
default_behaviour: unchanged # no flag, no tuning.toml change = IMUPLUS + [orientation]
needs_reflash: once
protocol_version: 1 -> 2
evidence_levels: [DS = datasheet, CODE = this repo, EST = my estimate, FIELD = commonly reported and not in the datasheet]
hardware_tested: false       # no part of this repo has run on a real board
```

## As built (2026-10-11)

Implemented as proposed, with these differences. Where this list and the sections
below disagree, this list is right.

| Topic | Proposed | Built |
| --- | --- | --- |
| Mode confirmation | `flags.bit0` in the sample | `status.mode`. The USB sample line carries no flags, so the status packet is the one source on both transports. `flags.bit0` is still set on BLE |
| USB mode command | sent on connect | sent once samples flow, repeated every 0.5 s until a status confirms it (the board ignores input while booting) |
| IMU mode startup | calibration and field shown as n/a | NDOF checks skipped: mode and one calibration line, no waiting, gestures never blocked |
| Old firmware (no status packet) | refused | accepted in IMU mode with a warning; refused in NDOF mode |
| `.imu.bin` column | `flags` | `mode` (from the last status packet) |
| Gesture history line | `{t_s, key, peak_ms2, rise_ms}` | `{t_s, key, trigger_ms2}`. Peak and rise time need samples after the trigger; the report computes them |
| `.json` | as listed | also `limits` (the `[gravity]` values in use) and `session.ready_s` (when startup finished), so the report can exclude the reference shuffle from tuning |
| Failure message | command without `--gravity` | also names the mode authority order and the README section |
| Game integration | `Controller(on_startup=...)` | also `controller.startup_done` and `controller.startup_error` |
| Firmware | flash 87.6 % | v3 builds at 87.7 %. **Not flashed: no board was attached** |

Open items O1-O5 below are all still open; they need hardware.

## 1. Summary

- Rotate linear acceleration into the world frame with the quaternion. `up` then comes
  from gravity, with no configured axis.
- `right` cannot come from any sensor: the magnetometer finds north, not the screen. One
  prompted "shuffle right" at startup supplies it. This replaces `[orientation]`.
- NDOF is not needed for `up`/`down`. It only holds the heading (so `left`/`right`)
  steady over time. `--gravity` always uses it, as asked. A `tuning.toml` setting picks
  the chip mode when `--gravity` is absent, so logs can compare the two modes.
- The 20-byte sample does not change, so per-sample latency does not change.

## 2. Run modes

`--gravity` overrules `tuning.toml`. `fusion_mode` is the first setting in `tuning.toml`.

| Invocation | Chip mode | Gesture frame | Startup checks |
| --- | --- | --- | --- |
| no flag, `fusion_mode = "imu"` (default) | IMUPLUS | `[orientation]` (today) | calibration; field = `n/a (IMU mode)` |
| no flag, `fusion_mode = "ndof"` | NDOF | `[orientation]` (today) | calibration, field |
| `--gravity` | NDOF, whatever `fusion_mode` says | world frame | calibration, field, world reference |

The tuning rows in `[usb]`/`[ble]` apply in every row of the table.

## 3. BNO055 capabilities (pasted list checked against the datasheet)

| Output | Claimed | Datasheet | Verdict |
| --- | --- | --- | --- |
| Euler angles | 100 Hz | fusion data 100 Hz in IMU and NDOF (Table 3-14); 1° = 16 LSB | confirmed |
| Quaternion | 100 Hz | same; 1 = 2^14 LSB | confirmed |
| Angular velocity | 100 Hz, rad/s | 100 Hz; default unit is dps (16 LSB), rps (900 LSB) by `UNIT_SEL` | confirmed, unit is a setting |
| Acceleration (with gravity) | 100 Hz | 100 Hz; 1 m/s² = 100 LSB | confirmed |
| Magnetic field | 20 Hz | 20 Hz in NDOF; 1 µT = 16 LSB; range ±1300 µT (x, y), ±2500 µT (z) | confirmed, **NDOF only**: IMU mode suspends the magnetometer |
| Linear acceleration | 100 Hz | fusion data, 100 Hz; 1 m/s² = 100 LSB | confirmed |
| Gravity vector | 100 Hz | fusion data, 100 Hz; 1 m/s² = 100 LSB | confirmed |
| Temperature | 1 Hz | 1 °C per LSB; rate not checked | unit confirmed, rate not checked |

The firmware samples at 50 Hz, so every rate above has headroom.

## 4. Questions

| ID | Question | Answer | Evidence |
| --- | --- | --- | --- |
| Q1 | Is NDOF + quaternion + linear accel, rotated to world frame, optimal? | The rotation is right. NDOF is optional: `up`/`down` need only tilt, which IMU mode already corrects with the accelerometer. NDOF adds a heading that does not drift, which helps `left`/`right` only, and only in a clean magnetic field. | DS 3.3.3 note 2 |
| Q2 | Reflash to enable NDOF? | Yes, once. The firmware hard-codes `OPERATION_MODE_IMUPLUS` and has no host-to-board channel. After that reflash the mode is switched at run time (to config mode 19 ms, to a fusion mode 7 ms). | CODE `main.cpp`; DS Table 3-6 |
| Q3 | Does NDOF make calibration drift faster? | Gyro heading drift: slower (the magnetometer corrects it). Calibration status: less stable, because NDOF adds the magnetometer's status, the one most disturbed by surroundings. Background calibration runs in every fusion mode and cannot be turned off. If the field is distorted the chip ignores the magnetometer and heading drifts as in IMU mode. Heading can also step when the magnetometer calibration updates. Tilt, so `up`/`down`, is unaffected. | DS 3.3.3 notes 1-2, 3.11; step: FIELD |
| Q4 | Can the setup handle the throughput? | Yes by estimate. USB: about 3.3 kB/s of 11.5 kB/s today, +0.2 kB/s. BLE: 1.0 kB/s, +0.06 kB/s. I2C: about 2-3 ms of each 20 ms period. | EST, unmeasured |
| Q5 | Latency over BLE or USB? | No change expected: same sample size and rate, NDOF fusion is still 100 Hz. Bridge adds one quaternion rotation per sample (microseconds). Compare `host_p50_ms` and `latency_p95_ms` with and without the flag to confirm. | DS Table 3-14; EST |
| Q6 | Does the battery bank disturb the magnetometer and fusion? | It can disturb heading only. Steel cell cans and the inductor core add a fixed offset; supply current adds a few µT at 1 cm (100 mA: about 2 µT; Earth: 25-65 µT). Fixed rigidly to the sensor, the offset is calibrated out. Moving relative to the sensor (dangling cable, bank in a pocket), it is not. A MagSafe bank's magnets can swamp the sensor. Tilt, linear acceleration and IMU mode are unaffected. | EST; DS 3.11.3 |

Q6 mitigations: fix the bank at least 5 cm from the sensor, keep the power leads
together, no magnetic banks. The startup field check (section 7) is the test.

## 5. Design decisions

| ID | Decision | Why |
| --- | --- | --- |
| D1 | `--gravity`: NDOF + world-frame detection. Overrules `tuning.toml` | as requested |
| D2 | `tuning.toml` top-level `fusion_mode = "imu" \| "ndof"`, used only without `--gravity`. Default `"imu"` | keeps today's behaviour; lets Q1/Q3 be settled by A/B logs |
| D3 | World frame is computed in the bridge: `a_world = q * a * q^-1` | keeps the firmware decision-free |
| D4 | `up` = world +Z. `right` = horizontal unit vector captured from one prompted gesture | no sensor observes the screen direction |
| D5 | `GestureDetector` logic and the `[usb]`/`[ble]` rows are reused unchanged; only its input vector changes | a threshold is a physical acceleration in either frame |
| D6 | `[orientation]` is ignored under `--gravity` | it is the hard-coded orientation being removed |
| D7 | Sample packet stays 20 bytes; magnetometer and uptime go in a new 5 Hz status packet | no MTU negotiation; no latency change |
| D8 | Gravity vector is not sent or logged | derivable from the quaternion; its length is fixed by the fusion, so it carries no drift signal (EST, bench-check once) |
| D9 | Mid-game magnetic excursions are logged only | as requested: no fallback |
| D10 | A failed startup reference exits with code 1 and the message in section 7. No silent fall-back to `[orientation]` | a wrong frame is worse than no game |
| D11 | Startup is a data-driven state machine (`StartupGuide`) that emits events; the terminal is one consumer | a game can render the same prompts later (section 7) |
| D12 | A "session" is one bridge run. No round concept | the browser game sends no round signal |

## 6. Changes

### 6.1 Protocol v2 (`protocol.h`, `protocol.py`, `protocol.md` together)

```yaml
sample:                       # unchanged layout, 20 bytes, 50 Hz
  flags.bit0: 1 = NDOF, 0 = IMUPLUS
status:                       # new, 5 Hz
  ble: notify characteristic 7e3f0004-..., 11 bytes, struct "<I3hB"
  usb: "T,<uptime_ms>,<mx>,<my>,<mz>,<mode>"
  fields:
    uptime_ms: u32   # millis(), not truncated
    mag: i16[3]      # raw / 16 = microtesla; zeros in IMUPLUS
    mode: u8         # BNO055 OPR_MODE: 0x08 IMUPLUS, 0x0C NDOF
command:                      # new, host -> board
  ble: write characteristic 7e3f0005-..., 1 byte = mode
  usb: "M,<mode>\n"
rules:
  - board boots in IMUPLUS
  - bridge sends the mode on every connect: NDOF if --gravity, else tuning.toml fusion_mode
    # a BLE connect does not reboot the board, so it may still be in the previous mode
  - bridge waits for flags.bit0 to match; 2 s timeout -> "re-flash the firmware"
```

### 6.2 Firmware (`FW_VERSION` 3)

- Read `M,` lines from `Serial` and writes to the command characteristic; call
  `bno->setMode()`.
- Every 10th sample: read the magnetometer vector, send the status packet.
- No `delay()` added to the loop beyond the mode switch itself.

### 6.3 Bridge

| File | Change |
| --- | --- |
| `__main__.py` | `--gravity` flag; builds the failure command (section 7) |
| `config.py` | `Config.gravity: bool = False`, `Config.fusion_mode` |
| `tuning.py`, `tuning.toml` | top-level `fusion_mode`; new `[gravity]` table; loader accepts both |
| `world.py` (new) | quaternion rotate, world reference; synchronous, takes `now` |
| `startup.py` (new) | `StartupGuide` and `StartupEvent`; terminal printer |
| `gestures.py` | `update()` accepts an already-oriented vector; logic untouched |
| `pipeline.py` | startup phase (no key events) before the first gesture; under `--gravity`, `(a·right, a·forward, a·up)` into the detector |
| `client.py` | `Controller(on_startup=callable)` forwards the same events |
| `transport/usb.py`, `ble.py` | parse status packets, send the mode command |
| `transport/fake.py` | scripted quaternions and status so tests cover the world frame |
| `latency/recorder.py`, `metrics.py` | second row file, session file (section 8) |
| `latency/report.py` | new sections, new order (section 9) |
| `.gitignore` | `logs/runs/` |
| `README.md`, `tuning.toml` comments | commands and options (README gets a section now; see section 12) |

```toml
# tuning.toml, first setting in the file, above [orientation]
fusion_mode = "imu"        # "imu" or "ndof". Ignored when --gravity is given.

[gravity]                  # --gravity only
mag_min_ut = 20            # warn below
mag_max_ut = 80            # warn above; Earth's field is 25-65
still_ms2 = 0.5            # |linear accel| under this counts as still
reference_timeout_s = 10
```

### 6.4 World reference

```yaml
up: world +Z                          # from the quaternion; no input needed
right:
  capture: first horizontal acceleration peak >= the transport's `right` threshold
  value: unit vector of that peak's horizontal part, in the world frame
forward: up x right                   # rejected by the dominant-axis test, as today
valid_while: heading error stays under about 20 deg (EST); the dominant-axis test fails at 45 deg
recapture: session start only
```

## 7. Startup: checks, prompts, failure

### 7.1 Integration shape

```python
@dataclass(frozen=True)
class StartupEvent:
    step: str      # "mode" | "calibration" | "field" | "reference"
    status: str    # "prompt" | "ok" | "warn" | "fail"
    message: str   # one sentence, ready to show
    data: dict     # numbers for a UI: {"sys": 3, "gyro": 3, ...}, {"ut": 47.0}, ...

class StartupGuide:                    # synchronous, no I/O, no printing
    def on_sample(self, sample, status, now) -> list[StartupEvent]
    done: bool; failed: bool
```

- The pipeline feeds it samples until `done`; no key events are emitted meanwhile.
- `startup.print_events` is the terminal consumer. A game passes its own callable to
  `Controller(on_startup=...)` and draws the same prompts. `WebSocketSink` can send
  `{"type": "startup", ...}` the same way; not in this proposal.
- `Controller.reset()` does not restart startup.

### 7.2 Sequence (printed in this order; runs in every mode where the check applies)

| # | Step | Prompt shown | Method | Result line |
| --- | --- | --- | --- | --- |
| 1 | mode | none | `flags.bit0` matches the request within 2 s | `fusion mode: NDOF` |
| 2 | calibration | "Hold the controller still." then, if mag is below 2 in NDOF, "Draw a figure 8 in the air." | wait up to 20 s for gyro = 3 and (NDOF) mag >= 2 | `calibration: sys 3 gyro 3 accel 1 mag 3  OK` or `WARN` |
| 3 | field | none | median and spread of field strength over 2 s against `mag_min_ut`/`mag_max_ut`. NDOF only | `magnetic field: 47 uT (+/- 2)  OK`, or `WARN: 212 uT, move magnets, speakers or the battery bank away` |
| 4 | reference (`--gravity` only) | "Hold still." then "Shuffle RIGHT once, quickly." | quaternion length within 1 +/- 0.02; still for 1 s; then one right shuffle within `reference_timeout_s`, at least 70 % horizontal | `world reference: OK` or `FAILED (<reason>)` |

Steps 1-3 warn and continue. Step 4 failing exits with code 1. A step 1 failure exits
with the re-flash message from section 6.1.

The step 2 values are the **initial calibration** for the report. Calibration is kept
logging every sample afterwards.

During play: field strength outside the limits logs one `WARNING` per excursion (start,
peak, duration) and is counted in the session `.json`. Nothing else reacts.

### 7.3 Failure message (step 4)

The command is `sys.argv` with `--gravity` removed, so the transport, port and sinks
carry over.

```
Startup failed: the initial world reference could not be set (<reason>).
Ground-referenced mode was not started. To run with the fixed sensor orientation
from tuning.toml instead, run:

  python -m wefit_bridge --transport usb --sink websocket
```

## 8. Logging

All times are seconds since the bridge process started. The only absolute time is the
file-name stamp. `.json` gains `t0_offset_s` (bridge start to first sample) and
`uptime_at_t0_s` (board uptime, from the status packet), so "how long until drift" can
be read against either clock. Existing `rx_us` and `SCHEMA = 1` rows are untouched.

```yaml
logs/raw/<stamp>_<transport>.imu.bin:   # new; row i matches row i of the existing .bin
  dtype: [accel "<3i2", quat "<4i2", calib u1, flags u1, mag_ut16 "<u2"]
  size: 18 bytes/row, 0.9 kB/s, 3.2 MB/hour
  notes: raw wire integers; mag_ut16 = last field strength * 16, 0 = none
logs/raw/<stamp>_<transport>.json:      # extended
  session: {transport, fusion_mode, gesture_frame: "fixed" | "world", gravity_flag: bool}
  startup: {mode, calibration: {sys, gyro, accel, mag, wait_s}, field: {median_ut, spread_ut, status},
            reference: {ok, reason, right_world}}
  mag_excursions: [{start_s, peak_ut, duration_s}]
  tuning: the GestureConfig in use      # the report needs the thresholds that were live
logs/runs/<stamp>_<transport>.jsonl:    # new, git-ignored; one file per session
  line 1: {schema, session, transport, fusion_mode, gesture_frame}
  line n: {t_s, key, peak_ms2, rise_ms}   # one line per gesture, appended as it fires
```

One JSON line per gesture means a killed bridge still leaves a readable history.

Not logged: world-frame acceleration (recomputed from `accel`, `quat` and
`right_world`), gravity vector (D8), Euler angles, temperature, raw gyro.

## 9. Report (`python report.py`, same HTML file)

Order is fixed. Sections 1 is the top of the page; 2-4 follow.

| # | Part | Content | From |
| --- | --- | --- | --- |
| 1 | **Session** | Header row: transport (BLE or USB), fusion mode (NDOF or IMU), gesture frame (world or fixed). Startup health table: mode, calibration (initial sys/gyro/accel/mag and seconds taken), magnetic field, world reference, each OK/WARN/FAILED. Then gestures: count and per-minute rate by direction, estimated kcal | `.json` `session`, `startup`; `key` |
| 2 | **Tuning** | Per direction, one panel per transport: histogram of peak world-axis acceleration for fired gestures and for near misses (peaks >= 50 % of threshold that did not fire), threshold line drawn; table of rise time (rest to threshold) and time above `rest_threshold` | `accel`, `quat`, `tuning` |
| 3 | **Debug** | Calibration over time (step plot, sys/gyro/accel/mag, 0-3). Tilt error over time (asin of the rest residual / 9.81). Heading drift over time (quaternion rotation about world up, accumulated over still windows only; deg and deg/min). Magnetic field over time with the limit band and excursions marked | `calib`, `accel`, `quat`, `mag_ut16` |
| 4 | **Latency** | The existing phase 0 report, unchanged | existing `.bin` |

Changes to your suggestions:

| Suggestion | Verdict |
| --- | --- |
| Log world-frame motion | Report it, do not log it: derived data |
| Linear magnitude for thresholds | Kept, as per-gesture peaks plus near misses. Near misses are what show a threshold set too high |
| Gravity magnitude for drift | Replaced by rest residual. The fused gravity vector always has the same length; leftover linear acceleration at rest is what shows a tilted frame |
| Gyro drift | Kept; needs no new data. "Still" means acceleration under `still_ms2`, which a slow hand turn passes, so the cleanest reading is the controller left on a table |
| Calories | Kept as a labelled estimate, below |

```yaml
calories:                      # EST, about +/- 50 %; active energy only
  body_mass_kg: 70
  efficiency: 0.25
  method: mechanical work / efficiency
  kcal_per_gesture:
    up: 0.16      # jump, centre of mass raised 0.25 m
    down: 0.23    # squat, centre of mass travel 0.35 m
    left: 0.15    # side shuffle, to 1.5 m/s and back to rest
    right: 0.15
```

## 10. Flash pipeline check (2026-10-11)

Checked by building and listing targets; **no board was attached, so upload itself was
not run.**

| Item | Result |
| --- | --- |
| `pio run -d firmware` | Succeeds in 6.8 s. Flash 87.6 % (1,148,569 of 1,310,720 B), RAM 12.0 % |
| Tracked files under `firmware/` | 4: `platformio.ini`, `src/main.cpp`, `include/config.h`, `include/protocol.h` |
| `firmware/.pio/` | Git-ignored; holds all build output and the library cache |
| `data/`, `lib/`, `test/` | None exist, so no filesystem image can be built or flashed |
| `upload` target | Writes bootloader, partition table, boot_app0 and `firmware.bin` only. `uploadfs` is a separate target and is never run by the README commands |
| `upload_port`, `upload_speed` | Not set: port auto-detected, default speed |
| Library versions | Resolved to BNO055 1.6.4, Unified Sensor 1.1.15, BusIO 1.17.4; `^` ranges, so they can float |

Findings:

1. The pipeline is clean today; no stray cache is tracked or flashed.
2. **Stale-cache risk is local, not in git.** After editing `platformio.ini`, switching
   branches that change libraries, or a failed build, a stale `firmware/.pio/` can
   produce odd upload or link errors. Fix: `pio run -d firmware -t clean`, or delete
   `firmware/.pio/`. Proposed README troubleshooting line.
3. **Flash headroom is tight.** 87.6 % used; the v3 firmware adds a few hundred bytes of
   code, which is safe, but the 1.3 MB app partition is the limit. If a later change
   overflows, `board_build.partitions = huge_app.csv` is already noted in
   `platformio.ini`.
4. The v3 reflash needs the same command as before: `pio run -d firmware -t upload`
   (`.venv/Scripts/python.exe -m platformio ...` when the venv is not activated).

## 11. Tests (logic group, no hardware)

- Rotation: known quaternions map sensor axes to the expected world axes.
- The same scripted motion fires the same gestures with the controller in six mountings.
- `StartupGuide`: every step as ok, warn and fail; reference accepted, timed out,
  rejected as too vertical; no key events emitted during startup.
- Failure message: `--gravity` removed, other arguments kept.
- `tuning.toml`: `fusion_mode` valid, invalid value rejected, `--gravity` overrules it.
- Protocol v2 round trip; status line parse; v1 firmware refused with one sentence.
- Without `--gravity` and with the default `fusion_mode`, existing tests pass unchanged.

## 12. Open items

| ID | Item | Resolve by |
| --- | --- | --- |
| O1 | Quaternion direction (sensor-to-world or its inverse) and world Z sign | bench: a jump must read `up` in two different mountings |
| O2 | Whether switching mode resets calibration status | read `calib` across a switch |
| O3 | Fused gravity length really is constant (D8) | one-off read of `VECTOR_GRAVITY` |
| O4 | NDOF or IMU as the `fusion_mode` default | compare heading-drift and field plots from the play room |
| O5 | BLE throughput at 55 notifications/s on the host's connection interval | `loss_pct`, `longest_gap_ms` |
| O6 | The README documents flags that do not exist yet | marked "planned" until built |

## 13. Build order

1. Protocol v2, firmware, transports. Reflash (section 10). `check.py usb`.
2. `world.py`, `startup.py`, detector input, `--gravity`, `fusion_mode`. Resolve O1-O3.
3. `.imu.bin`, `logs/runs/`, `.gitignore`.
4. Report sections, in the section 9 order.
5. README: drop the "planned" marking. `architecture.md`, `protocol.md`, `CLAUDE.md`.
