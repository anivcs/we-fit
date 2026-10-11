"""Write a latency report to logs/reports/ from the bridge's logs in logs/raw/.

    python report.py                 newest USB and newest Bluetooth session, side by side
    python report.py usb             newest session over one transport (usb, ble or fake)
    python report.py logs/raw/<file> a specific session; give several to compare them
"""

import sys


def main() -> int:
    try:
        from wefit_bridge.latency.report import main as report
    except ImportError as e:
        print(f"{e}. Run: pip install -r requirements.txt")
        return 1
    return report()


if __name__ == "__main__":
    sys.exit(main())
