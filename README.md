# we-fit

Motion Controlled Subway Surfer.

This branch holds the motion controller: an ESP32 with a BNO055 motion sensor, and a
Python program (the "bridge") that turns its movement into four arrow-key inputs:
`up`, `down`, `left`, `right`.

```
ESP32 + BNO055  ──USB cable or Bluetooth──>  Python bridge  ──>  arrow keys for the game
```

The repo also holds the browser game those inputs drive. Section 6 runs the two together.

The ESP32 only sends raw sensor readings. Python decides what counts as a gesture.

> **Status:** the Python side passes its tests against a simulated controller, and the
> firmware compiles. Nobody has run the USB or Bluetooth path against a real board
> yet, in either sensor mode. If a step below does not behave as described, that is
> new information.

## 1. Install (once per machine)

You need Python 3.11 or newer and git. The browser game (section 6) also needs Node.js.

```powershell
git clone https://github.com/anivcs/we-fit.git
cd we-fit
git checkout motion-controller

python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run
`Set-ExecutionPolicy -Scope Process RemoteSigned` first.

Check the install. This needs no hardware:

```powershell
python check.py logic
```

Every line should say `PASSED`.

## 2. Flash the ESP32 (once per board)

Wiring: BNO055 `SDA` to GPIO 21, `SCL` to GPIO 22, plus `VIN` and `GND`.

1. Plug the ESP32 into the laptop with a USB **data** cable. Charge-only cables do
   not work.
2. Build and upload:

   ```powershell
   pio run -d firmware -t upload
   ```

   The first run downloads the ESP32 compiler (several hundred MB). If it sits at
   `Connecting......`, hold the board's `BOOT` button until the upload starts.
3. Confirm the board is alive:

   ```powershell
   pio device monitor -d firmware -b 115200
   ```

   You should see `BNO055 CONNECTED!`, `BLE advertising as WeFit`, `READY`, and then
   a stream of lines starting with `S,`. Press `Ctrl+C` to close the monitor.

The same firmware serves both USB and Bluetooth. You do not re-flash to switch.

`pio run -d firmware -t upload` writes only the bootloader, partition table and the
program. If the build or upload fails oddly after editing `firmware/platformio.ini` or
changing branches, clear the local build cache and try again:

```powershell
pio run -d firmware -t clean
```

(or delete the `firmware/.pio/` folder; it is git-ignored and rebuilt on the next run).

If the laptop does not see the board at all, install the driver for its USB chip:
CP210x (Silicon Labs) or CH340 (WCH), whichever is printed on the board.

## 3. Wired test (USB)

This is the simplest way to check that everything works.

1. Plug the ESP32 in.
2. **Close the serial monitor** and anything else using the port. Only one program
   can open it at a time.
3. Run the USB checks:

   ```powershell
   python check.py usb
   ```

   The last check compares the ESP32's clock with the laptop's for 6 seconds and prints
   the result under `PASSES`, for example `ESP32 clock runs +40 ppm against this PC,
   and maps onto the PC clock to within 3.0 ms (p95)`. Nothing sets the ESP32's clock
   and you do not need to: the bridge works out the difference from the readings. The
   check fails only if the two clocks disagree badly (over 1 % drift or 100 ms spread).

4. Run the bridge:

   ```powershell
   python -m wefit_bridge --transport usb
   ```

   Opening the port restarts the board, so wait about 5 seconds. Then move the
   controller sharply left, right, up or down. Each movement prints two lines:

   ```json
   {"type": "key", "key": "left", "pressed": true, "t": 15180.5}
   {"type": "key", "key": "left", "pressed": false, "t": 15180.62}
   ```

   Press `Ctrl+C` to stop.

The port is found automatically. To choose it yourself, add `--port COM5`.

## 4. Bluetooth test

The ESP32 uses Bluetooth Low Energy. The Python program connects to it directly.

**Do not pair the ESP32 in your operating system's Bluetooth settings.** It will not
work better, and it can stop the program from connecting. If you already paired a
device called `WeFit`, remove it there first.

1. **Flash the board** over USB if you have not yet (section 2).
2. **Power the ESP32.** Any USB power works: the laptop, a power bank or a wall
   charger. It can stay plugged into the laptop; USB and Bluetooth work at the same
   time.
3. **Turn Bluetooth on.**
   - Windows: Settings > Bluetooth & devices > Bluetooth: On. Stop there. Do not
     click "Add device".
   - macOS: turn Bluetooth on, then allow your terminal app (Terminal, iTerm or
     VS Code) under System Settings > Privacy & Security > Bluetooth.
   - Linux: `bluetoothctl power on`. The BlueZ service must be running.
4. **Check that the laptop can see the board:**

   ```powershell
   python -m wefit_bridge --scan
   ```

   Expected output, with your own address:

   ```
   Bluetooth devices named 'WeFit' (scanning 8 s):
     address = A4:CF:12:DE:01:BC   signal = -52 dBm
   ```

5. **Run the Bluetooth checks.** They confirm that Bluetooth is on, the board is
   visible, readings arrive, and the ESP32's clock tracks the laptop's (same check as
   in section 3, over Bluetooth):

   ```powershell
   python check.py bluetooth
   ```

6. **Run the bridge:**

   ```powershell
   python -m wefit_bridge --transport ble
   ```

   Within about 10 seconds it logs `controller connected: A4:CF:12:DE:01:BC`. Move the
   controller and the same `key` lines appear as in the wired test. If the board
   loses power or goes out of range, the bridge reconnects by itself.

### If Bluetooth does not find the board

| Symptom | Cause and fix |
| --- | --- |
| `--scan` lists no `WeFit` | The board is unpowered or not flashed. Plug it in and look for `BLE advertising as WeFit` in the serial monitor. |
| It was visible, now it is not | Another laptop or phone is connected to it. The board accepts one connection at a time and hides while connected. Stop the other program. |
| `Bluetooth is off` | Turn Bluetooth on (step 3). A desktop PC may need a USB Bluetooth adapter. |
| Found, but cannot connect | Remove `WeFit` from the OS Bluetooth device list, then unplug and replug the board. |
| Several `WeFit` boards in the room | Pin yours by address, as described below. |

To pin one board: edit `bridge/config.toml` (it is tracked in git, so
clients share it), set `transport = "ble"`, and put the address from `--scan` under `[ble]`:

```toml
[ble]
name = "WeFit"
address = "A4:CF:12:DE:01:BC"
```

Then run `python -m wefit_bridge --config bridge/config.toml`. On macOS the address
is a long UUID instead of `AA:BB:...`; use it the same way.

## 5. Run all checks

```powershell
python check.py              # everything
python check.py logic        # code logic and installed packages; no hardware needed
python check.py usb          # is the ESP32 plugged in and sending readings?
python check.py bluetooth    # is Bluetooth on, is the ESP32 visible and sending?
```

Hardware checks fail when the hardware is absent. Each failure prints one sentence
saying what to do.

## 6. Play the browser game

Three things run on the laptop: the game page, the bridge, and a browser. No Docker is
needed. You also need [Node.js](https://nodejs.org) (current LTS) for the game page.

1. **Start the game page.** In one terminal:

   ```powershell
   cd frontend
   npm install          # first time only
   npm run dev
   ```

   Leave it running. It serves the game at `http://localhost:5173`.

