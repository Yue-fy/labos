from __future__ import annotations

import argparse
import hashlib
import zipfile
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from labos import __version__
from labos.delivery import write_package
from labos.portable_archive import preflight_outputs, publish_outputs, validate_members

ROOT = Path(__file__).resolve().parents[1]


def build_release(output: Path, windows_runtime: Path | None = None) -> list[Path]:
    roles = ["central", "agent"]
    names = [f"LabOS-{role.title()}-{__version__}.zip" for role in roles]
    if windows_runtime:
        names.append(f"LabOS-Agent-Windows-x64-{__version__}.zip")
    targets = [output / name for name in [*names, "SHA256SUMS"]]
    preflight_outputs(targets)
    with ExitStack() as stack:
        runtime = stack.enter_context(zipfile.ZipFile(windows_runtime)) if windows_runtime else None
        members = validate_members(runtime, prefix="python") if runtime else []
        output.mkdir(parents=True, exist_ok=True)
        stage = Path(stack.enter_context(TemporaryDirectory(prefix=".labos-release-", dir=output)))
        docs = [doc for doc in sorted((ROOT / "docs").glob("*.md")) if not doc.name.endswith("_ZH.md")]
        for role, name in zip(roles, names):
            with zipfile.ZipFile(stage / name, "w", compression=zipfile.ZIP_DEFLATED) as package:
                write_package(package, role)
                package.write(ROOT / "README.md", "README.md")
                for doc in docs:
                    if doc.name not in package.namelist():
                        package.write(doc, doc.name)
                    package.write(doc, "docs/" + doc.name)
                if role == "central" and windows_runtime:
                    package.write(windows_runtime, "delivery/windows-x64-runtime.zip")
        if runtime:
            with zipfile.ZipFile(stage / names[-1], "w", compression=zipfile.ZIP_DEFLATED) as package:
                write_package(package, "agent")
                for member in members:
                    package.writestr(member, runtime.read(member))
                for doc in docs:
                    if doc.name not in package.namelist():
                        package.write(doc, doc.name)
        sums = "".join(f"{hashlib.sha256((stage / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
        (stage / "SHA256SUMS").write_text(sums, encoding="utf-8")
        publish_outputs([(stage / target.name, target) for target in targets])
    return targets[:-1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--windows-runtime", type=Path)
    args = parser.parse_args()
    for archive in build_release(args.output, args.windows_runtime):
        print(f"{archive} ({archive.stat().st_size:,} bytes)")
