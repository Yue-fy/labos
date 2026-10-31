"""Apply a verified LabOS overlay to a stopped, existing portable installation."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import uuid


def apply_update(update, target):
    from labos.cooperation_worker import load_worker_config
    from labos.files import InstanceLock, atomic_write

    update, target = Path(update).resolve(), Path(target).resolve()
    if not (target / "config.yaml").is_file() or not (target / "cooperation.yaml").is_file():
        raise ValueError("Select the existing provisioned LabOS report-worker folder")
    payload = update / "overlay"
    entries = json.loads((update / "payload-manifest.json").read_text(encoding="utf-8"))["files"]
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Missing update payload manifest")
    contents = {}
    for name, digest in entries.items():
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or (len(path.parts) == 1 and path.suffix not in {".py", ".ps1", ".cmd", ".md", ".json"})
            and path.name != "pilot-worker.example.yaml"
            or (
                len(path.parts) > 1
                and not (
                    name.startswith("src/labos/") or name.startswith("python/Lib/site-packages/")
                )
            )
        ):
            raise ValueError("Update manifest contains a protected or invalid path")
        source = (payload / name).resolve()
        destination = (target / name).resolve()
        if not source.is_relative_to(payload) or not destination.is_relative_to(target):
            raise ValueError("Update path escapes its installation")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Update payload checksum mismatch")
        contents[name] = content
    config = load_worker_config(target / "cooperation.yaml")
    states = [config.state_dir]
    from labos.pilot_worker import load_pilot_worker_config
    for name in ("pilot-worker.yaml", "dark-a-worker.yaml", "optical-readback-worker.yaml"):
        if (target / name).is_file():
            state = load_pilot_worker_config(target / name).state_dir
            if state not in states:
                states.append(state)
    backup = (
        target
        / "data/pilot-update-backups"
        / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    with ExitStack() as locks:
        for state in states:
            locks.enter_context(InstanceLock(state))
        for name, content in contents.items():
            destination = target / name
            if destination.exists():
                old = backup / name
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, old)
            atomic_write(destination, content)
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(update / "payload-manifest.json", backup / "applied-manifest.json")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    update = Path(__file__).resolve().parent
    sys.path.insert(0, str(update / "overlay/src"))
    try:
        backup = apply_update(update, args.target)
        print(f"LabOS overlay applied. Replaced files backed up at {backup}")
        print(
            "Connection configuration and journals retained. Physical approval remains a separate local setting."
        )
        return 0
    except (OSError, ValueError, RuntimeError, KeyError):
        print(
            "Update refused or incomplete. Check payload integrity, installation path and stopped-worker locks. Keep the backup directory for recovery."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
