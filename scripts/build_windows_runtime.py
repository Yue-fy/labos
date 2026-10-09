"""Build an offline Windows x64 Python runtime from upstream release and binary wheels."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip"
PYTHON_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"


def build():
    scratch = ROOT / "build" / "windows-runtime"
    scratch.mkdir(parents=True, exist_ok=True)
    original = scratch / "python.zip"
    if not original.exists():
        with urllib.request.urlopen(PYTHON_URL, timeout=60) as response:
            original.write_bytes(response.read())
    if hashlib.sha256(original.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise ValueError("official Python SHA-256 mismatch")
    wheels = scratch / "wheels"
    wheels.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                    "--platform", "win_amd64", "--python-version", "314", "--implementation", "cp",
                    "--abi", "cp314", "-r", str(ROOT / "src/labos/assets/requirements-agent.txt"),
                    "--dest", str(wheels)], check=True)
    output = ROOT / "dist/delivery/windows-x64-runtime.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = {"python": {"version": "3.14.8", "source": PYTHON_URL, "sha256": PYTHON_SHA256},
                  "wheels": []}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        with zipfile.ZipFile(original) as upstream:
            for name in upstream.namelist():
                if name.endswith("._pth"):
                    continue
                package.writestr("python/" + name, upstream.read(name))
        package.writestr("python/python314._pth", "python314.zip\n.\nLib/site-packages\n../src\nimport site\n")
        for wheel in sorted(wheels.glob("*.whl")):
            provenance["wheels"].append({"file": wheel.name,
                                         "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()})
            with zipfile.ZipFile(wheel) as distribution:
                for name in distribution.namelist():
                    if name.endswith("/"):
                        continue
                    if name.startswith("/") or ".." in name.split("/"):
                        raise ValueError("unsafe wheel path")
                    original_name = name
                    if ".data/" in name:
                        _, suffix = name.split(".data/", 1)
                        scheme, relative = suffix.split("/", 1)
                        if scheme not in {"purelib", "platlib"}:
                            continue
                        name = relative
                    package.writestr("python/Lib/site-packages/" + name, distribution.read(original_name))
        package.writestr("python/RUNTIME_PROVENANCE.json", json.dumps(provenance, indent=2))
    print(f"{output} ({output.stat().st_size:,} bytes; Windows execution not tested on this Linux host)")


if __name__ == "__main__":
    build()
