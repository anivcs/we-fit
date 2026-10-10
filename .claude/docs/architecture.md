# Architecture — controller pipeline

## Data flow

```
 ESP32 + BNO055  (x N, identical firmware)
   | sample IMU at 50 Hz
   | UDP datagram, 60 bytes, unicast to bridge :4210
   v
 Python bridge (one process on the game host, asyncio)
   transport  ->  registry  ->  gesture detector  ->  publisher
   (decode)      (device ->     (per controller)      (pluggable)
                  player slot)
   |
   v
 Game server  — BLACK BOX, not ours. Interface unknown.
```

The bridge runs on the same machine as the game (the "Local HDMI Display Device" in
the backend branch's architecture diagram) or anywhere on the same LAN.

## What the other team has said so far

From `origin/infra/backend` (not merged into this branch):

- Diagram shows controller → display device over "UDP / WebSockets - Local Network".
- Planned REST endpoint `POST game/sync/` with payload `session id, movement type`.
  This suggests the game wants **discrete movement events**, not raw IMU streams.
  Our arrow-key contract is compatible: `movement type` maps to `up/down/left/right`.
- Their diagram names an MPU6050. Our hardware is a **BNO055**. Unresolved mismatch;
  it only matters to us (the BNO055 does fusion on-chip, the MPU6050 does not).

None of this is a contract. Keep the publisher swappable.

## Repo layout (planned)

```
we-fit/
├── .claude/                      project context (this directory)
├── firmware/                     PlatformIO project
│   ├── platformio.ini            env:esp32dev, framework=arduino, monitor_speed=115200
│   ├── include/
│   │   ├── config.h              pins, sample rate, UDP port, timeouts
│   │   └── secrets.h.example     WIFI_SSID / WIFI_PASS template (real file gitignored)
│   ├── src/
│   │   └── main.cpp              setup + non-blocking loop, wires the libs together
│   ├── lib/
│   │   ├── imu/                  BNO055 probe (0x28/0x29), init, read into ImuReading
│   │   ├── net/                  Wi-Fi connect/reconnect, discovery, UDP send
│   │   └── protocol/             protocol.h — packed structs, mirrors docs/protocol.md
│   └── test/                     native unit tests for packet packing (optional)
├── bridge/
│   ├── pyproject.toml            requires-python >=3.11, no runtime deps in core
│   ├── config.example.toml       listen port, player map, gesture thresholds, publisher
│   ├── src/wefit_bridge/
│   │   ├── __main__.py           CLI entry point
│   │   ├── config.py             tomllib loader -> dataclasses
│   │   ├── protocol.py           struct formats, decode/encode, mirrors protocol.h
│   │   ├── transport.py          asyncio DatagramProtocol, discovery replies, heartbeats
│   │   ├── registry.py           device_id -> ControllerState, player slots, timeouts, loss stats
│   │   ├── gestures.py           per-controller detector -> up/down/left/right (thresholds + cooldown)
│   │   ├── keys.py               arrow-key state machine: one key at a time, auto-release, reset
│   │   ├── control.py            reset command channel (UDP 4211, JSON)
│   │   ├── events.py             outbound models: KeyEvent, ControllerStatus, ImuSample (debug)
│   │   └── publishers/
│   │       ├── base.py           Publisher protocol: async publish(event), start(), close()
│   │       ├── console.py        prints JSON lines — default until the game API is known
│   │       └── ...               udp_json / websocket / http added when needed
│   └── tests/                    protocol round-trip, registry, gestures on recorded data
├── tools/
│   └── fake_controller.py        emits valid packets for N fake devices
└── legacy/
    └── firstiterationsubwaysurfers/   original Arduino IDE sketch
```

## Component responsibilities

### Firmware

- Probe and initialise the BNO055 exactly as the prototype does.
- Join Wi-Fi; reconnect in the background if it drops.
- Discover the bridge: broadcast `HELLO` once per second until an `ACK` arrives,
  then unicast `SAMPLE` packets to the ACK's source address.
- Fall back to discovery if no `ACK` heartbeat is seen for 3 s.
- Sample on a fixed schedule using `millis()`, not `delay()`. Never block on the network.
- Keep serial output for debug only (boot banner, state changes, calibration status).
- Device id is the station MAC. No per-unit configuration.

### Bridge

- **transport** — one UDP socket. Validates magic + version + length, drops anything
  else. Answers `HELLO` with `ACK`, and sends a 1 Hz `ACK` heartbeat to each live device.
- **registry** — owns per-controller state keyed by device id: player slot, address,
  last seen, last sequence number, packet-loss counter. Assigns player slots from the
  config map first, then first-come for unknown devices. Marks a controller
  disconnected after 2 s of silence and frees or holds its slot (config choice).
- **gestures** — one detector instance per controller, so cooldowns and filters never
  leak between players. Starts as a port of the prototype's logic (up/left/right) plus
  `down` as the mirror of `up`. Orientation-based gestures can be added later using
  the quaternion.
- **keys** — turns detected gestures into boolean key press/release events, enforcing
  one key at a time and the auto-release timer.
- **control** — accepts `reset` and applies it to the registry, detectors and keys.
- **publishers** — receive key and status events tagged with player number. The only
  module that knows anything about the game server.

## Multi-controller concerns

| Concern | Approach |
| --- | --- |
| Telling controllers apart | MAC in every packet; never rely on source IP/port |
| Player numbering | `device_id -> player` map in `config.toml`; join order as fallback |
| Stable numbering across reboots | Use the config map; MAC survives reboot, DHCP lease may not |
| Packet loss / reorder | `seq` per device; drop stale packets, count gaps, never retransmit |
| One controller flooding | Per-device state and bounded queues; a slow publisher drops raw samples, never key events |
| Stuck keys | Auto-release timer, plus forced release on disconnect and on reset |
| Clock differences | Device `t_ms` is used only for per-device deltas; bridge stamps arrival time |
| Disconnects | Timeout in registry -> `ControllerStatus` event to the publisher |

Bandwidth is not a concern: 4 controllers x 50 Hz x 60 bytes is about 12 kB/s.

## Output contract: arrow keys

The game-facing interface behaves like a keyboard with four arrow keys.

- Keys: exactly `up`, `down`, `left`, `right`. Each is boolean: pressed or released.
- **One key at a time per controller.** No diagonals, no chords. If a new gesture
  fires while another key is down, the bridge emits the release first, then the new
  press (latest wins). The detector also picks one dominant axis, so two gestures
  cannot fire from one motion.
- Subway Surfers moves are discrete taps, so a detected gesture is a **press followed
  by an automatic release** after `key_hold_ms` (default 120 ms, configurable). The
  game never has to track held keys.
- The 1000 ms cooldown from the prototype stays as a per-controller default; tune it
  per gesture once on hardware.
- Assumption to confirm: the one-at-a-time rule applies per controller, so two players
  can each have a key down at the same time.

Events (proposal to the game team, not agreed):

```json
{"type": "key", "player": 1, "key": "left", "pressed": true,  "t": 1760000000.123}
{"type": "key", "player": 1, "key": "left", "pressed": false, "t": 1760000000.243}
{"type": "status", "player": 1, "device": "a4cf12de01bc", "state": "connected"}
```

A state snapshot is also available for polling consumers:
`{"player": 1, "up": false, "down": false, "left": true, "right": false}`.
At most one field is true.

Raw samples (quaternion, linear acceleration, gyro) are an optional debug stream,
off by default, not part of the game contract.

When a controller disconnects, the bridge releases any held key before emitting
`status: disconnected`, so a dropped controller can never leave a key stuck down.

## Drift and per-round reset

- The BNO055 runs in `IMUPLUS` (no magnetometer), so heading drifts over time.
- The game resets this each round. The bridge provides the hook:
  `reset(player: int | None)`. It captures the current quaternion as the new reference
  orientation, clears filters and cooldowns, and releases any held key. `None` means
  all controllers.
- Gestures use sensor-frame linear acceleration with gravity removed by the BNO055,
  so heading drift does not affect `up/down/left/right` detection. Reset matters for
  orientation-derived values and for starting each round from a clean state.
- Players must hold or mount the controller in the same orientation every round;
  axes are fixed to the sensor frame.
- How the game triggers `reset` is open. Proposed: a small control channel on the
  bridge (UDP port 4211, JSON `{"cmd": "reset", "player": 1}`), or a method call if
  the publisher ends up in-process with the game. No firmware or wire-protocol change
  is needed for it.

## Network: phone hotspot

- The bridge host and every ESP32 join one phone's mobile-data Wi-Fi hotspot.
- The ESP32 is 2.4 GHz only. Set the hotspot to 2.4 GHz (on iPhone, enable "Maximize
  Compatibility"), or the controllers will not see it.
- Phones typically hand out addresses in a small private range and cap the number of
  connected clients (often 5-10, fewer on some iPhones). Count the bridge host
  against that cap.
- Some hotspots filter broadcast. Firmware therefore supports a configured
  `BRIDGE_HOST` that skips discovery. Give the bridge host a fixed or noted address.
- Mobile data is not used for game traffic; all of it stays on the hotspot LAN, so
  latency is local Wi-Fi latency (typically a few ms, with occasional spikes).
- Keep each controller's Wi-Fi power save off (`WiFi.setSleep(false)`) to avoid
  latency spikes of 100 ms or more.
