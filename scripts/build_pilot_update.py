"""Build the optional cryostat commissioning overlay with pinned pure Python wheels."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

from labos import __version__
from labos.delivery import write_package

ROOT = Path(__file__).resolve().parents[1]
WHEELS = {
    "pyvisa-1.16.2-py3-none-any.whl": "54f034adafd3e8d1858d57cdafec64e920444f4b84b31c9fd17487fbad0a197a",
    "pyserial-3.5-py2.py3-none-any.whl": "c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0",
}


def build(output, wheels_dir):
    output, wheels_dir = Path(output), Path(wheels_dir)
    payload = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        write_package(archive, "agent")
    with zipfile.ZipFile(buffer) as archive:
        for name in archive.namelist():
            if name in {"ROLE", "pyproject.toml"} or name.endswith(
                (".example.yaml", ".example.json")
            ):
                continue
            if "/" not in name and (
                Path(name).suffix not in {".py", ".ps1", ".cmd", ".md", ".json"}
                or name.endswith("_ZH.md")
            ):
                continue
            payload[name] = archive.read(name)
        # Only the disabled commissioning template is part of this update.
        payload["pilot-worker.example.yaml"] = archive.read("pilot-worker.example.yaml")
    for name, expected in WHEELS.items():
        content = (wheels_dir / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Physical wheel checksum mismatch: " + name)
        with zipfile.ZipFile(io.BytesIO(content)) as wheel:
            for member in wheel.namelist():
                path = PurePosixPath(member)
                if path.is_absolute() or ".." in path.parts or "\\" in member:
                    raise ValueError("Invalid wheel member")
                if not member.endswith("/"):
                    payload["python/Lib/site-packages/" + member] = wheel.read(member)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(payload.items()):
            archive.writestr("overlay/" + name, content)
        archive.write(ROOT / "src/labos/assets/Apply-Pilot-Update.py", "Apply-Pilot-Update.py")
        archive.write(
            ROOT / "src/labos/assets/PHYSICAL_PILOT_EN.md", "START_HERE_PHYSICAL_PILOT_EN.md"
        )
        archive.write(
            ROOT / "src/labos/assets/DARK_A_SHORT_TEST_EN.md", "START_HERE_DARK_A_EN.md"
        )
        archive.write(
            ROOT / "src/labos/assets/OPTICAL_READBACK_EN.md", "START_HERE_OPTICAL_READBACK_EN.md"
        )
        archive.write(wheels_dir / "MANIFEST.json", "PHYSICAL_DEPENDENCIES.json")
        archive.writestr(
            "payload-manifest.json",
            json.dumps(
                {
                    "version": __version__,
                    "files": {
                        name: hashlib.sha256(content).hexdigest()
                        for name, content in sorted(payload.items())
                    },
                },
                indent=2,
            )
            + "\n",
        )
    output.chmod(0o600)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wheels-dir", type=Path, default=ROOT / "dist/delivery/physical-wheels")
    args = parser.parse_args()
    result = build(args.output, args.wheels_dir)
    print(f"{result} ({result.stat().st_size:,} bytes)")
