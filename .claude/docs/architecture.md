# Architecture — input pipeline

## Data flow

```
 ESP32 + BNO055                         firmware/
   | read linear accel + quaternion at 50 Hz
   | USB serial text line  AND  BLE notification (20 bytes)
   v
 transport   usb (pyserial) | ble (bleak) | fake
   |                                    bridge/src/wefit_bridge/transport/
   | Sample
   v
 gestures    thresholds + cooldown      gestures.py
   | "up" | "down" | "left" | "right"
   v
 keys        one key at a time,         keys.py
   |         auto-release
   | KeyEvent(key, pressed, t)
   v
 sinks  ──>  console  (JSON lines)      sinks/
        ──>  keyboard (real OS arrow keys)
        ──>  Controller.poll() / .state()   client.py, for a Python game script
```

Everything runs on the machine that runs the game. There is no network and no server.

## Division of work: firmware vs Python

| | Firmware (C++) | Bridge (Python) |
| --- | --- | --- |
| Talks to the BNO055 | yes | no |
| Sensor fusion, gravity removal | BNO055 chip does it | no |
| Decides what a gesture is | **no** | **yes** |
| Thresholds, cooldown | none | `GestureConfig`, set in TOML |
| Arrow-key rules | none | `KeyState` |

The prototype `.ino` did detection on the ESP32 and printed text to USB serial. That
logic now lives in `gestures.py`; the firmware kept only the sensor setup. The
alternative (detect on the ESP32, send one byte per gesture) was rejected because
every threshold change would need a reflash, and `down` is not tuned yet.

## Repo layout

```
we-fit/
├── .claude/                      project context
├── firmware/                     PlatformIO project (Arduino framework, esp32dev)
│   ├── platformio.ini            board, libs (Adafruit BNO055), monitor speed
│   ├── include/
│   │   ├── config.h              pins, I2C clock, sample rate, firmware version
│   │   └── protocol.h            BLE UUIDs, packed structs, scale factors
│   └── src/main.cpp              BNO055 init, BLE GATT server, 50 Hz notify loop
├── bridge/
│   ├── pyproject.toml            deps: bleak; extras: keyboard (pynput), dev (pytest)
│   ├── config.example.toml       transport, sinks, key hold, gesture thresholds
│   ├── src/wefit_bridge/
│   │   ├── __init__.py           exports Controller, Config, load_config, KeyEvent, KEYS
│   │   ├── __main__.py           CLI: python -m wefit_bridge
│   │   ├── config.py             Config dataclass + TOML loader
│   │   ├── protocol.py           UUIDs, struct formats, Sample, decode/encode
│   │   ├── events.py             KeyEvent, KEYS
│   │   ├── gestures.py           GestureDetector: accel -> up/down/left/right
│   │   ├── keys.py               KeyState: one key at a time, auto-release
│   │   ├── pipeline.py           Pipeline (sync core) + run() (asyncio driver)
│   │   ├── client.py             Controller: blocking facade on a background thread
│   │   ├── transport/
│   │   │   ├── __init__.py       make_transport(config)
│   │   │   ├── usb.py            find the ESP32's serial port, read sample lines, reopen on loss
│   │   │   ├── ble.py            scan, connect, version check, notify, reconnect
│   │   │   └── fake.py           scripted gestures, no hardware
│   │   └── sinks/
│   │       ├── __init__.py       Sink protocol, make_sink(name)
│   │       ├── console.py        JSON lines to stdout
│   │       └── keyboard.py       presses real arrow keys via pynput
│   └── tests/
│       ├── test_protocol.py, test_gestures.py, test_keys.py, test_pipeline.py   logic
│       └── test_setup.py         sanity checks: packages, USB, Bluetooth
├── examples/
│   └── game_stub.py              minimal game loop using Controller
├── check.py                      one command for all checks (or logic | usb | bluetooth)
├── requirements.txt              top-level deps + editable install of bridge/
├── README.md                     setup instructions for another machine
└── firstiterationsubwaysurfers/  original Arduino IDE prototype, reference only
```

## How the game gets input

Two options; both are implemented. The game team picks one.

1. **Keyboard sink.** Run `python -m wefit_bridge --sink keyboard` next to the game.
   The bridge presses the real arrow keys, so any game that already reads the keyboard
   works with no code changes, including a browser game (the backend branch's diagram
   shows an HTML + Three.js frontend). The game window must have focus. There is no
   reset hook in this mode.
2. **In-process.** A Python game script imports the bridge:

   ```python
   from wefit_bridge import Controller

   with Controller() as controller:
       controller.reset()                 # start of each round
       for event in controller.poll():    # each frame; never blocks
           ...                            # event.key, event.pressed
       controller.state()                 # {"up": False, "down": False, "left": True, "right": False}
   ```

## Output contract: arrow keys

- Keys: exactly `up`, `down`, `left`, `right`. Each is boolean.
- **One key at a time.** The detector picks the dominant axis, so one motion cannot
  produce two gestures. If a gesture fires while a key is down, the bridge emits the
  release first, then the new press.
- A gesture is a **tap**: press, then automatic release after `key_hold_ms` (120 ms).
- After a gesture the detector re-arms only when all axes have stayed under
  `rest_threshold` (1.0 m/s²) for `rest_ms` (150 ms), and at least `cooldown_ms`
  (500 ms) has passed. The rest gate is what rejects the opposite-direction spike
  when a motion stops (an `up` swing ends with a −Z jolt that would otherwise read
  as `down`). This logic and its numbers come from the teammates' sketch.
- A lost BLE link cannot leave a key stuck: the release timer runs independently of
  incoming samples, and shutdown releases any held key.

Event shape from the console sink:

```json
{"type": "key", "key": "left", "pressed": true,  "t": 15180.5}
{"type": "key", "key": "left", "pressed": false, "t": 15180.62}
```

`t` is the host's monotonic clock in seconds, useful only for differences.

## Drift and per-round reset

- The BNO055 runs in `IMUPLUS` (no magnetometer), so heading drifts over time.
- The game resets each round by calling `Controller.reset()`. It releases any held
  key, clears the cooldown, and stores the current quaternion as `reference_quat`.
- Gestures use sensor-frame linear acceleration, so drift does not affect them.
  `reference_quat` is captured for future orientation-based gestures; nothing reads it yet.
- The player must hold the controller the same way each round, because the axes are
  fixed to the sensor.

## USB notes

- The wired path exists to test the sensor and gesture logic with the fewest moving
  parts. It is the default transport.
- The port is auto-detected by USB vendor ID (CP210x, CH340/CH9102, FTDI, Espressif).
  Windows also lists "Standard Serial over Bluetooth link" COM ports; those have no
  vendor ID and are skipped.
- Only one program can hold the port. The serial monitor must be closed first.
- pyserial is blocking; `usb.py` reads lines with `asyncio.to_thread`.

## Bluetooth notes

- **BLE, not Bluetooth Classic.** Works on every ESP32 variant (S3 and C3 have no
  Classic), needs no OS pairing or COM port, and `bleak` supports Windows, macOS and
  Linux.
- Firmware uses the BLE library built into the ESP32 Arduino core; no extra dependency.
- The host must NOT pair the device in OS Bluetooth settings; `bleak` connects
  directly. The board accepts one connection and stops advertising while connected.
- The controller advertises as `WeFit`. With a single controller the bridge finds it
  by name. If several are powered on in the same room, set `[ble] address` in the
  config to pick one.
- 20-byte packets fit the default BLE MTU, so no MTU negotiation is required.
- Expected latency is one connection interval plus one sample period, roughly
  30-50 ms. Not measured yet.
