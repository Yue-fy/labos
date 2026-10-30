from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

from labos import __version__
from labos.delivery import write_package

ROOT = Path(__file__).resolve().parents[1]


def build_release(output: Path, windows_runtime: Path | None = None) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for role in ("central", "agent"):
        path = output / f"LabOS-{role.title()}-{__version__}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            write_package(package, role)
            package.write(ROOT / "README.md", "README.md")
            for doc in (ROOT / "docs").glob("*_ZH.md"):
                if doc.name not in package.namelist():
                    package.write(doc, doc.name)
                package.write(doc, "docs/" + doc.name)
            if role == "central" and windows_runtime:
                package.write(windows_runtime, "delivery/windows-x64-runtime.zip")
        packages.append(path)
    if windows_runtime:
        path = output / f"LabOS-Agent-Windows-x64-{__version__}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            write_package(package, "agent")
            with zipfile.ZipFile(windows_runtime) as runtime:
                for name in runtime.namelist():
                    if not name.startswith("python/") or ".." in name.split("/"):
                        raise ValueError("unsafe runtime archive")
                    package.writestr(name, runtime.read(name))
            for doc in (ROOT / "docs").glob("*_ZH.md"):
                if doc.name not in package.namelist():
                    package.write(doc, doc.name)
        packages.append(path)
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in packages)
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return packages


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--windows-runtime", type=Path)
    args = parser.parse_args()
    for archive in build_release(args.output, args.windows_runtime):
        print(f"{archive} ({archive.stat().st_size:,} bytes)")
