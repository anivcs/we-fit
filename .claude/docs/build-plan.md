# Build plan

## Done

- Spec for a single controller (USB or BLE) and a single-player game.
- Bridge: protocol, gestures (ported from the sketch at 04c71fc, incl. `down` and the
  return-to-rest gate), keys, pipeline, console and keyboard sinks, `Controller`
  facade, CLI with `--scan`.
- Transports: fake (working), USB serial and BLE (written, untested on hardware).
- Firmware: BNO055 setup from the prototype, BLE GATT server, USB sample lines,
  50 Hz loop. Compiles.
- Checks: `python check.py` (logic + packages + USB + Bluetooth).
- `requirements.txt` and README setup instructions for another machine.

## M1 — Wired bring-up (next)

- Flash: `pio run -d firmware -t upload`. Confirm `BNO055 CONNECTED!`, `READY` and
  `S,` lines in the serial monitor.
- `python check.py usb`, then `python -m wefit_bridge --transport usb -v`.
- Compare with the sketch: the same motions should give the same directions.
- Watch for: port auto-detection picking the right COM port, the board's reset on
  port open, and garbled lines when log messages interleave.
- Done when: all `usb` checks pass and gestures print the right keys.

## M2 — Bluetooth bring-up

- `python -m wefit_bridge --scan`, `python check.py bluetooth`,
  `python -m wefit_bridge --transport ble -v`.
- Check reconnect: power-cycle the controller, and separately restart the bridge.
- Correct the README's Bluetooth section wherever reality differs from it.
- Done when: all `bluetooth` checks pass and the bridge survives a power cycle.

## M3 — Tune gestures

- Add a recorder (samples to a file) and a replay transport, so thresholds are tuned
  against recorded motion.
- Keep `gestures.py` in step with the teammates' sketch, or agree that the TOML
  config is now the place to tune and retire the sketch.
- Done when: 20 deliberate gestures in each direction give 20 correct key taps and
  no false ones.

## M4 — Hand over to the game

- Agree with the game team: keyboard sink or in-process `Controller`.
- Measure end-to-end latency (motion to key event) on both transports.
- Done when: the game is playable with the controller.

## Open questions

| # | Question | Default assumed | Who decides |
| --- | --- | --- | --- |
| 1 | Is the game a Python script (use `Controller`) or the browser frontend from the backend branch (use the keyboard sink)? | Both supported | Game team |
| 2 | In keyboard-sink mode the game cannot call `reset()`. Is a reset hook needed there? | No; gestures do not depend on drift | Game team |
| 3 | Tap with auto-release, or key held for the duration of the motion? | Tap, 120 ms | Game team |
| 4 | Exact ESP32 board model and its USB chip | `esp32dev` | Us |
| 5 | Who owns gesture tuning from here: the sketch or the bridge config? | Bridge config | Us + sketch author |
| 6 | Battery power and enclosure | Out of scope | Us |
| 7 | The backend diagram names an MPU6050; hardware is a BNO055 | BNO055 | Us, tell the backend team |
