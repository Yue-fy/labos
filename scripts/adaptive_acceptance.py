"""Execute reproducibility and moved-peak acceptance through real loopback TCP."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import h5py

from labos.demo import acceptance
from labos.files import atomic_write


def verify(directory: Path) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    reports = []
    for name, peak in (("repeat-a", 635), ("repeat-b", 635), ("moved-peak", 707)):
        print(f"Running {name}: hidden simulated resonance {peak} nm", file=sys.stderr, flush=True)
        reports.append(acceptance(directory / name, adaptive=True, resonance_nm=peak, seed=42))
    first, repeated, moved = reports
    assert first["rounds"] == repeated["rounds"], "seeded policy decisions were not repeatable"
    with h5py.File(first["hdf5"]) as a, h5py.File(repeated["hdf5"]) as b:
        assert (a["raw/counts"][:] == b["raw/counts"][:]).all(), "seeded spectra changed"
        assert (a["raw/wavelength_nm"][:] == b["raw/wavelength_nm"][:]).all()
    assert first["rounds"][0]["plan"] == moved["rounds"][0]["plan"]
    assert first["rounds"][1]["plan"] != moved["rounds"][1]["plan"], "refinement ignored measured data"
    assert first["detected_peak_nm"] == 635 and moved["detected_peak_nm"] == 707
    result = {"status": "PASS", "simulated": True, "reproducibility": "identical spectra and decisions",
              "moved_peak": "635 -> 707 nm changed subsequent scan ranges", "runs": reports}
    atomic_write(directory / "adaptive-acceptance.json", json.dumps(result, indent=2).encode())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args(argv)
    directory = args.directory or Path(tempfile.mkdtemp(prefix="labos-adaptive-"))
    result = verify(directory)
    print(json.dumps({"status": result["status"], "report": str(directory / "adaptive-acceptance.json"),
                      "peaks_nm": [r["detected_peak_nm"] for r in result["runs"]]}, indent=2))


if __name__ == "__main__":
    main()
