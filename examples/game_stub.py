"""Minimal game loop showing how a game script consumes controller input.

    python examples/game_stub.py          # controller on USB
    python examples/game_stub.py ble      # controller over Bluetooth
    python examples/game_stub.py fake     # scripted gestures, no hardware
"""

import sys
import time

from wefit_bridge import Config, Controller


def main() -> None:
    config = Config(transport=sys.argv[1] if len(sys.argv) > 1 else "usb")

    with Controller(config) as controller:
        controller.reset()  # call at the start of every round
        lane = 0
        print(f"Reading the controller over {config.transport}. Ctrl+C to quit", flush=True)
        try:
            while True:
                for event in controller.poll():
                    if not event.pressed:
                        continue
                    if event.key == "left":
                        lane = max(lane - 1, -1)
                    elif event.key == "right":
                        lane = min(lane + 1, 1)
                    print(f"{event.key:<5}  lane={lane:+d}", flush=True)
                time.sleep(1 / 60)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
