# Latency tracking

Goal: measure the delay from the ESP32 reading the motion sensor to the browser showing
the result, per transport (USB or Bluetooth).

| Phase | Covers | State |
| --- | --- | --- |
| 0 | Sensor read -> key sent by the bridge. Loss, jitter, clock check, logs, report. | **Built** (2026-10-10). Never run against a real board. |
| 1 | Bridge -> browser frame, motion-onset sample, HUD. | Planned |
| 2 | Absolute link latency (needs a protocol change). | Planned |

## Phase 0: what exists

### Timestamps

| Point | Clock | Where it is taken |
| --- | --- | --- |
| Sensor read | ESP32 `millis()` | `t_ms`, stamped before the I2C reads in `sendSample()` |
| Arrival at the PC | `clock.now` | `Sample.rx`: USB reader thread after `readline()`; first line of the BLE notify callback |
| Picked up | `clock.now` | `run()` before `Pipeline.on_sample` |
| Key sent | `clock.now` | `run()` after `Pipeline.on_sample` returns (sinks have emitted) |

`clock.now` is `time.perf_counter`. `time.monotonic` ticks every 15.6 ms on Windows
before Python 3.13, so the whole bridge (gesture timing included) moved off it.

### Clocks: no sync, a fitted mapping

Nothing sets the ESP32's clock, and it does not need to be set. The two clocks only have
to be compared, and the samples already carry what is needed:

- `lag = host arrival time - device time` is a constant, plus drift, plus each sample's delay.
- The fastest sample in each 10 s window marks the link's best case. A straight line
  through those points gives the offset and the drift (`metrics.link_delay_ms`).
- Each sample's link delay is its distance above that line.

Consequence: **every latency number is "above the link's best case"**. The link's
constant minimum transit time is unknown until Phase 2. Jitter, spikes, loss and
USB-versus-Bluetooth spread are all valid today.

Setup check: `python check.py usb` and `python check.py bluetooth` each read 6 s of
samples and print the drift (ppm) and how tightly the clocks map (p95, ms). They fail
above 1 % drift or 100 ms spread. These limits are deliberately coarse: they catch a
broken timestamp, not crystal error.

### Log files

```
logs/raw/      git-ignored    20261011T044512Z_usb.bin + .imu.bin + .json   per session
logs/runs/     git-ignored    20261011T044512Z_usb.jsonl                    per session
logs/reports/  committed      20261011T044512Z_usb-ble.html
```

A session is one bridge run. Since the gravity work (2026-10-11) the same tracker also
writes:

- `.imu.bin`: one 18-byte row per sample (`metrics.IMU_RECORD`), in the same row order as
  `.bin`: raw `accel`, `quat`, `calib`, plus `mode` and `mag_ut16` from the last status
  packet. 0.9 kB/s. World-frame values are not logged; `latency/motion.py` recomputes them.
- `.jsonl` in `logs/runs/`: the gesture history. Line 1 describes the session; then one
  line per gesture, `{t_s, key, trigger_ms2}`, appended as it fires.