2. **Start the bridge.** In a second terminal, with the venv activated and the ESP32
   powered (section 4):

   ```powershell
   python -m wefit_bridge --transport ble --sink websocket --sink console
   ```

   It logs `game WebSocket listening on ws://127.0.0.1:8765`, then
   `controller connected: ...` once it finds the board. `--sink console` also prints
   each gesture in the terminal, so you can see what the game is being sent.

   For the wired controller use `--transport usb`. With no board at all, use
   `--transport fake` to play scripted gestures.

   The bridge records the timing of every reading to `logs/raw/` (about 5 MB per hour).
   When you close the game tab, and again when you stop the bridge with `Ctrl+C`, it
   prints a short latency summary. To turn both off, add `--no-latency-log`:

   ```powershell
   python -m wefit_bridge --transport ble --sink websocket --sink console --no-latency-log
   ```

3. **Open the game** in a browser on the same laptop:

   ```
   http://localhost:5173/?controller=ws://localhost:8765
   ```

   The pill at the top reads `Controller: connected`. Jump (`up`) to start a run.
   `Backend: offline (scores not saved)` is expected here; the game plays normally.

The keyboard still works while the controller is connected: ← → lanes, ↑ or Space
jump, ↓ duck, P pause.

The game remembers a jump pressed up to 150 ms before you land and runs it as soon as you
touch down, so a slightly early jump is not lost. A duck cancels a pending jump. Change the
window with `jump_buffer_ms` in the `[game]` section of `tuning.toml` (0 turns it off, max
1000). The bridge sends it to the page each time the page connects, so after editing,
restart the bridge and the page picks it up on reconnect. Keyboard-only play, with no
bridge, uses the built-in 150 ms.

