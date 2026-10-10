"""Run the checks.

    python check.py              everything
    python check.py logic        code logic + installed packages (no hardware)
    python check.py usb          ESP32 on a USB cable
    python check.py bluetooth    ESP32 over Bluetooth
"""

import sys
from pathlib import Path

GROUPS = {
    "logic": "not usb and not bluetooth",
    "usb": "usb",
    "bluetooth": "bluetooth",
}


def main() -> int:
    try:
        import pytest
    except ImportError:
        print("pytest is not installed. Run: pip install -r requirements.txt")
        return 1

    group = sys.argv[1] if len(sys.argv) > 1 else None
    if group is not None and group not in GROUPS:
        print(__doc__)
        return 2

    args = [str(Path(__file__).parent / "bridge" / "tests"), "-v", "--tb=short"]
    if group is not None:
        args += ["-m", GROUPS[group]]
    return pytest.main(args)


if __name__ == "__main__":
    sys.exit(main())