- `.json` also holds `session` (fusion mode, gesture frame, `ready_s`), `startup` (each
  check's result), `mag_excursions`, `limits`, `tuning`, `t0_offset_s` and
  `uptime_at_t0_s`.
- Times in the `.json` and `.jsonl` are seconds since the bridge started
  (`clock.since_start`). `rx_us` in `.bin` is still since the first sample; add
  `t0_offset_s`.
- The report (`report.py`) now opens with Session, then Tuning and Debug, then Latency.

- The transport (`usb`, `ble`, `fake`) is in the file name and in the `.json`.
- `.bin`: one fixed 27-byte row per sample (`metrics.RECORD`, a numpy dtype). About
  1.4 KB/s, 5 MB/hour. Rows are buffered and written every 256 samples, on the event
  loop; no thread, no parsing.
- `.json`: transport, port or address, firmware info, the row layout, and the final
  summary. Written at start and again at exit, so a killed run still loads.
- Row fields: `epoch` (bumps when the link comes back), `n` (unwrapped `seq`),
  `dev_ms` (unwrapped `t_ms`), `rx_us`, `queue_us`, `done_us`, `key`.
- A silence of `transport.retry_delay_s` or longer starts a new epoch, because the board
  may have rebooted and restarted `seq` and `millis()`.

On by default. Off with `--no-latency-log`, or `[latency] enabled = false` in
`bridge/config.toml`.

### Metrics

Defined once in `metrics.METRICS`, keyed by `Summary` field.

| Field | Meaning |
| --- | --- |
| `latency_p50_ms`, `_p95_`, `_p99_`, `latency_max_ms` | Sensor read -> key sent, over every sample |
| `gesture_latency_p50_ms` | The same, only for samples that fired a gesture |
| `jitter_ms` | Standard deviation of latency |
| `host_p50_ms` | Arrival -> key sent (exact; one clock) |
| `loss_pct` | From gaps in `seq` |
| `longest_gap_ms` | Longest time with no sample |
| `sample_rate_hz` | From the device clock |
| `clock_drift_ppm` | ESP32 clock against the PC clock |
| `interruptions`, `dropped`, `corrupt` | Reconnects; BLE queue overflow; damaged lines or packets |

Percentiles use every sample, not only gestures: gestures are too rare (a few per
minute) for a p99, and any sample could have been the one that fired.

Left out on purpose: p99.9, RFC 3550 jitter, reorder and duplicate counts, event-loop
lag. None changes a decision for a gesture controller at 50 Hz.

### Output

- **Exit summary**: three lines logged when the game page disconnects from the WebSocket
  and when the bridge stops.
- **Report**: `python report.py` -> one HTML file in `logs/reports/` with a summary
  table, three charts (distribution, over time, arrival spacing) and definitions.
  Charts are matplotlib SVG embedded in the page.

### HUD hooks (no HUD yet)

- `LatencyTracker.live()` -> `Summary` over the last `LIVE_WINDOW_S` (30 s).
- `Summary.to_dict()` is JSON-ready.
- `metrics.HUD_FIELDS` lists the fields a HUD would show; `metrics.METRICS` has their
  labels, units and definitions.
- `run()` already holds the tracker and the sinks, so a HUD feed is one periodic
  `tracker.live().to_dict()` sent through `WebSocketSink`.

### Also fixed along the way

- Firmware: `t_ms` is stamped before the sensor read; the loop steps `lastSample` by the
  period so the rate no longer drifts low. `FW_VERSION` is 2. No layout change.
- BLE transport: a full queue now drops the oldest sample (it dropped the newest) and
  counts it.

## Phase 1: browser frame and motion onset

- **Onset sample**: when a gesture fires, walk back through recent samples on that axis
  to the last one at rest (`GestureConfig.rest_threshold`). Record `onset_n`. Report
  latency from onset as well as from the trigger sample; the difference is detection
  delay, set by the thresholds in `tuning.toml`.
- **Gesture id**: add `gid` to the WebSocket message (additive; today's page ignores it).
- **Browser ack**: a small `frontend/src/latency.js` records receive time, the result of
  `game.handleMove()`, and the first `tick()` after it, then sends them back.
  `WebSocketSink` logs them. Needs Anish's agreement: the game is his.
- **Browser clock**: a few ping/pong exchanges over the same WebSocket; keep the one
  with the shortest round trip.
- **HUD**: fed from `tracker.live()`.

"First frame that reflects the sample" means the first `tick()` after `handleMove`
returned true. It marks the frame being drawn, not the display showing it; software
cannot see the display.

## Phase 2: absolute link latency

- Host sends a ping, firmware echoes it with its own clock. The midpoint gives the true
  offset, with an error of half the round trip.
- USB: a text line. BLE: a new characteristic. This changes the protocol, so
  `PROTOCOL_VERSION`, `protocol.h`, `protocol.py` and `protocol.md` change together.
- Log the BLE connection interval from the firmware. Requesting a shorter interval is
  the main Bluetooth latency lever.

## Limits

- Latency excludes the link's best-case transit time (until Phase 2) and everything
  after the bridge (until Phase 1).
- `t_ms` has 1 ms resolution, and marks when the ESP32 read the BNO055, not when the
  chip measured. The chip's own fusion delay is invisible.
- Bluetooth retries lost radio packets itself, so radio loss appears as latency spikes,
  not as missing samples.
- `fake` sessions time the PC only.
