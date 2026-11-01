"""Build an offline Windows x64 Python runtime from upstream release and binary wheels."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from labos.portable_archive import (
    ArchivePaths, preflight_outputs, private_stage, publish_outputs, validate_members,
)

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip"
PYTHON_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"


def build():
    output = ROOT / "dist/delivery/windows-x64-runtime.zip"
    preflight_outputs([output])
    scratch = ROOT / "build" / "windows-runtime"
    scratch.mkdir(parents=True, exist_ok=True)
    original = scratch / "python.zip"
    if not original.exists():
        with private_stage(original) as (staged, stream):
            with urllib.request.urlopen(PYTHON_URL, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != PYTHON_SHA256:
                raise ValueError("official Python SHA-256 mismatch")
            stream.write(data)
            stream.flush()
            stream.close()
            publish_outputs([(staged, original)])
    if hashlib.sha256(original.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise ValueError("official Python SHA-256 mismatch")
    provenance = {"python": {"version": "3.14.8", "source": PYTHON_URL, "sha256": PYTHON_SHA256},
                  "wheels": []}
    with TemporaryDirectory(prefix="fresh-", dir=scratch) as invocation:
        wheels = Path(invocation) / "wheels"
        wheels.mkdir()
        subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                        "--platform", "win_amd64", "--python-version", "314", "--implementation", "cp",
                        "--abi", "cp314", "-r", str(ROOT / "src/labos/assets/requirements-agent.txt"),
                        "--dest", str(wheels)], check=True)
        with private_stage(output) as (staged, stream):
            paths = ArchivePaths()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as package:
                with zipfile.ZipFile(original) as upstream:
                    for member in validate_members(upstream):
                        if member.filename.endswith("._pth"):
                            continue
                        name = "python/" + member.filename
                        paths.add(name, directory=member.is_dir())
                        package.writestr(name, upstream.read(member))
                name = "python/python314._pth"
                paths.add(name)
                package.writestr(name, "python314.zip\n.\nLib/site-packages\n../src\nimport site\n")
                distributions = set()
                for wheel in sorted(wheels.glob("*.whl")):
                    distribution_name = re.sub(r"[-_.]+", "-", wheel.name.split("-", 1)[0]).lower()
                    if distribution_name in distributions:
                        raise ValueError(f"multiple wheels for distribution: {distribution_name}")
                    distributions.add(distribution_name)
                    provenance["wheels"].append({"file": wheel.name,
                                                 "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()})
                    with zipfile.ZipFile(wheel) as distribution:
                        members = validate_members(distribution)
                        mapped = []
                        for member in members:
                            name = member.filename
                            parts = name.rstrip("/").split("/")
                            if parts[0].endswith(".data"):
                                if len(parts) < 2 or parts[1] not in {"purelib", "platlib"}:
                                    continue
                                name = "/".join(parts[2:])
                                if member.is_dir():
                                    name += "/" if name else ""
                            target = "python/Lib/site-packages/" + name
                            if paths.add(target, directory=member.is_dir()):
                                mapped.append((member, target))
                        for member, target in mapped:
                            package.writestr(target, distribution.read(member))
                name = "python/RUNTIME_PROVENANCE.json"
                paths.add(name)
                package.writestr(name, json.dumps(provenance, indent=2))
            stream.close()
            publish_outputs([(staged, output)])
    print(f"{output} ({output.stat().st_size:,} bytes; Windows execution not tested on this Linux host)")


if __name__ == "__main__":
    build()
