"""Check a delivery's runtime locally, without configuration or device access.

Use a file instead of Python -c: Windows PowerShell 5.1 removes embedded
double quotes when passing an inline program to a native executable.
"""

import argparse
import importlib
from pathlib import Path
import sqlite3
import struct
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("agent", "central"), required=True)
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 11):
            raise RuntimeError("Python 3.11 or newer is required")
        root = Path(__file__).resolve().parent
        if not (root / "src/labos/__main__.py").is_file():
            raise RuntimeError("Package source is missing; extract the entire ZIP first")
        sys.path.insert(0, str(root / "src"))
        modules = ["ssl", "pydantic", "httpx", "yaml", "labos.cli", "labos.agent"]
        if args.role == "central":
            modules.extend(["fastapi", "uvicorn", "h5py", "labos.central"])
        for name in modules:
            importlib.import_module(name)
        with sqlite3.connect(":memory:") as connection:
            connection.execute("SELECT 1").fetchone()
        print(f"Python {sys.version.split()[0]} ({struct.calcsize('P') * 8} bit)")
        print(f"LabOS {args.role} runtime OK (local imports and SQLite; no device access)")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
