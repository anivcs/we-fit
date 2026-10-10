# we-fit

Motion Controlled Subway Surfer.

This branch holds the motion controller: an ESP32 with a BNO055 motion sensor, and a
Python program (the "bridge") that turns its movement into four arrow-key inputs:
`up`, `down`, `left`, `right`.

```
ESP32 + BNO055  ──USB cable or Bluetooth──>  Python bridge  ──>  arrow keys for the game
```

The ESP32 only sends raw sensor readings. Python decides what counts as a gesture.

> **Status:** the Python side passes its tests against a simulated controller, and the
> firmware compiles. Nobody has run the USB or Bluetooth path against a real board
> yet. If a step below does not behave as described, that is new information.

## 1. Install (once per machine)

You need Python 3.11 or newer and git.

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
   visible, and readings arrive:

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

To pin one board: copy `bridge/config.example.toml` to `bridge/config.toml`, set
`transport = "ble"`, and put the address from `--scan` under `[ble]`:

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

## 6. Use it with a game

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

## Gestures

Move the controller sharply, then hold it still for a moment before the next move.

| Key | Motion | Threshold |
| --- | --- | --- |
| `up` | acceleration along +Z | 7.0 m/s² |
| `down` | acceleration along −Z | 4.0 m/s² |
| `right` | acceleration along +X | 4.0 m/s² |
| `left` | acceleration along −X | 4.0 m/s² |

Only one key is ever down at a time. After a gesture, the next one needs 150 ms of
stillness and at least 500 ms since the last. To change these numbers, edit
`[gestures]` in `bridge/config.toml`; no re-flash is needed.

## Layout

```
firmware/     ESP32 code (PlatformIO)
bridge/       Python package wefit_bridge, and its tests
examples/     game_stub.py
check.py      runs the checks
firstiterationsubwaysurfers/   original Arduino sketch; the gesture logic came from here
```
Motion Controlled Subway Surfer

## Running locally

1. Backend + PostgreSQL: `docker compose up -d --build` (API at `http://localhost:8000/api/v1`).
2. Frontend: `cd frontend && npm install && npm run dev`, then open `http://localhost:5173` on the display device.

Frontend URL options:
- `?api=http://<backend-host>:8000/api/v1` if the backend isn't on the same host as the page.
- `?controller=ws://<esp32-ip>:81` to connect the ESP32 over WebSocket. It may send plain moves (`JUMP`, `DUCK`, `LEFT`, `RIGHT`), JSON (`{"move": "JUMP"}`), or raw accelerometer samples in g (`{"ax": 0.1, "ay": 2.3, "az": 0.0}`, +y up, +x right).

Keyboard fallback: ← → lanes, ↑ / Space jump, ↓ duck, P pause.

Tests: `uv run pytest` (backend) and `cd frontend && npm test`.