Each gesture reaches the game as one JSON message,
`{"move": "JUMP", "key": "up", "t": 15180.5}`, with `up`/`down`/`left`/`right` sent as
`JUMP`/`DUCK`/`LEFT`/`RIGHT`. Use `--ws-port` to change the port, and
`--ws-host 0.0.0.0` if the browser runs on another machine.

### Optional: save scores and show the leaderboard

The game only needs the backend for scores. Pick one way to run it; the pill changes
to `Backend: online` within 15 seconds.

- **Without Docker.** Scores go to a local SQLite file, `wefit.db`. In a third
  terminal, from the repo root with the venv activated:

  ```powershell
  pip install -r backend/requirements.txt      # first time only
  uvicorn api:app --app-dir backend --port 8000
  ```

- **With Docker and PostgreSQL**: `docker compose up -d --build`.

If the backend runs on another machine, add `&api=http://<backend-host>:8000/api/v1`
to the game URL.

## 7. Use it with another game

- **Any game that reads the keyboard.** This presses the real arrow keys; click the
  game window so it has focus:

  ```powershell
  python -m wefit_bridge --transport usb --sink keyboard
  ```

- **A Python game script.** Import the controller and poll it each frame:

  ```python
  from wefit_bridge import Config, Controller

  with Controller(Config(transport="ble")) as controller:   # or "usb"
      controller.reset()                  # at the start of each round
      for event in controller.poll():     # every frame; never blocks
          print(event.key, event.pressed)
  ```

  A runnable example: `python examples/game_stub.py usb` (or `ble`, or `fake` for no
  hardware).

- **Your own WebSocket controller for the browser game.** Anything that serves the
  same messages works with `?controller=ws://...`. It may send plain moves (`JUMP`,
  `DUCK`, `LEFT`, `RIGHT`), JSON (`{"move": "JUMP"}`), or raw accelerometer samples in
  g (`{"ax": 0.1, "ay": 2.3, "az": 0.0}`, +y up, +x right).

## Gestures and tuning

Move the controller sharply. Moves on different axes can be chained straight away, for
example a jump (`up`) followed at once by a lane change (`left` or `right`).

All the numbers are in [`tuning.toml`](tuning.toml) at the repo root. Edit it, save,
and restart the bridge; there is nothing to re-flash and no flag to pass. The bridge
logs the file and profile it loaded, for example `gesture tuning: ...\tuning.toml [ble]`.

The file has two profiles, `[usb]` for the cable and `[ble]` for Bluetooth, so each
connection can be tuned separately. Each profile has one row per direction:

```toml
[ble]
rest_threshold = 1.0
up    = { threshold = 7.0, rest_ms = 150, cooldown_ms = 500 }
down  = { threshold = 4.0, rest_ms = 150, cooldown_ms = 500 }
left  = { threshold = 4.0, rest_ms = 150, cooldown_ms = 500 }
right = { threshold = 4.0, rest_ms = 150, cooldown_ms = 500 }
```

| Setting | Meaning | If the controller... |
| --- | --- | --- |
| `threshold` (m/s²) | Acceleration that counts as this gesture. | ...misses moves: lower it. ...fires by accident: raise it. |
| `rest_ms` | How long that axis must be still before this direction can fire. It stops the jolt at the end of a jump from reading as a duck. | ...adds a phantom opposite move: raise it. ...misses a quick `up` then `down`: lower it. |
| `cooldown_ms` | Minimum time between two gestures in this same direction. | ...cannot repeat a move fast enough: lower it. ...double-fires: raise it. |
| `rest_threshold` (m/s²) | Below this an axis counts as still. One value per profile. | ...stops responding in a shaky hand: raise it. |

The shipped values are the same in both profiles: `up` needs 7.0 m/s² along +Z, and
`down` (−Z), `right` (+X) and `left` (−X) need 4.0 m/s². A gesture on the other axis is
never delayed, so `up` then `left` fires at once.

**Orientation.** If the sensor is mounted differently, set which sensor axis points to
the player's right and which points up. This applies to both profiles:

```toml
[orientation]
right = "+x"     # "+x" "-x" "+y" "-y" "+z" "-z"
up    = "+z"     # must be a different axis from `right`
```

Left and right swapped: change `"+x"` to `"-x"`. Up and down swapped: change `"+z"` to
`"-z"`. The comments in the file say how to find the axes from the serial monitor.

A misspelt setting or an invalid value stops the bridge with one line naming the file
and the setting. `python check.py logic` also checks the file. `--transport fake`
ignores the file and uses fixed values.

