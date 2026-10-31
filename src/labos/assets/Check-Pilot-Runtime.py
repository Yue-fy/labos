"""Check physical-worker imports without opening a VISA or serial session."""

import importlib
from pathlib import Path
import sys
import traceback


def main():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
        for module in ("pyvisa", "serial", "labos.cryostat_pilot", "labos.pilot_worker"):
            importlib.import_module(module)
        print("Pilot runtime imports passed; no instruments opened.")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