With the WebSocket sink every gesture arrives, so a chained `up` + `right` reaches the
game as two moves. With the keyboard sink, only one key is down at a time, so the first
key is released as soon as the second is pressed.

## Fusion mode and ground-referenced gestures

Needs firmware version 3: re-flash once with `pio run -d firmware -t upload` (section 2).

| Command | Sensor mode | Directions come from |
| --- | --- | --- |
| `python -m wefit_bridge --transport usb` | `fusion_mode` in `tuning.toml` (default `"imu"`) | `[orientation]` in `tuning.toml` |
| `python -m wefit_bridge --transport usb --gravity` | NDOF, always | gravity, plus one shuffle to the right at startup |

Use `--transport ble` for Bluetooth. Every other flag (`--sink`, `--port`, ...) works
with both.

**Which sensor mode is used**, highest authority first:

1. `--gravity` on the command line: always NDOF.
2. `fusion_mode = "imu"` or `"ndof"`, the first setting in [`tuning.toml`](tuning.toml).
3. Neither: IMU.

IMU combines the accelerometer and gyroscope. NDOF adds the magnetometer, which keeps
left and right from drifting but is disturbed by magnets, speakers and battery banks.

**At startup** the bridge prints one line per check, and gestures start after the last one.

| Check | IMU | NDOF | `--gravity` | What you do |
| --- | --- | --- | --- | --- |
| Fusion mode | yes | yes | yes | nothing |
| Calibration | reported, no waiting | yes | yes | hold still, then draw a figure 8 if asked |
| Magnetic field | skipped | yes | yes | nothing; a warning names what to move away |
| World reference | skipped | skipped | yes | hold still, then shuffle right once when asked |

Prompts look like `>>> Shuffle RIGHT once, quickly.` A warning does not stop the bridge.
A strong magnetic field during play is logged and nothing else happens.

If the world reference cannot be set, the bridge stops and prints the same command
without `--gravity`, which runs with the fixed orientation instead.

The limits behind these checks are in the `[gravity]` table of `tuning.toml`. To try
it with no board: `python -m wefit_bridge --transport fake --gravity`.

## Layout

```
tuning.toml   gesture thresholds, delays and sensor orientation
firmware/     ESP32 code (PlatformIO)
bridge/       Python package wefit_bridge, and its tests
frontend/     the browser game (Three.js, Vite)
backend/      optional score and leaderboard API (FastAPI)
examples/     game_stub.py
check.py      runs the bridge checks
report.py     writes a session report
logs/         raw/ sensor and timing logs, runs/ gesture histories (neither in git),
              reports/ session reports (in git)
firstiterationsubwaysurfers/   original Arduino sketch; the gesture logic came from here
```

Other tests: `uv run pytest` (backend) and `cd frontend && npm test`.

## Session report

Each bridge run is a session. It logs timing and sensor values to `logs/raw/` and its
gesture history to `logs/runs/`, one line per gesture. Turn the logs into a report with:

```powershell
python report.py
```

It writes one HTML file to `logs/reports/` and prints its path. Open it in a browser.

| Command | Report covers |
| --- | --- |
| `python report.py` | The newest USB session and the newest Bluetooth session, side by side |
| `python report.py usb` | The newest session over one connection: `usb`, `ble` or `fake` |
| `python report.py logs/raw/<file>.bin` | That session; give several files to compare them |

The report reads top to bottom:

1. **Session**: USB or Bluetooth, IMU or NDOF, the startup check results, gesture counts
   and a rough calorie estimate for a 70 kg person.
2. **Tuning**: how hard each movement was against its threshold in `tuning.toml`, per
   direction and per connection, including movements that almost fired.
3. **Debug**: calibration, tilt error, heading drift and magnetic field over time.
4. **Latency**: a summary table and three charts.

Every time in the report counts from when the bridge started. `--no-latency-log` turns
all of this logging off.

What the numbers mean:

- **Input latency** is the time from the ESP32 reading the sensor to the bridge sending
  the key to the game. The browser's drawing time is not measured yet.
- It is measured **above the connection's best case**. The ESP32 and the laptop have
  separate clocks, so the bridge compares each reading with the fastest ones it has seen.
  The connection's fixed minimum delay is not included.
- **Jitter** is how much the latency varies. **Loss** is readings that never arrived.

Raw logs in `logs/raw/` stay on your machine; git ignores them. Reports in
`logs/reports/` are meant to be committed. To try it with no board, run
`python -m wefit_bridge --transport fake` for half a minute, stop it, then
`python report.py fake`.
